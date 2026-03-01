"""
tests/test_real_data_pipeline.py
==================================
実データを使ったパイプライン通しテスト（cmd_139k_sub2）

検証方針:
- ANTHROPIC_API_KEY 不要（Stage2 LLM呼び出し部分は対象外）
- data/fixtures/keirin_20260301.json を入力として実フィルター評価
- data/results/20260228_results.json を使って result_collector の実データ検証
- cron.log との突合（3/1の実行ログ = 44件全フィルター不合格）

テスト期待値の根拠:
- 20260301 は日曜日（F6: 月・日は除外）→ 全44件フィルター不合格
- 武雄（7件）: F4でも除外（低回収率場リスト）
- 向日町（11件）: score_spread=9.18 < 12 → score_spreadフィルターも不合格
- 20260228_results.json: 予測あり2件（大垣12R・和歌山12R）、いずれも外れ

殿の指示: 「きちんと実データでテストしろ」（cmd_139k）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.filter_engine import FilterEngine

# ── パス定数 ──────────────────────────────────────────────────────────────────
FIXTURES_DIR = ROOT / "data" / "fixtures"
RESULTS_DIR = ROOT / "data" / "results"
LOGS_DIR = ROOT / "data" / "logs"
FIXTURE_20260301 = FIXTURES_DIR / "keirin_20260301.json"
RESULTS_20260228 = RESULTS_DIR / "20260228_results.json"
CRON_LOG = LOGS_DIR / "cron.log"
FILTERS_YAML = ROOT / "config" / "keirin" / "filters.yaml"


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── TestStage1RealData ───────────────────────────────────────────────────────


class TestStage1RealData:
    """
    Stage 1: 実データ（20260301 fixture）でフィルター評価

    テスト根拠:
    - 20260301 = 日曜日（Python: datetime(2026,3,1).weekday()==6）
    - F6[曜日]: 日 は除外リスト → 全44件がフィルター不合格
    - 現コード（cmd_136k_sub1）: filter=none の場合は requests/ に書き出さない（continue）
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = FilterEngine(str(FILTERS_YAML), sport="keirin")
        self.races = load_json(FIXTURE_20260301)

    def test_fixture_total_race_count(self):
        """fixture の総レース数が 44 件であること

        根拠: keirin_20260301.json を json.load した len()
        実行: python3 -c "import json; print(len(json.load(open('data/fixtures/keirin_20260301.json'))))"
        → 44
        """
        assert len(self.races) == 44, f"Expected 44 races, got {len(self.races)}"

    def test_fixture_venue_distribution(self):
        """fixture の競輪場別内訳が正しいこと

        根拠: cron.log + fixture 直接確認
        - 向日町: 11件
        - 武雄: 7件
        - kishiwada: 7件
        - komatsushima: 7件
        - kurume: 12件
        """
        from collections import Counter
        venue_counts = Counter(r["venue_name"] for r in self.races)
        assert venue_counts["向日町"] == 11, f"向日町: {venue_counts['向日町']}"
        assert venue_counts["武雄"] == 7, f"武雄: {venue_counts['武雄']}"
        assert venue_counts["kishiwada"] == 7, f"kishiwada: {venue_counts['kishiwada']}"
        assert venue_counts["komatsushima"] == 7, f"komatsushima: {venue_counts['komatsushima']}"
        assert venue_counts["kurume"] == 12, f"kurume: {venue_counts['kurume']}"

    def test_20260301_is_sunday(self):
        """20260301 が日曜日であること（F6フィルター前提の確認）

        根拠: datetime(2026,3,1).weekday() == 6（月曜=0, 日曜=6）
        """
        dt = datetime(2026, 3, 1)
        assert dt.weekday() == 6, "20260301 must be Sunday"

    def test_all_44_races_fail_filter(self):
        """全44件がフィルター不合格になること

        根拠:
        1. F6[曜日]: 20260301=日曜 → 全件除外
        2. 武雄はF4[競輪場]でも除外
        3. kishiwada/komatsushima/kurume はA級・非対象種別でF1・F2も不合格
        """
        passed_count = 0
        for race in self.races:
            passed, reasons = self.engine.apply(race)
            if passed:
                passed_count += 1
        assert passed_count == 0, f"Expected 0 passed races, got {passed_count}"

    def test_f6_sunday_filter_applies_to_all_races(self):
        """F6[曜日]フィルターが全44件に適用されること

        根拠: date="20260301" → 日曜 → F6除外理由に "F6[曜日]" が含まれる
        """
        for race in self.races:
            passed, reasons = self.engine.apply(race)
            assert not passed, f"{race['venue_name']} {race['race_no']}R should fail filter"
            f6_reasons = [r for r in reasons if "F6[曜日]" in r]
            assert len(f6_reasons) > 0, (
                f"F6 reason missing for {race['venue_name']} {race['race_no']}R: {reasons}"
            )

    def test_takeo_fails_f4_velodrome_filter(self):
        """武雄がF4[競輪場]（低回収率場）でも除外されること

        根拠: filters.yaml の exclude_velodromes に 武雄 が含まれる
        """
        takeo_races = [r for r in self.races if r["venue_name"] == "武雄"]
        assert len(takeo_races) == 7, f"Expected 7 武雄 races, got {len(takeo_races)}"
        for race in takeo_races:
            passed, reasons = self.engine.apply(race)
            assert not passed
            f4_reasons = [r for r in reasons if "F4[競輪場]" in r and "武雄" in r]
            assert len(f4_reasons) > 0, (
                f"F4 reason missing for 武雄 {race['race_no']}R: {reasons}"
            )

    def test_filter_type_none_count_equals_44(self):
        """filter_type=none になるレース数が 44 件であること

        根拠: 全件フィルター不合格 → filter_type="none"
        cron.log: Stage 1 完了: 44件のリクエストを生成（旧コード）
        現コード: 全44件がcontinueされ generated=0
        """
        none_count = sum(1 for r in self.races if not self.engine.apply(r)[0])
        assert none_count == 44

    def test_muko_1r_score_spread_below_threshold(self):
        """向日町1R の score_spread が閾値 12 未満であること

        根拠（手計算）:
        向日町1R エントリースコア: [68.3, 70.62, 69.59, 68.37, 75.18, 66.0, 73.0]
        max=75.18, min=66.0 → spread=9.18 < 12（min_score_spread=12）
        → score_spread フィルターも不合格
        """
        muko_1r = next(
            (r for r in self.races if r["venue_name"] == "向日町" and r["race_no"] == "1"),
            None,
        )
        assert muko_1r is not None, "向日町1R should exist in fixture"

        scores = [
            float(e["score"])
            for e in muko_1r["entries"]
            if e.get("score") is not None and float(e.get("score", 0)) > 0
        ]
        assert len(scores) == 7, f"Expected 7 entries with scores, got {len(scores)}"
        spread = max(scores) - min(scores)
        assert spread < 12, f"Expected spread < 12 (=min_score_spread), got {spread:.2f}"

        # FilterEngine での確認（複合フィルター）
        passed, reasons = self.engine.apply(muko_1r)
        assert not passed

    def test_stage1_current_code_generates_zero_requests(self):
        """現コード（cmd_136k_sub1）では 0 件の request が生成されること

        根拠:
        - 全44件が filter 不合格（filter_type=none）
        - cmd_136k_sub1: `continue` により requests/ 書き出しをスキップ
        - generated カウンターが 0 のまま
        """
        generated = 0
        for race in self.races:
            passed, _ = self.engine.apply(race)
            if passed:
                # passed のみ生成（現コードの動作）
                generated += 1
            # not passed: continue（cmd_136k_sub1 の動作 → 書き出しスキップ）
        assert generated == 0, f"Expected 0 requests generated, got {generated}"

    def test_entry_data_structure_all_races(self):
        """全レースの entries データ構造が正しいこと"""
        for race in self.races:
            assert "venue_name" in race
            assert "race_no" in race
            assert "entries" in race
            assert isinstance(race["entries"], list)
            for entry in race["entries"]:
                assert "car_no" in entry, f"car_no missing: {entry}"
                assert isinstance(entry["car_no"], int)
                assert 1 <= entry["car_no"] <= 9  # 車番は 1-9
                assert "name" in entry
                assert "grade" in entry
                assert "leg_type" in entry


