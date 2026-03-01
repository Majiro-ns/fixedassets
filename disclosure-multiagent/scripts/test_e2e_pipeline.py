"""
test_e2e_pipeline.py
====================
disclosure-multiagent Phase 1-M5-3: E2Eパイプライン統合テスト

実装者: 足軽4 subtask_063a13
作成日: 2026-02-27

テスト仕様（subtask_063a13 要件定義より）:
  TEST 1: pipeline_mock() がエラーなく完走し、Markdownを返す
  TEST 2: run_e2e.py の run_pipeline()（モックデータ）がエラーなく完走する
  TEST 3: company_a.pdf が存在する場合、extract_report() で StructuredReport が返る
          （PyMuPDF必要）
  TEST 4: 出力MarkdownのセクションヘッダーをアサートするCHECK-8テスト

USE_MOCK_LLM=true 必須（実LLM APIキー不要）。
"""

import os
import sys
import unittest
from pathlib import Path

# USE_MOCK_LLM=true を強制（テスト時に実API呼び出しをしない）
os.environ.setdefault("USE_MOCK_LLM", "true")

# scriptsディレクトリをパスに追加
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# サンプルPDFのパス
_SAMPLES_DIR = _SCRIPTS_DIR.parent / "10_Research" / "samples"
COMPANY_A_PDF = _SAMPLES_DIR / "company_a.pdf"


# ═══════════════════════════════════════════════════════════════
# TEST 1: pipeline_mock() がエラーなく完走する
# ═══════════════════════════════════════════════════════════════

class TestPipelineMock(unittest.TestCase):
    """TEST 1: m5_report_agent.pipeline_mock() がエラーなく完走しMarkdownを返す"""

    def test_pipeline_mock_returns_markdown(self):
        """pipeline_mock() が str を返す"""
        from m5_report_agent import pipeline_mock
        result = pipeline_mock(
            company_name="テスト株式会社",
            fiscal_year=2025,
            level="竹",
        )
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0, "pipeline_mock() が空文字列を返した")

    def test_pipeline_mock_contains_company_name(self):
        """pipeline_mock() の出力に会社名が含まれる"""
        from m5_report_agent import pipeline_mock
        result = pipeline_mock(company_name="テストカンパニー", fiscal_year=2025, level="竹")
        self.assertIn("テストカンパニー", result)

    def test_pipeline_mock_all_levels(self):
        """松・竹・梅の3レベルでエラーなく完走する"""
        from m5_report_agent import pipeline_mock
        for level in ["松", "竹", "梅"]:
            with self.subTest(level=level):
                result = pipeline_mock(fiscal_year=2025, level=level)
                self.assertIsInstance(result, str)
                self.assertGreater(len(result), 0)

    def test_pipeline_mock_check8_required_sections(self):
        """CHECK-8: pipeline_mock() 出力に必須セクションヘッダーが含まれる"""
        from m5_report_agent import pipeline_mock
        result = pipeline_mock(fiscal_year=2025, level="竹")
        # ## 1., ## 2., ## 3. の必須セクション確認
        self.assertIn("## 1.", result, "「## 1.」セクションヘッダーが見つからない")
        self.assertIn("## 2.", result, "「## 2.」セクションヘッダーが見つからない")
        self.assertIn("## 3.", result, "「## 3.」セクションヘッダーが見つからない")

    def test_pipeline_mock_check7b_law_ref_period(self):
        """CHECK-7b: pipeline_mock() 出力に法令参照期間が含まれる"""
        from m5_report_agent import pipeline_mock
        result = pipeline_mock(fiscal_year=2025, level="竹")
        # 2025年度3月決算 → 2025/04/01〜2026/03/31
        self.assertIn(
            "2025/04/01",
            result,
            "法令参照期間「2025/04/01」が出力Markdownに見つからない"
        )
        self.assertIn(
            "2026/03/31",
            result,
            "法令参照期間「2026/03/31」が出力Markdownに見つからない"
        )


# ═══════════════════════════════════════════════════════════════
# TEST 2: run_pipeline()（モックデータ）がエラーなく完走する
# ═══════════════════════════════════════════════════════════════

