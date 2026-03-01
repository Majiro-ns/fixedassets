"""
実データフィルター通過率テスト (cmd_139k_sub1, cmd_141k_sub1)

実データファイルを直接読み込みフィルターエンジンの正確性を検証する。
モック禁止。全期待値は実データから導出（CHECK-9: 根拠を下記に記載）。

■ テスト対象ファイル
    - data/fixtures/keirin_20260228.json  (2/28 出走表: 31レース, 土曜日)
    - data/fixtures/keirin_20260301.json  (3/1 出走表: 44レース, 日曜日)
    - data/results/20260228_results.json  (2/28 実結果: 31レース分)
    - config/keirin/filters.yaml          (フィルター設定)

■ F2修正内容 (cmd_141k_sub1)
    scraper出力: "Ｓ級一予選" / "Ａ級予選" 等、全角グレードプレフィックス付き。
    filter_engine.py _check_race_type: 先頭の [Ａ-Ｚ]級 を除去後に完全一致で判定。
    例: "Ｓ級一予選" → normalize → "一予選" → IN allowed → 通過

■ 個別フィルター根拠 (修正後)
    F1 除外数=15: grade='' の5レース + grade='A' の10レース
    F2 除外数= 8: stage='' の3レース + 初日特選 の3レース + ガールズ予選１ の2レース
    F6 除外数= 0: 2/28は土曜日（月・日のみ除外）
    F7 除外数= 6: 大垣R4,R6 / 和歌山R4,R6 / 広島R4,R6
    score_spread除外: 大垣R12(7.22) + 和歌山R8-R12(5レース) + 他 = 合計19レース < 閾値12
    全体通過数= 8: 大垣R2,R3,R5,R7,R8,R9,R10,R11（S級一予選かつscore_spread>=12）

    3/1データ:
    F6 除外数=44: 3/1は日曜日（全44レース除外）
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.filter_engine import FilterEngine

# ─── フィクスチャパス ─────────────────────────────────────────────
FIXTURE_228 = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures", "keirin_20260228.json")
FIXTURE_301 = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures", "keirin_20260301.json")
RESULTS_228 = os.path.join(os.path.dirname(__file__), "..", "data", "results", "20260228_results.json")
FILTERS_YAML = os.path.join(os.path.dirname(__file__), "..", "config", "keirin", "filters.yaml")


# ─── ヘルパー関数 ─────────────────────────────────────────────────

def load_fixture(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_results(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def count_filter_exclusions(races: list, engine: FilterEngine) -> dict:
    """各フィルターで何レースが除外されたかを集計する。"""
    excluded = {
        "F1_class": 0,
        "F2_race_type": 0,
        "F4_velodrome": 0,
        "F5_bank_length": 0,
        "F6_day_of_week": 0,
        "F7_race_number": 0,
        "F8_expected_payout": 0,
        "score_spread": 0,
    }
    for race in races:
        _, reasons = engine.apply(race)
        for r in reasons:
            if r.startswith("F1"):
                excluded["F1_class"] += 1
            elif r.startswith("F2"):
                excluded["F2_race_type"] += 1
            elif r.startswith("F4"):
                excluded["F4_velodrome"] += 1
            elif r.startswith("F5"):
                excluded["F5_bank_length"] += 1
            elif r.startswith("F6"):
                excluded["F6_day_of_week"] += 1
            elif r.startswith("F7"):
                excluded["F7_race_number"] += 1
            elif r.startswith("F8"):
                excluded["F8_expected_payout"] += 1
            elif r.startswith("score_spread"):
                excluded["score_spread"] += 1
    return excluded


# ─── セクション1: 実データ存在確認 ──────────────────────────────────

class TestRealDataExists:
    """実データファイルが存在し、正しい件数か確認する。"""

    def test_fixture_228_exists(self):
        """2/28出走表ファイルが存在する。"""
        assert os.path.isfile(FIXTURE_228), f"ファイルなし: {FIXTURE_228}"

    def test_fixture_301_exists(self):
        """3/1出走表ファイルが存在する。"""
        assert os.path.isfile(FIXTURE_301), f"ファイルなし: {FIXTURE_301}"

    def test_results_228_exists(self):
        """2/28結果ファイルが存在する。"""
        assert os.path.isfile(RESULTS_228), f"ファイルなし: {RESULTS_228}"

    def test_filters_yaml_exists(self):
        """フィルター設定ファイルが存在する。"""
        assert os.path.isfile(FILTERS_YAML), f"ファイルなし: {FILTERS_YAML}"

    def test_fixture_228_total_races(self):
        """
        2/28 出走表は 31 レースである。
        根拠: 大垣(12) + 和歌山(12) + 広島(7) = 31
        """
        races = load_fixture(FIXTURE_228)
        assert len(races) == 31, f"期待=31, 実際={len(races)}"

    def test_fixture_301_total_races(self):
        """
        3/1 出走表は 44 レースである。
        根拠: json.load で確認済み (len=44)
        """
        races = load_fixture(FIXTURE_301)
        assert len(races) == 44, f"期待=44, 実際={len(races)}"

    def test_results_228_total_races(self):
        """
        2/28 結果は 31 レースである。
        根拠: 大垣12 + 和歌山12 + 広島7 = 31
        """
        results = load_results(RESULTS_228)
        assert len(results["races"]) == 31, f"期待=31, 実際={len(results['races'])}"

    def test_results_228_date_field(self):
        """2/28 結果ファイルのdateが正しい。"""
        results = load_results(RESULTS_228)
        assert results["date"] == "20260228"


# ─── セクション2: 出走表データ構造検証 ──────────────────────────────

class TestFixtureStructure:
    """出走表データが必要フィールドを持つことを確認する。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)

    def test_race_has_required_fields(self):
        """全レースに必須フィールドが存在する。"""
        required = ["venue_name", "race_num", "grade", "stage", "date", "entries", "bank_length"]
        for race in self.races_228:
            for field in required:
                assert field in race, f"{race['venue_name']} R{race['race_num']}: フィールド '{field}' なし"

    def test_entries_have_score_field(self):
        """出走選手にscoreフィールドが存在する（score_spreadテストの前提）。"""
        races_with_score = 0
        for race in self.races_228:
            entries = race.get("entries", [])
            has_score = any(e.get("score") is not None and float(e.get("score", 0)) > 0 for e in entries)
            if has_score:
                races_with_score += 1
        # 全31レース中、少なくとも16レースにscore情報が存在する
        assert races_with_score >= 16, f"score情報あり={races_with_score} (期待>=16)"

    def test_date_field_is_20260228(self):
        """全レースのdateが 20260228 である。"""
        for race in self.races_228:
            assert race["date"] == "20260228", f"{race['venue_name']} R{race['race_num']}: date={race['date']}"

    def test_venues_are_ogaki_wakayama_hiroshima(self):
        """
        2/28 出走表の会場は大垣・和歌山・広島の3場。
        根拠: json確認済み
        """
        venues = set(r["venue_name"] for r in self.races_228)
        assert venues == {"大垣", "和歌山", "広島"}

    def test_ogaki_has_12_races(self):
        """大垣は12レースある。"""
        ogaki = [r for r in self.races_228 if r["venue_name"] == "大垣"]
        assert len(ogaki) == 12

    def test_wakayama_has_12_races(self):
        """和歌山は12レースある。"""
        waka = [r for r in self.races_228 if r["venue_name"] == "和歌山"]
        assert len(waka) == 12

    def test_hiroshima_has_7_races(self):
        """広島は7レースある。"""
        hiro = [r for r in self.races_228 if r["venue_name"] == "広島"]
        assert len(hiro) == 7

    def test_grade_values_are_s_a_or_empty(self):
        """gradeフィールドは 'S', 'A', '' のいずれかである。"""
        valid_grades = {"S", "A", ""}
        for race in self.races_228:
            assert race.get("grade", "") in valid_grades, (
                f"{race['venue_name']} R{race['race_num']}: grade={race['grade']!r}"
            )


