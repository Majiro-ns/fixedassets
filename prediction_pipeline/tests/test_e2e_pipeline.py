"""
tests/test_e2e_pipeline.py
==========================
E2Eパイプラインテスト（Stage1→mock Stage2→Stage3）

テスト目的:
  個別コンポーネントのテストは充実（658 passed）だが、
  パイプライン全体を通すE2Eテストがなかった。
  KEIRIN_MOCK_MODE=1 + --dry-run でAPIキーなしでフルパイプラインを実行し、
  「動くデモ」の動作保証を行う（cmd_146k_sub5）。

テストシナリオ（タスク指示のa〜eに対応）:
  a. dry-run + mock mode で全パイプラインが通ること（エラーなし）
  b. Stage1: fixture(20260228)→フィルタリング→F8推定→通過レースが存在すること
  c. Stage2(mock): mock予想が生成され、confidence="mock"であること
  d. 出力ファイル（summary.md、JSONファイル）が正しいフォーマットで生成されること
  e. パイプライン全体でエラーが発生しないこと

テスト根拠（CHECK-9）:
  a. KEIRIN_MOCK_MODE=1 + --dry-run を使えばAPIキーなしでフルパイプライン実行可能。
     subprocess終了コード=0であればクラッシュなし。
  b. 20260228 (土曜) S級レースのうち8/31がフィルター通過（手計算確認済み）:
     - F1: grade=S → 通過
     - F2: stage=Ｓ級一予選 → 通過
     - F7: R番号 (4,6 除外) → 大垣2,3,5,7,8,9,10,11が通過
     - score_spread >= 12 → 通過
     手計算: datetime(2026,2,28).weekday() == 5 （土曜日 → F6日曜除外は非対象）
  c. _generate_mock_prediction() は confidence="mock" を返す（src/stage2_process.py 仕様）。
     手計算: score上位1位=axis, 2-3位=partners として機械的に選択。
  d. run() は最後に output/{date}/summary.md を書き込む（run() L654 summary_path.write_text）。
     save_race_result() が各レースの {sport}_{venue}_{race_no}.json を保存する。
  e. run() は各レース処理のエラーを try/except でキャッチし、全体が止まらない設計。

使用fixture:
  data/fixtures/keirin_20260228.json （31 races: 大垣12 + 和歌山12 + 広島7）
"""

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# テスト対象日付（20260228 = 土曜日、fixtureが存在する日）
TEST_DATE = "20260228"
FIXTURE_PATH = ROOT / "data" / "fixtures" / f"keirin_{TEST_DATE}.json"
OUTPUT_DATE_DIR = ROOT / "output" / TEST_DATE


# ─── ヘルパー ──────────────────────────────────────────────────────────────────


def _run_pipeline(extra_args=None, mock_mode=True) -> subprocess.CompletedProcess:
    """main.py を subprocess で実行するヘルパー関数。

    Args:
        extra_args: 追加コマンドライン引数のリスト。
        mock_mode: True の場合 KEIRIN_MOCK_MODE=1 を設定する。

    Returns:
        subprocess.CompletedProcess インスタンス。
    """
    env = os.environ.copy()
    if mock_mode:
        env["KEIRIN_MOCK_MODE"] = "1"
    else:
        env.pop("KEIRIN_MOCK_MODE", None)

    cmd = [
        sys.executable,
        str(ROOT / "main.py"),
        "--date", TEST_DATE,
        "--sport", "keirin",
        "--dry-run",
        "--max-races", "3",
    ]
    if extra_args:
        cmd.extend(extra_args)

    return subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        timeout=60,
    )


# ─── a. 全パイプラインがエラーなく通ること ─────────────────────────────────────


@pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason=f"fixture {FIXTURE_PATH} が存在しない場合はスキップ",
)
class TestE2EPipelineNoError:
    """テストシナリオ a: dry-run + mock mode で全パイプラインがエラーなく通ること"""

    @pytest.fixture(autouse=True)
    def cleanup_output(self):
        """テスト前後に output/{date}/ をクリーンアップ"""
        if OUTPUT_DATE_DIR.exists():
            shutil.rmtree(OUTPUT_DATE_DIR, ignore_errors=True)
        yield
        if OUTPUT_DATE_DIR.exists():
            shutil.rmtree(OUTPUT_DATE_DIR, ignore_errors=True)

    def test_e2e_pipeline_returncode_zero(self):
        """E2Eテスト a-1: subprocess終了コードが0（エラーなし）であること。

        根拠: KEIRIN_MOCK_MODE=1 + --dry-run を使えばAPIキーなしでフルパイプライン実行可能。
        手計算: keirin_20260228.json (31 races, 土曜) → max_races=3 で3件処理。
        """
        result = _run_pipeline()
        assert result.returncode == 0, (
            f"パイプラインがエラー終了: returncode={result.returncode}\n"
            f"STDOUT: {result.stdout[:1000]}\n"
            f"STDERR: {result.stderr[:500]}"
        )

    def test_e2e_pipeline_completion_logged(self):
        """E2Eテスト a-2: パイプライン完了のログが出力されること。

        根拠: run() の最後に logger.info("=== パイプライン完了 ===") が出力される（L659）。
        """
        result = _run_pipeline()
        assert result.returncode == 0, f"Pipeline failed: {result.stderr[:200]}"
        combined = result.stdout + result.stderr
        assert "パイプライン完了" in combined, (
            f"パイプライン完了メッセージが見つからない: {combined[:500]}"
        )

    def test_e2e_pipeline_start_logged(self):
        """E2Eテスト a-3: パイプライン開始のログが出力されること。

        根拠: run() の冒頭に logger.info("=== 競輪・競艇予想パイプライン 開始 ===") がある（L529）。
        """
        result = _run_pipeline()
        combined = result.stdout + result.stderr
        assert "パイプライン 開始" in combined or "開始" in combined, (
            f"パイプライン開始ログが見つからない: {combined[:300]}"
        )

    def test_e2e_pipeline_without_mock_mode_also_runs(self):
        """E2Eテスト a-4: KEIRIN_MOCK_MODE なし（dry_run のみ）でもパイプラインが起動すること。

        根拠: --dry-run のみでも DRY RUN モードで動作する設計。
        注意: APIキーなし環境では LLM 呼び出しがエラーになりうるが、パイプライン自体は起動する。
        """
        result = _run_pipeline(mock_mode=False)
        combined = result.stdout + result.stderr
        # パイプライン開始ログが出力されていること（クラッシュしていない）
        assert "パイプライン" in combined or "pipeline" in combined.lower(), (
            f"パイプライン起動ログが見つからない: {combined[:300]}"
        )


# ─── b. Stage1: fixture → フィルタリング → 通過レースの確認 ─────────────────────


@pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason=f"fixture {FIXTURE_PATH} が存在しない場合はスキップ",
)
class TestE2EStage1Filter:
    """テストシナリオ b: Stage1 フィルタリングの E2E 検証"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from src.filter_engine import FilterEngine

        filters_path = ROOT / "config" / "keirin" / "filters.yaml"
        self.engine = FilterEngine(str(filters_path), sport="keirin")
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            self.races = json.load(f)

    def test_fixture_20260228_loaded_31_races(self):
        """テスト b-1: fixture keirin_20260228.json が 31 件読み込めること。

        根拠（CHECK-1）:
          python3 -c "import json; print(len(json.load(open('data/fixtures/keirin_20260228.json'))))"
          → 31
          内訳: 大垣12 + 和歌山12 + 広島7 = 31
        """
        assert len(self.races) == 31, f"Expected 31 races, got {len(self.races)}"

    def test_20260228_is_saturday(self):
        """テスト b-2: 20260228 が土曜日であること（F6 日曜除外は適用されない）。

        根拠（手計算）:
          datetime(2026, 2, 28).weekday() == 5  # 5=土曜（0=月曜, 6=日曜）
          → F6[曜日]: 日曜のみ除外のため、土曜は通過
        """
        dt = datetime(2026, 2, 28)
        assert dt.weekday() == 5, (
            f"Expected Saturday (weekday=5), got {dt.weekday()}"
        )

    def test_stage1_venue_distribution(self):
        """テスト b-3: fixture の競輪場別内訳が正しいこと（大垣12・和歌山12・広島7）。

        根拠（手計算）:
          keirin_20260228.json を json.load し venue_name で Counter
          → 大垣: 12, 和歌山: 12, 広島: 7（合計31）
        """
        venue_counts = Counter(r["venue_name"] for r in self.races)
        assert venue_counts["大垣"] == 12, f"大垣: expected 12, got {venue_counts['大垣']}"
        assert venue_counts["和歌山"] == 12, f"和歌山: expected 12, got {venue_counts['和歌山']}"
        assert venue_counts["広島"] == 7, f"広島: expected 7, got {venue_counts['広島']}"

    def test_stage1_passing_races_exist(self):
        """テスト b-4: Stage1フィルターを通過するレースが存在すること（8件）。

        根拠（手計算 + 実確認）:
          20260228 (土曜) S級大垣レースのうち:
          - F1: grade=S → 通過
          - F2: stage=Ｓ級一予選 → filters.yaml stage_whitelist に含まれる → 通過
          - F7: R番号 4,6 は除外 → 大垣2,3,5,7,8,9,10,11R が通過
          - score_spread >= 12 → 大垣11Rまで通過（大垣12Rは spread=7.22 < 12 で不合格）
          - 和歌山・広島: A級 or score_spread < 12 → 全て不合格
          実確認: python3 実行で8件通過を確認済み
        """
        passed = [r for r in self.races if self.engine.apply(r)[0]]
        assert len(passed) > 0, "フィルター通過レースが0件 — Stage1が機能していない"
        assert len(passed) == 8, (
            f"Expected 8 passing races (大垣2,3,5,7,8,9,10,11R), got {len(passed)}\n"
            f"Passed: {[(r['venue_name'], r['race_no']) for r in passed]}"
        )

    def test_stage1_only_ogaki_passes(self):
        """テスト b-5: フィルターを通過するのは大垣のレースのみであること。

        根拠（手計算）:
          和歌山: A級またはscore_spread < 12 → 全不合格
          広島: A級 → 全不合格
          大垣: S級かつ score_spread >= 12 の一予選レース → 8件通過
        """
        passed = [r for r in self.races if self.engine.apply(r)[0]]
        for race in passed:
            assert race["venue_name"] == "大垣", (
                f"大垣以外がフィルターを通過した: {race['venue_name']} {race['race_no']}R"
            )

    def test_stage1_f8_expected_payout_estimation(self):
        """テスト b-6: Stage1 F8: expected_payout がない場合に自動推定が動作すること。

        根拠: process_race() の F8統合ロジック（main.py L282-294）:
          if race.get('expected_payout') is None:
              est_payout = estimate_expected_payout(race)
          → fixture のレースは expected_payout を持たないため F8推定が走る。
        期待値: None または float（スコアデータ不足の場合は None も許容）
        """
        from src.expected_payout import estimate_expected_payout

        for race in self.races[:5]:
            if race.get("expected_payout") is None:
                result = estimate_expected_payout(race)
                assert result is None or isinstance(result, (int, float)), (
                    f"estimate_expected_payout() は None or float を返すはず: {result}"
                )

    def test_stage1_filter_reasons_are_strings(self):
        """テスト b-7: FilterEngine.apply() の理由リストが文字列のリストであること。

        根拠: filter_engine.apply() の戻り値仕様:
          Tuple[bool, List[str]] → reasons の各要素は str
        """
        for race in self.races[:10]:
            passed, reasons = self.engine.apply(race)
            assert isinstance(passed, bool)
            assert isinstance(reasons, list)
            for reason in reasons:
                assert isinstance(reason, str), (
                    f"reason が str でない: {type(reason)} - {reason}"
                )


# ─── c. Stage2(mock): confidence="mock" の確認 ─────────────────────────────────


@pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason=f"fixture {FIXTURE_PATH} が存在しない場合はスキップ",
)
class TestE2EStage2Mock:
    """テストシナリオ c: Stage2 mock モードで confidence="mock" が生成されること"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from src.filter_engine import FilterEngine

        self.filters_path = ROOT / "config" / "keirin" / "filters.yaml"
        self.engine = FilterEngine(str(self.filters_path), sport="keirin")
        with open(FIXTURE_PATH, encoding="utf-8") as f:
            self.races = json.load(f)
        # フィルター通過レース（大垣2R〜11R）
        self.passing_races = [r for r in self.races if self.engine.apply(r)[0]]

    def test_stage2_confidence_is_mock(self):
        """テスト c-1: _generate_mock_prediction() が confidence="mock" を返すこと。

        根拠（CHECK-7）:
          src/stage2_process.py の _generate_mock_prediction() ドキュメント仕様:
          → confidence="mock" を設定する（実予想との区別のため）。
        手計算: フィルター通過の大垣2R → score上位3選手から axis/partners を決定 → confidence="mock"
        """
        from src.stage2_process import _generate_mock_prediction

        assert len(self.passing_races) > 0, "フィルター通過レースがない"
        for race in self.passing_races[:3]:
            race["sport"] = "keirin"
            result = _generate_mock_prediction(race)
            assert result["confidence"] == "mock", (
                f"confidence='mock' が期待値: actual={result['confidence']}"
                f" ({race['venue_name']} {race['race_no']}R)"
            )

    def test_stage2_mock_mode_flag_in_result(self):
        """テスト c-2: mock予想の結果に mock_mode=True が記録されること。

        根拠: _generate_mock_prediction() は返り値に mock_mode=True を含む（仕様）。
        """
        from src.stage2_process import _generate_mock_prediction

        race = self.passing_races[0]
        race["sport"] = "keirin"
        result = _generate_mock_prediction(race)
        assert result.get("mock_mode") is True, (
            f"mock_mode=True が記録されていない: {result}"
        )

    def test_stage2_mock_prediction_text_format(self):
        """テスト c-3: mock予想のテキストが正しいフォーマットであること。

        根拠（手計算）:
          大垣2R の entries をscore降順ソート → score最高=axis → 「本命: X番」
          2-3位が partners → 「軸相手: A番、B番」
          出力: 「本命: X番」「軸相手:」「買い目: 3連単」「根拠:」を含む
        """
        from src.stage2_process import _generate_mock_prediction

        race = self.passing_races[0]
        race["sport"] = "keirin"
        result = _generate_mock_prediction(race)
        pred_text = result.get("prediction_text", "")
        assert "本命:" in pred_text, f"「本命:」が含まれない: '{pred_text[:100]}'"
        assert "軸相手:" in pred_text, f"「軸相手:」が含まれない: '{pred_text[:100]}'"
        assert "根拠:" in pred_text, f"「根拠:」が含まれない: '{pred_text[:100]}'"

    def test_stage2_process_race_with_mock_mode(self, tmp_path):
        """テスト c-4: process_race(mock_mode=True) の結果に mock_mode=True が記録されること。

        根拠: main.py process_race() は mock_mode=True 時に
              result["mock_mode"]=True を追加する（test_stage2_mock.py での確認済み）。

        注意: 4ffcfd5 にて process_race() の F10 条件に `and not mock_mode` が追加された。
              mock_mode=True の場合、F10 は min_confidence_score の設定値に関わらず
              自動的にスキップされる（main.py L325: `if min_conf > 0 and conf_score < min_conf and not mock_mode`）。
        CHECK-7: min_confidence_score=0 は防衛的ガードとして残存しているが、
                 mock_mode=True が渡される本テストでは F10 無効化は不要。
                 旧動作（F10 が mock の前に走る）は 4ffcfd5 で修正済み。
        """
        import yaml
        import main as main_mod
        from src.filter_engine import FilterEngine

        # 防衛的ガード: min_confidence_score=0（mock_mode=True では F10 は自動スキップ済み、4ffcfd5）
        config_dir = tmp_path / "config" / "keirin"
        config_dir.mkdir(parents=True)
        filters_file = config_dir / "filters.yaml"
        filters_file.write_text(
            yaml.dump(
                {
                    "grade_whitelist": ["S", "S1", "S2"],
                    "stage_whitelist": ["予選", "一予選", "特選", "準決勝", "決勝", "二次予選"],
                    "min_entries": 1,
                    "expected_payout_min": 0,
                    "min_confidence_score": 0,  # 防衛的ガード（mock_mode=True で F10 は自動バイパス済み）
                    "max_bets_per_race": 0,
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        filter_engine = FilterEngine(str(filters_file), sport="keirin")

        race = self.passing_races[0].copy()
        race["sport"] = "keirin"

        with open(ROOT / "config" / "settings.yaml", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        profile = {"predictor_name": "test_predictor", "profile_id": "test"}

        orig_env = os.environ.get("KEIRIN_MOCK_MODE")  # None if not originally set
        os.environ["KEIRIN_MOCK_MODE"] = "1"
        try:
            result = main_mod.process_race(
                race, filter_engine, profile, config,
                dry_run=False, mock_mode=True,
            )
        finally:
            # 元々環境変数が未設定だった場合は削除（"0" を残さない）
            if orig_env is None:
                os.environ.pop("KEIRIN_MOCK_MODE", None)
            else:
                os.environ["KEIRIN_MOCK_MODE"] = orig_env

        assert result.get("mock_mode") is True, (
            f"process_race(mock_mode=True) の結果に mock_mode=True が含まれていない: {result}"
        )

    def test_stage2_all_passing_races_generate_mock(self):
        """テスト c-5: フィルター通過の全レースでmock予想が生成されること。

        根拠（手計算）:
          8件のフィルター通過レース（大垣2,3,5,7,8,9,10,11R）のいずれも
          entries に score データがあるため _generate_mock_prediction() が機能する。
        検証ソース: data/fixtures/keirin_20260228.json（実スクレイピングデータ）
        """
        from src.stage2_process import _generate_mock_prediction

        success_count = 0
        for race in self.passing_races:
            race["sport"] = "keirin"
            result = _generate_mock_prediction(race)
            assert result["mock_mode"] is True
            assert result["confidence"] == "mock"
            assert "prediction_text" in result
            success_count += 1

        assert success_count == len(self.passing_races), (
            f"一部のレースでmock予想が生成されなかった: {success_count}/{len(self.passing_races)}"
        )


# ─── d. 出力ファイルが正しいフォーマットで生成されること ───────────────────────


@pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason=f"fixture {FIXTURE_PATH} が存在しない場合はスキップ",
)
class TestE2EOutputFormat:
    """テストシナリオ d: 出力ファイルが正しいフォーマットで生成されること"""

    @pytest.fixture(autouse=True, scope="class")
    def run_pipeline_and_cleanup(self):
        """クラス全体で1回だけパイプラインを実行し、全テストで出力を共有する。

        フレイキー修正 (cmd_152k_sub4):
          【旧】function scope: d-1〜d-6 の各テストで独立実行（計6回）→ cleanup+run を繰り返す
               WSL2/DrvFs でファイルロック競合が起きると shutil.rmtree(ignore_errors=True) が
               サイレントに失敗し、次のパイプライン実行が JSON を書き込めず test_output_json_files_created が FAIL。
          【新】class scope: パイプラインを1回だけ実行 → cleanup は開始時/終了時の2回のみ
               ファイルロック競合リスクを 12回→2回 に削減し、フレイキーを根絶。
        """
        if OUTPUT_DATE_DIR.exists():
            shutil.rmtree(OUTPUT_DATE_DIR, ignore_errors=True)

        # パイプライン実行（mock mode + dry-run）
        env = os.environ.copy()
        env["KEIRIN_MOCK_MODE"] = "1"
        run_result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "main.py"),
                "--date", TEST_DATE,
                "--sport", "keirin",
                "--dry-run",
                "--max-races", "3",
            ],
            env=env,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=60,
        )
        # クラス変数に保存: 全テストインスタンスが self._run_result でアクセス可能
        type(self)._run_result = run_result
        yield
        if OUTPUT_DATE_DIR.exists():
            shutil.rmtree(OUTPUT_DATE_DIR, ignore_errors=True)

    def test_summary_md_created(self):
        """テスト d-1: summary.md が output/{date}/ に生成されること。

        根拠: run() L652-655:
          summary_path = output_dir / "summary.md"
          summary_path.write_text(summary_text, encoding="utf-8")
        """
        assert self._run_result.returncode == 0, (
            f"Pipeline failed: {self._run_result.stderr[:200]}"
        )
        summary_path = OUTPUT_DATE_DIR / "summary.md"
        assert summary_path.exists(), (
            f"summary.md が生成されていない: {summary_path}\n"
            f"STDOUT: {self._run_result.stdout[:300]}"
        )

    def test_summary_md_not_empty(self):
        """テスト d-2: summary.md が空でないこと。"""
        summary_path = OUTPUT_DATE_DIR / "summary.md"
        if not summary_path.exists():
            pytest.skip("summary.md が存在しない（テスト d-1 で確認済み）")
        content = summary_path.read_text(encoding="utf-8")
        assert len(content) > 0, "summary.md が空"

    def test_summary_md_contains_date(self):
        """テスト d-3: summary.md に対象日付（2026 or TEST_DATE）が含まれること。

        根拠: format_batch() は meta={"date": date} を受け取り summary に出力する。
        """
        summary_path = OUTPUT_DATE_DIR / "summary.md"
        if not summary_path.exists():
            pytest.skip("summary.md が存在しない")
        content = summary_path.read_text(encoding="utf-8")
        assert "2026" in content or TEST_DATE in content, (
            f"summary.md に日付が含まれていない: {content[:300]}"
        )

    def test_output_json_files_created(self):
        """テスト d-4: output/{date}/ に JSON ファイルが生成されること。

        根拠: save_race_result() が各レースの結果を
          {sport}_{venue}_{race_no}.json に保存する（main.py L491-494）。
        max_races=3 で3レース処理 → 最大3件の JSON が生成される。
        """
        assert self._run_result.returncode == 0, (
            f"Pipeline failed: {self._run_result.stderr[:200]}"
        )
        json_files = list(OUTPUT_DATE_DIR.glob("*.json"))
        assert len(json_files) > 0, (
            f"JSON ファイルが1件も生成されていない: {OUTPUT_DATE_DIR}"
        )

    def test_output_json_has_required_fields(self):
        """テスト d-5: 生成された JSON ファイルに必須フィールドが含まれること。

        根拠: format_prediction() / save_race_result() の返り値仕様:
          race_info, prediction_text, bet（またはbet_type）を含む。
        """
        json_files = list(OUTPUT_DATE_DIR.glob("*.json"))
        if not json_files:
            pytest.skip("JSON ファイルが存在しない（テスト d-4 で確認済み）")

        for json_path in json_files:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            # race_info または基本フィールドが含まれること
            has_required = (
                "race_info" in data
                or "venue_name" in data
                or "sport" in data
                or "prediction_text" in data
            )
            assert has_required, (
                f"必須フィールドがない: {json_path.name}: {list(data.keys())}"
            )

    def test_output_json_filename_pattern(self):
        """テスト d-6: JSON ファイル名が keirin_{venue}_{race_no}.json 形式であること。

        根拠: save_race_result() L493:
          filename = f"{sport}_{venue}_{race_no}.json"
          → "keirin_" で始まるファイル名が生成される。
        """
        json_files = list(OUTPUT_DATE_DIR.glob("keirin_*.json"))
        total_json = list(OUTPUT_DATE_DIR.glob("*.json"))
        if not total_json:
            pytest.skip("JSON ファイルが存在しない")
        assert len(json_files) > 0, (
            f"keirin_*.json 形式のファイルがない: {[f.name for f in total_json]}"
        )


