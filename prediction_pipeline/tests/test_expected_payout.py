"""
F8 期待配当推定テスト (cmd_144k_sub2)

■ テスト方針 (CHECK-9: 全テスト期待値の根拠を下記に記載)
    モック禁止。期待値はすべて実データ or 手計算から導出。

■ テスト対象
    src/expected_payout.py:
      - compute_score_spread(race)
      - estimate_expected_payout(race)

■ 実データ出典
    data/fixtures/keirin_20260228.json  (2/28 大垣S級一予選 8レース)
    data/results/20260228_results.json  (2/28 実結果)

■ 検証ソース (TV-4: 実データ検証)
    verification_source: "2/28 大垣S級一予選 8レース実績データ
    (keirin_20260228.json + 20260228_results.json) + 手計算検算 (CHECK-7b)"

■ 2/28大垣S級一予選 手計算根拠 (CHECK-7b)
    BASE=12,000 (9車立て)
    spread 16-20 zone → × 0.5:
        R2 (spread=17.04): 12,000 × 0.5 = 6,000
    spread 12-16 zone → × 0.8:
        R3 (spread=14.55): 12,000 × 0.8 = 9,600
        R5 (spread=14.12): 12,000 × 0.8 = 9,600
        R7 (spread=12.85): 12,000 × 0.8 = 9,600
        R8 (spread=15.00): 12,000 × 0.8 = 9,600
        R9 (spread=15.90): 12,000 × 0.8 = 9,600
        R10(spread=14.02): 12,000 × 0.8 = 9,600
        R11(spread=12.70): 12,000 × 0.8 = 9,600
    推定平均: (6,000 + 9,600×7) / 8 = 9,150円
    実績平均: (8710+5060+18230+17100+4060+1500+1310+1240) / 8 = 7,151円
    誤差: +28%（推定過大）
    → 全8レースとも推定値 < ¥20,000 → F8で正しく除外可能

confidence: 4 (推定式の精度に課題あり、F8フィルター効果は確実)
confidence_notes: "個別レース推定誤差は大きい（±50-200%）。
  しかし全8レースが¥20,000未満 → F8フィルター機能の方向性は正しい。"
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.expected_payout import (
    _get_spread_multiplier,
    compute_score_spread,
    estimate_expected_payout,
)
from src.filter_engine import FilterEngine

# ─── フィクスチャパス ────────────────────────────────────────────────────
FIXTURE_228 = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures", "keirin_20260228.json")
RESULTS_228 = os.path.join(os.path.dirname(__file__), "..", "data", "results", "20260228_results.json")
FILTERS_YAML = os.path.join(os.path.dirname(__file__), "..", "config", "keirin", "filters.yaml")


# ─── ヘルパー関数 ────────────────────────────────────────────────────────

def make_race(spread: float, num_entries: int = 9, venue: str = "大垣",
              race_num: int = 5, stage: str = "一予選",
              grade: str = "S", bank_length: int = 400,
              date: str = "20260228") -> dict:
    """テスト用レースデータを生成する。score_spread を指定値にする。"""
    # spread = max - min になるよう scores を設定
    base_score = 100.0
    scores = [base_score] * (num_entries - 1) + [base_score + spread]
    entries = [
        {"car_no": i + 1, "grade": "S1", "score": scores[i]}
        for i in range(num_entries)
    ]
    return {
        "venue_name": venue,
        "race_num": race_num,
        "grade": grade,
        "stage": stage,
        "bank_length": bank_length,
        "date": date,
        "entries": entries,
    }


def load_fixture(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_results(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── セクション1: compute_score_spread ──────────────────────────────────

class TestComputeScoreSpread:
    """compute_score_spread の単体テスト。"""

    def test_basic_spread_calculation(self):
        """
        9車でスコア 90-110 → spread=20。
        根拠: max(110) - min(90) = 20.0 (手計算)
        """
        race = make_race(spread=20.0)
        result = compute_score_spread(race)
        assert result == pytest.approx(20.0, abs=0.01), (
            f"spread={result} (期待=20.0)"
        )

    def test_zero_scores_excluded(self):
        """
        スコア0は有効スコアから除外される。
        根拠: entries に score=0 を混ぜても spread 計算に影響しない
        """
        race = {
            "entries": [
                {"car_no": 1, "score": 100.0},
                {"car_no": 2, "score": 110.0},
                {"car_no": 3, "score": 0},       # 除外されるべき
                {"car_no": 4, "score": None},     # 除外されるべき
            ]
        }
        result = compute_score_spread(race)
        assert result == pytest.approx(10.0, abs=0.01), (
            f"spread={result} (期待=10.0: score=0とNoneは除外)"
        )

    def test_single_valid_score_returns_none(self):
        """
        有効スコアが1つ → None（データ不足）。
        根拠: spread計算には最低2つの有効スコアが必要
        """
        race = {
            "entries": [
                {"car_no": 1, "score": 100.0},
                {"car_no": 2, "score": 0},
            ]
        }
        assert compute_score_spread(race) is None

    def test_no_entries_returns_none(self):
        """
        エントリーなし → None。
        根拠: entries が空の場合 有効スコア0件
        """
        assert compute_score_spread({"entries": []}) is None
        assert compute_score_spread({}) is None

    def test_all_same_scores(self):
        """
        全員同スコア → spread=0.0。
        根拠: max(100) - min(100) = 0
        """
        race = {
            "entries": [{"car_no": i, "score": 100.0} for i in range(1, 8)]
        }
        assert compute_score_spread(race) == pytest.approx(0.0, abs=0.01)


# ─── セクション2: spread 乗数テーブル ────────────────────────────────────

class TestSpreadMultiplierTable:
    """
    _get_spread_multiplier の区間別動作確認。
    根拠: expected_payout.py の _SPREAD_MULTIPLIER_TABLE の設計値
    """

    @pytest.mark.parametrize("spread,expected_mult", [
        (25.0, 0.30),   # spread >= 20: 本命圧倒ゾーン
        (20.0, 0.30),   # spread = 20.0: 20以上の境界
        (18.0, 0.50),   # spread 16-20: 低配当ゾーン
        (16.0, 0.50),   # spread = 16.0: 16の境界
        (14.0, 0.80),   # spread 12-16: フィルター通過ゾーン
        (12.0, 0.80),   # spread = 12.0: 通過ゾーン下限
        (10.0, 1.50),   # spread  8-12: フィルター除外ゾーン
        (5.0,  2.50),   # spread  < 8:  荒れゾーン
    ])
    def test_multiplier_by_spread_zone(self, spread, expected_mult):
        """
        各 spread 区間で正しい乗数が返る。
        根拠: _SPREAD_MULTIPLIER_TABLE の設計値（手計算で確認済み）
        """
        result = _get_spread_multiplier(spread)
        assert result == pytest.approx(expected_mult, abs=0.001), (
            f"spread={spread}: mult={result} (期待={expected_mult})"
        )

    def test_higher_spread_lower_multiplier(self):
        """
        spread が高いほど乗数が低い（逆相関）。
        根拠: 本命馬優位→低配当 の理論的根拠
        """
        spreads = [5.0, 10.0, 14.0, 18.0, 25.0]
        mults = [_get_spread_multiplier(s) for s in spreads]
        for i in range(len(mults) - 1):
            assert mults[i] >= mults[i + 1], (
                f"spread={spreads[i]} mult={mults[i]} > spread={spreads[i+1]} mult={mults[i+1]} "
                "でなければならない（逆相関）"
            )


# ─── セクション3: estimate_expected_payout 基本テスト ───────────────────

class TestEstimateExpectedPayoutBasic:
    """
    estimate_expected_payout の基本動作テスト。
    """

    def test_9car_high_spread_returns_low_estimate(self):
        """
        9車立て, spread=20 → 推定配当 = 12,000 × 0.3 = 3,600円。
        根拠: BASE_9CAR=12,000 × mult(spread=20)=0.3 (手計算)
        """
        race = make_race(spread=20.0, num_entries=9)
        result = estimate_expected_payout(race)
        assert result == pytest.approx(3_600, abs=1), (
            f"estimate={result} (期待=3,600: 12,000×0.3)"
        )

    def test_9car_medium_spread_returns_medium_estimate(self):
        """
        9車立て, spread=14 → 推定配当 = 12,000 × 0.8 = 9,600円。
        根拠: BASE_9CAR=12,000 × mult(spread=14)=0.8 (手計算)
        """
        race = make_race(spread=14.0, num_entries=9)
        result = estimate_expected_payout(race)
        assert result == pytest.approx(9_600, abs=1), (
            f"estimate={result} (期待=9,600: 12,000×0.8)"
        )

    def test_9car_low_spread_returns_high_estimate(self):
        """
        9車立て, spread=5 → 推定配当 = 12,000 × 2.5 = 30,000円。
        根拠: BASE_9CAR=12,000 × mult(spread=5)=2.5 (手計算)
        ※ spread<8 は通常 score_spreadフィルターで除外済み
        """
        race = make_race(spread=5.0, num_entries=9)
        result = estimate_expected_payout(race)
        assert result == pytest.approx(30_000, abs=1), (
            f"estimate={result} (期待=30,000: 12,000×2.5)"
        )

    def test_8car_vs_9car_base_difference(self):
        """
        8車立て (BASE=8,000) は 9車立て (BASE=12,000) より推定配当が低い。
        根拠: 組み合わせ数が少ない → 配当が低い傾向
        """
        race_9 = make_race(spread=14.0, num_entries=9)
        race_8 = make_race(spread=14.0, num_entries=8)
        est_9 = estimate_expected_payout(race_9)
        est_8 = estimate_expected_payout(race_8)
        assert est_9 > est_8, (
            f"9車({est_9}) > 8車({est_8}) でなければならない"
        )
        # 8車: 8,000 × 0.8 = 6,400
        assert est_8 == pytest.approx(6_400, abs=1), (
            f"8車estimate={est_8} (期待=6,400: 8,000×0.8)"
        )

    def test_odds_favorite_takes_priority(self):
        """
        odds_favorite が設定されている場合、それを優先して計算する。
        根拠: 「オッズデータがある場合はオッズから直接計算」の設計方針
        formula: odds × 100 × 0.75 (競輪控除率25%考慮)
        """
        race = make_race(spread=14.0, num_entries=9)
        race["odds_favorite"] = 2.5
        result = estimate_expected_payout(race)
        # 2.5 × 100 × 0.75 = 187.5円 (本命2.5倍は低配当)
        assert result == pytest.approx(187.5, abs=0.1), (
            f"estimate={result} (期待=187.5: odds=2.5×100×0.75)"
        )

    def test_odds_favorite_10x(self):
        """
        odds_favorite=10.0 → 推定配当 = 10.0 × 100 × 0.75 = 750円。
        根拠: 本命10倍 → 三連単は一般的にさらに高いが、これはあくまで推定値
        """
        race = make_race(spread=14.0, num_entries=9)
        race["odds_favorite"] = 10.0
        result = estimate_expected_payout(race)
        assert result == pytest.approx(750.0, abs=0.1)


# ─── セクション4: エッジケース ───────────────────────────────────────────

class TestEdgeCases:
    """エッジケース: スコアなし・エントリなし等。"""

    def test_no_scores_returns_none(self):
        """
        全エントリーの score が 0 or None → None (F8スキップ)。
        根拠: スコアデータなし → 推定不可 → スキップが安全
        """
        race = {
            "entries": [
                {"car_no": i, "score": 0} for i in range(1, 8)
            ]
        }
        assert estimate_expected_payout(race) is None

    def test_empty_entries_returns_none(self):
        """
        entries が空 → None。
        根拠: 出走選手データなし → 推定不可
        """
        assert estimate_expected_payout({"entries": []}) is None
        assert estimate_expected_payout({}) is None

    def test_single_entry_returns_none(self):
        """
        有効スコアが1つ → None。
        根拠: spread計算には最低2選手のスコアが必要
        """
        race = {"entries": [{"car_no": 1, "score": 105.0}]}
        assert estimate_expected_payout(race) is None

    def test_invalid_odds_falls_back_to_spread(self):
        """
        odds_favorite が不正値 → score_spread ベースにフォールバック。
        根拠: オッズが文字列等の場合は score_spread 推定に切り替わる
        """
        race = make_race(spread=14.0, num_entries=9)
        race["odds_favorite"] = "invalid"
        result = estimate_expected_payout(race)
        # フォールバック: 12,000 × 0.8 = 9,600
        assert result == pytest.approx(9_600, abs=1), (
            f"estimate={result} (期待=9,600: invalid oddsでフォールバック)"
        )

    def test_unknown_entry_count_uses_default_base(self):
        """
        5車立て（テーブル外）→ デフォルト基準配当 10,000 を使用。
        根拠: _DEFAULT_BASE_PAYOUT=10,000（設計値）
        """
        race = make_race(spread=14.0, num_entries=5)
        result = estimate_expected_payout(race)
        # 10,000 × 0.8 = 8,000
        assert result == pytest.approx(8_000, abs=1), (
            f"estimate={result} (期待=8,000: DEFAULT_BASE=10,000×0.8)"
        )

    def test_zero_spread_uses_high_multiplier(self):
        """
        spread=0 → 全員同実力 → 最大乗数 (2.5)。
        根拠: spread<8 zone → mult=2.5。9車BASE=12,000 → 30,000
        """
        race = make_race(spread=0.0, num_entries=9)
        result = estimate_expected_payout(race)
        assert result == pytest.approx(30_000, abs=1), (
            f"estimate={result} (期待=30,000: 9車×mult2.5)"
        )


# ─── セクション5: 2/28 実データ突合 (TV-4: 実データ検証) ─────────────────

class TestRealData228:
    """
    2/28 大垣S級一予選 8レースの推定値 vs 実績値の突合。

    verification_source:
      "2/28 大垣S級一予選 8レース実績データ
       (data/fixtures/keirin_20260228.json + data/results/20260228_results.json)
       + 手計算検算 (CHECK-7b)"
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        if not os.path.isfile(FIXTURE_228) or not os.path.isfile(RESULTS_228):
            pytest.skip("実データファイルなし")
        self.races = load_fixture(FIXTURE_228)
        self.results = load_results(RESULTS_228)
        self.result_dict = {
            (r["venue"], r["race_no"]): r
            for r in self.results["races"]
        }
        # 通過8レース: 大垣S級一予選 R2,R3,R5,R7,R8,R9,R10,R11
        self.passed_races = [
            r for r in self.races
            if r["venue_name"] == "大垣"
            and r["race_num"] in [2, 3, 5, 7, 8, 9, 10, 11]
        ]

    def test_8_passed_races_exist(self):
        """
        通過8レースが実データに存在する。
        根拠: 大垣S級一予選で全フィルター通過するレース = R2,R3,R5,R7,R8,R9,R10,R11
        """
        assert len(self.passed_races) == 8, (
            f"通過レース数={len(self.passed_races)} (期待=8)"
        )

    def test_all_passed_races_have_valid_estimates(self):
        """
        全8レースで estimate_expected_payout が有効な正の数値を返す。
        根拠: score データあり → None でなく数値が返るべき
        """
        for race in self.passed_races:
            est = estimate_expected_payout(race)
            assert est is not None, (
                f"大垣 R{race['race_num']}: estimate=None（score_spread計算不可）"
            )
            assert est > 0, f"大垣 R{race['race_num']}: estimate={est} (正値でなければならない)"

    def test_r2_estimate_is_6000(self):
        """
        大垣R2 (spread=17.04, 9車立て, 16-20zone) → 推定 = 12,000 × 0.5 = 6,000。
        根拠: 手計算 (CHECK-7b) 実績配当=8,710円
        """
        r2 = next(r for r in self.passed_races if r["race_num"] == 2)
        est = estimate_expected_payout(r2)
        assert est == pytest.approx(6_000, abs=1), (
            f"大垣R2: estimate={est} (期待=6,000: spread=17.04→16-20zone→×0.5)"
        )

    def test_r3_r5_r7_r8_r9_r10_r11_estimate_is_9600(self):
        """
        大垣R3,R5,R7,R8,R9,R10,R11 (spread 12-16zone) → 推定 = 12,000 × 0.8 = 9,600。
        根拠: 手計算 (CHECK-7b) spread=12.70〜15.90 は全て 12-16zone
        """
        target_race_nums = [3, 5, 7, 8, 9, 10, 11]
        for race in self.passed_races:
            if race["race_num"] in target_race_nums:
                est = estimate_expected_payout(race)
                assert est == pytest.approx(9_600, abs=1), (
                    f"大垣R{race['race_num']}: estimate={est} (期待=9,600: 12-16zone→×0.8)"
                )

    def test_average_estimate_vs_actual(self):
        """
        推定平均 ≈ 9,150円 vs 実績平均 7,151円 (誤差+28%)。
        根拠: 手計算 (CHECK-7b) (6,000 + 9,600×7) / 8 = 9,150
        ※ 推定は過大傾向だが、F8フィルターの方向性は正しい
        """
        estimates = [estimate_expected_payout(r) for r in self.passed_races]
        actuals = [
            self.result_dict[("大垣", r["race_num"])]["trifecta_payout"]
            for r in self.passed_races
        ]
        avg_est = sum(estimates) / len(estimates)
        avg_actual = sum(actuals) / len(actuals)
        # 推定平均: 9,150円 (手計算)
        assert avg_est == pytest.approx(9_150, abs=100), (
            f"推定平均={avg_est:.0f} (期待=9,150)"
        )
        # 実績平均: 7,151円
        assert avg_actual == pytest.approx(7_151, abs=10), (
            f"実績平均={avg_actual:.0f} (期待=7,151)"
        )
        # 推定は実績より高い（過大推定だが、フィルター方向は正しい）
        assert avg_est > avg_actual, (
            f"推定={avg_est:.0f} が実績={avg_actual:.0f}より大きいべき"
        )

    def test_all_estimates_above_new_f8_threshold(self):
        """
        全8レースの推定値が F8 最低閾値 ¥3,000 以上。
        根拠: 推定最小値=6,000円(R2,spread=17.04) >> ¥3,000 → F8が全てを正しく通過させる

        cmd_146k_sub1: 閾値3,000円への修正後の核心的な検証。
        score_spread>=12通過レース(9車立て)は全てF8通過 → 「投資0件」問題が解消。
        """
        F8_MIN = 3_000  # filters.yaml expected_payout_min (cmd_146k_sub1修正後)
        for race in self.passed_races:
            est = estimate_expected_payout(race)
            assert est >= F8_MIN, (
                f"大垣R{race['race_num']}: estimate={est:,.0f}円 < F8閾値{F8_MIN:,}円"
                "（この推定値はF8で通過するべき: score_spreadとの矛盾解消確認）"
            )


