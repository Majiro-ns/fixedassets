"""
test_m8_multiyear.py
====================
disclosure-multiagent Phase 2-M8: 複数年度比較エージェント テスト

実装者: 足軽3 subtask_074a3_disclosure_f08_multiyear
作成日: 2026-02-28

テスト仕様:
  TC-1: YearlyReport 型確認（dataclass + フィールド型チェック）
  TC-2: 同一レポート2件 → added/removed/changed 全て空
  TC-3: セクション追加検出（new に "リスク管理" セクション追加）
  TC-4: セクション削除検出（old から "方針" セクション削除）
  TC-5: 変化率20%超で changed として検出（文字数変化テスト）
  TC-6: 3年分比較（2020→2021→2022）最新2年度のトレンド検出

手計算検証（CHECK-7b）:
  TC-5 変化率:
    old_text = "あ" * 100 = 100文字
    new_text = "あ" * 100 + "い" * 30 = 130文字
    difflib.SequenceMatcher("ああ...あ", "ああ...あいい...い").ratio()
    = 2 * 共通部 / (len(old) + len(new)) = 2 * 100 / (100 + 130) = 200/230 ≈ 0.870
    変化率 = 1 - 0.870 = 0.130 < 0.20 → changed にならない

    → より明確なテスト: 全く異なるテキストを追加
    old_text = "人材戦略について記載する。方針は採用強化である。" (25文字)
    new_text = old_text + "また、育成プログラムも大幅に刷新し、新入社員向けの研修を充実させる予定。" (追加44文字)
    SequenceMatcher.ratio() ≈ 2*25 / (25 + 69) = 50/94 ≈ 0.532
    変化率 = 1 - 0.532 = 0.468 > 0.20 → changed ✓

    → 単純化: old="A"*10, new="B"*10+added
    old="一" * 10, new="二" * 10  (完全別文字)
    ratio = 0.0, 変化率 = 1.0 > 0.20 → changed ✓
"""

import sys
import unittest
from dataclasses import is_dataclass
from pathlib import Path

# scriptsディレクトリをパスに追加
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from m8_multiyear_agent import (
    YearlyReport,
    YearDiff,
    CHANGE_RATE_THRESHOLD,
    compare_years,
    detect_section_changes,
    _text_change_rate,
)
from m3_gap_analysis_agent import (
    StructuredReport,
    SectionData,
)


# ─────────────────────────────────────────────────────────
# テスト用フィクスチャ
# ─────────────────────────────────────────────────────────

def _make_section(heading: str, text: str, section_id: str = None) -> SectionData:
    """テスト用 SectionData を生成する"""
    sid = section_id or f"SEC-{heading[:8]}"
    return SectionData(section_id=sid, heading=heading, text=text)


def _make_report(fiscal_year: int, sections: list[SectionData]) -> StructuredReport:
    """テスト用 StructuredReport を生成する"""
    return StructuredReport(
        document_id=f"DOC-{fiscal_year}",
        company_name="テスト株式会社",
        fiscal_year=fiscal_year,
        fiscal_month_end=3,
        sections=sections,
    )


def _make_yearly(fiscal_year: int, sections: list[SectionData]) -> YearlyReport:
    """テスト用 YearlyReport を生成する"""
    return YearlyReport(
        fiscal_year=fiscal_year,
        structured_report=_make_report(fiscal_year, sections),
        elapsed_sec=1.0,
    )


# 共通セクション（変化なし）
_COMMON_SECTIONS = [
    _make_section("第一部 企業情報", "企業情報のテキスト。事業内容について記載する。", "SEC-001"),
    _make_section("人材戦略", "人材戦略については採用・育成を重視する。", "SEC-002"),
    _make_section("サステナビリティ", "サステナビリティへの取り組みを推進する。", "SEC-003"),
]


# ─────────────────────────────────────────────────────────
# TC-1: YearlyReport 型確認
# ─────────────────────────────────────────────────────────

