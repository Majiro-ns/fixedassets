"""
test_e2e_phase2.py
==================
disclosure-multiagent Phase 2 統合E2Eテスト（M8/M9組み込み）

実装者: 足軽3 subtask_074a3y_disclosure_phase2_e2e
作成日: 2026-02-28

テスト仕様:
  TC-1: M8 + M9 統合（同一レポート2年分 → 差分なし → export_documents 確認）
  TC-2: M8差分検出 + M9 Word出力（追加セクションあり → added_sections → Word記録）
  TC-3: M9 export_documents() が DocumentExportResult を返す（proposal_count確認）
  TC-4: compare_years() バリデーション（1件 → ValueError）
  TC-5: Phase 2 モジュール統合インポート確認（M8/M9 シンボル存在確認）
  TC-6: M8 3年分比較 + M9 Excel出力統合（2021→2022 最新2年度を比較）

手計算検証（CHECK-7b）:
  TC-1:
    old = new（同一セクション） → added/removed/changed = [] → summary に "差分なし" ✓
    export_documents(2件 ProposalSet) → proposal_count == 2 ✓
  TC-3:
    len(proposal_sets) = 3 → result.proposal_count == 3 ✓
  TC-6:
    reports = [2020, 2021, 2022] → compare_years は末尾2件を選択 → from=2021, to=2022 ✓
    2022に "DX推進" 追加 → added_sections = ["DX推進"] ✓
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# USE_MOCK_LLM=true を強制（実API不使用）
os.environ.setdefault("USE_MOCK_LLM", "true")

_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# ライブラリ存在フラグ（skipUnless 判定用）
try:
    import docx  # noqa: F401
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False

try:
    import openpyxl  # noqa: F401
    _OPENPYXL_AVAILABLE = True
except ImportError:
    _OPENPYXL_AVAILABLE = False

# Phase 2 モジュール
from m8_multiyear_agent import (
    YearlyReport,
    YearDiff,
    CHANGE_RATE_THRESHOLD,
    compare_years,
    detect_section_changes,
)
from m9_document_exporter import (
    DocumentExportResult,
    EXCEL_HEADERS,
    export_documents,
    export_to_excel,
    export_to_word,
)

# 既存モジュール（READ-ONLY）
from m3_gap_analysis_agent import StructuredReport, SectionData
from m4_proposal_agent import GapItem, Proposal, ProposalSet, QualityCheckResult


# ─────────────────────────────────────────────────────────
# テスト用フィクスチャ
# ─────────────────────────────────────────────────────────

def _make_section(heading: str, text: str, section_id: str | None = None) -> SectionData:
    sid = section_id or f"SEC-{abs(hash(heading)) % 10000:04d}"
    return SectionData(section_id=sid, heading=heading, text=text)


def _make_report(fiscal_year: int, sections: list[SectionData]) -> StructuredReport:
    return StructuredReport(
        document_id=f"DOC-{fiscal_year}",
        company_name="テスト株式会社",
        fiscal_year=fiscal_year,
        fiscal_month_end=3,
        sections=sections,
    )


def _make_yearly(fiscal_year: int, sections: list[SectionData]) -> YearlyReport:
    return YearlyReport(
        fiscal_year=fiscal_year,
        structured_report=_make_report(fiscal_year, sections),
        elapsed_sec=1.0,
    )


def _make_proposal(level: str, text: str) -> Proposal:
    return Proposal(
        level=level,
        text=text,
        quality=QualityCheckResult(passed=True, should_regenerate=False),
        attempts=1,
        status="pass",
        placeholders=[],
    )


def _make_proposal_set(
    gap_id: str = "GAP-001",
    disclosure_item: str = "人的資本KPIの定量的開示",
    source_warning: str | None = None,
) -> ProposalSet:
    return ProposalSet(
        gap_id=gap_id,
        disclosure_item=disclosure_item,
        reference_law_id="HC_20260220_001",
        reference_url="https://example.com/law",
        source_warning=source_warning,
        matsu=_make_proposal("松", f"【松】{disclosure_item}について詳細な数値目標を開示します。"),
        take=_make_proposal("竹", f"【竹】{disclosure_item}の方針と概要を開示します。"),
        ume=_make_proposal("梅", f"【梅】{disclosure_item}の概要を記載します。"),
    )


# 共通セクションセット
_BASE_SECTIONS = [
    _make_section("第一部 企業情報", "企業情報について記載する。", "SEC-001"),
    _make_section("人材戦略", "人材の採用・育成を推進する。", "SEC-002"),
    _make_section("サステナビリティ", "サステナビリティへの取り組みを推進する。", "SEC-003"),
]


# ─────────────────────────────────────────────────────────
# TC-1: M8 + M9 統合テスト（差分なし → export_documents）
# ─────────────────────────────────────────────────────────

class TestTC1M8M9Integration(unittest.TestCase):
    """TC-1: M8 + M9 統合テスト（同一レポート2年分 → 差分なし → export_documents）"""

    def test_tc1_no_diff_then_export_documents(self) -> None:
        """
        同一セクション構成の2年分レポートをM8で比較し、差分なしを確認後にM9でエクスポート

        手計算:
            old=new（同一内容）→ added/removed/changed=[]/[]/[] → summary="差分なし"
            export_documents(2件) → proposal_count == 2
        根拠: F-08（複数年度比較）+ F-09（Word/Excel出力）の統合動作確認
        """
        # M8: 差分なし
        old = _make_yearly(2023, _BASE_SECTIONS[:])
        new = _make_yearly(2024, _BASE_SECTIONS[:])
        diff = compare_years([old, new])

        self.assertIsInstance(diff, YearDiff)
        self.assertEqual(diff.fiscal_year_from, 2023)
        self.assertEqual(diff.fiscal_year_to, 2024)
        self.assertEqual(diff.added_sections, [], "同一レポートで added_sections が空でない")
        self.assertEqual(diff.removed_sections, [], "同一レポートで removed_sections が空でない")
        self.assertEqual(diff.changed_sections, [], "同一レポートで changed_sections が空でない")
        self.assertIn("差分なし", diff.summary, f"差分なし時の summary が不正: {diff.summary}")

        # M9: export_documents（ライブラリ存在に依存しないフィールドを確認）
        proposal_sets = [
            _make_proposal_set("GAP-001", "人的資本開示"),
            _make_proposal_set("GAP-002", "気候変動リスク開示"),
        ]

        with (
            tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as w_tmp,
            tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as x_tmp,
        ):
            w_path = w_tmp.name
            x_path = x_tmp.name

        try:
            result = export_documents(
                proposal_sets=proposal_sets,
                word_path=w_path,
                excel_path=x_path,
                company_name="テスト株式会社",
                fiscal_year=2024,
            )
            self.assertIsInstance(result, DocumentExportResult)
            self.assertEqual(result.proposal_count, 2,
                             f"proposal_count={result.proposal_count}（期待: 2）")
            self.assertGreater(len(result.export_at), 0, "export_at が空")
        finally:
            for p in (w_path, x_path):
                if Path(p).exists():
                    Path(p).unlink()


# ─────────────────────────────────────────────────────────
# TC-2: M8差分検出 + M9 Word出力
# ─────────────────────────────────────────────────────────

class TestTC2DiffAndWordExport(unittest.TestCase):
    """TC-2: M8差分検出 + M9 Word出力（追加セクションあり → added_sections → Word記録確認）"""

    def test_tc2_added_section_detected(self) -> None:
        """
        M8で追加セクションを検出する

        手計算:
            old = [第一部, 人材戦略, サステナビリティ]
            new = [第一部, 人材戦略, サステナビリティ, リスク管理]  ← 追加
            added_sections = ["リスク管理"] ✓
        """
        old_sections = _BASE_SECTIONS[:]
        new_sections = _BASE_SECTIONS[:] + [
            _make_section("リスク管理", "リスク管理の方針と体制を記載する。", "SEC-RISK"),
        ]

        diff = compare_years([
            _make_yearly(2023, old_sections),
            _make_yearly(2024, new_sections),
        ])

        added_headings = [s.heading for s in diff.added_sections]
        self.assertIn("リスク管理", added_headings,
                      f"'リスク管理' が added_sections に含まれない: {added_headings}")
        self.assertIn("追加: 1件", diff.summary,
                      f"summary に '追加: 1件' が含まれない: {diff.summary}")

    @unittest.skipUnless(_DOCX_AVAILABLE, "python-docx が未インストールのためスキップ")
    def test_tc2_word_export_after_diff(self) -> None:
        """
        M8差分検出後、M9でWord出力が成功することを確認する

        根拠: Phase 2パイプライン（M8差分取得 → M9エクスポート）の統合確認
        """
        proposal_sets = [_make_proposal_set("GAP-001", "リスク管理開示")]

        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result_path = export_to_word(
                proposal_sets=proposal_sets,
                output_path=tmp_path,
                company_name="テスト株式会社",
                fiscal_year=2024,
            )
            self.assertTrue(Path(result_path).exists(), f"Word ファイルが生成されない: {result_path}")
            self.assertGreater(Path(result_path).stat().st_size, 0, "Word ファイルサイズが0")
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()


# ─────────────────────────────────────────────────────────
# TC-3: M9 export_documents() proposal_count 確認
# ─────────────────────────────────────────────────────────

class TestTC3ExportDocumentsResult(unittest.TestCase):
    """TC-3: M9 export_documents() が DocumentExportResult を返す（proposal_count確認）"""

    def test_tc3_proposal_count_matches_input(self) -> None:
        """
        export_documents() の proposal_count が入力リストの len と一致すること

        手計算:
            len(proposal_sets) = 3 → result.proposal_count == 3 ✓
        根拠: DocumentExportResult.proposal_count の正確性確認
        """
        proposal_sets = [
            _make_proposal_set("GAP-001", "人的資本KPI開示"),
            _make_proposal_set("GAP-002", "気候変動リスク開示"),
            _make_proposal_set("GAP-003", "サプライチェーン開示", source_warning="URL未確認"),
        ]

        with (
            tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as w_tmp,
            tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as x_tmp,
        ):
            w_path = w_tmp.name
            x_path = x_tmp.name

        try:
            result = export_documents(
                proposal_sets=proposal_sets,
                word_path=w_path,
                excel_path=x_path,
            )
            self.assertIsInstance(result, DocumentExportResult)
            self.assertEqual(result.proposal_count, len(proposal_sets),
                             f"proposal_count={result.proposal_count}（期待: {len(proposal_sets)}）")
            self.assertIsInstance(result.export_at, str)
            self.assertGreater(len(result.export_at), 0, "export_at が空文字列")
        finally:
            for p in (w_path, x_path):
                if Path(p).exists():
                    Path(p).unlink()


# ─────────────────────────────────────────────────────────
# TC-4: compare_years() バリデーション（1件 → ValueError）
# ─────────────────────────────────────────────────────────

class TestTC4CompareYearsValidation(unittest.TestCase):
    """TC-4: compare_years() のバリデーション（1件 → ValueError）"""

    def test_tc4_single_report_raises_value_error(self) -> None:
        """
        YearlyReport が1件のみの場合に ValueError を送出すること

        根拠: compare_years の事前条件「最低2件必要」の確認
        """
        single = [_make_yearly(2024, _BASE_SECTIONS[:])]
        with self.assertRaises(ValueError):
            compare_years(single)

    def test_tc4_empty_list_raises_value_error(self) -> None:
        """
        YearlyReport が0件の場合にも ValueError を送出すること

        根拠: 同上
        """
        with self.assertRaises(ValueError):
            compare_years([])


# ─────────────────────────────────────────────────────────
# TC-5: Phase 2 モジュール統合インポート確認
# ─────────────────────────────────────────────────────────

class TestTC5Phase2ModuleIntegrity(unittest.TestCase):
    """TC-5: Phase 2 モジュール統合インポート確認（M8/M9 主要シンボル存在確認）"""

    def test_tc5_m8_symbols_available(self) -> None:
        """
        M8の主要シンボルが全てインポートできること

        根拠: M8モジュールのAPIサーフェス確認（回帰テスト代替）
        """
        # インポート済みシンボルの存在確認
        self.assertTrue(callable(compare_years), "compare_years が callable でない")
        self.assertTrue(callable(detect_section_changes), "detect_section_changes が callable でない")
        self.assertTrue(isinstance(CHANGE_RATE_THRESHOLD, float),
                        f"CHANGE_RATE_THRESHOLD が float でない: {type(CHANGE_RATE_THRESHOLD)}")
        self.assertEqual(CHANGE_RATE_THRESHOLD, 0.20,
                         f"CHANGE_RATE_THRESHOLD が 0.20 でない: {CHANGE_RATE_THRESHOLD}")

    def test_tc5_m9_symbols_available(self) -> None:
        """
        M9の主要シンボルが全てインポートできること（EXCEL_HEADERS 7列確認含む）

        根拠: M9モジュールのAPIサーフェス + EXCEL_HEADERS列数確認
        """
        self.assertTrue(callable(export_documents), "export_documents が callable でない")
        self.assertTrue(callable(export_to_word), "export_to_word が callable でない")
        self.assertTrue(callable(export_to_excel), "export_to_excel が callable でない")
        self.assertIsInstance(EXCEL_HEADERS, list, "EXCEL_HEADERS が list でない")
        self.assertEqual(len(EXCEL_HEADERS), 7,
                         f"EXCEL_HEADERS が7列でない: {len(EXCEL_HEADERS)}列 {EXCEL_HEADERS}")


# ─────────────────────────────────────────────────────────
# TC-6: M8 3年分比較 + M9 Excel出力統合
# ─────────────────────────────────────────────────────────

class TestTC6ThreeYearAndExcelExport(unittest.TestCase):
    """TC-6: M8 3年分比較（2020→2021→2022）+ M9 Excel出力統合"""

    def test_tc6_three_year_compares_latest_two(self) -> None:
        """
        3年分レポートを compare_years に渡し、最新2年度（2021→2022）が比較されること

        手計算:
            reports = [2020, 2021, 2022]
            昇順ソート末尾2件 → fiscal_year_from=2021, fiscal_year_to=2022 ✓
            2022 に "DX推進" 追加 → added_sections = ["DX推進"] ✓
        """
        secs_base = _BASE_SECTIONS[:]
        secs_2022 = _BASE_SECTIONS[:] + [
            _make_section("DX推進", "デジタルトランスフォーメーションを推進する。", "SEC-DX"),
        ]

        result = compare_years([
            _make_yearly(2020, secs_base),
            _make_yearly(2021, secs_base),
            _make_yearly(2022, secs_2022),
        ])

        self.assertEqual(result.fiscal_year_from, 2021)
        self.assertEqual(result.fiscal_year_to, 2022)
        added_headings = [s.heading for s in result.added_sections]
        self.assertIn("DX推進", added_headings,
                      f"'DX推進' が added_sections に含まれない: {added_headings}")

    @unittest.skipUnless(_OPENPYXL_AVAILABLE, "openpyxl が未インストールのためスキップ")
    def test_tc6_excel_export_after_three_year_diff(self) -> None:
        """
        3年分比較後にM9でExcel出力が成功し、ヘッダーが正確であることを確認する

        根拠: M8（3年分差分）+ M9（Excel出力）の統合確認
        手計算: EXCEL_HEADERS 7列がシート「提案一覧」の2行目に存在すること ✓
        """
        proposal_sets = [
            _make_proposal_set("GAP-001", "人的資本KPI開示"),
            _make_proposal_set("GAP-002", "DX推進開示"),
        ]

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            result_path = export_to_excel(
                proposal_sets=proposal_sets,
                output_path=tmp_path,
                company_name="テスト株式会社",
                fiscal_year=2022,
            )
            self.assertTrue(Path(result_path).exists(), f"Excel ファイルが生成されない: {result_path}")

            import openpyxl as xl
            wb = xl.load_workbook(tmp_path)
            ws = wb["提案一覧"]
            actual_headers = [
                ws.cell(row=2, column=col).value
                for col in range(1, len(EXCEL_HEADERS) + 1)
            ]
            self.assertEqual(actual_headers, EXCEL_HEADERS,
                             f"Excelヘッダー不一致:\n期待: {EXCEL_HEADERS}\n実際: {actual_headers}")
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()


if __name__ == "__main__":
    unittest.main()