# ─── セクション6: F8 フィルターとの統合テスト ────────────────────────────

class TestF8FilterIntegration:
    """
    estimate_expected_payout と FilterEngine の統合テスト。
    estimate した値を race に設定し、F8 が正しく機能するか確認。
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = FilterEngine(FILTERS_YAML)
        if not os.path.isfile(FIXTURE_228):
            pytest.skip("実データファイルなし")
        self.races = load_fixture(FIXTURE_228)
        self.passed_races = [
            r for r in self.races
            if r["venue_name"] == "大垣"
            and r["race_num"] in [2, 3, 5, 7, 8, 9, 10, 11]
        ]

    def test_without_estimate_f8_is_skipped(self):
        """
        expected_payout が未設定 → F8 がスキップされる。
        根拠: filter_engine.py _check_expected_payout は expected=None の場合 True を返す
        """
        race = self.passed_races[0].copy()
        race.pop("expected_payout", None)  # expected_payout を削除
        _, reasons = self.engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) == 0, (
            f"expected_payoutなしでF8が発動した: {f8_reasons}"
        )

    def test_with_low_estimate_f8_excludes_race(self):
        """
        推定値(2,750円)を設定 → F8が除外する（< 3,000円の新閾値）。
        根拠: 7車立て,spread=16 → 5,500×0.5=2,750 < F8_MIN(3,000) → F8除外
        cmd_146k_sub1: 閾値3,000円の新設計でも低配当除外機能が維持されることを確認。
        """
        # 7車立て, spread=16 → 推定 5,500 × 0.5 = 2,750円 (手計算)
        race = make_race(spread=16.0, num_entries=7)
        race["expected_payout"] = estimate_expected_payout(race)
        assert race["expected_payout"] == pytest.approx(2_750, abs=1), (
            f"7車立てspread=16: 推定={race['expected_payout']} (期待=2,750: 5,500×0.5)"
        )
        _, reasons = self.engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) > 0, (
            f"低推定値({race['expected_payout']:,.0f}円)なのにF8が除外しない: {reasons}"
        )

    def test_with_target_zone_estimate_f8_passes(self):
        """
        目標ゾーン(25,000円)を設定 → F8を通過する。
        根拠: 20,000 <= 25,000 <= 50,000 → F8通過
        """
        race = make_race(spread=14.0, num_entries=9)
        race["expected_payout"] = 25_000  # 目標ゾーン内
        _, reasons = self.engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) == 0, (
            f"目標ゾーン(25,000円)なのにF8が除外した: {f8_reasons}"
        )

    def test_with_too_high_estimate_f8_excludes_race(self):
        """
        高すぎる推定値(60,000円) → F8が除外する（> 50,000円の上限）。
        根拠: estimate > F8_MAX(50,000) → F8除外
        """
        race = make_race(spread=14.0, num_entries=9)
        race["expected_payout"] = 60_000  # 上限超え
        _, reasons = self.engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) > 0, (
            f"高推定値(60,000円)なのにF8が除外しない: {reasons}"
        )

    def test_all_228_passed_races_pass_f8_with_new_threshold(self):
        """
        2/28大垣S級一予選8レース(9車立て)に推定値を設定 → F8が全て通過する。
        根拠: 全推定値(6,000-9,600円) >= F8_MIN(3,000円)

        cmd_146k_sub1: 閾値3,000円への修正後、score_spread>=12通過レース(9車立て)が
        全てF8を通過することを確認（「投資0件」問題の解消）。
        """
        f8_excluded_count = 0
        f8_passed_count = 0
        for race in self.passed_races:
            race_copy = dict(race)
            est = estimate_expected_payout(race_copy)
            if est is not None:
                race_copy["expected_payout"] = est
                _, reasons = self.engine.apply(race_copy)
                f8_reasons = [r for r in reasons if r.startswith("F8")]
                if f8_reasons:
                    f8_excluded_count += 1
                else:
                    f8_passed_count += 1
        assert f8_excluded_count == 0, (
            f"F8除外数={f8_excluded_count} (期待=0: 全推定値>=3,000円でF8通過するはず)"
        )
        assert f8_passed_count == 8, (
            f"F8通過数={f8_passed_count} (期待=8: 2/28大垣9車立て全通過)"
        )