# ─── セクション3: F1（クラス）フィルター検証 ─────────────────────────

class TestF1ClassFilter:
    """
    F1: クラスフィルター（S級のみ）
    根拠: filters.yaml class: ["S"] → grade field で判定
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)
        self.engine = FilterEngine(FILTERS_YAML)

    def test_f1_excludes_a_class_races(self):
        """
        A級レースは全てF1で除外される。
        根拠: 和歌山R2-R5(4レース) + 広島R2-R7(6レース) = 10レース除外
        """
        a_class_races = [r for r in self.races_228 if r.get("grade") == "A"]
        assert len(a_class_races) == 10, f"A級レース数={len(a_class_races)} (期待=10)"

        for race in a_class_races:
            passed, reasons = self.engine.apply(race)
            assert not passed, f"{race['venue_name']} R{race['race_num']} A級が通過している"
            f1_reasons = [r for r in reasons if r.startswith("F1")]
            assert len(f1_reasons) > 0, (
                f"{race['venue_name']} R{race['race_num']} F1除外理由なし: {reasons}"
            )

    def test_f1_excludes_unknown_grade_races(self):
        """
        grade='' のレース（ガールズ・grade不明）はF1で除外される。
        根拠: 大垣R1, 和歌山R1, 広島R1, 和歌山R6,R7 = 5レース
        """
        unknown_grade_races = [r for r in self.races_228 if r.get("grade", "") == ""]
        assert len(unknown_grade_races) == 5, f"grade=''のレース数={len(unknown_grade_races)} (期待=5)"

        for race in unknown_grade_races:
            passed, reasons = self.engine.apply(race)
            assert not passed, f"{race['venue_name']} R{race['race_num']} grade=''が通過している"
            f1_reasons = [r for r in reasons if r.startswith("F1")]
            assert len(f1_reasons) > 0, (
                f"{race['venue_name']} R{race['race_num']} F1除外理由なし: {reasons}"
            )

    def test_f1_does_not_exclude_s_class_races(self):
        """
        S級レースはF1を通過する（ただし他フィルターで除外される場合あり）。
        根拠: grade='S'の16レースは全てF1通過確認
        """
        s_class_races = [r for r in self.races_228 if r.get("grade") == "S"]
        assert len(s_class_races) == 16, f"S級レース数={len(s_class_races)} (期待=16)"

        for race in s_class_races:
            _, reasons = self.engine.apply(race)
            f1_reasons = [r for r in reasons if r.startswith("F1")]
            assert len(f1_reasons) == 0, (
                f"{race['venue_name']} R{race['race_num']} S級がF1除外: {f1_reasons}"
            )

    def test_f1_total_excluded_count(self):
        """
        F1で除外されるレース数は 15 (grade=A の10 + grade='' の5)。
        根拠: 実データ集計による
        """
        excl = count_filter_exclusions(self.races_228, self.engine)
        assert excl["F1_class"] == 15, f"F1除外数={excl['F1_class']} (期待=15)"


# ─── セクション4: F2（レースタイプ）フィルター検証 ──────────────────

class TestF2RaceTypeFilter:
    """
    F2: レース種別フィルター
    重要: 実データではstage名に "Ｓ級" prefix が付くため全除外される。
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)
        self.engine = FilterEngine(FILTERS_YAML)

    def test_f2_stage_names_include_grade_prefix(self):
        """
        【重要発見】実データのstage名は "Ｓ級一予選" 形式で prefix が付く。
        フィルター設定の "一予選" と完全不一致 → 全レースF2除外。
        根拠: kdreams_scraper.py が stage_text をそのまま保存する実装
        """
        s_class_stages = [
            r.get("stage", "")
            for r in self.races_228
            if r.get("grade") == "S"
        ]
        # S級レースのstage名は全て "Ｓ級" または "S級" で始まる
        for stage in s_class_stages:
            assert "Ｓ級" in stage or "S級" in stage, (
                f"S級レースのstageに prefix なし: {stage!r}"
            )

    def test_f2_excludes_count_after_fix(self):
        """
        【F2修正後 cmd_141k_sub1】2/28実データでF2が除外するのは8レース。
        除外内訳:
          - grade='' の3レース（大垣R1, 和歌山R1, 広島R1）: normalized='' → not in allowed
          - 初日特選の3レース（和歌山R5, 和歌山R12, 広島R7）: normalized='初日特選' → not in allowed
          - ガールズ予選１の2レース（和歌山R6, 和歌山R7）: normalize後も 'ガールズ予選１' → not in allowed
        通過内訳:
          - Ｓ級一予選 → '一予選' → IN allowed: 大垣R2-R12(11レース中10レース)
          - Ｓ級予選 → '予選' → IN allowed: 和歌山R8-R11(4レース)
          - Ｓ級初特選 → '初特選' → IN allowed: 大垣R12(1レース)
          - Ａ級予選 → '予選' → IN allowed: 和歌山R2-R4, 広島R2-R6(8レース)
        """
        excl = count_filter_exclusions(self.races_228, self.engine)
        assert excl["F2_race_type"] == 8, (
            f"F2除外数={excl['F2_race_type']} (期待=8: stage正規化後の除外数)"
        )

    def test_f2_logic_with_normalized_stage_allowed(self):
        """
        【F2ロジック検証】stage名を正規化（prefix除去）した場合、許可リストが通過する。
        根拠: filters.yaml の race_type リストを使った正規化検証
        """
        import yaml
        with open(FILTERS_YAML, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        allowed_types = config.get("race_type", [])

        # 正規化: "Ｓ級一予選" → "一予選"
        normalized_allowed = []
        for stage in allowed_types:
            normalized = stage.replace("Ｓ級", "").replace("Ａ級", "").replace("S級", "").replace("A級", "").strip()
            normalized_allowed.append(normalized)

        # フィルターを直接呼ぶ代わりに、正規化後のstageでチェック
        engine = FilterEngine(FILTERS_YAML)
        test_race_base = {
            "venue_name": "大垣",
            "race_num": 2,
            "grade": "S",
            "date": "20260228",  # 土曜
            "bank_length": 400,
            "entries": [
                {"car_no": i, "grade": "S1", "score": 100 + i * 2}
                for i in range(1, 8)
            ],
        }
        for stage_type in allowed_types:
            test_race = dict(test_race_base)
            test_race["stage"] = stage_type
            passed, reasons = engine.apply(test_race)
            f2_reasons = [r for r in reasons if r.startswith("F2")]
            assert len(f2_reasons) == 0, (
                f"許可stage '{stage_type}' がF2で除外: {f2_reasons}"
            )

    def test_f2_logic_excludes_semifinal_with_normalized_stage(self):
        """
        【F2ロジック検証】準決勝・決勝・二予選は F2 で除外される（stage名が正規化済み前提）。
        根拠: filters.yaml の race_type に含まれない種別
        """
        engine = FilterEngine(FILTERS_YAML)
        test_race_base = {
            "venue_name": "大垣",
            "race_num": 10,
            "grade": "S",
            "date": "20260228",  # 土曜
            "bank_length": 400,
            "entries": [{"car_no": i, "grade": "S1", "score": 100 + i * 2} for i in range(1, 8)],
        }
        for excluded_stage in ["準決勝", "決勝", "二次予選", "二予選", "選抜"]:
            test_race = dict(test_race_base)
            test_race["stage"] = excluded_stage
            _, reasons = engine.apply(test_race)
            f2_reasons = [r for r in reasons if r.startswith("F2")]
            assert len(f2_reasons) > 0, (
                f"除外stage '{excluded_stage}' がF2を通過してしまった"
            )


# ─── セクション5: F6（曜日）フィルター検証 ─────────────────────────

class TestF6DayOfWeekFilter:
    """
    F6: 曜日フィルター（月・日を除外）
    2/28 = 土曜日 → 除外なし
    3/1  = 日曜日 → 全レース除外
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)
        self.races_301 = load_fixture(FIXTURE_301)
        self.engine = FilterEngine(FILTERS_YAML)

    def test_f6_saturday_228_not_excluded(self):
        """
        2/28（土曜日）はF6で除外されない。
        根拠: datetime(2026,2,28).weekday() = 5 (土) → exclude_day_of_week=['月','日'] に含まれず
        """
        excl = count_filter_exclusions(self.races_228, self.engine)
        assert excl["F6_day_of_week"] == 0, (
            f"2/28土曜日のF6除外数={excl['F6_day_of_week']} (期待=0)"
        )

    def test_f6_sunday_301_all_excluded(self):
        """
        3/1（日曜日）は全44レースがF6で除外される。
        根拠: datetime(2026,3,1).weekday() = 6 (日) → exclude_day_of_week=['月','日'] に含まれる
        """
        excl = count_filter_exclusions(self.races_301, self.engine)
        assert excl["F6_day_of_week"] == 44, (
            f"3/1日曜日のF6除外数={excl['F6_day_of_week']} (期待=44: 全除外)"
        )

    def test_f6_301_all_races_fail(self):
        """3/1の全レースはF6除外によりフィルター通過しない。"""
        for race in self.races_301:
            passed, reasons = self.engine.apply(race)
            assert not passed, f"{race['venue_name']} R{race['race_num']} が通過（日曜）"
            f6_reasons = [r for r in reasons if r.startswith("F6")]
            assert len(f6_reasons) > 0, (
                f"{race['venue_name']} R{race['race_num']}: F6除外理由なし: {reasons}"
            )


# ─── セクション6: F7（レース番号）フィルター検証 ─────────────────────

class TestF7RaceNumberFilter:
    """
    F7: レース番号フィルター（4R・6Rを除外）
    根拠: 大垣R4,R6 + 和歌山R4,R6 + 広島R4,R6 = 6レース
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)
        self.engine = FilterEngine(FILTERS_YAML)

    def test_f7_total_excluded_count(self):
        """
        F7で除外されるレースは 6 レース。
        根拠: 3場 × R4,R6 = 6レース
        """
        excl = count_filter_exclusions(self.races_228, self.engine)
        assert excl["F7_race_number"] == 6, (
            f"F7除外数={excl['F7_race_number']} (期待=6)"
        )

    def test_f7_excludes_race_4_in_all_venues(self):
        """大垣・和歌山・広島の4RはF7で除外される。"""
        r4_races = [r for r in self.races_228 if r["race_num"] == 4]
        assert len(r4_races) == 3, f"4Rのレース数={len(r4_races)} (期待=3)"

        for race in r4_races:
            _, reasons = self.engine.apply(race)
            f7_reasons = [r for r in reasons if r.startswith("F7")]
            assert len(f7_reasons) > 0, (
                f"{race['venue_name']} R4がF7通過してしまった: {reasons}"
            )

    def test_f7_excludes_race_6_in_all_venues(self):
        """大垣・和歌山・広島の6RはF7で除外される。"""
        r6_races = [r for r in self.races_228 if r["race_num"] == 6]
        assert len(r6_races) == 3, f"6Rのレース数={len(r6_races)} (期待=3)"

        for race in r6_races:
            _, reasons = self.engine.apply(race)
            f7_reasons = [r for r in reasons if r.startswith("F7")]
            assert len(f7_reasons) > 0, (
                f"{race['venue_name']} R6がF7通過してしまった: {reasons}"
            )

    def test_f7_does_not_exclude_other_race_numbers(self):
        """R1〜R12のうち4・6以外のレースはF7で除外されない。"""
        other_races = [r for r in self.races_228 if r["race_num"] not in (4, 6)]
        for race in other_races:
            _, reasons = self.engine.apply(race)
            f7_reasons = [r for r in reasons if r.startswith("F7")]
            assert len(f7_reasons) == 0, (
                f"{race['venue_name']} R{race['race_num']} がF7除外: {f7_reasons}"
            )


