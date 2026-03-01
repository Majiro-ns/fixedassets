"""
tests/test_real_data_results.py
================================

collect_results.py の実データ検証テスト。
20260228_results.json を用いた実際のレースデータでの品質検証。

検証内容:
  a. 結果データの構造検証
  b. 的中判定ロジック検証 (check_hit)
  c. ROI計算の検証
  d. 月次ROI整合性

verification_source:
  - data/results/20260228_results.json (実スクレイピング結果 2026-02-28T20:28:07)
  - data/logs/monthly_roi.json (2026-02月累計)
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from collect_results import check_hit

RESULTS_FILE = ROOT / "data" / "results" / "20260228_results.json"
MONTHLY_ROI_FILE = ROOT / "data" / "logs" / "monthly_roi.json"
# 2026-02-28 処理後の静的ベースライン（20260301_results.json 等の実行有無に依存しない）
MONTHLY_ROI_BASELINE_FILE = ROOT / "tests" / "fixtures" / "monthly_roi_baseline_202602.json"


# ─── フィクスチャ ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def results_data():
    """20260228_results.json を読み込む"""
    with open(RESULTS_FILE, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def monthly_roi_data():
    """monthly_roi.json を読み込む"""
    with open(MONTHLY_ROI_FILE, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def monthly_roi_baseline():
    """2026-02-28 処理後の静的スナップショット。
    実際の monthly_roi.json は 3 月以降のデータで更新されるため、
    「202603 初期化直後は全 0」を検証するテストは静的ファイルを使用する。
    """
    with open(MONTHLY_ROI_BASELINE_FILE, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def all_races(results_data):
    return results_data["races"]


@pytest.fixture(scope="module")
def bet_races(all_races):
    """our_prediction が存在するレース（実際にベットしたレース）"""
    return [r for r in all_races if "our_prediction" in r]


# ─── a. 結果データの構造検証 ─────────────────────────────────────────────────

class TestResultDataStructure:
    """20260228_results.json の構造と整合性を検証する。"""

    def test_top_level_fields(self, results_data):
        """トップレベルフィールドが存在すること"""
        assert "date" in results_data
        assert "fetched_at" in results_data
        assert "races" in results_data
        assert results_data["date"] == "20260228"

    def test_total_race_count(self, all_races):
        """全レース数: 大垣12 + 和歌山12 + 広島7 = 31"""
        # 根拠: 実スクレイピング結果。広島は7Rまで取得済み（20:28時点）
        assert len(all_races) == 31

    def test_venues_present(self, all_races):
        """大垣・和歌山・広島の3会場が存在すること"""
        venues = {r["venue"] for r in all_races}
        assert "大垣" in venues
        assert "和歌山" in venues
        assert "広島" in venues

    def test_ogaki_12_races(self, all_races):
        """大垣は12レース"""
        ogaki = [r for r in all_races if r["venue"] == "大垣"]
        assert len(ogaki) == 12

    def test_wakayama_12_races(self, all_races):
        """和歌山は12レース"""
        wakayama = [r for r in all_races if r["venue"] == "和歌山"]
        assert len(wakayama) == 12

    def test_hiroshima_7_races(self, all_races):
        """広島は7レース（スクレイピング時点で取得済み分）"""
        hiroshima = [r for r in all_races if r["venue"] == "広島"]
        assert len(hiroshima) == 7

    def test_required_fields_per_race(self, all_races):
        """全レースに必須フィールドが存在すること"""
        required = [
            "venue", "race_no", "trifecta_result", "trifecta_payout",
            "trio_result", "trio_payout",
        ]
        for race in all_races:
            for field in required:
                assert field in race, (
                    f"{race['venue']} R{race['race_no']}: フィールド欠落 {field}"
                )

    def test_trifecta_result_has_3_numbers(self, all_races):
        """trifecta_result は常に3要素であること"""
        for race in all_races:
            assert len(race["trifecta_result"]) == 3, (
                f"{race['venue']} R{race['race_no']}: trifecta_result が3要素でない"
            )

    def test_trio_result_has_3_numbers(self, all_races):
        """trio_result は常に3要素であること"""
        for race in all_races:
            assert len(race["trio_result"]) == 3

    def test_trio_result_is_sorted_trifecta(self, all_races):
        """trio_result は trifecta_result のソート済みと一致すること
        根拠: collect_results.py L471 "trio_result": sorted(top3[:3])
        """
        for race in all_races:
            expected = sorted(race["trifecta_result"])
            assert race["trio_result"] == expected, (
                f"{race['venue']} R{race['race_no']}: "
                f"trio_result={race['trio_result']} != sorted(trifecta)={expected}"
            )

    def test_car_numbers_valid_range(self, all_races):
        """車番は 1〜9 の範囲内であること（競輪の車番規則）"""
        for race in all_races:
            for cn in race["trifecta_result"]:
                assert 1 <= cn <= 9, (
                    f"{race['venue']} R{race['race_no']}: 車番 {cn} が範囲外"
                )

    def test_no_duplicate_car_numbers_in_top3(self, all_races):
        """top3 内に重複車番がないこと（同じ選手が複数着順に入ることはない）"""
        for race in all_races:
            top3 = race["trifecta_result"]
            assert len(set(top3)) == 3, (
                f"{race['venue']} R{race['race_no']}: top3に重複 {top3}"
            )

    def test_payouts_positive(self, all_races):
        """払戻金は全て正の整数であること（発売が無効でなければ0にならない）"""
        for race in all_races:
            assert race["trifecta_payout"] > 0, (
                f"{race['venue']} R{race['race_no']}: trifecta_payout が0以下"
            )
            assert race["trio_payout"] > 0, (
                f"{race['venue']} R{race['race_no']}: trio_payout が0以下"
            )

    def test_trifecta_payout_ge_trio_payout(self, all_races):
        """3連単配当 ≥ 3連複配当
        根拠: 3連単は着順が厳密なため、3連複より高配当になる
        """
        for race in all_races:
            assert race["trifecta_payout"] >= race["trio_payout"], (
                f"{race['venue']} R{race['race_no']}: "
                f"trifecta={race['trifecta_payout']} < trio={race['trio_payout']}"
            )

    def test_race_no_are_positive_integers(self, all_races):
        """race_no は正の整数であること"""
        for race in all_races:
            assert isinstance(race["race_no"], int)
            assert race["race_no"] >= 1


# ─── 具体的レースの着順・払戻金スポットチェック ──────────────────────────────

class TestSpotCheckRaceResults:
    """実際のレース結果を手計算・公式記録と照合したスポットチェック。
    verification_source: 20260228_results.json（実スクレイピングデータ）
    """

    def test_ogaki_r1_result(self, all_races):
        """大垣 R1: 着順 7-2-9, 3連複[2,7,9]=3210円, 3連単=25530円"""
        race = next(r for r in all_races if r["venue"] == "大垣" and r["race_no"] == 1)
        assert race["trifecta_result"] == [7, 2, 9]
        assert race["trio_result"] == [2, 7, 9]
        assert race["trifecta_payout"] == 25530
        assert race["trio_payout"] == 3210

    def test_ogaki_r6_result(self, all_races):
        """大垣 R6: 着順 1-7-5, 3連複[1,5,7]=640円, 3連単=2870円"""
        race = next(r for r in all_races if r["venue"] == "大垣" and r["race_no"] == 6)
        assert race["trifecta_result"] == [1, 7, 5]
        assert race["trio_result"] == [1, 5, 7]
        assert race["trifecta_payout"] == 2870
        assert race["trio_payout"] == 640

    def test_wakayama_r12_result(self, all_races):
        """和歌山 R12: 着順 4-5-7, 3連複[4,5,7]=2830円, 3連単=13750円"""
        race = next(r for r in all_races if r["venue"] == "和歌山" and r["race_no"] == 12)
        assert race["trifecta_result"] == [4, 5, 7]
        assert race["trio_result"] == [4, 5, 7]
        assert race["trifecta_payout"] == 13750
        assert race["trio_payout"] == 2830

    def test_hiroshima_r2_high_payout(self, all_races):
        """広島 R2: 超高配当レース（3連単106240円）の確認"""
        race = next(r for r in all_races if r["venue"] == "広島" and r["race_no"] == 2)
        assert race["trifecta_result"] == [5, 6, 3]
        assert race["trio_result"] == [3, 5, 6]
        assert race["trifecta_payout"] == 106240
        assert race["trio_payout"] == 12770


# ─── b. 的中判定ロジック検証 (check_hit) with real data ─────────────────────

class TestCheckHitWithRealData:
    """実データを使ったcheck_hitの検証。"""

    def _make_race_result(self, race_entry):
        """レースエントリからcheck_hit用のrace_resultを構築する。"""
        return {
            "top3": race_entry["trifecta_result"],
            "payouts": {
                "trio": [{
                    "numbers": race_entry["trio_result"],
                    "payout": race_entry["trio_payout"],
                }],
                "trifecta": [{
                    "numbers": race_entry["trifecta_result"],
                    "payout": race_entry["trifecta_payout"],
                }],
            },
        }

    def test_ogaki_r12_miss(self, all_races):
        """大垣 R12: 3連複[1,1,5]、実際の結果[2,3,9] → 外れ
        根拠: check_hit比較 sorted([1,1,5])=[1,1,5] vs sorted([9,2,3])=[2,3,9] → 不一致
        """
        race = next(r for r in all_races if r["venue"] == "大垣" and r["race_no"] == 12)
        # JSONのhit/payout確認
        assert race["hit"] is False
        assert race["payout"] == 0

        # check_hit直接検証
        bet = {
            "bet_type": "3連複ながし",
            "combinations": race["our_prediction"]["combinations"],  # [[1, 1, 5]]
            "unit_bet": 1200,
            "total_investment": 1200,
        }
        race_result = self._make_race_result(race)
        hit, payout = check_hit(bet, race_result)
        assert hit is False
        assert payout == 0

    def test_wakayama_r12_miss(self, all_races):
        """和歌山 R12: 3連複[[2,4,6],[2,4,6],[4,6,6]]、実際[4,5,7] → 外れ
        根拠: [4,5,7]はどの組合せとも一致しない
        """
        race = next(r for r in all_races if r["venue"] == "和歌山" and r["race_no"] == 12)
        assert race["hit"] is False
        assert race["payout"] == 0

        bet = {
            "bet_type": "3連複ながし",
            "combinations": race["our_prediction"]["combinations"],  # [[2,4,6],[2,4,6],[4,6,6]]
            "unit_bet": 1200,
            "total_investment": 3600,
        }
        race_result = self._make_race_result(race)
        hit, payout = check_hit(bet, race_result)
        assert hit is False
        assert payout == 0

    def test_check_hit_consistent_with_json(self, bet_races):
        """check_hit()の計算結果がJSONのhit/payoutと一致すること（整合性確認）"""
        for race in bet_races:
            pred = race["our_prediction"]
            bet = {
                "bet_type": pred["bet_type"],
                "combinations": pred["combinations"],
                "unit_bet": pred.get("unit_bet", 1200),
                "total_investment": pred["investment"],
            }
            race_result = self._make_race_result(race)
            computed_hit, _ = check_hit(bet, race_result)
            assert computed_hit == race["hit"], (
                f"{race['venue']} R{race['race_no']}: "
                f"check_hit()={computed_hit} but json says hit={race['hit']}"
            )

    def test_all_bet_races_on_20260228_are_miss(self, bet_races):
        """2026/02/28の全予測レースが外れであること（実績データと一致）"""
        for race in bet_races:
            assert race["hit"] is False, (
                f"{race['venue']} R{race['race_no']}: 予期しない的中"
            )
            assert race["payout"] == 0

    def test_hypothetical_hit_trio(self, all_races):
        """仮説的的中テスト: 大垣R6に[1,5,7]で賭けていたら的中
        根拠: 実際の着順[1,7,5] → trio=[1,5,7]。単位賭け1000円、配当640円
        payout = (640 * 1000) // 100 = 6400円
        """
        race = next(r for r in all_races if r["venue"] == "大垣" and r["race_no"] == 6)
        bet = {
            "bet_type": "3連複ながし",
            "combinations": [[1, 5, 7]],
            "unit_bet": 1000,
            "total_investment": 1000,
        }
        race_result = self._make_race_result(race)
        hit, payout = check_hit(bet, race_result)
        assert hit is True
        # 手計算: (640 * 1000) // 100 = 6400
        assert payout == 6400

    def test_hypothetical_miss_wrong_combination(self, all_races):
        """仮説的外れテスト: 大垣R6に[1,3,7]で賭けたら外れ（3は含まれない）"""
        race = next(r for r in all_races if r["venue"] == "大垣" and r["race_no"] == 6)
        bet = {
            "bet_type": "3連複ながし",
            "combinations": [[1, 3, 7]],
            "unit_bet": 1000,
            "total_investment": 1000,
        }
        race_result = self._make_race_result(race)
        hit, payout = check_hit(bet, race_result)
        assert hit is False
        assert payout == 0


# ─── c. ROI計算の検証 ────────────────────────────────────────────────────────

class TestROICalculation:
    """2026/02/28 の投資・払戻・ROI を検証する。
    verification_source: 20260228_results.json（実スクレイピング）
    """

    def test_bet_count_20260228(self, bet_races):
        """2026/02/28の予測レース数=2（大垣R12、和歌山R12）"""
        assert len(bet_races) == 2

    def test_bet_race_venues_and_races(self, bet_races):
        """ベットしたレースは大垣R12と和歌山R12であること"""
        bet_ids = {(r["venue"], r["race_no"]) for r in bet_races}
        assert ("大垣", 12) in bet_ids
        assert ("和歌山", 12) in bet_ids

    def test_investment_ogaki_r12(self, all_races):
        """大垣R12の投資額=1200円（3連複1組×1200円）"""
        race = next(r for r in all_races if r["venue"] == "大垣" and r["race_no"] == 12)
        assert race["our_prediction"]["investment"] == 1200

    def test_investment_wakayama_r12(self, all_races):
        """和歌山R12の投資額=3600円（3連複3組×1200円）"""
        race = next(r for r in all_races if r["venue"] == "和歌山" and r["race_no"] == 12)
        assert race["our_prediction"]["investment"] == 3600

    def test_total_investment_20260228(self, bet_races):
        """2026/02/28の総投資額=4800円（1200+3600）"""
        total = sum(r["our_prediction"]["investment"] for r in bet_races)
        assert total == 4800

    def test_total_payout_20260228(self, bet_races):
        """2026/02/28の総払戻=0円（全外れ）"""
        total = sum(r.get("payout", 0) for r in bet_races)
        assert total == 0

    def test_roi_20260228_is_zero(self, bet_races):
        """2026/02/28のROI=0.0 (total_payout/total_investment = 0/4800)
        手計算: 0 / 4800 = 0.0
        """
        total_investment = sum(r["our_prediction"]["investment"] for r in bet_races)
        total_payout = sum(r.get("payout", 0) for r in bet_races)
        assert total_investment > 0
        roi = total_payout / total_investment
        assert roi == 0.0


# ─── d. 月次ROI整合性 ───────────────────────────────────────────────────────

class TestMonthlyROIConsistency:
    """monthly_roi.json の202602データとの整合性を検証する。
    verification_source: data/logs/monthly_roi.json
    """

    def test_february_data_exists(self, monthly_roi_data):
        """202602のデータが存在すること"""
        assert "202602" in monthly_roi_data

    def test_february_bet_count(self, monthly_roi_data):
        """2月のbet_count=8（タスク仕様より）"""
        data = monthly_roi_data["202602"]
        # 根拠: 20260223,20260224,20260225,20260228の合計8レースにベット
        assert data["bet_count"] == 8

    def test_february_total_investment(self, monthly_roi_data):
        """2月の総投資額=26400円"""
        data = monthly_roi_data["202602"]
        # 手計算根拠: 各日のbetを集計した累計
        assert data["total_investment"] == 26400

    def test_february_total_payout(self, monthly_roi_data):
        """2月の総払戻=0円（全外れ）"""
        data = monthly_roi_data["202602"]
        assert data["total_payout"] == 0

    def test_february_actual_roi(self, monthly_roi_data):
        """2月のROI=0.0（全外れ）"""
        data = monthly_roi_data["202602"]
        assert data["actual_roi"] == 0.0

    def test_february_hit_count(self, monthly_roi_data):
        """2月の的中件数=0"""
        data = monthly_roi_data["202602"]
        assert data["hit_count"] == 0

    def test_february_dates_processed(self, monthly_roi_data):
        """2月の処理済み日付に20260228が含まれること"""
        data = monthly_roi_data["202602"]
        assert "20260228" in data["dates_processed"]

    def test_roi_formula_consistency(self, monthly_roi_data):
        """ROI計算式の整合性: actual_roi = total_payout / total_investment
        手計算: 0 / 26400 = 0.0
        """
        data = monthly_roi_data["202602"]
        if data["total_investment"] > 0:
            expected_roi = data["total_payout"] / data["total_investment"]
            assert abs(data["actual_roi"] - expected_roi) < 0.001

    def test_hit_rate_formula_consistency(self, monthly_roi_data):
        """hit_rate = hit_count / bet_count
        手計算: 0 / 8 = 0.0
        """
        data = monthly_roi_data["202602"]
        if data["bet_count"] > 0:
            expected_rate = data["hit_count"] / data["bet_count"]
            assert abs(data["hit_rate"] - expected_rate) < 0.001

    def test_20260228_investment_within_monthly(self, bet_races, monthly_roi_data):
        """2/28の投資額(4800)が月次総計(26400)に含まれる（部分集合）"""
        daily_investment = sum(r["our_prediction"]["investment"] for r in bet_races)
        monthly_investment = monthly_roi_data["202602"]["total_investment"]
        assert daily_investment == 4800
        assert daily_investment <= monthly_investment

    def test_march_data_exists(self, monthly_roi_data):
        """202603のデータが存在すること（次月の初期化確認）"""
        assert "202603" in monthly_roi_data

    def test_march_empty_state(self, monthly_roi_baseline):
        """202603は全て0（2026-02-28処理直後の初期状態）
        根拠: tests/fixtures/monthly_roi_baseline_202602.json（静的スナップショット）
        注: monthly_roi.json は3月以降のデータで更新されるため、静的ベースラインを使用。
        """
        data = monthly_roi_baseline["202603"]
        assert data["bet_count"] == 0
        assert data["total_investment"] == 0
        assert data["total_payout"] == 0
        assert data["actual_roi"] == 0.0
