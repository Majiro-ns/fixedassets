"""
FilterEngine のテストスイート

S1準決勝フィルターのロジックを検証する。
ネットワーク・APIキーは不要。
"""

import sys
import os
import tempfile
import pytest

# src/ をパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.filter_engine import FilterEngine, DEFAULT_FILTERS


# ─── テスト用レースデータ ─────────────────────────────────────────

# S1選手3名以上 + 特選 → フィルター通過すべきレース（新フィルター基準: 特選/二次予選のみ）
S1_SEMIFINAL_RACE = {
    "venue_name": "川崎",
    "race_no": 9,
    "grade": "S1",
    "stage": "特選",
    "entries": [
        {"car_no": 1, "name": "選手A", "grade": "S1"},
        {"car_no": 2, "name": "選手B", "grade": "S1"},
        {"car_no": 3, "name": "選手C", "grade": "S1"},
        {"car_no": 4, "name": "選手D", "grade": "S2"},
        {"car_no": 5, "name": "選手E", "grade": "S2"},
        {"car_no": 6, "name": "選手F", "grade": "A1"},
        {"car_no": 7, "name": "選手G", "grade": "A1"},
    ],
}

# A級レース → フィルターで除外すべきレース
A_CLASS_RACE = {
    "venue_name": "松戸",
    "race_no": 3,
    "grade": "A1",
    "stage": "一般",
    "entries": [
        {"car_no": 1, "name": "選手H", "grade": "A1"},
        {"car_no": 2, "name": "選手I", "grade": "A1"},
        {"car_no": 3, "name": "選手J", "grade": "A1"},
        {"car_no": 4, "name": "選手K", "grade": "A2"},
        {"car_no": 5, "name": "選手L", "grade": "A2"},
        {"car_no": 6, "name": "選手M", "grade": "A2"},
        {"car_no": 7, "name": "選手N", "grade": "A2"},
    ],
}

# S1選手2名（最低ライン未満）→ フィルターで除外すべき
S1_BELOW_MINIMUM_RACE = {
    "venue_name": "高松",
    "race_no": 5,
    "grade": "S2",
    "stage": "準決勝",
    "entries": [
        {"car_no": 1, "name": "選手O", "grade": "S1"},
        {"car_no": 2, "name": "選手P", "grade": "S1"},
        {"car_no": 3, "name": "選手Q", "grade": "S2"},
        {"car_no": 4, "name": "選手R", "grade": "S2"},
        {"car_no": 5, "name": "選手S", "grade": "A1"},
        {"car_no": 6, "name": "選手T", "grade": "A1"},
        {"car_no": 7, "name": "選手U", "grade": "A1"},
    ],
}

# 二次予選 + S1選手5名 → フィルター通過すべき（新フィルター基準: 決勝67%で除外）
S1_FINAL_RACE = {
    "venue_name": "立川",
    "race_no": 11,
    "grade": "S1",
    "stage": "二次予選",
    "entries": [
        {"car_no": 1, "name": "選手V", "grade": "S1"},
        {"car_no": 2, "name": "選手W", "grade": "S1"},
        {"car_no": 3, "name": "選手X", "grade": "S1"},
        {"car_no": 4, "name": "選手Y", "grade": "S1"},
        {"car_no": 5, "name": "選手Z", "grade": "S1"},
        {"car_no": 6, "name": "選手AA", "grade": "S2"},
        {"car_no": 7, "name": "選手BB", "grade": "S2"},
    ],
}


# ─── FilterEngine 初期化テスト ────────────────────────────────────

class TestFilterEngineInit:
    """FilterEngine の初期化テスト。"""

    def test_init_with_nonexistent_config(self):
        """存在しない config ファイルを指定してもデフォルト設定で初期化されること。"""
        engine = FilterEngine("/nonexistent/path/filters.yaml")
        assert engine.filters == DEFAULT_FILTERS

    def test_init_with_valid_yaml(self):
        """有効な YAML ファイルを読み込めること。"""
        yaml_content = "min_s1_count: 4\nallowed_stages:\n  - 準決勝\n  - 決勝\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", encoding="utf-8", delete=False
        ) as f:
            f.write(yaml_content)
            tmp_path = f.name

        try:
            engine = FilterEngine(tmp_path)
            assert engine.filters.get("min_s1_count") == 4
        finally:
            os.unlink(tmp_path)