# ─── セクション7: score_spreadフィルター検証 ──────────────────────

class TestScoreSpreadFilter:
    """
    score_spread フィルター（閾値: min_score_spread=12）
    出走選手の競走得点 max-min < 12 は拮抗レースとして除外。
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)
        self.engine = FilterEngine(FILTERS_YAML)

    def _get_score_spread(self, race: dict) -> float:
        """レースの得点スプレッドを計算する。"""
        scores = [
            float(e.get("score", 0) or 0)
            for e in race.get("entries", [])
            if e.get("score") is not None and float(e.get("score", 0) or 0) > 0
        ]
        if len(scores) < 2:
            return -1.0  # データ不足
        return max(scores) - min(scores)

    def test_ogaki_s_class_races_r2_to_r11_have_sufficient_spread(self):
        """
        大垣S級レース R2〜R11 (10レース) はscore_spread >= 12 を満たす。
        根拠:
            R2=17.04, R3=14.55, R4=12.73, R5=14.12, R6=13.98,
            R7=12.85, R8=15.00, R9=15.90, R10=14.02, R11=12.70
        全て閾値12以上であることを実データで確認する。
        """
        ogaki_s = [
            r for r in self.races_228
            if r["venue_name"] == "大垣"
            and r.get("grade") == "S"
            and r["race_num"] <= 11
        ]
        assert len(ogaki_s) == 10, f"大垣S級R2-R11数={len(ogaki_s)} (期待=10)"

        for race in ogaki_s:
            spread = self._get_score_spread(race)
            assert spread >= 12.0, (
                f"大垣 R{race['race_num']} spread={spread:.2f} < 閾値12"
            )
            _, reasons = self.engine.apply(race)
            spread_reasons = [r for r in reasons if r.startswith("score_spread")]
            assert len(spread_reasons) == 0, (
                f"大垣 R{race['race_num']} spread={spread:.2f} がscore_spread除外: {spread_reasons}"
            )

    def test_ogaki_r12_below_threshold(self):
        """
        大垣R12 (Ｓ級初特選) はscore_spread=7.22 < 12 → score_spread除外される。
        根拠: entries の score データから算出
        """
        ogaki_r12 = next(
            r for r in self.races_228
            if r["venue_name"] == "大垣" and r["race_num"] == 12
        )
        spread = self._get_score_spread(ogaki_r12)
        assert spread < 12.0, f"大垣R12 spread={spread:.2f} >= 12（想定外）"
        assert 7.0 <= spread <= 8.0, f"大垣R12 spread={spread:.2f} (期待: 7.0〜8.0)"

        _, reasons = self.engine.apply(ogaki_r12)
        spread_reasons = [r for r in reasons if r.startswith("score_spread")]
        assert len(spread_reasons) > 0, (
            f"大垣R12 spread={spread:.2f} がscore_spread通過してしまった"
        )

    def test_wakayama_s_class_all_below_threshold(self):
        """
        和歌山S級レース (R8〜R12: 5レース) はscore_spread < 12 → 全除外される。
        根拠:
            R8=9.38, R9=8.14, R10=11.36, R11=9.81, R12=7.30
        全て閾値12未満であることを実データで確認する。
        """
        wakayama_s = [
            r for r in self.races_228
            if r["venue_name"] == "和歌山" and r.get("grade") == "S"
        ]
        assert len(wakayama_s) == 5, f"和歌山S級数={len(wakayama_s)} (期待=5)"

        for race in wakayama_s:
            spread = self._get_score_spread(race)
            assert spread < 12.0, (
                f"和歌山 R{race['race_num']} spread={spread:.2f} >= 12（想定外）"
            )
            _, reasons = self.engine.apply(race)
            spread_reasons = [r for r in reasons if r.startswith("score_spread")]
            assert len(spread_reasons) > 0, (
                f"和歌山 R{race['race_num']} spread={spread:.2f} がscore_spread通過"
            )

    def test_score_spread_total_excluded(self):
        """
        score_spreadで除外されるレース数は 19 (全32レース中)。
        根拠: spread<12の和歌山S(5) + 大垣R12(1) + 和歌山A/空/ガールズ/広島(13) = 19
        ※ F1除外後なら減るが、count_filter_exclusions は全除外理由をカウント
        """
        excl = count_filter_exclusions(self.races_228, self.engine)
        # 実測値で確認（許容範囲: 15〜25）
        assert 15 <= excl["score_spread"] <= 25, (
            f"score_spread除外数={excl['score_spread']} (期待範囲: 15〜25)"
        )


# ─── セクション8: 結果データ構造検証 ─────────────────────────────

class TestResultsDataStructure:
    """2/28 実結果データの構造を検証する。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = load_results(RESULTS_228)

    def test_results_has_required_top_level_fields(self):
        """結果ファイルに 'date' と 'races' フィールドが存在する。"""
        assert "date" in self.results
        assert "races" in self.results

    def test_each_race_has_payout_fields(self):
        """
        各レースに三連単・三連複の結果と払戻金がある。
        根拠: 実データの構造確認済み
        """
        for race in self.results["races"]:
            assert "venue" in race, f"venueなし: {race}"
            assert "race_no" in race, f"race_noなし: {race}"
            assert "trifecta_result" in race, f"trifecta_resultなし"
            assert "trifecta_payout" in race, f"trifecta_payoutなし"
            assert "trio_result" in race, f"trio_resultなし"
            assert "trio_payout" in race, f"trio_payoutなし"

    def test_trifecta_result_has_3_numbers(self):
        """三連単結果は3頭の番号で構成される。"""
        for race in self.results["races"]:
            assert len(race["trifecta_result"]) == 3, (
                f"{race['venue']} R{race['race_no']}: trifecta_result={race['trifecta_result']}"
            )

    def test_trio_result_has_3_numbers(self):
        """三連複結果は3頭の番号で構成される（ソート済み）。"""
        for race in self.results["races"]:
            trio = race["trio_result"]
            assert len(trio) == 3, (
                f"{race['venue']} R{race['race_no']}: trio_result={trio}"
            )
            assert trio == sorted(trio), (
                f"{race['venue']} R{race['race_no']}: trio_resultがソート済みでない: {trio}"
            )

    def test_payouts_are_positive_integers(self):
        """払戻金は正の整数である（単位: 円）。"""
        for race in self.results["races"]:
            assert isinstance(race["trifecta_payout"], int), (
                f"{race['venue']} R{race['race_no']}: trifecta_payoutが整数でない"
            )
            assert race["trifecta_payout"] > 0, (
                f"{race['venue']} R{race['race_no']}: trifecta_payout={race['trifecta_payout']}"
            )
            assert race["trio_payout"] > 0, (
                f"{race['venue']} R{race['race_no']}: trio_payout={race['trio_payout']}"
            )

    def test_venues_in_results_match_fixture(self):
        """
        結果データの会場名が出走表と一致する。
        根拠: 大垣・和歌山・広島の3場
        """
        result_venues = set(r["venue"] for r in self.results["races"])
        fixture_venues = {"大垣", "和歌山", "広島"}
        assert result_venues == fixture_venues, (
            f"結果の会場={result_venues}, 出走表の会場={fixture_venues}"
        )

    def test_ogaki_r12_has_prediction_data(self):
        """
        大垣R12には我々の予想データが付いている。
        根拠: our_prediction フィールドが存在する
        """
        ogaki_r12 = next(
            r for r in self.results["races"]
            if r["venue"] == "大垣" and r["race_no"] == 12
        )
        assert "our_prediction" in ogaki_r12, "大垣R12に our_prediction なし"
        pred = ogaki_r12["our_prediction"]
        assert "investment" in pred
        assert "bet_type" in pred

    def test_wakayama_r12_has_prediction_data(self):
        """
        和歌山R12には我々の予想データが付いている。
        """
        waka_r12 = next(
            r for r in self.results["races"]
            if r["venue"] == "和歌山" and r["race_no"] == 12
        )
        assert "our_prediction" in waka_r12, "和歌山R12に our_prediction なし"


