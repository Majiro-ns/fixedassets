"""
TierClassifier テストスイート (cmd_138k_sub5)

tier_classifier.py の classify() / _classify_keirin() / _classify_kyotei() /
_keirin_score() / _kyotei_score() を網羅的に検証する。

テスト期待値の根拠 (CHECK-9):
  - Tier S: mr_t_cognitive_profile.yaml optimal_filters.filter_A ROI=148.7%, n=131
    条件: S1×3名以上 × 特選/二次予選 × 優良場（熊本/別府/防府/立川/川崎） × 非500m × 逆指標なし
  - Tier A (s_race_type): 同上条件から優良場が外れた場合
  - Tier A (a_race_type): 設計書 Section 4 ROI=110-130%目標 / 準決勝・初日特別選抜
  - Tier B: CREフィルター通過 × S1あり × 上位条件不満足
  - Tier SKIP: 逆指標(ROI最悪: 「自信」=27%/「見えた」=0%/「鉄板」=0%/「間違いない」=0%)
               or S1不足(min_s1_count=3) or フィルター不通過
  - confidence_score: score_weights 重み付き合算
    s_class=0.30, race_type_premium=0.25, preferred_venue=0.20, non_500m=0.15, no_reverse=0.10
    合計 = 1.0（上限 min(score, 1.0) でキャップ）
"""

from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tier_classifier import TierClassifier, _DEFAULT_CONFIG


# ─── テスト用ヘルパー ──────────────────────────────────────────────────────

def _make_s1_entries(s1_count: int, total: int = 7) -> list[dict]:
    """S1選手 s1_count 名 + A1 残り で total 名の選手リストを生成する。"""
    entries = [{"grade": "S1"} for _ in range(s1_count)]
    entries += [{"grade": "A1"} for _ in range(total - s1_count)]
    return entries


def _keirin_race(
    race_type: str = "特選",
    venue: str = "熊本",
    track_length: int = 400,
    s1_count: int = 4,
    comment: str = "",
) -> dict:
    """競輪テスト用レースデータを生成する。"""
    return {
        "sport": "keirin",
        "race_type": race_type,
        "venue": venue,
        "track_length": track_length,
        "race_number": 9,
        "comment": comment,
        "entries": _make_s1_entries(s1_count),
    }


# ─── フィクスチャ ──────────────────────────────────────────────────────────

@pytest.fixture
def classifier():
    """デフォルト設定の TierClassifier（config_path=None）。"""
    return TierClassifier(config_path=None)


# ═══════════════════════════════════════════════════════════════════════════
# Group 1: Tier S テスト
# 根拠: filter_A 全条件通過 → ROI=148.7%, n=131
# ═══════════════════════════════════════════════════════════════════════════