# ─── TestPipelineIntegration ──────────────────────────────────────────────────


class TestPipelineIntegration:
    """
    パイプライン結合テスト
    fixtures読み込み → フィルター適用 → データ型・構造検証
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = FilterEngine(str(FILTERS_YAML), sport="keirin")
        self.races = load_json(FIXTURE_20260301)

    def test_filter_engine_return_types(self):
        """FilterEngine.apply() の戻り値型が正しいこと"""
        for race in self.races[:3]:
            result = self.engine.apply(race)
            assert isinstance(result, tuple), "apply() should return tuple"
            assert len(result) == 2
            passed, reasons = result
            assert isinstance(passed, bool)
            assert isinstance(reasons, list)
            for reason in reasons:
                assert isinstance(reason, str)

    def test_classify_returns_valid_structure(self):
        """FilterEngine.classify() の戻り値構造が正しいこと"""
        for race in self.races[:5]:
            result = self.engine.classify(race)
            assert isinstance(result, dict)
            assert "type" in result, "classify() should return 'type'"
            assert result["type"] in ("A", "B", "C"), f"Unknown type: {result['type']}"
            assert "confidence" in result
            assert isinstance(result["confidence"], int)
            assert 0 <= result["confidence"] <= 3
            assert "reasons" in result
            assert isinstance(result["reasons"], list)

    def test_invalid_race_empty_entries(self):
        """entries が空のレースでもエラーが発生しないこと"""
        empty_race = {"venue_name": "unknown", "date": "20260301", "entries": []}
        passed, reasons = self.engine.apply(empty_race)
        assert isinstance(passed, bool)
        assert isinstance(reasons, list)

    def test_race_without_date_skips_f6(self):
        """date フィールドがないレースでは F6[曜日] がスキップされること

        根拠: FilterEngine._check_day_of_week() は date が空の場合 True を返す
        """
        race_no_date = {
            "venue_name": "川崎",
            "race_no": "9",
            "race_num": 9,
            "grade": "S",
            "stage": "特選",
            "bank_length": 400,
            "entries": [],
        }
        _, reasons = self.engine.apply(race_no_date)
        f6_reasons = [r for r in reasons if "F6[曜日]" in r]
        assert len(f6_reasons) == 0, "F6 should be skipped when date field is missing"

    def test_s_class_tokusen_weekday_passes_filter(self):
        """S級×特選×平日（水曜）×適正会場のレースがフィルターを通過すること

        根拠（手計算）:
        - F1: grade="S" → 通過
        - F2: stage="特選" → filters.yaml race_type に含む → 通過
        - F4: venue_name="川崎" → 除外リストなし → 通過
        - F5: bank_length=400 → 500m ではない → 通過
        - F6: date="20260225"（水曜） → 除外日でない → 通過
        - F7: race_num=9 → 4,6 でない → 通過
        - F8: expected_payout=None → スキップ → 通過
        - score_spread: 設定された min_score_spread=12、スコア差=80-60=20 >= 12 → 通過
        """
        passing_race = {
            "venue_name": "川崎",
            "race_no": "9",
            "race_num": 9,
            "grade": "S",
            "stage": "特選",
            "bank_length": 400,
            "date": "20260225",  # 水曜日
            "entries": [
                {"car_no": i, "name": f"選手{i}", "grade": "S1", "score": 60 + i * 4}
                for i in range(1, 8)
            ],
        }
        passed, reasons = self.engine.apply(passing_race)
        assert passed, f"S級特選川崎水曜 should pass filter, reasons: {reasons}"

    def test_sunday_race_never_passes(self):
        """日曜日のレースは他の条件が揃っていてもフィルターを通過しないこと"""
        sunday_race = {
            "venue_name": "川崎",
            "race_no": "9",
            "race_num": 9,
            "grade": "S",
            "stage": "特選",
            "bank_length": 400,
            "date": "20260301",  # 日曜日
            "entries": [],
        }
        passed, reasons = self.engine.apply(sunday_race)
        assert not passed, "Sunday race should always fail filter"
        f6_reasons = [r for r in reasons if "F6[曜日]" in r]
        assert len(f6_reasons) > 0

    def test_full_data_flow_first_5_races(self):
        """最初の5レースでフルデータフローが正常に動作すること"""
        pipeline_results = []
        for race in self.races[:5]:
            passed, reasons = self.engine.apply(race)
            classification = self.engine.classify(race)
            pipeline_results.append(
                {
                    "venue": race["venue_name"],
                    "race_no": race["race_no"],
                    "passed": passed,
                    "reasons": reasons,
                    "type": classification["type"],
                    "confidence": classification["confidence"],
                }
            )

        assert len(pipeline_results) == 5
        for r in pipeline_results:
            assert r["passed"] == False  # 全件日曜日のため
            assert r["type"] in ("A", "B", "C")
            assert isinstance(r["confidence"], int)


# ─── TestCronLogVerification ──────────────────────────────────────────────────


class TestCronLogVerification:
    """
    cron.log（3/1 07:02 実行分）との突合テスト

    検証目的:
    - cron.log が記録した 44 件と fixture の件数が一致すること
    - 日曜除外（F6）の理由文言が一致すること
    - 武雄のフィルター理由が一致すること
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races = load_json(FIXTURE_20260301)
        self.engine = FilterEngine(str(FILTERS_YAML), sport="keirin")
        with open(CRON_LOG, encoding="utf-8") as f:
            self.cron_log = f.read()

    def test_cron_log_stage1_completion_message(self):
        """cron.log に Stage 1 完了（44件）のメッセージが記録されていること

        根拠: cron.log 末尾
        "=== Stage 1 完了: 44件のリクエストを生成 ==="
        """
        assert "Stage 1 完了: 44件のリクエストを生成" in self.cron_log, (
            "cron.log should record '44件のリクエストを生成' for 20260301"
        )

    def test_fixture_count_matches_cron_log(self):
        """fixture の総レース数（44）が cron.log の記録と一致すること"""
        assert len(self.races) == 44

    def test_all_races_fail_filter_consistent_with_cron_log(self):
        """FilterEngine で全44件が不合格になること（cron.logの記録と整合）

        根拠:
        - cron.log: "[フィルター不合格]" が44回記録（旧コードでも全件除外）
        - 現FilterEngine でも同様に全件除外されることを確認
        """
        filter_failed_count = sum(
            1 for r in self.races if not self.engine.apply(r)[0]
        )
        assert filter_failed_count == 44

    def test_f6_sunday_exclusion_in_cron_log(self):
        """cron.log に日曜除外（F6）の文言が記録されていること"""
        assert "F6[曜日]: 日曜日は除外対象" in self.cron_log, (
            "cron.log should contain F6 Sunday exclusion message"
        )

    def test_f6_applies_to_all_races_in_fixture(self):
        """fixture の全44件に F6[曜日] が適用されること（cron.logと整合）"""
        for race in self.races:
            _, reasons = self.engine.apply(race)
            f6_hit = any("F6[曜日]" in r for r in reasons)
            assert f6_hit, (
                f"F6 should apply to all races. "
                f"Missing for {race['venue_name']} {race['race_no']}R"
            )

    def test_takeo_f4_in_cron_log(self):
        """cron.log に武雄のF4[競輪場]除外が記録されていること"""
        assert "F4[競輪場]: '武雄' は低回収率場" in self.cron_log, (
            "cron.log should contain F4 武雄 exclusion message"
        )

    def test_takeo_f4_consistent_with_filter_engine(self):
        """FilterEngine の武雄F4結果が cron.log の記録と一致すること"""
        takeo_races = [r for r in self.races if r["venue_name"] == "武雄"]
        assert len(takeo_races) == 7
        for race in takeo_races:
            _, reasons = self.engine.apply(race)
            f4_hit = any("F4[競輪場]" in r and "武雄" in r for r in reasons)
            assert f4_hit, f"F4 武雄 should appear in reasons for 武雄 {race['race_no']}R"