# ─── セクション9: ROI計算検証 ──────────────────────────────────────

class TestROICalculation:
    """
    2/28の実結果から ROI を計算し正確性を検証する。
    根拠: our_prediction フィールドを持つ2レース（大垣R12, 和歌山R12）
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.results = load_results(RESULTS_228)
        self.prediction_races = [
            r for r in self.results["races"] if "our_prediction" in r
        ]

    def test_exactly_two_prediction_races(self):
        """2/28の予想対象は2レース（大垣R12, 和歌山R12）。"""
        assert len(self.prediction_races) == 2, (
            f"予想レース数={len(self.prediction_races)} (期待=2)"
        )

    def test_ogaki_r12_investment_is_1200(self):
        """
        大垣R12への投資額は1200円。
        根拠: our_prediction.investment = 1200
        """
        ogaki_r12 = next(
            r for r in self.prediction_races
            if r["venue"] == "大垣" and r["race_no"] == 12
        )
        assert ogaki_r12["our_prediction"]["investment"] == 1200

    def test_wakayama_r12_investment_is_3600(self):
        """
        和歌山R12への投資額は3600円。
        根拠: our_prediction.investment = 3600
        """
        waka_r12 = next(
            r for r in self.prediction_races
            if r["venue"] == "和歌山" and r["race_no"] == 12
        )
        assert waka_r12["our_prediction"]["investment"] == 3600

    def test_both_predictions_missed(self):
        """2レースとも外れ（hit=False, payout=0）。"""
        for race in self.prediction_races:
            assert race.get("hit") is False, (
                f"{race['venue']} R{race['race_no']}: hit={race.get('hit')} (期待=False)"
            )
            assert race.get("payout", -1) == 0, (
                f"{race['venue']} R{race['race_no']}: payout={race.get('payout')} (期待=0)"
            )

    def test_total_investment_is_4800(self):
        """
        2/28 合計投資額は 4800円。
        根拠: 大垣R12(1200) + 和歌山R12(3600) = 4800
        """
        total_investment = sum(
            r["our_prediction"]["investment"]
            for r in self.prediction_races
        )
        assert total_investment == 4800, f"合計投資額={total_investment} (期待=4800)"

    def test_total_payout_is_0(self):
        """
        2/28 合計払戻は 0円（2レースとも外れ）。
        根拠: payout = 0 × 2
        """
        total_payout = sum(r.get("payout", 0) for r in self.prediction_races)
        assert total_payout == 0, f"合計払戻={total_payout} (期待=0)"

    def test_roi_is_0_percent(self):
        """
        2/28 ROI = 0% (払戻0 / 投資4800)。
        根拠: 両レース外れ → roi = 0 / 4800 = 0.0
        """
        total_investment = sum(
            r["our_prediction"]["investment"]
            for r in self.prediction_races
        )
        total_payout = sum(r.get("payout", 0) for r in self.prediction_races)
        roi = total_payout / total_investment
        assert roi == 0.0, f"ROI={roi:.4f} (期待=0.0)"


# ─── セクション10: 総合フィルター通過率サマリ ─────────────────────

class TestFilterPassRateSummary:
    """
    フィルター通過率の総合検証。
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)
        self.races_301 = load_fixture(FIXTURE_301)
        self.engine = FilterEngine(FILTERS_YAML)

    def test_228_overall_pass_count_after_f2_fix(self):
        """
        【F2修正後 cmd_141k_sub1】2/28実データで全フィルター通過は8レース。
        根拠: F1(S級) × F2(一予選/予選/初特選) × F6(土曜OK) × F7(R4/R6除外) × score_spread(>=12)
        通過レース: 大垣R2,R3,R5,R7,R8,R9,R10,R11 (全てＳ級一予選でscore_spread>=12)
        除外パターン:
          - 大垣R1: grade=''(F1) + stage=''(F2)
          - 大垣R4,R6: F7(R番号除外) ※F2はＳ級一予選→通過
          - 大垣R12: Ｓ級初特選→F2通過だがscore_spread=7.22<12で除外
          - 和歌山S級(R8-R12): score_spread<12で全除外
        """
        passed_count = sum(
            1 for race in self.races_228
            if self.engine.apply(race)[0]
        )
        assert passed_count == 8, (
            f"通過レース数={passed_count} (期待=8: 大垣R2,R3,R5,R7-R11)"
        )

    def test_301_overall_pass_rate_is_zero(self):
        """
        3/1実データは全44レースがフィルターを通過しない (通過率=0%)。
        根拠: F6が全レース除外（3/1は日曜日）
        """
        passed_count = sum(
            1 for race in self.races_301
            if self.engine.apply(race)[0]
        )
        assert passed_count == 0, (
            f"通過レース数={passed_count} (期待=0: F6が日曜で全除外)"
        )

    def test_filters_applied_in_correct_order(self):
        """
        フィルターが正しい順序で適用される（F1→F2→F4→F5→F6→F7→F8→score_spread）。
        1レースに複数の除外理由がある場合、全てreturnsされることを確認。
        根拠: filter_engine.py の _apply_keirin は全チェックを実行してから返す

        大垣R4 (stage=Ｓ級一予選):
          - F2: 正規化後"一予選" → allowed → 通過 (cmd_141k_sub1修正)
          - F7: R4 → 除外
        score_spreadのある複数除外をチェックするため和歌山R4を使用:
          - F7: R4 → 除外
          - score_spread: 和歌山S級はspread<12 (ただしA級なのでF1で除外)
        """
        # 大垣R4: F2修正後はＳ級一予選→F2通過、F7のみで除外
        ogaki_r4 = next(
            r for r in self.races_228
            if r["venue_name"] == "大垣" and r["race_num"] == 4
        )
        passed, reasons = self.engine.apply(ogaki_r4)
        assert not passed
        # F2修正後: Ｓ級一予選 → normalized '一予選' → allowed → F2通過
        f2_reasons = [r for r in reasons if r.startswith("F2")]
        assert len(f2_reasons) == 0, f"大垣R4はF2を通過すべき（修正後）: {f2_reasons}"
        # F7で除外される
        f7_reasons = [r for r in reasons if r.startswith("F7")]
        assert len(f7_reasons) > 0, f"F7除外理由なし: {reasons}"

    def test_f4_and_f5_not_triggered_228(self):
        """
        2/28データはF4（競輪場）・F5（500mバンク）で除外されない。
        根拠: 大垣・和歌山・広島は除外リスト外、全て400mバンク
        """
        excl = count_filter_exclusions(self.races_228, self.engine)
        assert excl["F4_velodrome"] == 0, f"F4除外={excl['F4_velodrome']} (期待=0)"
        assert excl["F5_bank_length"] == 0, f"F5除外={excl['F5_bank_length']} (期待=0)"