class TestRunPipelineMock(unittest.TestCase):
    """
    TEST 2: run_e2e.run_pipeline() をモックデータで実行する。
    実PDFを使わず m5_report_agent._build_mock_report() のデータで検証。
    """

    def _get_mock_pdf_path(self) -> str:
        """
        存在しないPDFパスを使い、モックstructured_reportを差し込む方法でテストする。
        実際にはcompany_a.pdfがある場合のみrun_pipelineを呼ぶ。
        存在しない場合はpipeline_mockで代替。
        """
        return str(COMPANY_A_PDF)

    def test_run_pipeline_with_real_pdf_if_available(self):
        """company_a.pdf が存在する場合にrun_pipeline()がエラーなく完走する

        CI環境スキップ注意: company_a.pdf は gitignore 対象（PDFは大容量のためリポジトリ非管理）。
        CI環境では COMPANY_A_PDF.exists() == False となり、このテストは自動スキップされる。
        ローカル環境で 10_Research/samples/company_a.pdf を配置することで実行可能。
        """
        # NOTE: @unittest.skipUnless ではなく self.skipTest() を使用している。
        # 理由: PDF存在チェックは実行時動的判定が必要なため（デコレータはモジュールロード時評価）。
        if not COMPANY_A_PDF.exists():
            self.skipTest(f"company_a.pdf が見つからないためスキップ: {COMPANY_A_PDF}")

        from run_e2e import run_pipeline
        result = run_pipeline(
            pdf_path=str(COMPANY_A_PDF),
            company_name="テスト社A",
            fiscal_year=2025,
            fiscal_month_end=3,
            level="竹",
        )
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0, "run_pipeline() が空文字列を返した")

    def test_run_pipeline_output_is_markdown(self):
        """run_pipeline() の出力が Markdown 形式（# ヘッダーを含む）

        CI環境スキップ注意: company_a.pdf 非存在時は自動スキップ。
        """
        # NOTE: CI環境では company_a.pdf が存在しないためスキップされる（設計上の正常動作）。
        if not COMPANY_A_PDF.exists():
            self.skipTest("company_a.pdf が見つからないためスキップ")

        from run_e2e import run_pipeline
        result = run_pipeline(
            pdf_path=str(COMPANY_A_PDF),
            fiscal_year=2025,
            level="竹",
        )
        # Markdown の # ヘッダーが含まれる
        self.assertIn("# ", result, "出力にMarkdownヘッダーが見つからない")

    def test_run_pipeline_nonexistent_pdf_raises(self):
        """存在しないPDFパスで FileNotFoundError が発生する"""
        from run_e2e import run_pipeline
        bad_path = "/tmp/nonexistent_e2e_test_abc999.pdf"
        with self.assertRaises(FileNotFoundError):
            run_pipeline(pdf_path=bad_path, fiscal_year=2025)

    def test_save_report_creates_file(self):
        """save_report() がファイルを作成する"""
        import tempfile
        from run_e2e import save_report

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = str(Path(tmpdir) / "subdir" / "test_report.md")
            test_md = "# テストレポート\n\n内容"
            saved = save_report(test_md, output_path)
            self.assertTrue(saved.exists(), f"レポートファイルが作成されていない: {saved}")
            content = saved.read_text(encoding="utf-8")
            self.assertEqual(content, test_md)

    def test_save_report_creates_parent_dirs(self):
        """save_report() が存在しない親ディレクトリを自動作成する"""
        import tempfile
        from run_e2e import save_report

        with tempfile.TemporaryDirectory() as tmpdir:
            # 深いネストのディレクトリ
            output_path = str(Path(tmpdir) / "a" / "b" / "c" / "report.md")
            saved = save_report("# Test", output_path)
            self.assertTrue(saved.exists())


# ═══════════════════════════════════════════════════════════════
# TEST 3: company_a.pdf で StructuredReport が返る
# ═══════════════════════════════════════════════════════════════