# ─── フィルターロジックテスト ─────────────────────────────────────

class TestFilterEngineLogic:
    """フィルターロジックのテスト（設定ファイル不要）。"""

    def setup_method(self):
        """各テスト前にデフォルト設定でエンジンを生成する。"""
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_s1_semifinal_filter_pass(self):
        """S1選手3名以上 + 特選 のみ通過するか（正常系）。apply() は (bool, reasons) を返す。"""
        engine = FilterEngine("config/keirin/filters.yaml")
        passed, reasons = engine.apply(S1_SEMIFINAL_RACE)
        assert passed is True, f"通過すべきレースが除外された: {reasons}"

    def test_a_class_race_filter_reject(self):
        """A級レースがフィルターで除外されること。"""
        engine = FilterEngine("config/keirin/filters.yaml")
        passed, reasons = engine.apply(A_CLASS_RACE)
        assert passed is False

    def test_s1_below_minimum_filter_reject(self):
        """S1選手が最低ライン（3名）未満の場合に除外されること。"""
        passed, reasons = self.engine.apply(S1_BELOW_MINIMUM_RACE)
        assert passed is False

    def test_s1_final_race_filter_pass(self):
        """二次予選はROI=55.38%のため除外されること（cmd_126k_sub2）。"""
        passed, reasons = self.engine.apply(S1_FINAL_RACE)
        assert passed is False, f"除外すべきレースが通過した: {reasons}"

    def test_empty_entries_filter_pass(self):
        """空エントリー+S1+特選 は新9フィルター（F1-F9）を通過する。
        選手数チェックは apply_legacy() (旧API) で行う。"""
        empty_race = {
            "venue_name": "テスト",
            "race_no": 1,
            "grade": "S1",
            "stage": "特選",
            "entries": [],
        }
        passed, reasons = self.engine.apply(empty_race)
        # 新9フィルターには出走人数チェックなし → 通過
        assert passed is True

    def test_missing_stage_filter_reject(self):
        """stage キーが存在しない場合に除外されること。"""
        race_no_stage = {
            "venue_name": "テスト",
            "race_no": 1,
            "grade": "S1",
            "entries": S1_SEMIFINAL_RACE["entries"],
        }
        passed, reasons = self.engine.apply(race_no_stage)
        assert passed is False


class TestFilterEngineStageCheck:
    """ステージフィルターの詳細テスト。"""

    def setup_method(self):
        """各テスト前にデフォルト設定でエンジンを生成する。"""
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_semifinal_stage_passes(self):
        """「準決勝」はROI=51.25%のため除外されること（cmd_126k_sub2）。"""
        assert self.engine._check_stage({"stage": "準決勝"}) is False

    def test_final_stage_passes(self):
        """「決勝」はROI=0%のため除外されること（cmd_126k_sub2）。"""
        assert self.engine._check_stage({"stage": "決勝"}) is False

    def test_general_stage_rejected(self):
        """「一般」はROI=194.95%のため通過すること（cmd_126k_sub2）。"""
        assert self.engine._check_stage({"stage": "一般"}) is True

    def test_unknown_stage_rejected(self):
        """未知のステージが除外されること。"""
        assert self.engine._check_stage({"stage": "不明"}) is False


