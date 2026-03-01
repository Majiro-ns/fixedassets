"""
フィルター品質分析テスト (cmd_142k_sub3)

F2修正(dfd176c)後の2/28データにおける通過レース8件の品質を検証する。
通過レースの詳細分析・実結果との突合・各フィルターの選別効果を定量的に検証。

■ 検証対象ファイル
    - data/fixtures/keirin_20260228.json  (2/28 出走表: 31レース)
    - data/results/20260228_results.json  (2/28 実結果)
    - config/keirin/filters.yaml          (フィルター設定)

■ 通過レース概要（F2修正後）
    通過数: 8 / 31 (大垣R2, R3, R5, R7, R8, R9, R10, R11)
    全て大垣、全てS級一予選、全てscore_spread >= 12

■ フィルター独立効果（2/28データ）
    F1(クラス)単独除外:    15レース (A級10 + grade空5)
    F2(種別)単独除外:       8レース (初日特選3 + ガールズ2 + stage空3)
    F7(R番号)単独除外:      6レース (R4×3会場 + R6×3会場)
    score_spread単独除外: 19レース (spread<12)

■ CHECK-9: テスト期待値の根拠
    - 通過8レース: 実際にFilterEngine.apply()を実行して確認
    - score_spread値: entries.score max-min から手計算
      R2=17.04 (107.50-90.46), R3=14.55 (107.41-92.86),
      R5=14.12 (108.12-94.00), R7=12.85 (109.60-96.75),
      R8=15.00 (105.77-90.77), R9=15.90 (108.95-93.05),
      R10=14.02 (108.25-94.23), R11=12.70 (109.28-96.58)
    - F1独立除外15: grade='A'の10レース + grade=''の5レース = 15
    - F2独立除外8: stage正規化後が許可リスト外の8レース
    - F7独立除外6: race_num in [4,6] × 3会場
    - SS独立除外19: spread<12の19レース (大垣R12 + 和歌山全12 - 和歌山R8-R12はS = 和歌山8 + 広島7 ...)
      → 実際にスキャンして確認

    結果データ根拠（20260228_results.json より）:
    通過レース trifecta_payout: R2=8710, R3=5060, R5=18230, R7=17100,
                                 R8=4060, R9=1500, R10=1310, R11=1240
    通過レース trio_payout:      R2=1390, R3=2470, R5=3580, R7=1700,
                                 R8=550,  R9=810,  R10=730, R11=630
    大垣R12(除外) trifecta_payout: 20210 (score_spread=7.22 → 低信頼性)
"""

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.filter_engine import FilterEngine

# ─── パス定数 ─────────────────────────────────────────────────────────
FIXTURE_228 = os.path.join(
    os.path.dirname(__file__), "..", "data", "fixtures", "keirin_20260228.json"
)
RESULTS_228 = os.path.join(
    os.path.dirname(__file__), "..", "data", "results", "20260228_results.json"
)
FILTERS_YAML = os.path.join(
    os.path.dirname(__file__), "..", "config", "keirin", "filters.yaml"
)

# 通過レースの期待値（2/28 大垣のみ、R番号リスト）
EXPECTED_PASSING_RACE_NUMS = {2, 3, 5, 7, 8, 9, 10, 11}

# score_spread 閾値（filters.yaml: min_score_spread: 12）
SCORE_SPREAD_THRESHOLD = 12

# 通過レースのscore_spread実測値（手計算で検証済み）
EXPECTED_SPREAD = {
    2: 17.04,   # 107.50 - 90.46
    3: 14.55,   # 107.41 - 92.86
    5: 14.12,   # 108.12 - 94.00
    7: 12.85,   # 109.60 - 96.75
    8: 15.00,   # 105.77 - 90.77
    9: 15.90,   # 108.95 - 93.05
    10: 14.02,  # 108.25 - 94.23
    11: 12.70,  # 109.28 - 96.58
}

# F2許可ステージ（filters.yaml と一致）
ALLOWED_STAGES = ["予選", "一予選", "特選", "初特選", "一般", "一次予選"]


# ─── ヘルパー関数 ─────────────────────────────────────────────────────