class TestTC1YearlyReportType(unittest.TestCase):
    """TC-1: YearlyReport 型確認（dataclass + フィールド型チェック）"""

    def test_yearly_report_is_dataclass(self):
        """YearlyReport が dataclass であること"""
        self.assertTrue(is_dataclass(YearlyReport), "YearlyReport は dataclass でなければならない")

    def test_yearly_report_fields(self):
        """YearlyReport の全フィールドが正しい値で設定できること"""
        report = _make_yearly(2024, _COMMON_SECTIONS[:])
        self.assertEqual(report.fiscal_year, 2024)
        self.assertIsInstance(report.structured_report, StructuredReport)
        self.assertIsInstance(report.elapsed_sec, float)

    def test_year_diff_is_dataclass(self):
        """YearDiff が dataclass であること"""
        self.assertTrue(is_dataclass(YearDiff), "YearDiff は dataclass でなければならない")

    def test_year_diff_fields(self):
        """YearDiff の全フィールドが正しい型で取得できること"""
        old = _make_yearly(2023, _COMMON_SECTIONS[:])
        new = _make_yearly(2024, _COMMON_SECTIONS[:])
        result = compare_years([old, new])

        self.assertIsInstance(result, YearDiff)
        self.assertIsInstance(result.fiscal_year_from, int)
        self.assertIsInstance(result.fiscal_year_to, int)
        self.assertIsInstance(result.added_sections, list)
        self.assertIsInstance(result.removed_sections, list)
        self.assertIsInstance(result.changed_sections, list)
        self.assertIsInstance(result.summary, str)


# ─────────────────────────────────────────────────────────
# TC-2: 同一レポート2件 → 差分なし
# ─────────────────────────────────────────────────────────

class TestTC2NoChange(unittest.TestCase):
    """TC-2: 同一レポート2件 → added/removed/changed 全て空"""

    def test_identical_reports_no_diff(self):
        """同一内容の2年度レポートは差分ゼロ

        手計算:
            old.sections = new.sections（同一）
            追加: {}, 削除: {}, 変更: {} → 全て空 ✓
        """
        old = _make_yearly(2023, _COMMON_SECTIONS[:])
        new = _make_yearly(2024, _COMMON_SECTIONS[:])
        result = compare_years([old, new])

        self.assertEqual(result.added_sections, [],
                         f"同一レポートで added_sections が空でない: {[s.heading for s in result.added_sections]}")
        self.assertEqual(result.removed_sections, [],
                         f"同一レポートで removed_sections が空でない: {[s.heading for s in result.removed_sections]}")
        self.assertEqual(result.changed_sections, [],
                         f"同一レポートで changed_sections が空でない: {[s.heading for s in result.changed_sections]}")
        self.assertIn("差分なし", result.summary,
                      f"同一レポートで summary に '差分なし' が含まれない: {result.summary}")

    def test_fiscal_year_from_to(self):
        """compare_years が正しい年度方向（古→新）で比較すること"""
        old = _make_yearly(2023, _COMMON_SECTIONS[:])
        new = _make_yearly(2024, _COMMON_SECTIONS[:])
        result = compare_years([old, new])

        self.assertEqual(result.fiscal_year_from, 2023)
        self.assertEqual(result.fiscal_year_to, 2024)


# ─────────────────────────────────────────────────────────
# TC-3: セクション追加検出
# ─────────────────────────────────────────────────────────

class TestTC3SectionAdded(unittest.TestCase):
    """TC-3: セクション追加検出（new に "リスク管理" セクション追加）"""

    def test_added_section_detected(self):
        """新年度に追加されたセクションが added_sections に含まれること

        手計算:
            old.sections = [第一部, 人材戦略, サステナビリティ]
            new.sections = [第一部, 人材戦略, サステナビリティ, リスク管理]  ← 追加
            追加: {"リスク管理"} → added_sections = [SectionData(heading="リスク管理")] ✓
        """
        old_sections = _COMMON_SECTIONS[:]
        new_sections = _COMMON_SECTIONS[:] + [
            _make_section("リスク管理", "リスク管理の方針と体制について記載する。", "SEC-RISK"),
        ]

        old = _make_yearly(2023, old_sections)
        new = _make_yearly(2024, new_sections)
        result = compare_years([old, new])

        added_headings = [s.heading for s in result.added_sections]
        self.assertIn("リスク管理", added_headings,
                      f"'リスク管理' が added_sections に含まれない: {added_headings}")
        self.assertEqual(len(result.removed_sections), 0,
                         f"削除なしのはずが removed_sections に値がある: {[s.heading for s in result.removed_sections]}")
        self.assertIn("追加: 1件", result.summary,
                      f"summary に '追加: 1件' が含まれない: {result.summary}")