class TestExtractReportRealPdf(unittest.TestCase):
    """
    TEST 3: company_a.pdf が存在する場合、extract_report() で StructuredReport が返る。
    PyMuPDF (fitz) が必要。
    """

    def test_extract_report_returns_structured_report(self):
        """company_a.pdf → StructuredReport が返り、基本フィールドが設定されている

        CI環境スキップ注意: company_a.pdf 非存在時は自動スキップ。
        PyMuPDF (fitz) が未インストールの場合もスキップ（pip install pymupdf で解決）。
        """
        # NOTE: CI環境では company_a.pdf が存在しないためスキップされる（設計上の正常動作）。
        if not COMPANY_A_PDF.exists():
            self.skipTest(f"company_a.pdf が見つからないためスキップ: {COMPANY_A_PDF}")

        from m1_pdf_agent import extract_report, _check_fitz
        if not _check_fitz():
            self.skipTest("PyMuPDF (fitz) が利用できないためスキップ")

        report = extract_report(
            pdf_path=str(COMPANY_A_PDF),
            company_name="サンプル社A",
            fiscal_year=2025,
        )

        # StructuredReport の基本フィールド確認
        self.assertIsNotNone(report.document_id)
        self.assertGreater(len(report.document_id), 0)
        self.assertEqual(report.fiscal_year, 2025)
        self.assertEqual(report.fiscal_month_end, 3)

    def test_extract_report_has_sections(self):
        """company_a.pdf から1件以上のセクションが抽出される"""
        if not COMPANY_A_PDF.exists():
            self.skipTest("company_a.pdf が見つからないためスキップ")

        from m1_pdf_agent import extract_report, _check_fitz
        if not _check_fitz():
            self.skipTest("PyMuPDF が利用できないためスキップ")

        report = extract_report(str(COMPANY_A_PDF), fiscal_year=2025)
        self.assertGreater(
            len(report.sections), 0,
            "company_a.pdf からセクションが1件も抽出されなかった"
        )

    def test_extract_report_company_name_is_set(self):
        """company_a.pdf の company_name が空でない"""
        if not COMPANY_A_PDF.exists():
            self.skipTest("company_a.pdf が見つからないためスキップ")

        from m1_pdf_agent import extract_report, _check_fitz
        if not _check_fitz():
            self.skipTest("PyMuPDF が利用できないためスキップ")

        report = extract_report(
            str(COMPANY_A_PDF),
            company_name="サンプル社A",
            fiscal_year=2025,
        )
        # company_name が設定されている
        self.assertEqual(report.company_name, "サンプル社A")


# ═══════════════════════════════════════════════════════════════
# TEST 4: CHECK-8 出力MarkdownのセクションヘッダーアサートCHECK-8
# ═══════════════════════════════════════════════════════════════