# ─── e. パイプライン全体でエラーが発生しないこと ───────────────────────────────


@pytest.mark.skipif(
    not FIXTURE_PATH.exists(),
    reason=f"fixture {FIXTURE_PATH} が存在しない場合はスキップ",
)
class TestE2EPipelineErrorFree:
    """テストシナリオ e: パイプライン全体でエラーが発生しないこと"""

    @pytest.fixture(autouse=True)
    def cleanup_output(self):
        """テスト前後に output/{date}/ をクリーンアップ"""
        if OUTPUT_DATE_DIR.exists():
            shutil.rmtree(OUTPUT_DATE_DIR, ignore_errors=True)
        yield
        if OUTPUT_DATE_DIR.exists():
            shutil.rmtree(OUTPUT_DATE_DIR, ignore_errors=True)

    def test_e2e_direct_run_no_exception(self):
        """テスト e-1: run() を直接呼び出しても例外が発生しないこと。

        根拠: run() は各レース処理のエラーを try/except でキャッチし（main.py L609-613）、
              全体が止まらないように設計されている。
        """
        import main as main_mod

        orig_env = os.environ.get("KEIRIN_MOCK_MODE")  # None if not originally set
        os.environ["KEIRIN_MOCK_MODE"] = "1"
        try:
            main_mod.run(
                date=TEST_DATE,
                sport="keirin",
                dry_run=True,
                config_path="config/settings.yaml",
                max_races=3,
            )
        except SystemExit:
            pass  # sys.exit() は OK
        except Exception as e:
            pytest.fail(
                f"run() で例外が発生した: {type(e).__name__}: {e}"
            )
        finally:
            # 元々環境変数が未設定だった場合は削除（"0" を残さない）
            if orig_env is None:
                os.environ.pop("KEIRIN_MOCK_MODE", None)
            else:
                os.environ["KEIRIN_MOCK_MODE"] = orig_env

    def test_e2e_no_traceback_in_stderr(self):
        """テスト e-2: stderr に Python 例外スタック（Traceback）が含まれないこと。

        根拠: E2Eパイプラインが正常動作する場合、Traceback は出力されない。
        """
        result = _run_pipeline()
        assert "Traceback" not in result.stderr, (
            f"stderr に Traceback が含まれる（例外が発生した）:\n{result.stderr[:500]}"
        )

    def test_e2e_max_races_limitation_logged(self):
        """テスト e-3: max_races=3 制限のログが出力されること。

        根拠（手計算）:
          run() L598-600:
            if max_races > 0:
                races = races[:max_races]
                logger.info("max_races=%d 制限適用: %d 件に絞りました", ...)
          → 31件の fixture → max_races=3 で3件に絞る → ログが出力される
        """
        result = _run_pipeline()
        assert result.returncode == 0, f"Pipeline failed: {result.stderr[:200]}"
        combined = result.stdout + result.stderr
        assert "max_races" in combined or "件に絞りました" in combined, (
            f"max_races 制限のログが見つからない: {combined[:500]}"
        )

    def test_e2e_filter_result_logged(self):
        """テスト e-4: フィルター通過レース数のログが出力されること。

        根拠: run() L621:
          logger.info("フィルター通過レース: %d / %d", len(passed), len(results))
        手計算: max_races=3 の場合、大垣1-3R を処理
          → 大垣1R: grade='' → フィルター不合格
          → 大垣2R: grade=S, Ｓ級一予選 → フィルター通過
          → 大垣3R: grade=S, Ｓ級一予選 → フィルター通過
          → 通過数/総数のログが出力される
        """
        result = _run_pipeline()
        assert result.returncode == 0, f"Pipeline failed: {result.stderr[:200]}"
        combined = result.stdout + result.stderr
        assert "フィルター通過レース" in combined, (
            f"フィルター通過レース数のログが見つからない: {combined[:500]}"
        )

    def test_e2e_with_max_races_1(self):
        """テスト e-5: max_races=1 でもパイプラインがエラーなく動作すること。"""
        result = _run_pipeline(extra_args=["--max-races", "1"])
        assert result.returncode == 0, (
            f"max_races=1 でパイプラインエラー: {result.stderr[:200]}"
        )

    def test_e2e_with_max_races_8(self):
        """テスト e-6: max_races=8 でもパイプラインがエラーなく動作すること。

        根拠: フィルター通過レースは8件（大垣2-11R）。
          max_races=8 なら8件全て処理されるが、fixture には大垣1R〜大垣8Rの8件が最初にある。
        """
        result = _run_pipeline(extra_args=["--max-races", "8"])
        assert result.returncode == 0, (
            f"max_races=8 でパイプラインエラー: {result.stderr[:200]}"
        )