# ─────────────────────────────────────────────────────────
# TC-4: セクション削除検出
# ─────────────────────────────────────────────────────────

class TestTC4SectionRemoved(unittest.TestCase):
    """TC-4: セクション削除検出（old から "方針" セクション削除）"""

    def test_removed_section_detected(self):
        """旧年度から削除されたセクションが removed_sections に含まれること

        手計算:
            old.sections = [第一部, 人材戦略, サステナビリティ, 経営方針]  ← 経営方針あり
            new.sections = [第一部, 人材戦略, サステナビリティ]
            削除: {"経営方針"} → removed_sections = [SectionData(heading="経営方針")] ✓
        """
        old_sections = _COMMON_SECTIONS[:] + [
            _make_section("経営方針", "経営の基本方針について記載する。", "SEC-POL"),
        ]
        new_sections = _COMMON_SECTIONS[:]

        old = _make_yearly(2023, old_sections)
        new = _make_yearly(2024, new_sections)
        result = compare_years([old, new])

        removed_headings = [s.heading for s in result.removed_sections]
        self.assertIn("経営方針", removed_headings,
                      f"'経営方針' が removed_sections に含まれない: {removed_headings}")
        self.assertEqual(len(result.added_sections), 0,
                         f"追加なしのはずが added_sections に値がある: {[s.heading for s in result.added_sections]}")
        self.assertIn("削除: 1件", result.summary,
                      f"summary に '削除: 1件' が含まれない: {result.summary}")


# ─────────────────────────────────────────────────────────
# TC-5: 変化率20%超で changed として検出
# ─────────────────────────────────────────────────────────

class TestTC5TextChangeDetection(unittest.TestCase):
    """TC-5: 変化率20%超で changed として検出（文字数変化テスト）

    手計算:
        CHANGE_RATE_THRESHOLD = 0.20
        old_text = "一" * 10 = "一一一一一一一一一一"（10文字）
        new_text = "二" * 10 = "二二二二二二二二二二"（10文字・完全別文字）
        SequenceMatcher("一"*10, "二"*10).ratio() = 0.0（共通部なし）
        変化率 = 1.0 - 0.0 = 1.0 > 0.20 → changed ✓
    """

    def test_text_change_rate_above_threshold(self):
        """変化率が閾値(0.20)を超えるテキスト変化が検出されること"""
        old_text = "一" * 10   # 10文字
        new_text = "二" * 10   # 10文字（完全別文字）
        rate = _text_change_rate(old_text, new_text)
        self.assertGreater(rate, CHANGE_RATE_THRESHOLD,
                           f"変化率 {rate:.3f} が閾値 {CHANGE_RATE_THRESHOLD} 以下")

    def test_text_change_rate_below_threshold(self):
        """同一テキストの変化率がゼロであること（閾値以下）

        手計算:
            SequenceMatcher("abc", "abc").ratio() = 1.0
            変化率 = 1.0 - 1.0 = 0.0 ≤ 0.20 ✓
        """
        text = "人材戦略については採用・育成を重視する。"
        rate = _text_change_rate(text, text)
        self.assertLessEqual(rate, CHANGE_RATE_THRESHOLD,
                             f"同一テキストの変化率 {rate:.3f} が閾値 {CHANGE_RATE_THRESHOLD} を超えている")

    def test_changed_section_detected_on_high_change_rate(self):
        """本文変化率 > 20% のセクションが changed_sections に含まれること"""
        old_text = "一" * 10
        new_text = "二" * 10   # 変化率 1.0 > 0.20

        old_sections = [_make_section("人材戦略", old_text, "SEC-002")]
        new_sections = [_make_section("人材戦略", new_text, "SEC-002")]

        changes = detect_section_changes(
            _make_report(2023, old_sections),
            _make_report(2024, new_sections),
        )

        changed_headings = [s.heading for s in changes["changed"]]
        self.assertIn("人材戦略", changed_headings,
                      f"高変化率のセクション '人材戦略' が changed に含まれない: {changed_headings}")
        self.assertEqual(changes["added"], [], f"added が空でない: {changes['added']}")
        self.assertEqual(changes["removed"], [], f"removed が空でない: {changes['removed']}")

    def test_unchanged_section_not_in_changed(self):
        """変化率 ≤ 20% のセクションが changed_sections に含まれないこと"""
        same_text = "サステナビリティへの取り組みを推進する。"
        old_sections = [_make_section("サステナビリティ", same_text, "SEC-003")]
        new_sections = [_make_section("サステナビリティ", same_text, "SEC-003")]

        changes = detect_section_changes(
            _make_report(2023, old_sections),
            _make_report(2024, new_sections),
        )
        self.assertEqual(changes["changed"], [],
                         f"同一テキストなのに changed に含まれる: {[s.heading for s in changes['changed']]}")