class TestFilterEngineS1Count:
    """S1選手数フィルターの詳細テスト。"""

    def setup_method(self):
        """各テスト前にデフォルト設定でエンジンを生成する。"""
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_exactly_3_s1_passes(self):
        """S1選手がちょうど3名の場合に通過すること（境界値テスト）。"""
        race = {
            "entries": [
                {"grade": "S1"}, {"grade": "S1"}, {"grade": "S1"},
                {"grade": "A1"}, {"grade": "A1"}, {"grade": "A1"}, {"grade": "A1"},
            ]
        }
        assert self.engine._check_s1_count(race) is True

    def test_2_s1_rejected(self):
        """S1選手が2名の場合に除外されること（境界値テスト）。"""
        race = {
            "entries": [
                {"grade": "S1"}, {"grade": "S1"},
                {"grade": "A1"}, {"grade": "A1"}, {"grade": "A1"},
                {"grade": "A1"}, {"grade": "A1"},
            ]
        }
        assert self.engine._check_s1_count(race) is False

    def test_7_s1_passes(self):
        """全員S1選手の場合に通過すること。"""
        race = {
            "entries": [{"grade": "S1"} for _ in range(7)]
        }
        assert self.engine._check_s1_count(race) is True


# ─── score_spread フィルターテスト（#T002対策案2 cmd_132k_sub2）────────────

class TestScoreSpreadFilter:
    """_check_score_spread の境界値・欠損テスト。"""

    def _make_engine(self, min_score_spread: float) -> FilterEngine:
        """min_score_spread を指定したエンジンを作成。"""
        engine = FilterEngine("/nonexistent/path/filters.yaml")
        engine.filters["min_score_spread"] = min_score_spread
        return engine

    def _make_race(self, scores: list) -> dict:
        """指定した競走得点リストの entries を持つレースデータを作成。"""
        return {
            "venue_name": "川崎",
            "race_no": 9,
            "grade": "S1",
            "stage": "特選",
            "entries": [{"car_no": i + 1, "score": s} for i, s in enumerate(scores)],
        }

    def test_spread_below_threshold_rejected(self):
        """spread=11.9 < 12 → SKIP（除外）されること。"""
        # max=90.0, min=78.1 → spread=11.9
        engine = self._make_engine(12)
        race = self._make_race([90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 78.1])
        passed, reason = engine._check_score_spread(race)
        assert not passed
        assert "score_spread" in reason
        assert "11.9" in reason or "11.90" in reason

    def test_spread_equal_threshold_passes(self):
        """spread=12.0 == 12 → 通過すること（境界値: >=）。"""
        # max=90.0, min=78.0 → spread=12.0
        engine = self._make_engine(12)
        race = self._make_race([90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 78.0])
        passed, _ = engine._check_score_spread(race)
        assert passed

    def test_spread_above_threshold_passes(self):
        """spread=12.1 > 12 → 通過すること。"""
        # max=90.1, min=78.0 → spread=12.1
        engine = self._make_engine(12)
        race = self._make_race([90.1, 88.0, 86.0, 84.0, 82.0, 80.0, 78.0])
        passed, _ = engine._check_score_spread(race)
        assert passed

    def test_score_missing_passes(self):
        """score フィールドが欠損している場合は通過すること。"""
        engine = self._make_engine(12)
        race = {
            "venue_name": "川崎",
            "race_no": 9,
            "grade": "S1",
            "stage": "特選",
            "entries": [
                {"car_no": 1, "name": "選手A", "grade": "S1"},
                {"car_no": 2, "name": "選手B", "grade": "S1"},
            ],
        }
        passed, _ = engine._check_score_spread(race)
        assert passed

    def test_min_score_spread_zero_disabled(self):
        """min_score_spread=0（無効化）の場合は常に通過すること。"""
        engine = self._make_engine(0)
        race = self._make_race([90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 90.0])
        passed, _ = engine._check_score_spread(race)
        assert passed


# ─── F2: 全角グレードプレフィックス正規化テスト（cmd_141k_sub1）────────────