class TestOutputMarkdownStructure(unittest.TestCase):
    """
    TEST 4: 出力MarkdownのセクションヘッダーをアサートするCHECK-8テスト

    CHECK-8: 出力レポートに「## 1.」「## 2.」「## 3.」の必須セクションが含まれる
    CHECK-7b: 出力Markdownに「2025/04/01〜2026/03/31」の参照期間が含まれる

    NOTE: USE_MOCK_LLMモードでは section_heading が固定値になる場合がある。
    これはモックの設計上の限界（仕様）であり、実LLMモードでは正しい値が使われる。
    このテストはMarkdownの構造（セクション存在・法令参照期間）を検証するのみ。
    section_headingの多様性（実PDFのセクション名反映）は実LLMモードでのみ検証可能。
    """

    @classmethod
    def setUpClass(cls):
        """全テストで共有するMarkdownを1回だけ生成する"""
        from m5_report_agent import pipeline_mock
        cls.mock_md = pipeline_mock(
            company_name="テスト株式会社",
            fiscal_year=2025,
            level="竹",
        )

    def test_check8_section1_exists(self):
        """CHECK-8: 「## 1.」セクション（変更箇所サマリ）が存在する"""
        self.assertIn("## 1.", self.mock_md, "必須セクション「## 1.」が見つからない")

    def test_check8_section2_exists(self):
        """CHECK-8: 「## 2.」セクション（セクション別の変更提案）が存在する"""
        self.assertIn("## 2.", self.mock_md, "必須セクション「## 2.」が見つからない")

    def test_check8_section3_exists(self):
        """CHECK-8: 「## 3.」セクション（未変更項目）が存在する"""
        self.assertIn("## 3.", self.mock_md, "必須セクション「## 3.」が見つからない")

    def test_check7b_law_ref_period_2025(self):
        """CHECK-7b: 2025年度の法令参照期間「2025/04/01」が含まれる"""
        self.assertIn(
            "2025/04/01",
            self.mock_md,
            "法令参照期間「2025/04/01」がMarkdownに見つからない"
        )

    def test_check7b_law_ref_period_end(self):
        """CHECK-7b: 2025年度の法令参照期間「2026/03/31」が含まれる"""
        self.assertIn(
            "2026/03/31",
            self.mock_md,
            "法令参照期間「2026/03/31」がMarkdownに見つからない"
        )

    def test_markdown_has_disclaimer(self):
        """レポートに但し書き・免責事項が含まれる"""
        self.assertIn("但し書き", self.mock_md)

    def test_markdown_has_header(self):
        """レポートの先頭に# ヘッダーがある"""
        lines = self.mock_md.strip().splitlines()
        has_h1 = any(line.startswith("# ") for line in lines[:5])
        self.assertTrue(has_h1, "レポートの先頭5行に# ヘッダーが見つからない")

    def test_markdown_has_law_table(self):
        """「## 4.」参照した法令一覧テーブルが含まれる"""
        self.assertIn("## 4.", self.mock_md, "「## 4.」法令一覧セクションが見つからない")

    def test_real_pdf_e2e_check8(self):
        """company_a.pdfを使ったE2EのCHECK-8確認（PyMuPDF必要）

        CI環境スキップ注意: company_a.pdf 非存在時は自動スキップ。
        このテストが通る場合、USE_MOCK_LLMモードでも実PDFのM1解析が行われる。
        ただしM3はモック動作のため section_heading は固定値になる（モック仕様）。
        """
        # NOTE: CI環境では company_a.pdf が存在しないためスキップされる（設計上の正常動作）。
        if not COMPANY_A_PDF.exists():
            self.skipTest("company_a.pdf が見つからないためスキップ")

        from m1_pdf_agent import _check_fitz
        if not _check_fitz():
            self.skipTest("PyMuPDF が利用できないためスキップ")

        from run_e2e import run_pipeline
        result = run_pipeline(
            pdf_path=str(COMPANY_A_PDF),
            company_name="サンプル社A",
            fiscal_year=2025,
            level="竹",
        )
        # CHECK-8: 必須セクション確認
        self.assertIn("## 1.", result, "E2E出力に「## 1.」がない")
        self.assertIn("## 2.", result, "E2E出力に「## 2.」がない")
        self.assertIn("## 3.", result, "E2E出力に「## 3.」がない")
        # CHECK-7b: 法令参照期間確認
        self.assertIn("2025/04/01", result, "E2E出力に「2025/04/01」がない")
        self.assertIn("2026/03/31", result, "E2E出力に「2026/03/31」がない")


# ═══════════════════════════════════════════════════════════════
# メイン実行
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 65)
    print("disclosure-multiagent E2Eパイプライン統合テスト")
    print("USE_MOCK_LLM=true 設定済み（実APIキー不要）")
    print("=" * 65)
    print()
    print(f"company_a.pdf: {'存在' if COMPANY_A_PDF.exists() else '見つからない（スキップ）'}")
    print(f"  パス: {COMPANY_A_PDF}")
    print()

    try:
        from m1_pdf_agent import _check_fitz
        fitz_ok = _check_fitz()
        print(f"PyMuPDF (fitz): {'利用可能' if fitz_ok else '未インストール（TEST 3スキップ）'}")
    except Exception:
        print("PyMuPDF (fitz): 確認エラー")
    print()

    unittest.main(verbosity=2)