# ─────────────────────────────────────────────────────────
# TC-6: 3年分比較（最新2年度のトレンド検出）
# ─────────────────────────────────────────────────────────

class TestTC6ThreeYearTrend(unittest.TestCase):
    """TC-6: 3年分比較（2020→2021→2022）最新2年度のトレンド検出

    compare_years は年度昇順の末尾2件を比較する:
        [2020, 2021, 2022] → 2021 vs 2022 を比較 ✓
    """

    def test_three_year_compares_latest_two(self):
        """3年分渡した場合、最新2年度（2021→2022）を比較すること"""
        # 2020年度: 共通セクションのみ
        secs_2020 = _COMMON_SECTIONS[:]

        # 2021年度: 共通 + ESG追加
        secs_2021 = _COMMON_SECTIONS[:] + [
            _make_section("ESG戦略", "ESGへの取り組みを開始した。", "SEC-ESG"),
        ]

        # 2022年度: 共通 + ESG + DX追加（2021→2022の差分: DX追加）
        secs_2022 = _COMMON_SECTIONS[:] + [
            _make_section("ESG戦略", "ESGへの取り組みを開始した。", "SEC-ESG"),
            _make_section("DX推進", "デジタルトランスフォーメーションを推進する。", "SEC-DX"),
        ]

        r2020 = _make_yearly(2020, secs_2020)
        r2021 = _make_yearly(2021, secs_2021)
        r2022 = _make_yearly(2022, secs_2022)

        result = compare_years([r2020, r2021, r2022])

        # 最新2年度(2021→2022)を比較していること
        self.assertEqual(result.fiscal_year_from, 2021,
                         f"fiscal_year_from が 2021 でない: {result.fiscal_year_from}")
        self.assertEqual(result.fiscal_year_to, 2022,
                         f"fiscal_year_to が 2022 でない: {result.fiscal_year_to}")

        # 2021→2022 で "DX推進" が追加されていること
        added_headings = [s.heading for s in result.added_sections]
        self.assertIn("DX推進", added_headings,
                      f"'DX推進' が added_sections に含まれない: {added_headings}")

    def test_compare_years_raises_on_single_report(self):
        """レポートが1件しかない場合に ValueError を送出すること"""
        single = [_make_yearly(2024, _COMMON_SECTIONS[:])]
        with self.assertRaises(ValueError, msg="1件のみ渡した場合は ValueError が必要"):
            compare_years(single)

    def test_three_year_summary_format(self):
        """3年分比較のサマリーに正しい年度範囲が含まれること"""
        secs_base = _COMMON_SECTIONS[:]
        secs_with_new = _COMMON_SECTIONS[:] + [
            _make_section("新規セクション", "新規追加内容", "SEC-NEW"),
        ]
        reports = [
            _make_yearly(2020, secs_base),
            _make_yearly(2021, secs_base),
            _make_yearly(2022, secs_with_new),
        ]
        result = compare_years(reports)
        # サマリーに最新2年度の年度が含まれること
        self.assertIn("2021", result.summary,
                      f"summary に '2021' が含まれない: {result.summary}")
        self.assertIn("2022", result.summary,
                      f"summary に '2022' が含まれない: {result.summary}")


if __name__ == "__main__":
    unittest.main()