class TestRaceTypeNormalization:
    """F2フィルターの全角グレードプレフィックス正規化テスト。

    scraper出力は "Ｓ級一予選" / "Ａ級予選" 等、全角グレードプレフィックス付き。
    filters.yaml は "一予選" / "予選" 等プレフィックスなし。
    正規化（先頭の [Ａ-Ｚ]級 を除去）して完全一致で判定する。
    """

    def setup_method(self):
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_fullwidth_s_grade_prefix_normalized(self):
        """Ｓ級特選 → 特選 に正規化されて通過すること。"""
        race = {"stage": "Ｓ級特選", "grade": "S1", "entries": []}
        passed, reason = self.engine._check_race_type(race)
        assert passed is True, f"Ｓ級特選は通過すべき: {reason}"

    def test_fullwidth_a_grade_prefix_normalized(self):
        """Ａ級予選 → 予選 に正規化されて通過すること。"""
        race = {"stage": "Ａ級予選", "grade": "A1", "entries": []}
        passed, reason = self.engine._check_race_type(race)
        assert passed is True, f"Ａ級予選（予選）は通過すべき: {reason}"

    def test_fullwidth_s_grade_semifinal_rejected(self):
        """Ｓ級準決勝 → 準決勝（許可リスト外）で除外されること。"""
        race = {"stage": "Ｓ級準決勝", "grade": "S1", "entries": []}
        passed, reason = self.engine._check_race_type(race)
        assert passed is False

    def test_halfwidth_stage_without_prefix(self):
        """プレフィックスなし（半角）の「特選」はそのまま通過すること。"""
        race = {"stage": "特選", "grade": "S1", "entries": []}
        passed, _ = self.engine._check_race_type(race)
        assert passed is True

    def test_fullwidth_ichiyosen_normalized(self):
        """Ｓ級一予選 → 一予選 に正規化されて通過すること。"""
        race = {"stage": "Ｓ級一予選", "grade": "S1", "entries": []}
        passed, _ = self.engine._check_race_type(race)
        assert passed is True


# ─── F4: 競輪場フィルター境界値テスト ──────────────────────────────────────

class TestVelodromeFilter:
    """F4フィルターの境界値テスト。"""

    def setup_method(self):
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_excluded_venue_rejected(self):
        """除外場（小田原）はF4で除外されること。"""
        race = {"venue_name": "小田原", "stage": "特選", "grade": "S1"}
        passed, reason = self.engine._check_velodrome(race)
        assert passed is False
        assert "F4" in reason

    def test_allowed_venue_passes(self):
        """除外リスト外の場は通過すること。"""
        race = {"venue_name": "川崎", "stage": "特選", "grade": "S1"}
        passed, _ = self.engine._check_velodrome(race)
        assert passed is True

    def test_all_excluded_venues(self):
        """除外リスト全会場（小田原・名古屋・高知・玉野・武雄）が除外されること。"""
        excluded = ["小田原", "名古屋", "高知", "玉野", "武雄"]
        for venue in excluded:
            race = {"venue_name": venue}
            passed, _ = self.engine._check_velodrome(race)
            assert passed is False, f"{venue} は除外されるべき"

    def test_partial_match_not_excluded(self):
        """部分一致では除外されないこと（例: '名古屋競輪場' は除外リスト '名古屋' と完全一致しない）。"""
        race = {"venue_name": "名古屋競輪場"}
        # 完全一致判定のため、'名古屋競輪場' != '名古屋' → 通過
        passed, _ = self.engine._check_velodrome(race)
        assert passed is True


# ─── F5: バンク長フィルター境界値テスト ────────────────────────────────────

class TestBankLengthFilter:
    """F5フィルターの境界値テスト（500mバンク除外）。"""

    def setup_method(self):
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_400m_bank_passes(self):
        """400mバンクは通過すること。"""
        race = {"bank_length": 400}
        passed, _ = self.engine._check_bank_length(race)
        assert passed is True

    def test_500m_bank_rejected(self):
        """500mバンクはF5で除外されること。"""
        race = {"bank_length": 500}
        passed, reason = self.engine._check_bank_length(race)
        assert passed is False
        assert "F5" in reason

    def test_333m_bank_passes(self):
        """333mバンクは通過すること（333mは高速バンク）。"""
        race = {"bank_length": 333}
        passed, _ = self.engine._check_bank_length(race)
        assert passed is True

    def test_default_bank_length_passes(self):
        """bank_lengthが未設定の場合、デフォルト400mで通過すること。"""
        race = {}  # bank_length なし
        passed, _ = self.engine._check_bank_length(race)
        assert passed is True


# ─── F6: 曜日フィルター境界値テスト ────────────────────────────────────────

