"""
tests/test_stage2_mock.py
==========================
Stage 2 mock mode のテスト。

テスト期待値の根拠（CHECK-9）:
  a. mock mode有効時にAPIを呼ばないこと:
     → is_mock_mode()=True の場合、generate_prediction()を呼ばずに
       _generate_mock_prediction()を使う。APIのimportすら不要。
  b. score上位3選手が正しく選択されること:
     → entry['score']でソートした1位=axis、2-4位=partners の手計算で確認。
  c. 出力フォーマットが実APIと同一であること:
     → 「本命: X番（名前）\n軸相手: ...\n買い目: ...\n根拠: ...」
  d. mock_mode=True が出力に記録されること:
     → process_race() の戻り値に result["mock_mode"]=True が含まれること。
  e. 2/28データでのmock予想生成:
     → keirin_20260228.json から実データを読んでmock予想が生成されること。
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

# プロジェクトルートをパスに追加
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.stage2_process import (
    is_mock_mode,
    _generate_mock_prediction,
    _get_score,
    MOCK_MODE_ENV,
)


# ─── テスト用ヘルパー ──────────────────────────────────────────────────────

def _make_race(entries: list) -> Dict[str, Any]:
    """テスト用レース辞書を作成する。"""
    return {
        "venue_name": "川崎",
        "race_no": "9",
        "grade": "S1",
        "stage": "特選",
        "sport": "keirin",
        "entries": entries,
    }


def _make_entry(car_no: int, name: str, score: float) -> Dict[str, Any]:
    """テスト用エントリー辞書を作成する。"""
    return {"car_no": car_no, "name": name, "score": score, "grade": "S1", "leg_type": "逃げ"}


# ─── a. mock mode有効時にAPIを呼ばないこと ────────────────────────────────

class TestIsMockMode:
    """is_mock_mode() の動作テスト。"""

    def test_mock_mode_on(self, monkeypatch):
        """KEIRIN_MOCK_MODE=1 の場合 True を返すこと。"""
        monkeypatch.setenv(MOCK_MODE_ENV, "1")
        assert is_mock_mode() is True

    def test_mock_mode_off_default(self, monkeypatch):
        """KEIRIN_MOCK_MODE が未設定の場合 False を返すこと。"""
        monkeypatch.delenv(MOCK_MODE_ENV, raising=False)
        assert is_mock_mode() is False

    def test_mock_mode_off_zero(self, monkeypatch):
        """KEIRIN_MOCK_MODE=0 の場合 False を返すこと。"""
        monkeypatch.setenv(MOCK_MODE_ENV, "0")
        assert is_mock_mode() is False

    def test_mock_mode_off_other_value(self, monkeypatch):
        """KEIRIN_MOCK_MODE=yes 等、1以外の場合 False を返すこと。"""
        monkeypatch.setenv(MOCK_MODE_ENV, "yes")
        assert is_mock_mode() is False


class TestMockModeSkipsAPI:
    """mock mode有効時にAPIを呼ばないことを確認するテスト。"""

    def test_mock_mode_no_anthropic_call(self, monkeypatch):
        """mock mode有効時に anthropic.Anthropic が呼ばれないこと。
        根拠: _generate_mock_prediction() はAPIを呼ばない純粋な関数。
        手計算: score=[110.0, 108.0, 105.0] → axis=1(110.0), partners=[2,3]
        """
        entries = [
            _make_entry(1, "選手A", 110.0),
            _make_entry(2, "選手B", 108.0),
            _make_entry(3, "選手C", 105.0),
        ]
        race = _make_race(entries)

        # APIモジュールをモック（呼ばれたら失敗）
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = _generate_mock_prediction(race)

        # anthropic.Anthropic() が呼ばれていないこと
        mock_anthropic.Anthropic.assert_not_called()
        assert result["axis"] == 1
        assert result["mock_mode"] is True


# ─── b. score上位3選手が正しく選択されること ──────────────────────────────

class TestMockPredictionScoreSelection:
    """score上位3選手が正しく選択されることのテスト。"""

    def test_score_top3_selected(self):
        """score上位3選手（軸1名・相手2名）が選択されること。
        手計算:
          entries: car_no=[1,2,3,4], score=[100, 110, 95, 108]
          ソート降順: [2(110), 4(108), 1(100), 3(95)]
          axis=2（score=110最高）, partners=[4, 1]（2位と3位）
        """
        entries = [
            _make_entry(1, "選手A", 100.0),
            _make_entry(2, "選手B", 110.0),
            _make_entry(3, "選手C", 95.0),
            _make_entry(4, "選手D", 108.0),
        ]
        race = _make_race(entries)
        result = _generate_mock_prediction(race)

        assert result["axis"] == 2, "score最高(110.0)のcar_no=2が軸のはず"
        assert result["partners"] == [4, 1], "score2位(108.0)=4, 3位(100.0)=1が相手のはず"

    def test_partners_max_two(self):
        """相手はscore2位・3位の2名であること（score top3 = 軸1名+相手2名）。
        根拠: タスク仕様「score上位1-2-3着の組み合わせ」= 3選手合計でnaiveな3連単。
        手計算: 7選手中 score上位1名=軸, 上位2-3名=相手(2名) → partners=[2,3]
        """
        entries = [_make_entry(i, f"選手{i}", float(100 - i)) for i in range(1, 8)]
        race = _make_race(entries)
        result = _generate_mock_prediction(race)

        assert len(result["partners"]) == 2, "相手はscore2位・3位の2名"

    def test_axis_not_in_partners(self):
        """軸選手が相手リストに含まれないこと。"""
        entries = [
            _make_entry(1, "選手A", 110.0),
            _make_entry(2, "選手B", 108.0),
            _make_entry(3, "選手C", 105.0),
        ]
        race = _make_race(entries)
        result = _generate_mock_prediction(race)

        assert result["axis"] not in result["partners"], "軸は相手リストに含まれない"

    def test_score_field_variants(self):
        """score/competitive_score/win_rate の複数フィールドに対応すること。
        手計算: car_no=2 の competitive_score=0.85 が最高 → axis=2
        """
        entries = [
            {"car_no": 1, "name": "選手A", "win_rate": 0.30},
            {"car_no": 2, "name": "選手B", "competitive_score": 0.85},
            {"car_no": 3, "name": "選手C", "score": 0.70},
        ]
        race = _make_race(entries)
        result = _generate_mock_prediction(race)

        assert result["axis"] == 2, "competitive_score=0.85が最高 → car_no=2が軸"

    def test_insufficient_entries(self):
        """選手が1名以下の場合はデータ不足として処理されること。"""
        entries = [_make_entry(1, "選手A", 100.0)]
        race = _make_race(entries)
        result = _generate_mock_prediction(race)

        assert result["axis"] is None, "選手1名ではaxis=None"
        assert result["partners"] == [], "選手1名ではpartnersは空"
        assert result["mock_mode"] is True

    def test_empty_entries(self):
        """エントリーが空の場合はデータ不足として処理されること。"""
        race = _make_race([])
        result = _generate_mock_prediction(race)

        assert result["axis"] is None
        assert result["partners"] == []
        assert result["mock_mode"] is True


# ─── c. 出力フォーマットが実APIと同一であること ───────────────────────────

class TestMockPredictionFormat:
    """出力フォーマットのテスト。"""

    def _get_standard_result(self):
        entries = [
            _make_entry(4, "選手D", 115.0),
            _make_entry(2, "選手B", 110.0),
            _make_entry(6, "選手F", 108.0),
            _make_entry(1, "選手A", 100.0),
        ]
        race = _make_race(entries)
        return _generate_mock_prediction(race)

    def test_prediction_text_has_honmei(self):
        """prediction_textに「本命: X番」形式が含まれること。
        根拠: 実APIの出力フォーマット（stage2_process.py ドキュメント仕様）と同一形式。
        手計算: score最高=4(115.0) → 「本命: 4番」
        """
        result = self._get_standard_result()
        assert "本命: 4番" in result["prediction_text"]

    def test_prediction_text_has_jikuaite(self):
        """prediction_textに「軸相手: X番、Y番」形式が含まれること。
        手計算: 2位=2(110.0), 3位=6(108.0) → 「軸相手: 2番、6番」
        """
        result = self._get_standard_result()
        assert "軸相手:" in result["prediction_text"]
        assert "2番" in result["prediction_text"]
        assert "6番" in result["prediction_text"]

    def test_prediction_text_has_kaime(self):
        """prediction_textに「買い目: 3連単 ... ながし」が含まれること。"""
        result = self._get_standard_result()
        assert "買い目: 3連単" in result["prediction_text"]
        assert "ながし" in result["prediction_text"]

    def test_prediction_text_has_konko(self):
        """prediction_textに「根拠:」が含まれること。"""
        result = self._get_standard_result()
        assert "根拠:" in result["prediction_text"]

    def test_confidence_is_mock(self):
        """confidence='mock' が設定されること（実予想と区別）。"""
        result = self._get_standard_result()
        assert result["confidence"] == "mock"

    def test_reasoning_contains_score_info(self):
        """reasoning に score情報が含まれること。"""
        result = self._get_standard_result()
        assert "Mock mode" in result["reasoning"]
        assert "score" in result["reasoning"]


# ─── d. mock_mode=True が出力に記録されること ─────────────────────────────

class TestMockModeFlag:
    """mock_mode=True フラグが出力に記録されることのテスト。"""

    def test_mock_mode_true_in_result(self):
        """_generate_mock_prediction() の返り値に mock_mode=True が含まれること。"""
        entries = [
            _make_entry(1, "選手A", 100.0),
            _make_entry(2, "選手B", 110.0),
            _make_entry(3, "選手C", 95.0),
        ]
        race = _make_race(entries)
        result = _generate_mock_prediction(race)

        assert result.get("mock_mode") is True, "mock_mode=True が記録されるべき"

    def test_mock_mode_in_process_race(self, monkeypatch, tmp_path):
        """process_race(mock_mode=True) の返り値に mock_mode=True が含まれること。
        根拠: main.pyのprocess_race()がmock_mode=Trueの場合、
              result["mock_mode"]=True を追加する。
        """
        # main.py の process_race をインポートして実行
        import main as main_mod
        from src.filter_engine import FilterEngine

        # フィルター設定ファイルの準備（全通過するダミー設定）
        import yaml
        config_dir = tmp_path / "config" / "keirin"
        config_dir.mkdir(parents=True)
        filters_file = config_dir / "filters.yaml"
        filters_file.write_text(yaml.dump({
            "grade_whitelist": ["S1", "S2"],
            "stage_whitelist": ["特選", "準決勝", "決勝", "二次予選", "一次予選"],
            "min_entries": 1,
            "expected_payout_min": 0,
            "min_confidence_score": 0,
            "max_bets_per_race": 0,
        }, allow_unicode=True), encoding="utf-8")

        filter_engine = FilterEngine(str(filters_file), sport="keirin")
        profile = {"predictor_name": "test_predictor", "profile_id": "test"}
        config = {
            "llm": {"model": "claude-haiku-4-5-20251001"},
            "pipeline": {"config_dir": str(tmp_path / "config")},
        }

        entries = [
            _make_entry(1, "選手A", 100.0),
            _make_entry(2, "選手B", 110.0),
            _make_entry(3, "選手C", 95.0),
        ]
        race = {
            "venue_name": "川崎",
            "race_no": "9",
            "grade": "S1",
            "stage": "特選",
            "sport": "keirin",
            "entries": entries,
        }

        result = main_mod.process_race(
            race, filter_engine, profile, config,
            dry_run=False, mock_mode=True,
        )

        assert result.get("mock_mode") is True, "process_race(mock_mode=True) の結果に mock_mode=True が含まれるべき"


# ─── e. 2/28データでのmock予想生成 ──────────────────────────────────────

class TestMockPredictionRealData:
    """実データ（2/28 fixture）を使ったmock予想生成テスト。"""

    FIXTURE_PATH = ROOT / "data" / "fixtures" / "keirin_20260228.json"

    @pytest.mark.skipif(
        not Path(ROOT / "data" / "fixtures" / "keirin_20260228.json").exists(),
        reason="keirin_20260228.json が存在しない場合はスキップ",
    )
    def test_real_data_mock_prediction_generated(self):
        """2/28 データでmock予想が生成されること（実データ検証）。
        検証ソース: data/fixtures/keirin_20260228.json（スクレイピング済みデータ）
        手計算: race[0].entries をscore降順ソート → axis=score最高選手のcar_no
        """
        with open(self.FIXTURE_PATH, encoding="utf-8") as f:
            races = json.load(f)

        assert len(races) > 0, "fixture に少なくとも1レースあるはず"

        race = races[0]
        race["sport"] = "keirin"

        result = _generate_mock_prediction(race)

        # 基本的な構造を確認
        assert result["mock_mode"] is True
        assert result["axis"] is not None, "実データでもaxisが生成されるはず"
        assert len(result["partners"]) >= 1, "実データでもpartnersが1名以上生成されるはず"
        assert "本命:" in result["prediction_text"]
        assert "軸相手:" in result["prediction_text"]

    @pytest.mark.skipif(
        not Path(ROOT / "data" / "fixtures" / "keirin_20260228.json").exists(),
        reason="keirin_20260228.json が存在しない場合はスキップ",
    )
    def test_real_data_axis_is_highest_score(self):
        """2/28 データで軸選手がscore最高の選手であること。
        手計算: entries の score 最大値を持つ選手のcar_noがaxisと一致するはず。
        """
        with open(self.FIXTURE_PATH, encoding="utf-8") as f:
            races = json.load(f)

        for race in races[:3]:  # 最初の3レースで検証
            race["sport"] = "keirin"
            entries = race.get("entries", [])
            if not entries:
                continue

            result = _generate_mock_prediction(race)

            if result["axis"] is None:
                continue

            # 手計算: score最高の選手のcar_noを確認
            best_entry = max(entries, key=_get_score)
            expected_axis = best_entry.get("car_no")

            assert result["axis"] == expected_axis, (
                f"axisがscore最高選手のcar_noと一致するはず: "
                f"expected={expected_axis}(score={_get_score(best_entry)}), "
                f"actual={result['axis']}"
            )

    @pytest.mark.skipif(
        not Path(ROOT / "data" / "fixtures" / "keirin_20260228.json").exists(),
        reason="keirin_20260228.json が存在しない場合はスキップ",
    )
    def test_real_data_all_races_generate_mock(self):
        """2/28 データの全レースでmock予想が生成されること（パイプライン動作確認）。
        検証ソース: data/fixtures/keirin_20260228.json
        """
        with open(self.FIXTURE_PATH, encoding="utf-8") as f:
            races = json.load(f)

        success_count = 0
        for race in races:
            race["sport"] = "keirin"
            result = _generate_mock_prediction(race)
            assert result["mock_mode"] is True
            assert "prediction_text" in result
            assert result["confidence"] == "mock"
            success_count += 1

        assert success_count == len(races), "全レースでmock予想が生成されるべき"


# ─── f. W-1修正: dry_run + mock_mode 同時指定テスト (cmd_146k_sub4) ─────────

class TestMockModePriorityOverDryRun:
    """W-1修正: mock_mode=True + dry_run=True 同時指定時の優先順位テスト。

    【背景】
    A8のcmd_145k_sub1_cr CRでW-1検出:
    「KEIRIN_MOCK_MODE=1 + --dry-run 同時指定時、dry_run が優先されmock予想が未生成」

    【修正内容】
    main.py process_race() の条件分岐を:
      旧: if dry_run: ... elif mock_mode: ...
      新: if mock_mode: ... elif dry_run: ...
    → 優先順位: mock_mode > dry_run > 実API呼び出し

    【CHECK-7b 手計算検算】
    result 構造: result["prediction"]["text"] に予想テキスト（formatter.py参照）
    - dry_run=True, mock_mode=False → prediction["text"] に「[DRY RUN]」含む
    - dry_run=True, mock_mode=True  → prediction["text"] に「本命:」含む（mock優先）
    - dry_run=False, mock_mode=True → prediction["text"] に「本命:」含む
    """

    def _make_process_race_inputs(self, tmp_path):
        """process_race() 呼び出し用の共通入力を作成する。"""
        import yaml
        config_dir = tmp_path / "config" / "keirin"
        config_dir.mkdir(parents=True)
        filters_file = config_dir / "filters.yaml"
        # 全チェック通過するシンプルな設定（F8/score_spread/F10を無効化）
        filters_file.write_text(yaml.dump({
            "class": ["S"],
            "race_type": ["特選", "予選", "一予選", "初特選", "一般", "一次予選"],
            "exclude_velodromes": [],
            "exclude_track_500m": False,
            "exclude_day_of_week": [],
            "exclude_race_number": [],
            "expected_payout_min": 0,
            "expected_payout_max": 9999999,
            "min_score_spread": 0,
            "min_confidence_score": 0,
        }, allow_unicode=True), encoding="utf-8")

        from src.filter_engine import FilterEngine
        filter_engine = FilterEngine(str(filters_file), sport="keirin")
        profile = {"predictor_name": "test", "profile_id": "test"}
        config = {
            "llm": {"model": "claude-haiku-4-5-20251001"},
            "pipeline": {"config_dir": str(tmp_path / "config")},
        }
        race = {
            "venue_name": "川崎",
            "race_no": "9",
            "grade": "S1",
            "stage": "特選",
            "sport": "keirin",
            "entries": [
                _make_entry(1, "選手A", 100.0),
                _make_entry(2, "選手B", 110.0),
                _make_entry(3, "選手C", 95.0),
            ],
        }
        return race, filter_engine, profile, config

    def test_mock_and_dryrun_both_true_generates_mock(self, tmp_path):
        """dry_run=True + mock_mode=True → mock予想が生成されること（W-1修正の核心）。
        根拠: W-1修正後、mock_mode が dry_run より優先される。
        手計算: result["prediction"]["text"] に「本命:」含む。「[DRY RUN]」は含まない。"""
        import main as main_mod
        race, fe, profile, config = self._make_process_race_inputs(tmp_path)

        result = main_mod.process_race(
            race, fe, profile, config,
            dry_run=True, mock_mode=True,
        )

        pred = result.get("prediction", {}).get("text", "")
        assert "本命:" in pred, (
            f"dry_run=True+mock_mode=True → mock予想('本命:')が期待値だが実際: '{pred[:80]}'"
        )
        assert "[DRY RUN]" not in pred, (
            "mock_modeがdry_runより優先されるべきなのに[DRY RUN]テキストが生成された"
        )
        assert result.get("mock_mode") is True, "mock_mode=True が result に記録されるべき"

    def test_dryrun_only_generates_dryrun_text(self, tmp_path):
        """dry_run=True + mock_mode=False → 従来通り [DRY RUN] テキストが生成されること。
        根拠: W-1修正後も dry_run=True 単独の動作は変わらない。
        手計算: result["prediction"]["text"] に「[DRY RUN]」含む。"""
        import main as main_mod
        race, fe, profile, config = self._make_process_race_inputs(tmp_path)

        result = main_mod.process_race(
            race, fe, profile, config,
            dry_run=True, mock_mode=False,
        )

        pred = result.get("prediction", {}).get("text", "")
        assert "[DRY RUN]" in pred, (
            f"dry_run=True+mock_mode=False → '[DRY RUN]'が期待値だが実際: '{pred[:80]}'"
        )
        assert "本命:" not in pred, "dry_run単独ではmock予想は生成されない"
        assert result.get("mock_mode") is not True, "dry_run単独ではmock_modeフラグは記録されない"

    def test_mock_only_generates_mock(self, tmp_path):
        """dry_run=False + mock_mode=True → mock予想が生成されること（既存動作確認）。
        根拠: 修正前から動作していたパターン。回帰テスト。
        手計算: result["prediction"]["text"] に「本命:」含む。"""
        import main as main_mod
        race, fe, profile, config = self._make_process_race_inputs(tmp_path)

        result = main_mod.process_race(
            race, fe, profile, config,
            dry_run=False, mock_mode=True,
        )

        pred = result.get("prediction", {}).get("text", "")
        assert "本命:" in pred, (
            f"dry_run=False+mock_mode=True → mock予想('本命:')が期待値だが実際: '{pred[:80]}'"
        )
        assert "[DRY RUN]" not in pred, "mock_mode単独では[DRY RUN]テキストは生成されない"
        assert result.get("mock_mode") is True, "mock_mode=True が result に記録されるべき"

    def test_neither_dryrun_nor_mock_goes_to_api_path(self, tmp_path):
        """dry_run=False + mock_mode=False → 実API呼び出しパスに到達すること（APIはmockで代替）。
        根拠: W-1修正後も通常パスは変わらない。mock_modeフラグが記録されない。
        ※ 実API呼び出しはテスト内でモックして回避する。"""
        import main as main_mod
        race, fe, profile, config = self._make_process_race_inputs(tmp_path)

        # generate_prediction をモックして実際のAPI呼び出しを回避
        with patch("main.generate_prediction", return_value="軸: 1番\n相手: 2番、3番\nコメント: テスト"):
            result = main_mod.process_race(
                race, fe, profile, config,
                dry_run=False, mock_mode=False,
            )

        assert result is not None, "process_race() は None を返さない"
        assert result.get("mock_mode") is not True, "mock_mode=False なのに mock フラグが立っている"
        # 通常パスでは prediction["text"] に実APIの応答が入る
        pred = result.get("prediction", {}).get("text", "")
        assert "軸: 1番" in pred, f"通常パスでmock応答が返るはず: '{pred[:80]}'"