class TestTierS:
    """Tier S 判定テスト（全条件: S1×3+名 × 特選/二次予選 × 優良場 × 非500m × 逆指標なし）。"""

    def test_tier_s_tokusen_kumamoto(self, classifier):
        """熊本×特選×S1×4名×400m → Tier S（典型的filter_A条件）。

        根拠: best_velodromes: 熊本(ROI=169%), 特選 = tier_s_race_types, 400m = 非500m
        期待: tier="S", filter_type="A", confidence=1.0
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=4)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "S"
        assert result["filter_type"] == "A"
        assert result["confidence_score"] == 1.0
        assert result["negative_flags"] == []

    def test_tier_s_niji_yosen_kawasaki(self, classifier):
        """川崎×二次予選×S1×3名×333m → Tier S。

        根拠: tier_s_race_types に「二次予選」含む / 川崎 = best_velodromes
        期待: tier="S"
        """
        race = _keirin_race("二次予選", "川崎", 333, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "S"
        assert result["filter_type"] == "A"

    def test_tier_s_preferred_venue_beppu(self, classifier):
        """別府×特選×S1×3名×400m → Tier S（best_velodromes 別府）。

        根拠: preferred_venues = ["熊本", "別府", "防府", "立川", "川崎"]
        期待: tier="S"
        """
        race = _keirin_race("特選", "別府", 400, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "S"

    def test_tier_s_bool_filter_true(self, classifier):
        """filter_result=True (bool) でも Tier S を正常判定する。

        根拠: classify() の bool 正規化（L145-146）が動作することを確認
        """
        race = _keirin_race("特選", "防府", 400, s1_count=3)
        result = classifier.classify(race, True)  # bool 渡し
        assert result["tier"] == "S"
        assert result["filter_type"] == "A"


# ═══════════════════════════════════════════════════════════════════════════
# Group 2: Tier A テスト
# 根拠: 設計書 Section 4 ROI=110-130% / 優良場外の特選 or 準決勝/初日特別選抜
# ═══════════════════════════════════════════════════════════════════════════

class TestTierA:
    """Tier A 判定テスト。"""

    def test_tier_a_non_preferred_venue_tokusen(self, classifier):
        """松戸×特選×S1×3名×400m（優良場外） → Tier A（s_race_type経由）。

        根拠: is_s_class AND is_s_race_type AND NOT is_preferred_venue AND is_non_500m
        期待: tier="A", filter_type="A"
        """
        race = _keirin_race("特選", "松戸", 400, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "A"
        assert result["filter_type"] == "A"

    def test_tier_a_junketsu_bofu(self, classifier):
        """防府×準決勝×S1×3名×333m → Tier A（a_race_type経由）。

        根拠: tier_a_race_types = ["準決勝", "初日特別選抜"]
        期待: tier="A", filter_type="A"
        confidence = s_class(0.30) + preferred_venue(0.20) + non_500m(0.15) + no_reverse(0.10) = 0.75
        """
        race = _keirin_race("準決勝", "防府", 333, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "A"
        assert result["filter_type"] == "A"
        assert result["confidence_score"] == pytest.approx(0.75)

    def test_tier_a_hatsubi_tokusen(self, classifier):
        """立川×初日特別選抜×S1×3名×400m → Tier A。

        根拠: tier_a_race_types に「初日特別選抜」含む
        """
        race = _keirin_race("初日特別選抜", "立川", 400, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "A"

    def test_tier_a_confidence_score_non_preferred_venue(self, classifier):
        """非優良場×特選×S1×3名×400m の confidence_score 検証。

        根拠: _keirin_score(True, True, False, True, True)
        = 0.30 + 0.25 + 0.00 + 0.15 + 0.10 = 0.80
        """
        race = _keirin_race("特選", "松戸", 400, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["confidence_score"] == pytest.approx(0.80)


# ═══════════════════════════════════════════════════════════════════════════
# Group 3: Tier B テスト
# 根拠: filter_passed AND is_s_class → 上位条件不満足 (ROI=95-110%)
# ═══════════════════════════════════════════════════════════════════════════

class TestTierB:
    """Tier B 判定テスト。"""

    def test_tier_b_general_race_filter_passed(self, classifier):
        """小倉×一般×S1×3名×400m×filter通過 → Tier B。

        根拠: 一般 は tier_s/a_race_types 外 → B に降格
        期待: tier="B", filter_type="none"
        """
        race = _keirin_race("一般", "小倉", 400, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "B"
        assert result["filter_type"] == "none"

    def test_tier_b_has_negative_flag_race_type(self, classifier):
        """Tier B 時: negative_flags に「レース種別 '予選' は優先種別外」が記録される。

        根拠: _classify_keirin L274-275: not is_s_race_type and not is_a_race_type の場合
        """
        race = _keirin_race("予選", "小倉", 400, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "B"
        assert any("優先種別外" in flag for flag in result["negative_flags"])

    def test_tier_b_500m_preferred_venue_demoted_to_b(self, classifier):
        """熊本×特選×S1×3名×500m → Tier B（500mバンクで S 降格）。

        根拠: is_non_500m=False → Tier S/A(s_race_type) 条件落ち → filter通過のためTier B
        by_track_length: 500m ROI=62% → 避けるべき
        """
        race = _keirin_race("特選", "熊本", 500, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "B"
        assert result["filter_type"] == "none"


# ═══════════════════════════════════════════════════════════════════════════
# Group 4: Tier SKIP テスト
# 根拠: 逆指標ROI(自信=27%/見えた=0%/鉄板=0%/間違いない=0%) or S1不足 or filter不通過
# ═══════════════════════════════════════════════════════════════════════════

class TestTierSkip:
    """Tier SKIP 判定テスト。"""

    def test_skip_reverse_jishin(self, classifier):
        """逆指標「自信」→ SKIP（filter通過・Tier S条件完全満足でも SKIP）。

        根拠: reverse_indicator_patterns 「自信」ROI=27% → 期待値より大幅に低い
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=4,
                            comment="今日は自信あり！S級決戦！")
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"
        assert result["filter_type"] == "none"
        assert any("逆指標キーワード" in flag for flag in result["negative_flags"])

    def test_skip_reverse_mieta(self, classifier):
        """逆指標「見えた」→ SKIP。

        根拠: reverse_indicator_patterns 「見えた」ROI=0%
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=4,
                            comment="勝ちが見えた！")
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"

    def test_skip_reverse_tetsuban(self, classifier):
        """逆指標「鉄板」→ SKIP。

        根拠: reverse_indicator_patterns 「鉄板」ROI=0%
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=4,
                            comment="鉄板本命！")
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"

    def test_skip_reverse_machiganai(self, classifier):
        """逆指標「間違いない」→ SKIP。

        根拠: reverse_indicator_patterns 「間違いない」ROI=0%
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=4,
                            comment="間違いない勝負レース")
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"

    def test_skip_insufficient_s1_count(self, classifier):
        """S1選手2名（閾値3名未満）→ SKIP。

        根拠: min_s1_count=3（filter_engine.py DEFAULT_FILTERS 準拠）
        S1不足ではTier S/A/Bいずれも不成立 → SKIP
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=2)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"
        assert any("S1選手数不足" in flag for flag in result["negative_flags"])

    def test_skip_filter_not_passed_no_s1(self, classifier):
        """filter_passed=False × S1=0名 → SKIP。

        根拠: CREフィルター不通過 = filter_type=none / Tier SKIP
        """
        race = _keirin_race("一般", "松戸", 400, s1_count=0)
        result = classifier.classify(race, {"passed": False})
        assert result["tier"] == "SKIP"
        assert result["filter_type"] == "none"

    def test_skip_confidence_is_zero_for_reverse(self, classifier):
        """逆指標SKIP時 confidence_score=0.0 を確認。

        根拠: _keirin_score(False, False, False, False, False) = 0.0
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=4,
                            comment="自信あり鉄板レース")
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"
        assert result["confidence_score"] == pytest.approx(0.0)

    def test_skip_multiple_reverse_keywords_in_negative_flags(self, classifier):
        """複数逆指標検出時: negative_flags に複数キーワードが記録される。

        根拠: L181-183: matched_reverse の各キーワードを negative_flags に追加
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=4,
                            comment="自信あり！間違いない！")
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"
        neg_keywords = " ".join(result["negative_flags"])
        assert "自信" in neg_keywords
        assert "間違いない" in neg_keywords