class TestDayOfWeekFilter:
    """F6フィルターのテスト（月・日は除外）。

    CHECK-7b 手計算検算:
    20260302 = 2026年3月2日 = 月曜日（weekday()=0）→ 除外
    20260303 = 2026年3月3日 = 火曜日（weekday()=1）→ 通過
    20260301 = 2026年3月1日 = 日曜日（weekday()=6）→ 除外
    20260306 = 2026年3月6日 = 金曜日（weekday()=4）→ 通過
    """

    def setup_method(self):
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_monday_rejected(self):
        """月曜日は除外されること（20260302=月曜日）。"""
        race = {"date": "20260302"}  # 2026-03-02 月曜日
        passed, reason = self.engine._check_day_of_week(race)
        assert passed is False
        assert "F6" in reason

    def test_sunday_rejected(self):
        """日曜日は除外されること（20260301=日曜日）。"""
        race = {"date": "20260301"}  # 2026-03-01 日曜日
        passed, reason = self.engine._check_day_of_week(race)
        assert passed is False

    def test_tuesday_passes(self):
        """火曜日は通過すること（20260303=火曜日）。"""
        race = {"date": "20260303"}  # 2026-03-03 火曜日
        passed, _ = self.engine._check_day_of_week(race)
        assert passed is True

    def test_friday_passes(self):
        """金曜日は通過すること（20260306=金曜日）。"""
        race = {"date": "20260306"}  # 2026-03-06 金曜日
        passed, _ = self.engine._check_day_of_week(race)
        assert passed is True

    def test_missing_date_passes(self):
        """日付なしはスキップ（通過）すること。"""
        race = {}  # date なし
        passed, _ = self.engine._check_day_of_week(race)
        assert passed is True

    def test_invalid_date_format_passes(self):
        """不正な日付フォーマットはスキップ（通過）すること。"""
        race = {"date": "2026/03/02"}  # 不正フォーマット
        passed, _ = self.engine._check_day_of_week(race)
        assert passed is True


# ─── F7: レース番号フィルター境界値テスト ──────────────────────────────────

class TestRaceNumberFilter:
    """F7フィルターの境界値テスト（4R・6Rは除外）。"""

    def setup_method(self):
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_race4_rejected(self):
        """4Rは除外されること（回収率24%）。"""
        race = {"race_num": 4}
        passed, reason = self.engine._check_race_number(race)
        assert passed is False
        assert "F7" in reason

    def test_race6_rejected(self):
        """6Rは除外されること（回収率33%）。"""
        race = {"race_num": 6}
        passed, reason = self.engine._check_race_number(race)
        assert passed is False

    def test_race3_passes(self):
        """3Rは通過すること（境界値: 4Rの一つ前）。"""
        race = {"race_num": 3}
        passed, _ = self.engine._check_race_number(race)
        assert passed is True

    def test_race5_passes(self):
        """5Rは通過すること（境界値: 4Rと6Rの間）。"""
        race = {"race_num": 5}
        passed, _ = self.engine._check_race_number(race)
        assert passed is True

    def test_race9_passes(self):
        """9Rは通過すること。"""
        race = {"race_num": 9}
        passed, _ = self.engine._check_race_number(race)
        assert passed is True

    def test_zero_race_number_passes(self):
        """race_num=0（未設定相当）は通過すること。"""
        race = {"race_num": 0}
        passed, _ = self.engine._check_race_number(race)
        assert passed is True


# ─── F8: 期待配当ゾーン境界値テスト ────────────────────────────────────────