# ─── TestResultCollector ──────────────────────────────────────────────────────


class TestResultCollector:
    """
    実データ result_collector テスト

    データ: data/results/20260228_results.json
    検証: 払戻金集計・hit/miss判定・データ構造
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_json(RESULTS_20260228)
        self.races = self.data["races"]

    def test_results_file_basic_structure(self):
        """20260228_results.json の基本構造が正しいこと"""
        assert self.data["date"] == "20260228"
        assert "fetched_at" in self.data
        assert "races" in self.data
        assert isinstance(self.races, list)
        assert len(self.races) > 0

    def test_all_races_have_required_fields(self):
        """全レースエントリに必須フィールドが含まれること"""
        required_fields = ["venue", "race_no", "trifecta_result", "trifecta_payout",
                           "trio_result", "trio_payout"]
        for race in self.races:
            for field in required_fields:
                assert field in race, f"Field '{field}' missing from race: {race}"

    def test_trifecta_trio_relationship(self):
        """3連単と3連複の関係（3連複 = 3連単の昇順ソート）が正しいこと

        根拠: collect_results.py の race_entry 生成ロジック
        "trio_result": sorted(top3[:3]) if top3 else []
        """
        for race in self.races:
            trifecta = race.get("trifecta_result", [])
            trio = race.get("trio_result", [])
            if trifecta and trio:
                assert sorted(trifecta) == sorted(trio), (
                    f"trio should be sorted trifecta: "
                    f"trifecta={trifecta}, trio={trio} "
                    f"({race['venue']} {race['race_no']}R)"
                )

    def test_predictions_exist_in_results(self):
        """予測あり（our_prediction）のレースが含まれること"""
        predicted = [r for r in self.races if r.get("our_prediction") is not None]
        assert len(predicted) > 0, "Should have at least one race with our_prediction"

    def test_hit_miss_field_types(self):
        """hit/miss フィールドの型が正しいこと"""
        for race in self.races:
            if "our_prediction" in race:
                assert "hit" in race, f"'hit' field missing: {race}"
                assert isinstance(race["hit"], bool)
                assert "payout" in race
                assert isinstance(race["payout"], int)
                assert race["payout"] >= 0

    def test_oogaki_12r_data(self):
        """大垣12R: 実データの確認（予測あり・外れ・払戻0）

        根拠（20260228_results.json 直接確認）:
        - 3連単結果: [9, 2, 3]
        - 我々の予測: 軸5, 相手[1,1] → combinations=[[1,1,5]]
        - [1,1,5] ≠ [2,3,9] → 外れ
        - payout: 0
        """
        oogaki_12r = next(
            (r for r in self.races if r["venue"] == "大垣" and r["race_no"] == 12), None
        )
        assert oogaki_12r is not None, "大垣12R should exist"
        assert oogaki_12r["trifecta_result"] == [9, 2, 3], (
            f"Expected [9,2,3], got {oogaki_12r['trifecta_result']}"
        )
        assert oogaki_12r["hit"] == False
        assert oogaki_12r["payout"] == 0
        pred = oogaki_12r["our_prediction"]
        assert pred["axis"] == 5
        assert pred["investment"] == 1200

    def test_wakayama_12r_data(self):
        """和歌山12R: 実データの確認（予測あり・外れ・払戻0）

        根拠（20260228_results.json 直接確認）:
        - 3連単結果: [4, 5, 7], 3連複: [4, 5, 7]
        - 我々の予測: 軸4, 相手[2,6,6] → combinations=[[2,4,6],[2,4,6],[4,6,6]]
        - 3連複 [4,5,7] は 上記組み合わせに含まれない → 外れ
        """
        wakayama_12r = next(
            (r for r in self.races if r["venue"] == "和歌山" and r["race_no"] == 12), None
        )
        assert wakayama_12r is not None, "和歌山12R should exist"
        assert wakayama_12r["hit"] == False
        assert wakayama_12r["payout"] == 0
        pred = wakayama_12r["our_prediction"]
        assert pred["axis"] == 4
        assert pred["investment"] == 3600

    def test_total_investment_20260228(self):
        """20260228 の合計投資額が 4800 円であること

        根拠（手計算）:
        - 大垣12R: investment=1200 円
        - 和歌山12R: investment=3600 円
        - 合計: 4800 円
        """
        total = sum(
            r["our_prediction"]["investment"]
            for r in self.races
            if r.get("our_prediction") is not None
        )
        assert total == 4800, f"Expected total investment 4800, got {total}"

    def test_check_hit_trio_miss_real_data(self):
        """check_hit(): 大垣12Rの外れを実データで検証

        根拠（手計算）:
        - 3連複結果: sorted([9,2,3]) = [2,3,9]
        - 我々の組合せ: sorted([1,1,5]) = [1,1,5]
        - [1,1,5] ≠ [2,3,9] → 外れ, payout=0
        """
        from collect_results import check_hit

        bet = {
            "axis": 5,
            "partners": [1, 1],
            "bet_type": "3連複ながし",
            "combinations": [[1, 1, 5]],
            "unit_bet": 100,
        }
        race_result = {
            "top3": [9, 2, 3],
            "payouts": {
                "trio": [{"numbers": [2, 3, 9], "payout": 2870}],
                "trifecta": [{"numbers": [9, 2, 3], "payout": 20210}],
            },
        }
        hit, payout = check_hit(bet, race_result)
        assert hit == False
        assert payout == 0

    def test_check_hit_trio_hit_scenario(self):
        """check_hit(): 3連複的中シナリオ（仮想データ）

        根拠（手計算）:
        - 結果: top3=[3,1,5], trio_result=sorted([3,1,5])=[1,3,5]
        - 組合せ: sorted([1,3,5])=[1,3,5]
        - [1,3,5] == [1,3,5] → 的中
        - payout = (5000 * 100) // 100 = 5000 円
        """
        from collect_results import check_hit

        bet = {
            "axis": 1,
            "partners": [3, 5],
            "bet_type": "3連複ながし",
            "combinations": [[1, 3, 5]],
            "unit_bet": 100,
        }
        race_result = {
            "top3": [3, 1, 5],
            "payouts": {
                "trio": [{"numbers": [1, 3, 5], "payout": 5000}],
            },
        }
        hit, payout = check_hit(bet, race_result)
        assert hit == True
        assert payout == 5000

    def test_check_hit_no_top3_returns_false(self):
        """top3 が空の場合 check_hit() が False を返すこと"""
        from collect_results import check_hit

        bet = {"bet_type": "3連複ながし", "combinations": [[1, 2, 3]], "unit_bet": 100}
        race_result = {"top3": [], "payouts": {}}
        hit, payout = check_hit(bet, race_result)
        assert hit == False
        assert payout == 0

    def test_split_nums_utility(self):
        """_split_nums() ユーティリティ関数の動作確認

        根拠: collect_results._parse_refund_table() 内部で使用
        - "2=3=9" → [2, 3, 9]（3連複）
        - "9-2-3" → [9, 2, 3]（3連単）
        - "text" → []（数字なし）
        """
        from collect_results import _split_nums

        assert _split_nums("2=3=9", "=") == [2, 3, 9]
        assert _split_nums("9-2-3", "-") == [9, 2, 3]
        assert _split_nums("テキスト", "=") == []
        assert _split_nums("1=2", "=") == [1, 2]