def load_fixture(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_results(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compute_score_spread(race: dict) -> float | None:
    """レースのscore_spreadを計算する（entries.scoreのmax-min）。"""
    entries = race.get("entries", [])
    scores = [
        float(e.get("score", 0) or 0)
        for e in entries
        if e.get("score") is not None and float(e.get("score", 0) or 0) > 0
    ]
    if len(scores) < 2:
        return None
    return max(scores) - min(scores)


def get_passing_races(races: list, engine: FilterEngine) -> list:
    """FilterEngineを通過したレースのみ返す。"""
    return [r for r in races if engine.apply(r)[0]]


def normalize_stage(stage: str) -> str:
    """全角グレードプレフィックス（Ｓ級等）を除去して正規化する。"""
    return re.sub(r'^[Ａ-Ｚ]級', '', stage)


# ─── セクション1: 通過レースの品質検証 ─────────────────────────────────

class TestPassingRaceQuality:
    """
    F2修正後の通過8レースが品質基準を満たすことを検証する。

    品質基準:
    - S級レースのみ通過
    - score_spread >= 12 のみ通過
    - 許可ステージのみ通過
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)
        self.engine = FilterEngine(FILTERS_YAML)
        self.passing_races = get_passing_races(self.races_228, self.engine)

    def test_passing_race_count_is_8(self):
        """
        通過レース数は正確に8件である。
        根拠: FilterEngine.apply()で確認済み（大垣R2,R3,R5,R7,R8,R9,R10,R11）
        """
        assert len(self.passing_races) == 8, (
            f"通過レース数={len(self.passing_races)} (期待=8)"
        )

    def test_all_passing_races_are_in_ogaki(self):
        """
        全通過レースは大垣開催である。
        根拠: 和歌山はscore_spread不足、広島はA級+score_spread不足
        """
        for race in self.passing_races:
            assert race.get("venue_name") == "大垣", (
                f"大垣以外が通過: {race.get('venue_name')} R{race.get('race_num')}"
            )

    def test_all_passing_races_have_s_grade(self):
        """
        通過8レースは全てS級（race-levelのgradeフィールド）である。
        根拠: F1フィルターが grade='S' のみ通過させる
        """
        for race in self.passing_races:
            grade = race.get("grade", "")
            assert "S" in grade, (
                f"{race.get('venue_name')} R{race.get('race_num')}: grade={grade!r} (期待: 'S'含む)"
            )

    def test_all_passing_races_stage_is_s1_ichiyosen(self):
        """
        通過8レースのstageは全て 'Ｓ級一予選' である。
        根拠: 2/28大垣の通過レースは全てS級一予選（実データ確認済み）
        """
        for race in self.passing_races:
            stage = race.get("stage", "")
            assert stage == "Ｓ級一予選", (
                f"{race.get('venue_name')} R{race.get('race_num')}: stage={stage!r} (期待='Ｓ級一予選')"
            )

    def test_all_passing_races_normalized_stage_in_allowed(self):
        """
        通過8レースのstage正規化後が許可リストに含まれる。
        根拠: 'Ｓ級一予選' → normalize → '一予選' → ALLOWED_STAGES に含まれる
        """
        for race in self.passing_races:
            stage = race.get("stage", "")
            normalized = normalize_stage(stage)
            assert normalized in ALLOWED_STAGES, (
                f"{race.get('venue_name')} R{race.get('race_num')}: "
                f"normalized={normalized!r} は許可リスト外 ({ALLOWED_STAGES})"
            )

    def test_all_passing_races_score_spread_above_threshold(self):
        """
        通過8レースのscore_spreadは全て閾値12以上である。
        根拠: F2修正後、score_spread >= 12 のみ通過（min=12.70@R11）
        手計算検算:
          R11: max=109.28, min=96.58, spread=12.70 >= 12 ✓
          R7:  max=109.60, min=96.75, spread=12.85 >= 12 ✓
        """
        for race in self.passing_races:
            spread = compute_score_spread(race)
            assert spread is not None, (
                f"{race.get('venue_name')} R{race.get('race_num')}: scoreデータなし"
            )
            assert spread >= SCORE_SPREAD_THRESHOLD, (
                f"{race.get('venue_name')} R{race.get('race_num')}: "
                f"spread={spread:.2f} < 閾値{SCORE_SPREAD_THRESHOLD}"
            )

    def test_passing_race_spread_values_match_expected(self):
        """
        通過8レースのscore_spread実測値が期待値（手計算）と一致する。
        根拠: entries.score の max-min を手計算（CHECK-9対応）
        許容誤差: ±0.02 (浮動小数点精度)
        """
        for race in self.passing_races:
            race_num = race.get("race_num")
            if race_num not in EXPECTED_SPREAD:
                continue
            spread = compute_score_spread(race)
            expected = EXPECTED_SPREAD[race_num]
            assert abs(spread - expected) < 0.02, (
                f"大垣R{race_num}: spread={spread:.2f} (期待={expected:.2f})"
            )

    def test_all_entries_in_passing_races_are_s_grade(self):
        """
        通過8レースの全出走選手がS1またはS2グレードである。
        根拠: S級一予選にはS級選手のみ出走（A級混在なし）
        """
        for race in self.passing_races:
            entries = race.get("entries", [])
            for entry in entries:
                entry_grade = entry.get("grade", "")
                assert entry_grade.startswith("S"), (
                    f"{race.get('venue_name')} R{race.get('race_num')}: "
                    f"非S級選手 {entry.get('name')} grade={entry_grade!r}"
                )

    def test_passing_races_race_numbers_are_correct(self):
        """
        通過レースのR番号は R2,R3,R5,R7,R8,R9,R10,R11 のみである。
        根拠: R1はgrade空、R4/R6はF7除外、R12はscore_spread=7.22で除外
        """
        actual_race_nums = {
            r.get("race_num")
            for r in self.passing_races
            if r.get("venue_name") == "大垣"
        }
        assert actual_race_nums == EXPECTED_PASSING_RACE_NUMS, (
            f"通過R番号={actual_race_nums} (期待={EXPECTED_PASSING_RACE_NUMS})"
        )

    def test_min_score_spread_of_passing_races(self):
        """
        通過8レースの最小score_spreadは12.70（大垣R11）である。
        根拠: R11: max=109.28, min=96.58, spread=12.70
        """
        spreads = [compute_score_spread(r) for r in self.passing_races]
        spreads = [s for s in spreads if s is not None]
        min_spread = min(spreads)
        assert abs(min_spread - 12.70) < 0.02, (
            f"最小spread={min_spread:.2f} (期待=12.70±0.02)"
        )


# ─── セクション2: 実結果との突合 ──────────────────────────────────────

class TestResultsComparison:
    """
    通過レースと非通過レースの実結果を比較し、フィルターの有効性を検証する。

    仮説: score_spread >= 12（高実力差）の通過レースは、
    低スプレッド（拮抗）の非通過レースよりも安定した配当傾向を示す。
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)
        self.results_228 = load_results(RESULTS_228)
        self.engine = FilterEngine(FILTERS_YAML)
        self.passing_races = get_passing_races(self.races_228, self.engine)

        # 結果データをlookup辞書に変換
        self.result_by_venue_race = {
            (r.get("venue"), r.get("race_no")): r
            for r in self.results_228["races"]
        }

    def test_all_passing_races_have_results(self):
        """
        通過8レース全てに実結果データが存在する。
        根拠: 20260228_results.json は31レース全て収録している
        """
        for race in self.passing_races:
            venue = race.get("venue_name")
            race_num = race.get("race_num")
            key = (venue, race_num)
            assert key in self.result_by_venue_race, (
                f"{venue} R{race_num}: 実結果データなし"
            )

    def test_ogaki_r12_excluded_has_result_data(self):
        """
        大垣R12（score_spread=7.22で除外）の実結果データが存在する。
        根拠: R12は通過しないが、結果は記録されている（パフォーマンス比較用）
        """
        key = ("大垣", 12)
        assert key in self.result_by_venue_race, "大垣R12の実結果データなし"

    def test_ogaki_r12_excluded_by_score_spread(self):
        """
        大垣R12はscore_spread=7.22（< 閾値12）のためフィルター除外される。
        根拠: F2修正により R12はF2通過(初特選∈許可リスト)だがSS除外
        手計算: R12 score_spreadはデータ確認済み（7.22）
        """
        r12 = next(
            (r for r in self.races_228 if r.get("venue_name") == "大垣" and r.get("race_num") == 12),
            None,
        )
        assert r12 is not None, "大垣R12がデータなし"

        spread = compute_score_spread(r12)
        assert spread is not None
        assert spread < SCORE_SPREAD_THRESHOLD, (
            f"大垣R12 spread={spread:.2f} (期待 < {SCORE_SPREAD_THRESHOLD})"
        )

        passed, _ = self.engine.apply(r12)
        assert not passed, "大垣R12がフィルター通過してしまった（除外されるべき）"

    def test_ogaki_r12_has_prediction_data(self):
        """
        大垣R12の実結果に our_prediction フィールドがある（旧パイプラインの予想）。
        根拠: 結果JSONでour_predictionが記録されている
        """
        result = self.result_by_venue_race.get(("大垣", 12), {})
        assert "our_prediction" in result, "大垣R12にour_predictionなし"

    def test_ogaki_r12_prediction_did_not_hit(self):
        """
        大垣R12の旧パイプライン予想はハズレだった（hit=false）。
        根拠: 実結果JSON: 9-2-3 三連複、予想軸は5番
        """
        result = self.result_by_venue_race.get(("大垣", 12), {})
        assert result.get("hit") is False, "大垣R12がhit=trueになっている"
        assert result.get("payout", 0) == 0, "大垣R12のpayoutが0でない"

    def test_passing_races_trifecta_payouts_are_positive(self):
        """
        通過8レースの三連単配当は全て正数である。
        根拠: 実レースは必ず配当が発生する
        """
        for race in self.passing_races:
            venue = race.get("venue_name")
            race_num = race.get("race_num")
            result = self.result_by_venue_race.get((venue, race_num), {})
            payout = result.get("trifecta_payout", 0)
            assert payout > 0, (
                f"{venue} R{race_num}: trifecta_payout={payout} (期待 > 0)"
            )

    def test_passing_races_trifecta_payout_range(self):
        """
        通過8レースの三連単配当は1240円〜18230円の範囲に収まる。
        根拠: 20260228_results.json より直接確認
          min=1240 (R11), max=18230 (R5)
        """
        payouts = []
        for race in self.passing_races:
            venue = race.get("venue_name")
            race_num = race.get("race_num")
            result = self.result_by_venue_race.get((venue, race_num), {})
            payouts.append(result.get("trifecta_payout", 0))

        assert min(payouts) >= 1240, f"最小配当={min(payouts)} (期待>=1240)"
        assert max(payouts) <= 18230, f"最大配当={max(payouts)} (期待<=18230)"

    def test_ogaki_r12_trifecta_payout_is_high(self):
        """
        大垣R12（score_spread=7.22の拮抗レース）の三連単配当は20210円である。
        根拠: 拮抗レース（低spread）は結果が荒れやすく高配当になる傾向
        CHECK-7b: 20210 > 通過レース平均7151円 → 拮抗レースの荒れを示す
        """
        result = self.result_by_venue_race.get(("大垣", 12), {})
        payout = result.get("trifecta_payout", 0)
        assert payout == 20210, f"大垣R12 trifecta_payout={payout} (期待=20210)"

    def test_passing_races_avg_trifecta_lower_than_ogaki_r12(self):
        """
        通過レース平均三連単配当（約7151円）は大垣R12（20210円）より低い。
        根拠: score_spread >= 12の安定レースは結果が安定しやすい
        これはフィルターの有効性を示す重要な指標。
        """
        payouts = []
        for race in self.passing_races:
            venue = race.get("venue_name")
            race_num = race.get("race_num")
            result = self.result_by_venue_race.get((venue, race_num), {})
            payouts.append(result.get("trifecta_payout", 0))

        avg_passing = sum(payouts) / len(payouts)
        r12_payout = self.result_by_venue_race.get(("大垣", 12), {}).get("trifecta_payout", 0)

        assert avg_passing < r12_payout, (
            f"通過レース平均={avg_passing:.0f} >= 大垣R12={r12_payout} "
            f"(フィルター効果なし)"
        )

    def test_passing_races_trio_payout_values(self):
        """
        通過8レースの三連複配当は実結果と一致する。
        根拠: 20260228_results.json より: R2=1390, R3=2470, R5=3580, etc.
        """
        expected_trio = {
            2: 1390, 3: 2470, 5: 3580, 7: 1700,
            8: 550, 9: 810, 10: 730, 11: 630,
        }
        for race in self.passing_races:
            race_num = race.get("race_num")
            if race_num not in expected_trio:
                continue
            result = self.result_by_venue_race.get(("大垣", race_num), {})
            actual = result.get("trio_payout", -1)
            assert actual == expected_trio[race_num], (
                f"大垣R{race_num} trio_payout={actual} (期待={expected_trio[race_num]})"
            )


# ─── セクション3: フィルター選別効果分析 ──────────────────────────────

class TestFilterIndependentEffect:
    """
    各フィルターの独立効果（単独で適用した場合の除外数）を検証する。

    ■ 独立効果の定義:
      「そのフィルターのみ適用した場合に除外されるレース数」
      他のフィルターと独立して評価する。
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)

    def _f1_fails(self, race: dict) -> bool:
        """F1: grade に 'S' が含まれなければ除外。"""
        grade = str(race.get("grade", ""))
        return "S" not in grade

    def _f2_fails(self, race: dict) -> bool:
        """F2: normalized_stage が許可リスト外なら除外。"""
        stage = str(race.get("stage", ""))
        normalized = normalize_stage(stage)
        return normalized not in ALLOWED_STAGES

    def _f7_fails(self, race: dict) -> bool:
        """F7: race_num が 4 or 6 なら除外。"""
        return int(race.get("race_num", 0)) in [4, 6]

    def _ss_fails(self, race: dict) -> bool:
        """score_spread: spread < 12 なら除外。"""
        spread = compute_score_spread(race)
        if spread is None:
            return False
        return spread < SCORE_SPREAD_THRESHOLD

    def test_f1_independent_excludes_15_races(self):
        """
        F1単独除外数は 15レース（A級10 + grade空5）。
        根拠: A級→和歌山R2-R4,R5 + 広島R2-R7 = 10, grade空→大垣R1,和歌山R1,R6,R7,広島R1 = 5
        """
        excluded = [r for r in self.races_228 if self._f1_fails(r)]
        assert len(excluded) == 15, (
            f"F1独立除外数={len(excluded)} (期待=15)"
        )

    def test_f2_independent_excludes_8_races(self):
        """
        F2単独除外数は 8レース（初日特選3 + ガールズ2 + stage空3）。
        根拠: stage正規化後が許可リスト外: 初日特選×3 + ガールズ予選×2 + ''×3 = 8
        初日特選: 和歌山R5(A級), 和歌山R12(S級), 広島R7(A級)
        ガールズ: 和歌山R6, 和歌山R7
        stage空: 大垣R1, 和歌山R1, 広島R1
        """
        excluded = [r for r in self.races_228 if self._f2_fails(r)]
        assert len(excluded) == 8, (
            f"F2独立除外数={len(excluded)} (期待=8)"
        )

    def test_f7_independent_excludes_6_races(self):
        """
        F7単独除外数は 6レース（R4×3会場 + R6×3会場）。
        根拠: 3会場×(R4+R6) = 6。広島はR4,R6の両方存在。
        """
        excluded = [r for r in self.races_228 if self._f7_fails(r)]
        assert len(excluded) == 6, (
            f"F7独立除外数={len(excluded)} (期待=6)"
        )

    def test_score_spread_independent_excludes_19_races(self):
        """
        score_spread単独除外数は 19レース（spread < 12）。
        根拠: 大垣R12(7.22) + 和歌山全12レース(全て<12) + 広島全7(全て<12)
              ただし広島R6はspread=14.46で除外されない = 大垣1 + 和歌山12 + 広島6 = 19
        """
        excluded = [r for r in self.races_228 if self._ss_fails(r)]
        assert len(excluded) == 19, (
            f"score_spread独立除外数={len(excluded)} (期待=19)"
        )

    def test_f7_excludes_race_4_in_each_venue(self):
        """
        F7はR4を全会場（大垣・和歌山・広島）で除外する。
        根拠: exclude_race_number: [4, 6] の設定
        """
        r4_excluded = [
            r for r in self.races_228
            if self._f7_fails(r) and r.get("race_num") == 4
        ]
        venues = {r.get("venue_name") for r in r4_excluded}
        assert "大垣" in venues, "大垣R4がF7で除外されていない"
        assert "和歌山" in venues, "和歌山R4がF7で除外されていない"
        assert "広島" in venues, "広島R4がF7で除外されていない"
        assert len(r4_excluded) == 3, f"R4除外数={len(r4_excluded)} (期待=3)"

    def test_f7_excludes_race_6_in_each_venue(self):
        """
        F7はR6を全会場（大垣・和歌山・広島）で除外する。
        根拠: 広島は7レースまでなのでR6が存在する。
        """
        r6_excluded = [
            r for r in self.races_228
            if self._f7_fails(r) and r.get("race_num") == 6
        ]
        venues = {r.get("venue_name") for r in r6_excluded}
        assert "大垣" in venues, "大垣R6がF7で除外されていない"
        assert "和歌山" in venues, "和歌山R6がF7で除外されていない"
        assert "広島" in venues, "広島R6がF7で除外されていない"
        assert len(r6_excluded) == 3, f"R6除外数={len(r6_excluded)} (期待=3)"

    def test_f1_excludes_a_grade_races(self):
        """
        F1はA級（grade='A'）の10レースを除外する。
        根拠: 和歌山R2-R5 + 広島R2-R7 = 10レース
        """
        a_excluded = [r for r in self.races_228 if r.get("grade") == "A"]
        assert len(a_excluded) == 10, f"A級レース数={len(a_excluded)} (期待=10)"
        for r in a_excluded:
            assert self._f1_fails(r), (
                f"{r.get('venue_name')} R{r.get('race_num')} A級がF1通過"
            )

    def test_f1_excludes_empty_grade_races(self):
        """
        F1はgrade=''（ガールズ・grade不明）の5レースを除外する。
        根拠: 大垣R1 + 和歌山R1,R6,R7 + 広島R1 = 5レース
        """
        empty_excluded = [r for r in self.races_228 if r.get("grade", "") == ""]
        assert len(empty_excluded) == 5, f"grade=''レース数={len(empty_excluded)} (期待=5)"
        for r in empty_excluded:
            assert self._f1_fails(r), (
                f"{r.get('venue_name')} R{r.get('race_num')} grade=''がF1通過"
            )

    def test_f2_excludes_hatuhi_tokusen(self):
        """
        F2は「初日特選」を含むstageを除外する（許可リストに「初特選」はあるが「初日特選」はない）。
        根拠: 和歌山R5(Ａ級初日特選), 和歌山R12(Ｓ級初日特選), 広島R7(Ａ級初日特選) = 3レース
        """
        hatuhi_races = [
            r for r in self.races_228
            if "初日特選" in r.get("stage", "")
        ]
        assert len(hatuhi_races) == 3, f"初日特選レース数={len(hatuhi_races)} (期待=3)"
        for r in hatuhi_races:
            assert self._f2_fails(r), (
                f"{r.get('venue_name')} R{r.get('race_num')} 初日特選がF2通過"
            )

    def test_f2_excludes_girls_races(self):
        """
        F2はガールズレース（stage='ガールズ予選１'）を除外する。
        根拠: 和歌山R6, 和歌山R7 = 2レース（ガールズは許可リスト外）
        """
        girls_races = [
            r for r in self.races_228
            if "ガールズ" in r.get("stage", "")
        ]
        assert len(girls_races) == 2, f"ガールズレース数={len(girls_races)} (期待=2)"
        for r in girls_races:
            assert self._f2_fails(r), (
                f"{r.get('venue_name')} R{r.get('race_num')} ガールズがF2通過"
            )


class TestFilterCompoundEffect:
    """
    複数フィルターが同時に作用する複合効果を検証する。

    複合効果により、単一フィルターでは逃していたレースを確実に除外できる。
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.races_228 = load_fixture(FIXTURE_228)
        self.engine = FilterEngine(FILTERS_YAML)

    def _get_failed_filters(self, race: dict) -> set:
        """レースが失敗したフィルターのセットを返す。"""
        _, reasons = self.engine.apply(race)
        prefixes = set()
        for r in reasons:
            if r.startswith("F1"):
                prefixes.add("F1")
            elif r.startswith("F2"):
                prefixes.add("F2")
            elif r.startswith("F7"):
                prefixes.add("F7")
            elif r.startswith("score_spread"):
                prefixes.add("SS")
        return prefixes

    def test_races_failing_multiple_filters_count(self):
        """
        複数フィルターで除外されるレースは 16件である。
        根拠: 実データスキャン結果（和歌山・広島の多くが複合除外）
        """
        multi_fail = [
            r for r in self.races_228
            if len(self._get_failed_filters(r)) >= 2
        ]
        assert len(multi_fail) == 16, (
            f"複合除外レース数={len(multi_fail)} (期待=16)"
        )

    def test_races_failing_exactly_one_filter(self):
        """
        単一フィルターのみで除外されるレースは 7件である。
        根拠: F7のみ→大垣R4,R6(2件), SS のみ→大垣R12,和歌山R8-R11(5件)
        """
        single_fail = [
            r for r in self.races_228
            if not self.engine.apply(r)[0] and len(self._get_failed_filters(r)) == 1
        ]
        assert len(single_fail) == 7, (
            f"単一フィルター除外レース数={len(single_fail)} (期待=7)"
        )

    def test_f1_and_f2_compound_excludes_7_races(self):
        """
        F1とF2の両方で除外されるレースは 7件である。
        根拠: grade=''/A かつ stage正規化後が許可外のレース
          大垣R1(grade=''stage=''): F1+F2
          和歌山R1(grade=''stage=''): F1+F2
          和歌山R5(A,初日特選): F1+F2
          和歌山R6(ガールズ): F1+F2
          和歌山R7(ガールズ): F1+F2
          広島R1(grade=''stage=''): F1+F2
          広島R7(A,初日特選): F1+F2 = 7件
        """
        f1_and_f2 = [
            r for r in self.races_228
            if "F1" in self._get_failed_filters(r) and "F2" in self._get_failed_filters(r)
        ]
        assert len(f1_and_f2) == 7, (
            f"F1+F2複合除外数={len(f1_and_f2)} (期待=7)"
        )

    def test_f1_and_ss_compound_excludes_13_races(self):
        """
        F1とscore_spreadの両方で除外されるレースは 13件である。
        根拠: A級 or grade空 かつ score_spread < 12 のレース
        """
        f1_and_ss = [
            r for r in self.races_228
            if "F1" in self._get_failed_filters(r) and "SS" in self._get_failed_filters(r)
        ]
        assert len(f1_and_ss) == 13, (
            f"F1+SS複合除外数={len(f1_and_ss)} (期待=13)"
        )

    def test_f7_and_ss_compound_excludes_3_races(self):
        """
        F7とscore_spreadの両方で除外されるレースは 3件である。
        根拠: R4/R6 かつ score_spread < 12
          和歌山R4(spread=9.60), 和歌山R6(spread=8.23), 広島R4(spread=7.76)
          大垣R4(spread=12.73>=12)・大垣R6(spread=13.98>=12)・広島R6(spread=14.46>=12)はSS通過
        """
        f7_and_ss = [
            r for r in self.races_228
            if "F7" in self._get_failed_filters(r) and "SS" in self._get_failed_filters(r)
        ]
        assert len(f7_and_ss) == 3, (
            f"F7+SS複合除外数={len(f7_and_ss)} (期待=3)"
        )

    def test_ogaki_r4_fails_only_f7(self):
        """
        大垣R4はF7のみで除外される（score_spreadは十分: 12.73 >= 12）。
        根拠: grade='S', stage='Ｓ級一予選'（F1/F2通過）,
              score_spread=12.73>=12（SS通過）, race_num=4（F7除外）
        """
        r4 = next(
            (r for r in self.races_228 if r.get("venue_name") == "大垣" and r.get("race_num") == 4),
            None,
        )
        assert r4 is not None, "大垣R4データなし"

        failed = self._get_failed_filters(r4)
        assert failed == {"F7"}, (
            f"大垣R4の失敗フィルター={failed} (期待={{'F7'}})"
        )

    def test_ogaki_r6_fails_only_f7(self):
        """
        大垣R6はF7のみで除外される（score_spreadは十分: 13.98 >= 12）。
        根拠: grade='S', stage='Ｓ級一予選'（F1/F2通過）,
              score_spread=13.98>=12（SS通過）, race_num=6（F7除外）
        """
        r6 = next(
            (r for r in self.races_228 if r.get("venue_name") == "大垣" and r.get("race_num") == 6),
            None,
        )
        assert r6 is not None, "大垣R6データなし"

        failed = self._get_failed_filters(r6)
        assert failed == {"F7"}, (
            f"大垣R6の失敗フィルター={failed} (期待={{'F7'}})"
        )

    def test_ogaki_r12_fails_only_score_spread(self):
        """
        大垣R12はscore_spreadのみで除外される（grade/stage/race_numは適格）。
        根拠: grade='S', stage='Ｓ級初特選'（初特選∈許可リスト→F2通過）,
              race_num=12（F7無関係）, score_spread=7.22 < 12（SS除外）
        """
        r12 = next(
            (r for r in self.races_228 if r.get("venue_name") == "大垣" and r.get("race_num") == 12),
            None,
        )
        assert r12 is not None, "大垣R12データなし"

        failed = self._get_failed_filters(r12)
        assert failed == {"SS"}, (
            f"大垣R12の失敗フィルター={failed} (期待={{'SS'}})"
        )