class TestExpectedPayoutFilter:
    """F8フィルターの境界値テスト（min=3000, max=50000）。

    CHECK-7b 手計算検算:
    - 3000円 → min境界: 3000 >= 3000 → 通過 ✓
    - 2999円 → min境界下: 2999 < 3000 → 除外 ✓
    - 50000円 → max境界: 50000 <= 50000 → 通過 ✓
    - 50001円 → max境界超: 50001 > 50000 → 除外 ✓
    """

    def setup_method(self):
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_below_min_rejected(self):
        """期待配当 2999円（<3000）は除外されること。"""
        race = {"expected_payout": 2999}
        passed, reason = self.engine._check_expected_payout(race)
        assert passed is False
        assert "F8" in reason

    def test_at_min_passes(self):
        """期待配当 3000円（=min境界）は通過すること。"""
        race = {"expected_payout": 3000}
        passed, _ = self.engine._check_expected_payout(race)
        assert passed is True

    def test_within_range_passes(self):
        """期待配当 20000円（min-max内）は通過すること。"""
        race = {"expected_payout": 20000}
        passed, _ = self.engine._check_expected_payout(race)
        assert passed is True

    def test_at_max_passes(self):
        """期待配当 50000円（=max境界）は通過すること。"""
        race = {"expected_payout": 50000}
        passed, _ = self.engine._check_expected_payout(race)
        assert passed is True

    def test_above_max_rejected(self):
        """期待配当 50001円（>max）は除外されること。"""
        race = {"expected_payout": 50001}
        passed, reason = self.engine._check_expected_payout(race)
        assert passed is False

    def test_none_payout_passes(self):
        """expected_payout が未設定（None）の場合はスキップ（通過）すること。"""
        race = {}  # expected_payout なし
        passed, _ = self.engine._check_expected_payout(race)
        assert passed is True


# ─── F3: キーワードフィルターテスト ────────────────────────────────────────

class TestKeywordsFilter:
    """F3フィルターのテスト（逆指標キーワード除外）。"""

    def setup_method(self):
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def test_jishin_keyword_rejected(self):
        """「自信」を含むコメントは除外されること。"""
        passed, reason = self.engine._check_keywords("今日は自信ありの予想です")
        assert passed is False
        assert "F3" in reason

    def test_teppan_keyword_rejected(self):
        """「鉄板」を含むコメントは除外されること。"""
        passed, reason = self.engine._check_keywords("鉄板レースと見ています")
        assert passed is False

    def test_no_keywords_passes(self):
        """逆指標キーワードを含まないコメントは通過すること。"""
        passed, _ = self.engine._check_keywords("データを分析した予想です")
        assert passed is True

    def test_empty_comment_passes(self):
        """空コメントは通過すること。"""
        passed, _ = self.engine._check_keywords("")
        assert passed is True

    def test_multiple_keywords_rejected(self):
        """複数の逆指標キーワードが含まれても除外されること。"""
        passed, _ = self.engine._check_keywords("自信の鉄板レース、間違いない！")
        assert passed is False


# ─── フィルター組み合わせテスト ─────────────────────────────────────────────

class TestFilterCombination:
    """複数フィルターが同時に動作するケースのテスト。"""

    def setup_method(self):
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def _make_valid_race(self):
        """全フィルターを通過するベースレース（デフォルトフィルター設定）。"""
        return {
            "venue_name": "川崎",
            "grade": "S1",
            "stage": "特選",
            "bank_length": 400,
            "race_num": 9,
            "date": "20260303",  # 火曜日
            "expected_payout": 20000,
            "entries": [],
        }

    def test_valid_race_passes_all_filters(self):
        """全条件を満たすレースは全フィルター通過すること。"""
        race = self._make_valid_race()
        passed, reasons = self.engine.apply(race)
        assert passed is True, f"通過すべきレースが除外: {reasons}"

    def test_multiple_filter_failures_returns_all_reasons(self):
        """複数フィルター違反が発生した場合、全ての理由が返ること。"""
        race = self._make_valid_race()
        race["grade"] = "A1"          # F1違反
        race["stage"] = "決勝"         # F2違反
        race["venue_name"] = "小田原"  # F4違反
        passed, reasons = self.engine.apply(race)
        assert passed is False
        assert len(reasons) >= 3, f"3件以上の除外理由が必要: {reasons}"

    def test_single_filter_failure_rejects(self):
        """1つのフィルター違反でも除外されること。"""
        race = self._make_valid_race()
        race["race_num"] = 4  # F7違反のみ
        passed, reasons = self.engine.apply(race)
        assert passed is False
        assert any("F7" in r for r in reasons)

    def test_comment_keyword_also_checked(self):
        """コメントがある場合、キーワードフィルターも適用されること。"""
        race = self._make_valid_race()
        comment = "自信の予想"
        passed, reasons = self.engine.apply(race, comment=comment)
        assert passed is False
        assert any("F3" in r for r in reasons)

    def test_empty_comment_does_not_check_keywords(self):
        """コメントが空の場合、キーワードフィルターは適用されないこと。"""
        race = self._make_valid_race()
        passed, reasons = self.engine.apply(race, comment="")
        # コメントなし → キーワードチェックなし → F1-F8のみで判定
        # 有効レースなので全通過
        assert passed is True