# ═══════════════════════════════════════════════════════════════════════════
# Group 5: confidence_score 検証
# 根拠: score_weights 重み付き合算 (s_class=0.30, premium=0.25, venue=0.20, non500=0.15, norev=0.10)
# ═══════════════════════════════════════════════════════════════════════════

class TestConfidenceScore:
    """confidence_score の数値検証テスト。"""

    def test_confidence_score_all_conditions_true(self, classifier):
        """全条件True（Tier S）→ confidence_score = 1.0（重み合計 = 1.0）。

        根拠: 0.30+0.25+0.20+0.15+0.10=1.0
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=4)
        result = classifier.classify(race, {"passed": True})
        assert result["confidence_score"] == pytest.approx(1.0)

    def test_confidence_score_capped_at_1_0(self, classifier):
        """confidence_score は min(score, 1.0) でキャップされる。

        根拠: _keirin_score L318: return min(score, 1.0)
        全True=1.0 であり、1.0 を超えない
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=7)
        result = classifier.classify(race, {"passed": True})
        assert result["confidence_score"] <= 1.0

    def test_confidence_score_only_s_class_and_no_reverse(self, classifier):
        """s_class + no_reverse のみ真 → confidence = 0.30 + 0.10 = 0.40。

        根拠: 非優良場×一般（B tier）×filter通過
        _keirin_score(True, False, False, True, True) = 0.30+0.00+0.00+0.15+0.10 = 0.55
        （非500m は True なので 0.15 加算）
        """
        race = _keirin_race("一般", "松戸", 400, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "B"
        # _keirin_score(True, False, False, True, True) = 0.30+0.15+0.10 = 0.55
        assert result["confidence_score"] == pytest.approx(0.55)

    def test_confidence_score_returns_float_rounded_to_3(self, classifier):
        """confidence_score は round(score, 3) で返される（精度確認）。

        根拠: _classify_keirin L296: round(confidence, 3)
        """
        race = _keirin_race("準決勝", "防府", 333, s1_count=3)
        result = classifier.classify(race, {"passed": True})
        score = result["confidence_score"]
        # 小数点3桁以下がないこと（round(x, 3) の保証）
        assert score == round(score, 3)


# ═══════════════════════════════════════════════════════════════════════════
# Group 6: エッジケース・その他
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """エッジケースと境界値のテスト。"""

    def test_empty_entries_leads_to_skip(self, classifier):
        """entries=[] → S1選手0名 → SKIP。

        根拠: s1_count=0 < min_s1_count=3 → is_s_class=False → SKIP分岐
        """
        race = {
            "sport": "keirin",
            "race_type": "特選",
            "venue": "熊本",
            "track_length": 400,
            "race_number": 9,
            "comment": "",
            "entries": [],
        }
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"

    def test_bool_filter_result_false_with_sufficient_s1(self, classifier):
        """filter_result=False (bool) → CREフィルター不通過として扱われる。

        根拠: classify() の bool 正規化 → {"passed": False}
        S1=3名以上でも、B tier は filter_passed が必要（L266）
        """
        race = _keirin_race("一般", "小倉", 400, s1_count=3)
        result = classifier.classify(race, False)
        # filter_passed=False × is_a/s_race_type=False → SKIP
        assert result["tier"] == "SKIP"

    def test_default_config_used_when_no_path(self, classifier):
        """TierClassifier(config_path=None) でデフォルト設定が使用される。

        根拠: _load_config(None, sport) → default copy を返す
        """
        # デフォルト設定の min_s1_count=3 が適用されているか確認
        cfg_defaults = _DEFAULT_CONFIG["keirin"]
        assert cfg_defaults["min_s1_count"] == 3
        assert "熊本" in cfg_defaults["tier_s_preferred_venues"]
        assert "特選" in cfg_defaults["tier_s_race_types"]

    def test_track_length_zero_treated_as_non_500m(self, classifier):
        """track_length=0（未設定）→ is_non_500m=True として扱われる。

        根拠: L215: is_non_500m = (track_length not in avoid_lengths) if track_length else True
        track_length=0 は falsy → True を返す
        """
        race = {
            "sport": "keirin",
            "race_type": "特選",
            "venue": "熊本",
            "track_length": 0,  # 未設定
            "race_number": 9,
            "comment": "",
            "entries": _make_s1_entries(4),
        }
        result = classifier.classify(race, {"passed": True})
        # 0m = track_length 未設定 → is_non_500m=True → Tier S 成立
        assert result["tier"] == "S"

    def test_result_dict_has_all_required_keys(self, classifier):
        """classify() の戻り値に必須キー 5つが揃っていることを確認。

        根拠: _classify_keirin L293-299 の戻り値定義
        """
        race = _keirin_race("特選", "熊本", 400, s1_count=4)
        result = classifier.classify(race, {"passed": True})
        required_keys = {"tier", "filter_type", "confidence_score", "reasons", "negative_flags"}
        assert required_keys.issubset(result.keys())

    def test_reasons_list_is_not_empty(self, classifier):
        """classify() 戻り値の reasons リストは空でない。

        根拠: 各 Tier 分岐で reasons.append() が必ず呼ばれる
        """
        for race_type, venue in [
            ("特選", "熊本"),
            ("準決勝", "防府"),
            ("一般", "小倉"),
        ]:
            race = _keirin_race(race_type, venue, 400, s1_count=3)
            result = classifier.classify(race, {"passed": True})
            assert len(result["reasons"]) > 0, f"{race_type}×{venue} で reasons が空"


# ═══════════════════════════════════════════════════════════════════════════
# Group 7: 競艇 Tier テスト（補足）
# ═══════════════════════════════════════════════════════════════════════════

class TestKyoteiTier:
    """競艇 Tier 判定テスト（sport="kyotei" のルーティング確認）。"""

    def test_kyotei_tier_s(self, classifier):
        """住之江×1号艇×モーター45% → 競艇 Tier S。

        根拠: tier_s_anchor=1, motor_threshold=42.0%, 住之江 = tier_s_preferred_venues
        """
        race = {
            "sport": "kyotei",
            "venue": "住之江",
            "race_number": 7,
            "anchor_course": 1,
            "comment": "",
            "entries": [
                {"course": 1, "motor_win_rate": 45.0, "flying_count": 0},
                {"course": 2, "motor_win_rate": 38.0, "flying_count": 0},
            ],
        }
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "S"
        assert result["filter_type"] == "A"

    def test_kyotei_skip_flying(self, classifier):
        """F保持選手（flying_count>=1）含む → 競艇 SKIP。

        根拠: skip_flying_count_threshold=1
        """
        race = {
            "sport": "kyotei",
            "venue": "住之江",
            "race_number": 3,
            "anchor_course": 1,
            "comment": "",
            "entries": [
                {"course": 1, "motor_win_rate": 45.0, "flying_count": 0},
                {"course": 2, "motor_win_rate": 38.0, "flying_count": 1},
            ],
        }
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"
        assert any("F保持" in flag for flag in result["negative_flags"])

    def test_kyotei_skip_reverse_keyword(self, classifier):
        """競艇でも逆指標「鉄板」→ SKIP。

        根拠: 競艇も reverse_indicator_keywords を共有
        """
        race = {
            "sport": "kyotei",
            "venue": "住之江",
            "race_number": 5,
            "anchor_course": 1,
            "comment": "鉄板！絶対来る！",
            "entries": [
                {"course": 1, "motor_win_rate": 45.0, "flying_count": 0},
            ],
        }
        result = classifier.classify(race, {"passed": True})
        assert result["tier"] == "SKIP"
