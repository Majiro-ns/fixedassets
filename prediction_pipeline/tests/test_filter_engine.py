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