# ─── apply_ml_filters テスト ────────────────────────────────────────────────

class TestApplyMlFilters:
    """apply_ml_filters（F10〜F12）のテスト。"""

    def setup_method(self):
        self.engine = FilterEngine("/nonexistent/path/filters.yaml")

    def _make_valid_race(self):
        return {
            "venue_name": "川崎",
            "grade": "S1",
            "stage": "特選",
            "bank_length": 400,
            "race_num": 9,
            "date": "20260303",
            "expected_payout": 20000,
            "entries": [],
        }

    def test_no_ml_filters_configured_passes(self):
        """ML強化フィルターが未設定（デフォルト）の場合は全通過すること。

        デフォルト: min_confidence_score=0, min_win_rate_spread=0.0, max_bets_per_race=0
        → 全チェックがスキップされる
        """
        race = self._make_valid_race()
        passed, reasons = self.engine.apply_ml_filters(race)
        assert passed is True, f"デフォルト設定は全通過すべき: {reasons}"

    def test_f12_bets_exceeded_rejected(self):
        """F12: 点数が上限を超えた場合に除外されること。"""
        self.engine.filters["max_bets_per_race"] = 10
        race = self._make_valid_race()
        passed, reasons = self.engine.apply_ml_filters(race, num_bets=11)
        assert passed is False
        assert any("F12" in r for r in reasons)

    def test_f12_bets_at_limit_passes(self):
        """F12: 点数がちょうど上限の場合は通過すること（境界値）。"""
        self.engine.filters["max_bets_per_race"] = 10
        race = self._make_valid_race()
        passed, _ = self.engine.apply_ml_filters(race, num_bets=10)
        assert passed is True

    def test_f11_win_rate_spread_below_threshold_rejected(self):
        """F11: 勝率差が閾値未満（実力拮抗）なら除外されること。"""
        self.engine.filters["min_win_rate_spread"] = 0.20
        race = self._make_valid_race()
        race["entries"] = [
            {"win_rate": 0.50},
            {"win_rate": 0.45},
            {"win_rate": 0.42},
        ]
        # spread = 0.50 - 0.42 = 0.08 < 0.20 → 除外
        passed, reasons = self.engine.apply_ml_filters(race)
        assert passed is False
        assert any("F11" in r for r in reasons)

    def test_f11_win_rate_spread_above_threshold_passes(self):
        """F11: 勝率差が閾値以上なら通過すること。"""
        self.engine.filters["min_win_rate_spread"] = 0.20
        race = self._make_valid_race()
        race["entries"] = [
            {"win_rate": 0.60},
            {"win_rate": 0.30},
        ]
        # spread = 0.60 - 0.30 = 0.30 >= 0.20 → 通過
        passed, _ = self.engine.apply_ml_filters(race)
        assert passed is True

    def test_f11_missing_win_rate_skipped(self):
        """F11: win_rateデータが欠損している場合はスキップ（通過）すること。"""
        self.engine.filters["min_win_rate_spread"] = 0.20
        race = self._make_valid_race()
        race["entries"] = [
            {"name": "選手A"},  # win_rate なし
            {"name": "選手B"},  # win_rate なし
        ]
        passed, _ = self.engine.apply_ml_filters(race)
        assert passed is True

    def test_f12_none_num_bets_skipped(self):
        """F12: num_bets=None の場合はスキップ（通過）すること。"""
        self.engine.filters["max_bets_per_race"] = 10
        race = self._make_valid_race()
        passed, _ = self.engine.apply_ml_filters(race, num_bets=None)
        assert passed is True
