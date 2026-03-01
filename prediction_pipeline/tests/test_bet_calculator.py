"""
tests/test_bet_calculator.py
============================
bet_calculator.py の単体テスト。

バグ修正テスト（2026-03-01）:
  - partners重複番号によるdedup
  - 無効3連複組合せ（同一番号）のフィルタリング
  - axis番号がpartnersに含まれる場合の除外
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from bet_calculator import (
    calc_sanrenpu_nagashi,
    calc_sanrentan_nagashi,
    calc_wide_nagashi,
    calc_niren_nagashi,
    calc_niren_tan_nagashi,
    calc_from_strategy,
)


# --------------------------------------------------------------------------- #
# calc_sanrenpu_nagashi — 正常ケース
# --------------------------------------------------------------------------- #

class TestSanrenpuNagashiNormal:
    def test_basic_2partners(self):
        """軸1, 相手2,3 → 1点 [1,2,3]"""
        result = calc_sanrenpu_nagashi(axis=1, partners=[2, 3], unit_bet=500)
        assert result["bet_type"] == "3連複ながし"
        assert result["axis"] == 1
        assert result["partners"] == [2, 3]
        assert result["combinations"] == [(1, 2, 3)]
        assert result["num_bets"] == 1
        assert result["total_investment"] == 500

    def test_basic_3partners(self):
        """軸1, 相手[2,3,4] → C(3,2)=3点"""
        result = calc_sanrenpu_nagashi(axis=1, partners=[2, 3, 4], unit_bet=500)
        assert result["num_bets"] == 3
        assert result["total_investment"] == 1500
        # 買い目は全て3頭が異なること
        for combo in result["combinations"]:
            assert len(set(combo)) == 3

    def test_basic_4partners(self):
        """軸1, 相手[2,3,4,5] → C(4,2)=6点"""
        result = calc_sanrenpu_nagashi(axis=1, partners=[2, 3, 4, 5], unit_bet=500)
        assert result["num_bets"] == 6
        assert result["total_investment"] == 3000

    def test_all_combinations_valid(self):
        """全ての組合せが有効であること（3頭全て異なる）"""
        result = calc_sanrenpu_nagashi(axis=4, partners=[2, 6], unit_bet=1200)
        for combo in result["combinations"]:
            assert len(set(combo)) == 3, f"無効な組合せ: {combo}"

    def test_unit_bet_applied(self):
        """unit_betが正しく適用されること"""
        result = calc_sanrenpu_nagashi(axis=1, partners=[2, 3], unit_bet=1200)
        assert result["unit_bet"] == 1200
        assert result["total_investment"] == 1200


# --------------------------------------------------------------------------- #
# calc_sanrenpu_nagashi — バグ修正テスト（CRITICAL）
# --------------------------------------------------------------------------- #

class TestSanrenpuNagashiBugFix:
    def test_dedup_wakayama_partners_266(self):
        """
        【和歌山12Rバグ再現】partners=[2,6,6] → dedup後[2,6] → 1点のみ
        修正前: [(2,4,6), (2,4,6), (4,6,6)] = 3点・3,600円（重複・無効含む）
        修正後: [(2,4,6)] = 1点・1,200円
        """
        result = calc_sanrenpu_nagashi(axis=4, partners=[2, 6, 6], unit_bet=1200)
        assert result["partners"] == [2, 6], "dedup後のpartners確認"
        assert result["num_bets"] == 1, "有効1点のみ"
        assert result["total_investment"] == 1200, "正確な投資額"
        assert result["combinations"] == [(2, 4, 6)], "有効な組合せ"

    def test_dedup_ogaki_partners_11_raises(self):
        """
        【大垣12Rバグ再現】partners=[1,1] → dedup後[1] → 相手不足 → ValueError
        修正前: [(1,1,5)] = 1点・1,200円（無効bet）が生成されていた
        修正後: len(partners_dedup)=1 < 2 → ValueError
        """
        with pytest.raises(ValueError, match="相手は2名以上"):
            calc_sanrenpu_nagashi(axis=5, partners=[1, 1], unit_bet=1200)

    def test_invalid_combo_filtered(self):
        """
        axis=4, partners=[4,6,6] → dedup後[6] → 相手不足ValueError
        （axisと同じ番号がpartnersにある場合も除外）
        """
        with pytest.raises(ValueError, match="相手は2名以上"):
            calc_sanrenpu_nagashi(axis=4, partners=[4, 6, 6], unit_bet=1200)

    def test_axis_in_partners_excluded(self):
        """axis番号がpartnersに含まれても除外される"""
        result = calc_sanrenpu_nagashi(axis=5, partners=[5, 9, 1], unit_bet=1200)
        assert 5 not in result["partners"], "axisはpartnersから除外される"
        assert set(result["partners"]) == {1, 9}, "dedup+axis除外後（順序不問）"
        assert result["num_bets"] == 1

    def test_no_duplicate_combinations(self):
        """dedup後の組合せに重複がないこと"""
        result = calc_sanrenpu_nagashi(axis=4, partners=[2, 6, 6], unit_bet=1200)
        combos = result["combinations"]
        assert len(combos) == len(set(combos)), "組合せに重複なし"

    def test_correct_investment_after_dedup(self):
        """dedup後の正確な投資額が返ること（重複込みの過剰計上なし）"""
        # partners=[2,3,3,4] → dedup後[2,3,4] → C(3,2)=3点
        result = calc_sanrenpu_nagashi(axis=1, partners=[2, 3, 3, 4], unit_bet=500)
        assert result["num_bets"] == 3
        assert result["total_investment"] == 1500  # 1500円（過剰計上なし）

    def test_display_uses_dedup_partners(self):
        """display文字列はdedup後のpartnersを使用すること"""
        result = calc_sanrenpu_nagashi(axis=4, partners=[2, 6, 6], unit_bet=1200)
        # dedup後 partners=[2,6] → "3連複ながし 4-26"
        assert result["display"] == "3連複ながし 4-26"
        assert "266" not in result["display"], "重複番号が表示されない"


# --------------------------------------------------------------------------- #
# calc_sanrentan_nagashi — dedup
# --------------------------------------------------------------------------- #

class TestSanrentanNagashiBugFix:
    def test_dedup_partners(self):
        """partners=[2,3,3] → dedup後[2,3] → P(2,2)=2点"""
        result = calc_sanrentan_nagashi(axis=1, partners=[2, 3, 3], unit_bet=500)
        assert result["partners"] == [2, 3]
        assert result["num_bets"] == 2

    def test_raises_insufficient_after_dedup(self):
        """partners=[2,2] → dedup後[2] → ValueError"""
        with pytest.raises(ValueError, match="相手は2名以上"):
            calc_sanrentan_nagashi(axis=1, partners=[2, 2], unit_bet=500)

    def test_axis_excluded_from_partners(self):
        """partners=[1,2,3] (axisと重複) → axis=1を除外後[2,3]"""
        result = calc_sanrentan_nagashi(axis=1, partners=[1, 2, 3], unit_bet=500)
        assert 1 not in result["partners"]
        assert result["num_bets"] == 2


# --------------------------------------------------------------------------- #
# calc_wide_nagashi — dedup
# --------------------------------------------------------------------------- #

class TestWideNagashiBugFix:
    def test_dedup_partners(self):
        """partners=[2,3,3] → dedup後[2,3] → 2点"""
        result = calc_wide_nagashi(axis=1, partners=[2, 3, 3], unit_bet=300)
        assert result["partners"] == [2, 3]
        assert result["num_bets"] == 2

    def test_axis_excluded(self):
        """axis番号がpartnersに含まれても除外される"""
        result = calc_wide_nagashi(axis=1, partners=[1, 2, 3], unit_bet=300)
        assert 1 not in result["partners"]


# --------------------------------------------------------------------------- #
# calc_niren_nagashi / calc_niren_tan_nagashi — dedup
# --------------------------------------------------------------------------- #

class TestNirenNagashiBugFix:
    def test_niren_dedup(self):
        """partners=[2,3,3] → dedup後[2,3] → 2点"""
        result = calc_niren_nagashi(axis=1, partners=[2, 3, 3], unit_bet=500)
        assert result["partners"] == [2, 3]
        assert result["num_bets"] == 2

    def test_niren_tan_dedup(self):
        """partners=[2,2] → dedup後[2] → 1点"""
        result = calc_niren_tan_nagashi(axis=1, partners=[2, 2], unit_bet=500)
        assert result["partners"] == [2]
        assert result["num_bets"] == 1


# --------------------------------------------------------------------------- #
# calc_from_strategy — 統合テスト
# --------------------------------------------------------------------------- #

class TestCalcFromStrategy:
    def test_sanrenpu_with_duplicate_partners(self):
        """calc_from_strategyがdedup後の正確な結果を返すこと"""
        config = {"unit_bet": 1200}
        result = calc_from_strategy("sanrenpu_nagashi", axis=4, partners=[2, 6, 6], config=config)
        assert result["bet_type"] == "3連複ながし"
        assert result["num_bets"] == 1
        assert result["total_investment"] == 1200

    def test_sanrenpu_fully_invalid_raises(self):
        """dedup後に有効partnersなし → ValueError（呼び出し側でキャッチ）"""
        config = {"unit_bet": 1200}
        with pytest.raises(ValueError):
            calc_from_strategy("sanrenpu_nagashi", axis=5, partners=[1, 1], config=config)

    def test_skip_strategy(self):
        """skip戦略は影響なし"""
        config = {}
        result = calc_from_strategy("skip", axis=1, partners=[2, 3], config=config)
        assert result["bet_type"] == "skip"
