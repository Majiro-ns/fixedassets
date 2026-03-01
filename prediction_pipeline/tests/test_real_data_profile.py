"""
tests/test_real_data_profile.py
================================
実データを使ったMr.Tプロファイル検証 + ROI計算検証テスト。
cmd_139k_sub3: 足軽3 担当

【モック禁止】全テストは実データファイルを直接読み込む。

テスト期待値根拠（CHECK-9）:
  - Mr.Tプロファイル値: config/keirin/profiles/mr_t.yaml
    （netkeirin ID 634の842件蓄積予想データから生成されたCREプロファイル原本）
  - ROI計算値: data/logs/monthly_roi.json（実際の賭け記録 2月）
  - 実結果データ: data/results/20260228_results.json
  - フィルター設定: config/keirin/filters.yaml

【CHECK-7b: 手計算検算】
  2月ROI手計算:
    - total_investment = 26,400円, bet_count = 8件
    - 1件平均 = 26,400 / 8 = 3,300円/件
    - total_payout = 0円（全件未的中）
    - actual_roi = 0 / 26,400 × 100 = 0.0%

  20260228の賭け記録:
    - 大垣12R: investment=1,200円, hit=false → payout=0
    - 和歌山12R: investment=3,600円, hit=false → payout=0
    - 合計投資 = 1,200 + 3,600 = 4,800円
    - 合計払戻 = 0円
    - ROI = 0 / 4,800 = 0.0 (0%)
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

# ─── パス設定 ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from profile_loader import ProfileLoader
from tier_classifier import TierClassifier

# ─── 実データファイルパス ──────────────────────────────────────────────────────
PROFILE_PATH     = ROOT / "config" / "keirin" / "profiles" / "mr_t.yaml"
FILTER_PATH      = ROOT / "config" / "keirin" / "filters.yaml"
MONTHLY_ROI_PATH = ROOT / "data" / "logs" / "monthly_roi.json"
RESULTS_PATH     = ROOT / "data" / "results" / "20260228_results.json"
BACKTEST_PATH    = ROOT / "data" / "backtest" / "keirin_backtest_input.json"


# ─────────────────────────────────────────────────────────────────────────────
# フィクスチャ（実データをロード、モックなし）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mr_t_profile():
    """mr_t.yaml を実際にロードして返す（モックなし）。"""
    assert PROFILE_PATH.exists(), f"mr_t.yaml が見つからない: {PROFILE_PATH}"
    with open(PROFILE_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def filters_config():
    """filters.yaml を実際にロードして返す（モックなし）。"""
    assert FILTER_PATH.exists(), f"filters.yaml が見つからない: {FILTER_PATH}"
    with open(FILTER_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def monthly_roi():
    """monthly_roi.json を実際にロードして返す（モックなし）。"""
    assert MONTHLY_ROI_PATH.exists(), f"monthly_roi.json が見つからない: {MONTHLY_ROI_PATH}"
    with open(MONTHLY_ROI_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def results_20260228():
    """20260228_results.json を実際にロードして返す（モックなし）。"""
    assert RESULTS_PATH.exists(), f"20260228_results.json が見つからない: {RESULTS_PATH}"
    with open(RESULTS_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def backtest_input():
    """keirin_backtest_input.json を実際にロードして返す（モックなし）。"""
    assert BACKTEST_PATH.exists(), f"keirin_backtest_input.json が見つからない: {BACKTEST_PATH}"
    with open(BACKTEST_PATH, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# a. Mr.Tプロファイル内部整合性テスト
# ─────────────────────────────────────────────────────────────────────────────

class TestMrTProfileInternalConsistency:
    """Mr.Tプロファイルの内部整合性を検証する。

    根拠: config/keirin/profiles/mr_t.yaml（CREプロファイル原本 / netkeirin ID 634）
    """

    def test_strengths_venues_recovery_rate_above_1(self, mr_t_profile):
        """得意会場のrecovery_rateは全て1.0超であるべき。
        根拠: mr_t.yaml strengths.venues — 熊本1.69, 別府1.69, 防府1.55"""
        venues = mr_t_profile["strengths"]["venues"]
        assert len(venues) > 0, "得意会場リストが空"
        for v in venues:
            assert v["recovery_rate"] > 1.0, (
                f"得意会場「{v['name']}」の recovery_rate={v['recovery_rate']} が 1.0 以下"
            )

    def test_weaknesses_race_types_recovery_rate_below_1(self, mr_t_profile):
        """苦手レース種別のrecovery_rateは全て1.0未満であるべき。
        根拠: mr_t.yaml weaknesses.race_types — 決勝0.67, 選抜0.49,
              準決勝0.51(実パイプライン計算), 二次予選0.55(実パイプライン計算)
        CHECK-7b手計算: 準決勝ROI=51.25%→0.51, 二次予選ROI=55.38%→0.55"""
        race_types = mr_t_profile["weaknesses"]["race_types"]
        assert len(race_types) > 0, "苦手レース種別リストが空"
        for rt in race_types:
            assert rt["recovery_rate"] < 1.0, (
                f"苦手レース種別「{rt['name']}」の recovery_rate={rt['recovery_rate']} が 1.0 以上"
            )

    def test_high_confidence_min_hit_rate_exceeds_low_confidence_max(self, mr_t_profile):
        """high_confidenceの最小hit_rate > low_confidenceの最大hit_rate。
        根拠: trust_signals — high_confidence最小=0.300(高配当), low_confidence最大=0.109(自信)"""
        high_conf = mr_t_profile["trust_signals"]["high_confidence"]
        low_conf  = mr_t_profile["trust_signals"]["low_confidence"]

        high_rates = [s["hit_rate"] for s in high_conf if "hit_rate" in s]
        low_rates  = [s["hit_rate"] for s in low_conf  if "hit_rate" in s]

        assert len(high_rates) > 0, "high_confidence に hit_rate を持つシグナルがない"
        assert len(low_rates)  > 0, "low_confidence に hit_rate を持つシグナルがない"

        min_high = min(high_rates)
        max_low  = max(low_rates)

        assert min_high > max_low, (
            f"high_confidence 最小hit_rate({min_high:.3f}) <= "
            f"low_confidence 最大hit_rate({max_low:.3f})"
        )

    def test_reverse_indicator_jishin_recovery_rate_is_0270(self, mr_t_profile):
        """逆指標「自信」のrecovery_rateは0.270（逆指標として最悪クラス）。
        根拠: trust_signals.low_confidence — 「自信」hit_rate=10.9%, recovery_rate=0.270"""
        low_conf = mr_t_profile["trust_signals"]["low_confidence"]
        jishin = next((s for s in low_conf if s["keyword"] == "自信"), None)
        assert jishin is not None, "「自信」シグナルが trust_signals.low_confidence に見つからない"
        assert jishin["recovery_rate"] == pytest.approx(0.270, abs=0.001), (
            f"「自信」recovery_rate 期待=0.270, 実際={jishin['recovery_rate']}"
        )
        assert jishin["hit_rate"] == pytest.approx(0.109, abs=0.001), (
            f"「自信」hit_rate 期待=0.109, 実際={jishin['hit_rate']}"
        )

    def test_reverse_indicator_tetsuban_recovery_rate_below_1(self, mr_t_profile):
        """逆指標「鉄板」のrecovery_rateは1.0未満（過信バイアス）。
        根拠: trust_signals.low_confidence — 「鉄板」recovery_rate=0.609"""
        low_conf = mr_t_profile["trust_signals"]["low_confidence"]
        tetsuban = next((s for s in low_conf if s["keyword"] == "鉄板"), None)
        assert tetsuban is not None, "「鉄板」シグナルが trust_signals.low_confidence に見つからない"
        assert tetsuban["recovery_rate"] < 1.0, (
            f"「鉄板」recovery_rate={tetsuban['recovery_rate']} が 1.0 以上（逆指標が有利になっている）"
        )
        assert tetsuban["recovery_rate"] == pytest.approx(0.609, abs=0.001), (
            f"「鉄板」recovery_rate 期待=0.609, 実際={tetsuban['recovery_rate']}"
        )

    def test_high_recovery_patterns_all_above_1(self, mr_t_profile):
        """high_recovery_patterns の全パターンの recovery_rate が 1.0 超。
        根拠: mr_t.yaml high_recovery_patterns — 絞1.658, 獲りやすさ1.507, 高配当2.639, 大穴2.065"""
        patterns = mr_t_profile.get("high_recovery_patterns", [])
        assert len(patterns) > 0, "high_recovery_patterns が空"
        for p in patterns:
            assert p["recovery_rate"] > 1.0, (
                f"高回収パターン「{p['keyword']}」recovery_rate={p['recovery_rate']} が 1.0 以下"
            )

    def test_reverse_indicator_patterns_all_below_1(self, mr_t_profile):
        """reverse_indicator_patterns の全パターンの recovery_rate が 1.0 未満。
        根拠: mr_t.yaml reverse_indicator_patterns — 自信0.270, 鉄板0.609"""
        patterns = mr_t_profile.get("reverse_indicator_patterns", [])
        assert len(patterns) > 0, "reverse_indicator_patterns が空"
        for p in patterns:
            assert p["recovery_rate"] < 1.0, (
                f"逆指標「{p['keyword']}」recovery_rate={p['recovery_rate']} が 1.0 以上"
            )

    def test_shibo_keyword_highest_recovery_rate(self, mr_t_profile):
        """「絞」キーワードの recovery_rate=1.658 (最重要高精度シグナル)。
        根拠: mr_t.yaml trust_signals.high_confidence — 「絞れる」hit_rate=50%"""
        high_conf = mr_t_profile["trust_signals"]["high_confidence"]
        shibo = next((s for s in high_conf if s["keyword"] == "絞"), None)
        assert shibo is not None, "「絞」シグナルが trust_signals.high_confidence に見つからない"
        assert shibo["hit_rate"] == pytest.approx(0.500, abs=0.001)
        assert shibo["recovery_rate"] == pytest.approx(1.658, abs=0.001)

    def test_basic_stats_hit_rate_range(self, mr_t_profile):
        """basic_stats.hit_rate が 0〜1 の範囲に収まる。
        根拠: mr_t.yaml basic_stats — hit_rate=0.35（全予想平均）"""
        stats = mr_t_profile.get("basic_stats", {})
        hit_rate = stats.get("hit_rate", -1)
        assert 0.0 <= hit_rate <= 1.0, (
            f"basic_stats.hit_rate={hit_rate} が範囲外"
        )

    def test_weaknesses_race_numbers_are_4_and_6(self, mr_t_profile):
        """苦手レース番号が[4, 6]であること。
        根拠: mr_t.yaml weaknesses.race_numbers=[4,6]（回収率24〜33%）"""
        race_numbers = mr_t_profile["weaknesses"].get("race_numbers", [])
        assert set(race_numbers) == {4, 6}, (
            f"weaknesses.race_numbers 期待={{4,6}}, 実際={set(race_numbers)}"
        )

    def test_weaknesses_banks_contains_500m(self, mr_t_profile):
        """苦手バンクに '500m' が含まれること。
        根拠: mr_t.yaml weaknesses.banks=['500m']（ROI=62%）"""
        banks = mr_t_profile["weaknesses"].get("banks", [])
        assert "500m" in banks, f"weaknesses.banks に '500m' がない: {banks}"


# ─────────────────────────────────────────────────────────────────────────────
# b. フィルター設定との整合性テスト
# ─────────────────────────────────────────────────────────────────────────────

class TestFilterProfileAlignment:
    """filters.yaml と mr_t.yaml の設定整合性を検証する。

    根拠: config/keirin/filters.yaml vs config/keirin/profiles/mr_t.yaml
    """

    def test_f2_excludes_mr_t_weakness_race_types(self, mr_t_profile, filters_config):
        """F2 allowlist に mr_t の苦手レース種別（決勝・選抜・準決勝・二次予選）が含まれないこと。
        根拠: mr_t.yaml weaknesses.race_types(決勝0.67, 選抜0.49, 準決勝0.51, 二次予選0.55)
              全てF2から除外済み（cmd_126k_sub2）"""
        allowed_race_types = filters_config.get("race_type", [])
        weakness_race_types = [rt["name"] for rt in mr_t_profile["weaknesses"]["race_types"]]

        for weak_type in weakness_race_types:
            assert weak_type not in allowed_race_types, (
                f"苦手レース種別「{weak_type}」が F2 allowlist に含まれている"
            )

    def test_f2_includes_mr_t_primary_strength_tokusen(self, filters_config):
        """F2 allowlist に「特選」が含まれること（mr_t 得意 ROI=130%）。
        根拠: mr_t.yaml strengths.race_types — 特選 recovery_rate=1.30"""
        allowed_race_types = filters_config.get("race_type", [])
        assert "特選" in allowed_race_types, "「特選」が F2 allowlist に含まれていない"

    def test_f4_exclude_velodromes_not_in_mr_t_strength_venues(
        self, mr_t_profile, filters_config
    ):
        """F4 除外会場が mr_t の得意会場リストに含まれないこと（逆相関確認）。
        根拠: F4除外場(小田原/名古屋/高知/玉野/武雄=0〜30%ROI) は得意会場と逆相関すべき"""
        exclude_velodromes = filters_config.get("exclude_velodromes", [])
        strength_venues = [v["name"] for v in mr_t_profile["strengths"]["venues"]]

        for excl_venue in exclude_velodromes:
            assert excl_venue not in strength_venues, (
                f"F4除外場「{excl_venue}」が mr_t 得意会場に含まれている（逆相関矛盾）"
            )

    def test_f6_weekday_exclusions_match_mr_t_weaknesses(
        self, mr_t_profile, filters_config
    ):
        """F6 除外曜日が mr_t の苦手曜日と整合すること。
        根拠: mr_t.yaml weaknesses.weekdays=['日曜','月曜']
              filters.yaml exclude_day_of_week=['月','日']"""
        exclude_days = filters_config.get("exclude_day_of_week", [])
        weakness_weekdays = mr_t_profile["weaknesses"].get("weekdays", [])

        # フィルター短縮形 → プロファイル表記のマッピング
        day_mapping = {"日": "日曜", "月": "月曜"}

        for filter_day in exclude_days:
            profile_day = day_mapping.get(filter_day, filter_day)
            assert profile_day in weakness_weekdays, (
                f"F6 除外曜日「{filter_day}」(プロファイル表記「{profile_day}」) が"
                f" mr_t 苦手曜日{weakness_weekdays} に含まれない"
            )

    def test_f7_race_numbers_match_mr_t_weaknesses(self, mr_t_profile, filters_config):
        """F7 除外レース番号が mr_t の苦手レース番号と一致すること。
        根拠: mr_t.yaml weaknesses.race_numbers=[4,6]
              filters.yaml exclude_race_number=[4,6]（回収率24〜33%）"""
        exclude_race_numbers = set(filters_config.get("exclude_race_number", []))
        weakness_race_numbers = set(mr_t_profile["weaknesses"].get("race_numbers", []))
        assert exclude_race_numbers == weakness_race_numbers, (
            f"F7 除外番号 {exclude_race_numbers} と mr_t 苦手番号 {weakness_race_numbers} が不一致"
        )

    def test_f3_keywords_cover_mr_t_reverse_indicators(
        self, mr_t_profile, filters_config
    ):
        """F3 exclude_keywords が mr_t の reverse_indicator_patterns を網羅すること。
        根拠: mr_t.yaml reverse_indicator_patterns.keyword ⊆ filters.yaml exclude_keywords"""
        exclude_keywords = filters_config.get("exclude_keywords", [])
        reverse_patterns = mr_t_profile.get("reverse_indicator_patterns", [])

        for p in reverse_patterns:
            kw = p["keyword"]
            assert kw in exclude_keywords, (
                f"逆指標「{kw}」が F3 exclude_keywords に含まれていない"
            )

    def test_f5_500m_bank_exclusion_matches_mr_t_weakness(
        self, mr_t_profile, filters_config
    ):
        """F5 500mバンク除外が mr_t の苦手バンクと整合すること。
        根拠: mr_t.yaml weaknesses.banks=['500m'] / filters.yaml exclude_track_500m=true"""
        exclude_500m = filters_config.get("exclude_track_500m", False)
        weakness_banks = mr_t_profile["weaknesses"].get("banks", [])

        assert exclude_500m is True, "F5 exclude_track_500m が True でない"
        assert "500m" in weakness_banks, "mr_t 苦手バンクに '500m' が含まれていない"

    def test_f3_contains_jishin_and_tetsuban(self, filters_config):
        """F3 exclude_keywords に「自信」と「鉄板」が含まれること。
        根拠: mr_t.yaml — 「自信」ROI=27%, 「鉄板」ROI=61%（逆指標筆頭）"""
        exclude_keywords = filters_config.get("exclude_keywords", [])
        for kw in ["自信", "鉄板"]:
            assert kw in exclude_keywords, (
                f"逆指標「{kw}」が F3 exclude_keywords に含まれていない"
            )


# ─────────────────────────────────────────────────────────────────────────────
# c. CRE統合テスト
# ─────────────────────────────────────────────────────────────────────────────

class TestCREIntegration:
    """profile_loader + tier_classifier の実データ統合テスト。

    根拠: mr_t.yaml プロファイルを用いたスコア計算とTier分類
    """

    def test_profile_loader_loads_mr_t_correctly(self):
        """profile_loader.py で mr_t.yaml を実際にロードし構造検証。
        根拠: ProfileLoader.load() の実動作確認（cmd_131k_sub1 CRE断絶バグ再発防止）"""
        loader = ProfileLoader(str(ROOT / "config" / "keirin" / "profiles"))
        profile = loader.load("mr_t")

        assert profile is not None, "mr_t.yaml のロードに失敗"
        assert profile["profile_id"] == "mr_t_634"
        assert profile["sport"] == "keirin"
        assert "trust_signals" in profile
        assert "strengths" in profile
        assert "weaknesses" in profile
        assert "high_recovery_patterns" in profile
        assert "reverse_indicator_patterns" in profile

    def test_profile_loader_mr_t_listed_in_profiles(self):
        """list_profiles() に 'mr_t' が含まれること。
        根拠: config/keirin/profiles/mr_t.yaml の存在確認"""
        loader = ProfileLoader(str(ROOT / "config" / "keirin" / "profiles"))
        profiles = loader.list_profiles()
        assert "mr_t" in profiles

    def test_tier_s_kumamoto_tokusen_s1_3nin(self):
        """mr_t得意会場(熊本)×特選×S1×3名→Tier S判定。
        根拠: mr_t.yaml strengths.venues(熊本ROI169%) + strengths.race_types(特選ROI130%)
        tier_classifier.py: filter_A = S1>=3 × 特選/二次予選 × 優良場 × 非500m"""
        classifier = TierClassifier(config_path=str(ROOT / "config"))
        race_data = {
            "sport": "keirin",
            "race_type": "特選",
            "venue": "熊本",
            "track_length": 400,
            "race_number": 10,
            "comment": "ライン絞れる一戦。S1上位選手が揃った。",
            "entries": [
                {"grade": "S1"}, {"grade": "S1"}, {"grade": "S1"},
                {"grade": "S2"}, {"grade": "A1"}, {"grade": "A1"},
                {"grade": "A2"},
            ],
        }
        result = classifier.classify(race_data, {"passed": True})
        assert result["tier"] == "S", (
            f"熊本×特選×S1×3名 → 期待=Tier S, 実際={result['tier']}. "
            f"reasons={result['reasons']}"
        )
        assert result["confidence_score"] >= 0.9, (
            f"Tier S の confidence_score が低い: {result['confidence_score']}"
        )

    def test_tier_skip_jishin_keyword_overrides_all(self):
        """逆指標「自信」含む予想→Tier SKIP判定（優良条件でもSKIP）。
        根拠: mr_t.yaml reverse_indicator_patterns — 「自信」ROI=27%, hit_rate=10.9%
        tier_classifier.py: has_reverse → 常にSKIP（最優先）"""
        classifier = TierClassifier(config_path=str(ROOT / "config"))
        race_data = {
            "sport": "keirin",
            "race_type": "特選",
            "venue": "熊本",
            "track_length": 400,
            "race_number": 11,
            "comment": "自信あります！今日の本命！熊本特選S1勢揃い。",
            "entries": [
                {"grade": "S1"}, {"grade": "S1"}, {"grade": "S1"},
                {"grade": "S1"}, {"grade": "S2"}, {"grade": "A1"},
                {"grade": "A1"},
            ],
        }
        result = classifier.classify(race_data, {"passed": True})
        assert result["tier"] == "SKIP", (
            f"逆指標「自信」→ 期待=SKIP, 実際={result['tier']}. "
            f"reasons={result['reasons']}"
        )
        # 逆指標フラグが negative_flags に記録されること
        assert any("自信" in flag for flag in result["negative_flags"]), (
            f"逆指標「自信」が negative_flags に記録されていない: {result['negative_flags']}"
        )

    def test_tier_skip_kessho_filter_not_passed(self):
        """mr_t苦手「決勝」はフィルター不通過→Tier SKIP判定。
        根拠: mr_t.yaml weaknesses.race_types(決勝ROI=67%) / F2除外（ROI=0%）"""
        classifier = TierClassifier(config_path=str(ROOT / "config"))
        race_data = {
            "sport": "keirin",
            "race_type": "決勝",
            "venue": "熊本",
            "track_length": 400,
            "race_number": 12,
            "comment": "ライン絞れる一戦",
            "entries": [
                {"grade": "S1"}, {"grade": "S1"}, {"grade": "S1"},
                {"grade": "S2"}, {"grade": "A1"}, {"grade": "A1"},
                {"grade": "A2"},
            ],
        }
        # F2で決勝はフィルター不通過として渡す
        result = classifier.classify(race_data, {"passed": False})
        assert result["tier"] == "SKIP", (
            f"フィルター不通過（決勝）→ 期待=SKIP, 実際={result['tier']}"
        )

    def test_tier_classifier_with_real_backtest_kumamoto(self, backtest_input):
        """実バックテストデータ（熊本2R/特選/S1×5名）でTier分類実行。
        根拠: data/backtest/keirin_backtest_input.json — filter_type=C（得意会場×特選×S1）
        期待: Tier S（熊本×特選×S1×5名×400m×逆指標なし）"""
        classifier = TierClassifier(config_path=str(ROOT / "config"))

        races = backtest_input.get("races", [])
        assert len(races) > 0, "バックテストデータにレースが存在しない"

        # 最初のレース: keirin_kumamoto_2R_20260223 (熊本×特選)
        kumamoto_race = races[0]
        assert kumamoto_race["venue"] == "熊本", (
            f"最初のレースが熊本でない: {kumamoto_race['venue']}"
        )
        assert kumamoto_race["stage"] == "特選"

        entries = kumamoto_race.get("entries", [])
        assert len(entries) > 0, "バックテストエントリが空"

        race_data = {
            "sport": "keirin",
            "race_type": kumamoto_race["stage"],
            "venue": kumamoto_race["venue"],
            "track_length": kumamoto_race.get("bank_length", 400),
            "race_number": kumamoto_race["race_num"],
            "comment": kumamoto_race.get("mr_t_comment", ""),
            "entries": [{"grade": e.get("grade", "S1")} for e in entries],
        }

        result = classifier.classify(race_data, {"passed": True})

        # 熊本×特選×S1×5名→Tier S が期待値
        # S1カウント確認（検算）
        s1_count = sum(1 for e in entries if e.get("grade") == "S1")
        assert s1_count >= 3, f"S1選手数が3未満: {s1_count}名"

        assert result["tier"] == "S", (
            f"熊本×特選×S1×{s1_count}名 バックテストデータ → 期待=Tier S, "
            f"実際={result['tier']}. reasons={result['reasons']}"
        )

    def test_tier_confidence_score_logic(self):
        """confidence_score が条件充足に応じて増加すること。
        根拠: tier_classifier.py _keirin_score() の重み付き合算（合計1.0）"""
        classifier = TierClassifier(config_path=None)  # デフォルト設定使用

        # 全条件充足（Tier S）
        race_s = {
            "sport": "keirin", "race_type": "特選", "venue": "熊本",
            "track_length": 400, "race_number": 9, "comment": "絞れる一戦",
            "entries": [{"grade": "S1"}, {"grade": "S1"}, {"grade": "S1"},
                        {"grade": "S2"}, {"grade": "A1"}, {"grade": "A1"}, {"grade": "A2"}],
        }
        # 条件不充足（SKIP）
        race_skip = {
            "sport": "keirin", "race_type": "一般", "venue": "小田原",
            "track_length": 500, "race_number": 5, "comment": "自信あり",
            "entries": [{"grade": "A1"}, {"grade": "A1"}, {"grade": "A2"},
                        {"grade": "A2"}, {"grade": "A2"}, {"grade": "A2"}, {"grade": "A2"}],
        }
        res_s    = classifier.classify(race_s,    {"passed": True})
        res_skip = classifier.classify(race_skip, {"passed": False})

        assert res_s["confidence_score"] > res_skip["confidence_score"], (
            f"Tier S のスコア({res_s['confidence_score']}) <= "
            f"SKIP のスコア({res_skip['confidence_score']})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# d. ROI計算検証テスト（実データ手計算検算 CHECK-7b）
# ─────────────────────────────────────────────────────────────────────────────

class TestROICalculationVerification:
    """monthly_roi.json と 20260228_results.json を使ったROI検証。

    【手計算検算 CHECK-7b】
    2月 monthly_roi.json:
      - total_investment = 26,400円 / bet_count = 8件
      - 1件平均 = 26,400 / 8 = 3,300円/件
      - total_payout = 0円（全件未的中） → actual_roi = 0.0%

    20260228 実賭け記録:
      - 大垣12R:  investment=1,200円, hit=false → payout=0
      - 和歌山12R: investment=3,600円, hit=false → payout=0
      - 合計投資 = 1,200 + 3,600 = 4,800円, 合計払戻 = 0円, ROI = 0.0
    """

    def test_february_total_investment_is_26400(self, monthly_roi):
        """2月の総投資額が26,400円であること。
        根拠: data/logs/monthly_roi.json 202602.total_investment=26400"""
        feb = monthly_roi.get("202602", {})
        assert feb.get("total_investment") == 26400, (
            f"2月総投資額 期待=26,400円, 実際={feb.get('total_investment')}円"
        )

    def test_february_bet_count_is_8(self, monthly_roi):
        """2月の BET 件数が8件であること。
        根拠: data/logs/monthly_roi.json 202602.bet_count=8"""
        feb = monthly_roi.get("202602", {})
        assert feb.get("bet_count") == 8, (
            f"2月BET件数 期待=8件, 実際={feb.get('bet_count')}件"
        )

    def test_february_per_bet_investment_is_3300(self, monthly_roi):
        """1件あたり投資額が3,300円であること（手計算: 26,400 / 8 = 3,300）。
        根拠: monthly_roi.json 202602 から手計算"""
        feb = monthly_roi.get("202602", {})
        total = feb.get("total_investment", 0)
        count = feb.get("bet_count", 0)
        assert count > 0
        per_bet = total / count
        assert per_bet == pytest.approx(3300.0, abs=0.1), (
            f"1件あたり投資額 期待=3,300円, 実際={per_bet}円 "
            f"(total={total}, count={count})"
        )

    def test_february_total_payout_is_zero(self, monthly_roi):
        """2月の総払戻額が0円であること（全件未的中）。
        根拠: monthly_roi.json 202602.total_payout=0"""
        feb = monthly_roi.get("202602", {})
        assert feb.get("total_payout") == 0, (
            f"2月総払戻額 期待=0円, 実際={feb.get('total_payout')}円"
        )

    def test_february_actual_roi_is_zero(self, monthly_roi):
        """2月の actual_roi が 0.0 であること（手計算: 0/26400×100=0.0）。
        根拠: monthly_roi.json 202602.actual_roi=0.0"""
        feb = monthly_roi.get("202602", {})
        actual_roi = feb.get("actual_roi", -1)
        assert actual_roi == pytest.approx(0.0, abs=0.001), (
            f"2月 actual_roi 期待=0.0, 実際={actual_roi}"
        )

    def test_february_hit_count_is_zero(self, monthly_roi):
        """2月の的中件数が0件であること。
        根拠: monthly_roi.json 202602.hit_count=0"""
        feb = monthly_roi.get("202602", {})
        assert feb.get("hit_count") == 0, (
            f"2月的中件数 期待=0件, 実際={feb.get('hit_count')}件"
        )

    def test_february_dates_processed_contains_20260228(self, monthly_roi):
        """2月の処理済み日付に '20260228' が含まれること。
        根拠: monthly_roi.json 202602.dates_processed"""
        feb = monthly_roi.get("202602", {})
        dates = feb.get("dates_processed", [])
        assert "20260228" in dates, (
            f"'20260228' が処理済み日付に含まれない: {dates}"
        )

    def test_results_20260228_has_two_our_predictions(self, results_20260228):
        """20260228_results.json に our_prediction 付きレースが2件あること。
        根拠: 大垣12R + 和歌山12R の2件に our_prediction フィールドが存在"""
        races = results_20260228.get("races", [])
        bet_races = [r for r in races if "our_prediction" in r]
        assert len(bet_races) == 2, (
            f"our_prediction 付きレースが2件でない: {len(bet_races)}件"
        )

    def test_oohagi_r12_investment_is_1200(self, results_20260228):
        """大垣12R の投資額が1,200円であること（手計算検算）。
        根拠: 20260228_results.json 大垣12R.our_prediction.investment=1200"""
        races = results_20260228.get("races", [])
        oohagi_r12 = next(
            (r for r in races if r["venue"] == "大垣" and r["race_no"] == 12), None
        )
        assert oohagi_r12 is not None, "大垣12R が results に存在しない"
        pred = oohagi_r12.get("our_prediction", {})
        assert pred.get("investment") == 1200, (
            f"大垣12R 投資額 期待=1,200円, 実際={pred.get('investment')}円"
        )

    def test_wakayama_r12_investment_is_3600(self, results_20260228):
        """和歌山12R の投資額が3,600円であること（手計算検算）。
        根拠: 20260228_results.json 和歌山12R.our_prediction.investment=3600"""
        races = results_20260228.get("races", [])
        wakayama_r12 = next(
            (r for r in races if r["venue"] == "和歌山" and r["race_no"] == 12), None
        )
        assert wakayama_r12 is not None, "和歌山12R が results に存在しない"
        pred = wakayama_r12.get("our_prediction", {})
        assert pred.get("investment") == 3600, (
            f"和歌山12R 投資額 期待=3,600円, 実際={pred.get('investment')}円"
        )

    def test_all_bets_20260228_are_missed(self, results_20260228):
        """20260228 の全賭けが外れている（hit=false）こと。
        根拠: 20260228_results.json our_prediction のある全レースが hit=false"""
        races = results_20260228.get("races", [])
        bet_races = [r for r in races if "our_prediction" in r]
        assert len(bet_races) > 0
        for r in bet_races:
            assert r.get("hit") is False, (
                f"{r['venue']} {r['race_no']}R: hit={r.get('hit')} (期待=false)"
            )

    def test_all_payouts_20260228_are_zero(self, results_20260228):
        """20260228 の全賭け払戻額が0円であること。
        根拠: 20260228_results.json our_prediction のある全レースが payout=0"""
        races = results_20260228.get("races", [])
        bet_races = [r for r in races if "our_prediction" in r]
        for r in bet_races:
            assert r.get("payout") == 0, (
                f"{r['venue']} {r['race_no']}R: payout={r.get('payout')} (期待=0)"
            )

    def test_roi_formula_manual_calculation_20260228(self, results_20260228):
        """ROI 手計算検証: ROI = total_payout / total_investment。
        手計算: 大垣12R(1,200) + 和歌山12R(3,600) = 4,800円投資, 払戻0円 → ROI=0.0"""
        races = results_20260228.get("races", [])
        bet_races = [r for r in races if "our_prediction" in r]

        total_investment = sum(
            r["our_prediction"].get("investment", 0) for r in bet_races
        )
        total_payout = sum(r.get("payout", 0) for r in bet_races)

        # 手計算検算: 1200 + 3600 = 4800円
        assert total_investment == 4800, (
            f"20260228 合計投資額 期待=4,800円, 実際={total_investment}円"
        )
        # ROI = payout / investment（割合として）
        roi = total_payout / total_investment if total_investment > 0 else 0.0
        assert roi == pytest.approx(0.0, abs=0.001), (
            f"20260228 ROI 期待=0.0, 実際={roi}"
        )

    def test_trio_result_structure_all_races(self, results_20260228):
        """20260228_results.json の全レースに trio_result(3要素)と trio_payout が存在すること。
        根拠: scraper が三連複結果を取得する設計仕様"""
        races = results_20260228.get("races", [])
        assert len(races) > 0, "results ファイルにレースが存在しない"
        for r in races:
            assert "trio_result" in r, (
                f"{r['venue']} {r['race_no']}R に trio_result がない"
            )
            assert len(r["trio_result"]) == 3, (
                f"{r['venue']} {r['race_no']}R trio_result が3要素でない: {r['trio_result']}"
            )
            assert "trio_payout" in r
            assert isinstance(r["trio_payout"], int), (
                f"{r['venue']} {r['race_no']}R trio_payout が int でない"
            )
            assert r["trio_payout"] > 0, (
                f"{r['venue']} {r['race_no']}R trio_payout={r['trio_payout']} が0以下"
            )

    def test_results_date_matches_filename(self, results_20260228):
        """results ファイルの date フィールドがファイル名の日付と一致すること。
        根拠: 20260228_results.json の date="20260228" で整合性確認"""
        assert results_20260228.get("date") == "20260228", (
            f"date フィールド 期待='20260228', 実際={results_20260228.get('date')}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# e. roi_tracker.py 実データ検証
# ─────────────────────────────────────────────────────────────────────────────

class TestROITrackerWithRealData:
    """monthly_roi.json の実データを直接読んでスキーマ検証する。

    根拠: scripts/roi_tracker.py scan_output_for_month() の返却スキーマ仕様
    """

    def test_monthly_roi_json_exists_and_parseable(self):
        """monthly_roi.json が存在し、JSONとして読み込めること。
        根拠: data/logs/monthly_roi.json の存在・パース確認"""
        assert MONTHLY_ROI_PATH.exists(), (
            f"monthly_roi.json が存在しない: {MONTHLY_ROI_PATH}"
        )
        with open(MONTHLY_ROI_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), "monthly_roi.json のトップレベルが dict でない"

    def test_monthly_roi_schema_completeness(self, monthly_roi):
        """monthly_roi.json の全月データに必須フィールドが存在すること。
        根拠: roi_tracker.py scan_output_for_month() 返却スキーマ"""
        required_fields = [
            "month", "total_investment", "total_payout", "actual_roi",
            "bet_count", "hit_count", "hit_rate", "skip_count",
            "race_results", "dates_processed", "last_updated",
        ]
        for month_key, month_data in monthly_roi.items():
            for field in required_fields:
                assert field in month_data, (
                    f"{month_key} に必須フィールド '{field}' が欠如"
                )

    def test_monthly_roi_feb_data_consistency(self, monthly_roi):
        """2月データの internal consistency チェック。
        根拠: actual_roi = total_payout / total_investment × 100 の式"""
        feb = monthly_roi.get("202602", {})
        assert feb, "202602 のデータが存在しない"

        total_investment = feb["total_investment"]
        total_payout     = feb["total_payout"]
        actual_roi       = feb["actual_roi"]

        if total_investment > 0 and total_payout > 0:
            expected_roi = round(total_payout / total_investment * 100, 1)
            assert actual_roi == pytest.approx(expected_roi, abs=0.1), (
                f"actual_roi({actual_roi}) と手計算値({expected_roi}) が不一致"
            )
        elif total_payout == 0:
            assert actual_roi == pytest.approx(0.0, abs=0.001), (
                f"total_payout=0 なのに actual_roi={actual_roi} が 0.0 でない"
            )

    def test_monthly_roi_all_months_have_valid_data_types(self, monthly_roi):
        """全月の数値フィールドが正しい型であること。
        根拠: roi_tracker.py の型保証"""
        for month_key, month_data in monthly_roi.items():
            assert isinstance(month_data["total_investment"], int), (
                f"{month_key}.total_investment が int でない"
            )
            assert isinstance(month_data["bet_count"], int), (
                f"{month_key}.bet_count が int でない"
            )
            assert isinstance(month_data["actual_roi"], float), (
                f"{month_key}.actual_roi が float でない"
            )
            assert isinstance(month_data["race_results"], list), (
                f"{month_key}.race_results が list でない"
            )


# ─────────────────────────────────────────────────────────────────────────────
# f. cmd_143k_sub1: 実データ基準プロファイル修正検証テスト
# ─────────────────────────────────────────────────────────────────────────────

class TestProfileRealDataCorrections:
    """cmd_143k_sub1: 準決勝・二次予選をweaknessesに移動したことを検証する。

    【背景】
    cmd_139k_sub3 (A3) の実パイプライン計算で判明:
      - 準決勝: プロファイル推定125% → 実ROI 51.25%
      - 二次予選: プロファイル推定144% → 実ROI 55.38%
    殿の指示「見直せ」(2026-03-02) に基づき実データ値で更新。

    【CHECK-7b 手計算検算】
      - 準決勝 ROI=51.25% → recovery_rate = 51.25 / 100 = 0.5125 ≈ 0.51
      - 二次予選 ROI=55.38% → recovery_rate = 55.38 / 100 = 0.5538 ≈ 0.55
      - 両者とも 0 < recovery_rate < 1.0（損失圏） → weaknesses に配置が正しい

    【verification_source】
      filters.yaml コメント:「除外: 準決勝(51.25%), 二予選/二次予選(55.38%)」
      (cmd_126k_sub2 2026-03-01 更新 / A3 実データ検証 cmd_139k_sub3)
    """

    def test_junkessho_in_weaknesses_with_actual_roi(self, mr_t_profile):
        """準決勝が weaknesses.race_types に移動し recovery_rate=0.51（実パイプライン計算値）。
        根拠: filters.yaml cmd_126k_sub2 コメント「準決勝(51.25%)」
        手計算: 51.25 / 100 = 0.5125 → approx 0.51"""
        weakness_race_types = mr_t_profile["weaknesses"]["race_types"]
        junkessho = next(
            (rt for rt in weakness_race_types if rt["name"] == "準決勝"), None
        )
        assert junkessho is not None, (
            "「準決勝」が weaknesses.race_types に存在しない"
        )
        assert junkessho["recovery_rate"] == pytest.approx(0.51, abs=0.01), (
            f"準決勝 recovery_rate 期待=0.51(実ROI51.25%), 実際={junkessho['recovery_rate']}"
        )
        assert junkessho["recovery_rate"] < 1.0, "準決勝 recovery_rate が 1.0 以上（損失圏でない）"

    def test_niji_yosen_in_weaknesses_with_actual_roi(self, mr_t_profile):
        """二次予選が weaknesses.race_types に移動し recovery_rate=0.55（実パイプライン計算値）。
        根拠: filters.yaml cmd_126k_sub2 コメント「二予選/二次予選(55.38%)」
        手計算: 55.38 / 100 = 0.5538 → approx 0.55"""
        weakness_race_types = mr_t_profile["weaknesses"]["race_types"]
        niji_yosen = next(
            (rt for rt in weakness_race_types if rt["name"] == "二次予選"), None
        )
        assert niji_yosen is not None, (
            "「二次予選」が weaknesses.race_types に存在しない"
        )
        assert niji_yosen["recovery_rate"] == pytest.approx(0.55, abs=0.01), (
            f"二次予選 recovery_rate 期待=0.55(実ROI55.38%), 実際={niji_yosen['recovery_rate']}"
        )
        assert niji_yosen["recovery_rate"] < 1.0, "二次予選 recovery_rate が 1.0 以上（損失圏でない）"

    def test_junkessho_not_in_strengths(self, mr_t_profile):
        """準決勝が strengths.race_types に存在しないこと（weaknesses への移動を確認）。
        根拠: 実ROI=51.25%は得意ではなく苦手圏。CRE推定値1.25は誤り。"""
        strength_race_types = mr_t_profile["strengths"]["race_types"]
        names = [rt["name"] for rt in strength_race_types]
        assert "準決勝" not in names, (
            f"「準決勝」が依然として strengths.race_types に存在する: {names}"
        )

    def test_niji_yosen_not_in_strengths(self, mr_t_profile):
        """二次予選が strengths.race_types に存在しないこと（weaknesses への移動を確認）。
        根拠: 実ROI=55.38%は得意ではなく苦手圏。CRE推定値1.44は誤り。"""
        strength_race_types = mr_t_profile["strengths"]["race_types"]
        names = [rt["name"] for rt in strength_race_types]
        assert "二次予選" not in names, (
            f"「二次予選」が依然として strengths.race_types に存在する: {names}"
        )

    def test_tokusen_remains_in_strengths(self, mr_t_profile):
        """特選が strengths.race_types に残っていること（除外対象外）。
        根拠: filters.yaml F2 通過種別として現在も有効。"""
        strength_race_types = mr_t_profile["strengths"]["race_types"]
        names = [rt["name"] for rt in strength_race_types]
        assert "特選" in names, (
            f"「特選」が strengths.race_types にない: {names}"
        )
        tokusen = next(rt for rt in strength_race_types if rt["name"] == "特選")
        assert tokusen["recovery_rate"] > 1.0, (
            f"特選 recovery_rate={tokusen['recovery_rate']} が 1.0 以下（得意種別なのに損失圏）"
        )

    def test_high_recovery_patterns_have_status_field(self, mr_t_profile):
        """high_recovery_patterns の全パターンに status フィールドが存在すること。
        根拠: 実データ検証未済のため 'estimated' タグを付与（cmd_143k_sub1）"""
        patterns = mr_t_profile.get("high_recovery_patterns", [])
        assert len(patterns) > 0, "high_recovery_patterns が空"
        for p in patterns:
            assert "status" in p, (
                f"high_recovery_patterns「{p['keyword']}」に status フィールドがない"
            )
            assert p["status"] == "estimated", (
                f"高回収パターン「{p['keyword']}」status 期待='estimated', 実際={p['status']}"
            )

    def test_reverse_indicator_patterns_have_status_field(self, mr_t_profile):
        """reverse_indicator_patterns の全パターンに status フィールドが存在すること。
        根拠: CRE推定値。逆指標効果は高信頼度だが出典明記のため 'estimated' を付与。"""
        patterns = mr_t_profile.get("reverse_indicator_patterns", [])
        assert len(patterns) > 0, "reverse_indicator_patterns が空"
        for p in patterns:
            assert "status" in p, (
                f"reverse_indicator_patterns「{p['keyword']}」に status フィールドがない"
            )

    def test_weaknesses_now_has_four_race_types(self, mr_t_profile):
        """weaknesses.race_types が4種類（決勝・選抜・準決勝・二次予選）であること。
        根拠: cmd_143k_sub1 で準決勝・二次予選を追加"""
        weakness_race_types = mr_t_profile["weaknesses"]["race_types"]
        names = {rt["name"] for rt in weakness_race_types}
        expected = {"決勝", "選抜", "準決勝", "二次予選"}
        assert names == expected, (
            f"weaknesses.race_types 期待={expected}, 実際={names}"
        )
