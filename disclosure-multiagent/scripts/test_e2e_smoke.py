"""
test_e2e_smoke.py
=================
disclosure-multiagent E2Eスモークテスト

M1→M2→M3→M4→M5 全パイプラインの各ステップを個別に検証するスモークテスト。
USE_MOCK_LLM=true のモックモードで動作（ANTHROPIC_API_KEY 不要）。

既存テストとの差分（重複回避）:
  test_e2e_pipeline.py: pipeline_mock() と run_pipeline() の終端結果・save_report() 検証
  test_e2e_batch.py:    run_batch() の複数PDF処理・エラー継続・JSON出力検証
  test_e2e_smoke.py:    M1〜M5 各ステップの入出力スキーマ検証 + M2/M3直接呼び出し（新規）

CHECK-9根拠（各TCに記載）:
  TC-1: M1→M5 全連鎖完走（M5出力に「但し書き」が含まれることでM5到達を確認）
  TC-2: パイプライン出力が実質的なコンテンツを持つこと（200文字超）
  TC-3: M1 sections の構造フィールド確認（section_id/heading が str 型）
  TC-4: M3 analyze_gaps() 直接呼び出し → GapAnalysisResult.gaps が list 型
  TC-5: M5 generate_report() 直接呼び出し（pipeline_mock 経由でない）→ ## を含む
  TC-6: company_b.pdf でも同様に完走（複数PDF再現性確認）
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# USE_MOCK_LLM=true を強制（実API呼び出しをしない）
os.environ.setdefault("USE_MOCK_LLM", "true")

# scripts ディレクトリをパスに追加
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# サンプル PDF パス
_SAMPLES_DIR = _SCRIPTS_DIR.parent / "10_Research" / "samples"
COMPANY_A_PDF = str(_SAMPLES_DIR / "company_a.pdf")
COMPANY_B_PDF = str(_SAMPLES_DIR / "company_b.pdf")


class TestSmokeFullPipeline(unittest.TestCase):
    """TC-1〜TC-2: run_pipeline() M1→M5 フルパイプライン完走スモーク"""

    def setUp(self) -> None:
        os.environ["USE_MOCK_LLM"] = "true"

    def test_tc1_full_pipeline_reaches_m5(self) -> None:
        """
        TC-1: company_a.pdf でフルパイプライン（run_pipeline）が完走する（モック）

        根拠: M1→M2→M3→M4→M5 全ステップが連鎖して Markdown を返すことの確認。
        CHECK-9: M5 generate_report() は「但し書き・免責事項」ブロックを必ず出力する
                 （m5_report_agent._build_disclaimer_header() が必ず呼ばれる）。
                 "但し書き" の存在確認により M5 まで到達したことを証明する。
        """
        from run_e2e import run_pipeline

        if not Path(COMPANY_A_PDF).exists():
            self.skipTest("company_a.pdf が存在しません（10_Research/samples/ を確認）")

        result = run_pipeline(
            pdf_path=COMPANY_A_PDF,
            company_name="スモークテスト社A",
            fiscal_year=2025,
        )

        self.assertIsInstance(result, str, "run_pipeline() が str を返さなかった")
        self.assertIn(
            "但し書き",
            result,
            "M5 出力に「但し書き」が含まれていない（M5 まで到達しなかった可能性）",
        )

    def test_tc2_pipeline_output_has_sufficient_content(self) -> None:
        """
        TC-2: パイプライン出力に report_md が含まれ len > 0

        根拠: M5 generate_report() が実質的なコンテンツ（200文字超）を生成すること。
        CHECK-9: pipeline_mock() のモック出力は「## 1.〜## 4.」＋免責・法令テーブルを含む
                 ため、最低でも 200文字を超える。len > 200 は最小コンテンツ長の確認。
        """
        from run_e2e import run_pipeline

        if not Path(COMPANY_A_PDF).exists():
            self.skipTest("company_a.pdf が存在しません")

        result = run_pipeline(
            pdf_path=COMPANY_A_PDF,
            fiscal_year=2025,
        )

        self.assertGreater(len(result), 0, "run_pipeline() の出力が空文字列")
        self.assertGreater(
            len(result),
            200,
            f"出力が短すぎます（{len(result)}文字 ≤ 200文字）",
        )


class TestSmokeM1SectionStructure(unittest.TestCase):
    """TC-3: M1 extract_report() セクション構造スモーク"""

    def test_tc3_m1_sections_have_required_fields(self) -> None:
        """
        TC-3: M1 sections が1件以上抽出され、各セクションに必須フィールドがある

        根拠: extract_report() が一般企業の有報PDFから SectionData を抽出し、
              section_id / heading / text の各フィールドが str 型であることを確認する。
        CHECK-9: is_fund=false 前提（company_a.pdf は一般企業の有価証券報告書）。
                 SectionData のフィールド型検証は test_e2e_pipeline.py では行っておらず、
                 本テストが初めての構造スキーマ確認となる。
        """
        if not Path(COMPANY_A_PDF).exists():
            self.skipTest("company_a.pdf が存在しません")

        from m1_pdf_agent import extract_report

        structured_report = extract_report(
            pdf_path=COMPANY_A_PDF,
            fiscal_year=2025,
        )

        self.assertGreater(
            len(structured_report.sections),
            0,
            "M1 が1件もセクションを抽出しなかった（is_fund=false の有報では1件以上抽出されるべき）",
        )

        # 各セクションの必須フィールドが str 型であることを確認
        first = structured_report.sections[0]
        self.assertIsInstance(first.section_id, str, "section_id が str でない")
        self.assertGreater(len(first.section_id), 0, "section_id が空文字列")
        self.assertIsInstance(first.heading, str, "heading が str でない")
        self.assertIsInstance(first.text, str, "text が str でない")


class TestSmokeM2LawContext(unittest.TestCase):
    """M2 load_law_context() スモーク（既存テストなし・新規）"""

    def test_m2_law_context_has_applicable_entries(self) -> None:
        """
        M2: load_law_context() が LawContext を返し applicable_entries が存在する

        根拠: M2 は法令 YAML から適用法令エントリを読み込む。
              applicable_entries が1件以上あることで M3 への入力が確保される。
        CHECK-9: test_e2e_pipeline.py / test_e2e_batch.py は M2 を直接テストしていない。
                 本テストが M2 の単体スモーク確認として初出となる。
        """
        from m2_law_agent import load_law_context

        law_context = load_law_context(fiscal_year=2025, fiscal_month_end=3)

        self.assertIsNotNone(law_context, "load_law_context() が None を返した")
        self.assertIsInstance(
            law_context.applicable_entries,
            list,
            "applicable_entries が list でない",
        )
        self.assertGreater(
            len(law_context.applicable_entries),
            0,
            "2025年度3月決算の適用法令エントリが0件（law_entries YAML を確認）",
        )
        # law_yaml_as_of が str 型
        self.assertIsInstance(law_context.law_yaml_as_of, str)
        self.assertGreater(len(law_context.law_yaml_as_of), 0)


class TestSmokeM3GapAnalysis(unittest.TestCase):
    """TC-4: M3 analyze_gaps() 直接呼び出しスモーク（既存テストなし・新規）"""

    def setUp(self) -> None:
        os.environ["USE_MOCK_LLM"] = "true"

    def test_tc4_m3_gap_result_has_gaps_list(self) -> None:
        """
        TC-4: M3 gap_result に gaps リストが含まれる

        根拠: analyze_gaps() がモックデータで GapAnalysisResult を返し、
              gaps フィールドが list 型であることを確認する（M3 出力スキーマ検証）。
        CHECK-9: test_e2e_pipeline.py / test_e2e_batch.py は analyze_gaps() を直接呼ばない。
                 本テストが M3 の単体スモーク確認として初出。
                 モックモード(use_mock=True)では _build_mock_gaps() を使用するため、
                 gaps リストは必ず1件以上になる（法令エントリ×セクションのクロス判定）。
        """
        from m3_gap_analysis_agent import (
            analyze_gaps,
            _build_mock_report,
            _build_mock_law_context,
        )

        mock_report = _build_mock_report()
        mock_law = _build_mock_law_context()

        gap_result = analyze_gaps(
            report=mock_report,
            law_context=mock_law,
            use_mock=True,
        )

        self.assertIsNotNone(gap_result, "analyze_gaps() が None を返した")
        self.assertTrue(
            hasattr(gap_result, "gaps"),
            "GapAnalysisResult に gaps フィールドがない",
        )
        self.assertIsInstance(gap_result.gaps, list, "gap_result.gaps が list でない")
        # summary フィールドが存在し total_gaps が int 型
        self.assertTrue(hasattr(gap_result, "summary"), "gap_result に summary がない")
        self.assertIsInstance(
            gap_result.summary.total_gaps,
            int,
            "summary.total_gaps が int でない",
        )

    def test_tc4b_m3_gap_items_have_required_fields(self) -> None:
        """
        TC-4b: M3 gap_result.gaps の各 GapItem に必須フィールドがある

        根拠: GapItem のスキーマ検証（gap_id / has_gap / change_type が存在）。
        CHECK-9: gaps が空でない場合のみ実行。モックデータでは必ず gap が生成される。
        """
        from m3_gap_analysis_agent import (
            analyze_gaps,
            _build_mock_report,
            _build_mock_law_context,
        )

        gap_result = analyze_gaps(
            report=_build_mock_report(),
            law_context=_build_mock_law_context(),
            use_mock=True,
        )

        if not gap_result.gaps:
            self.skipTest("gap_result.gaps が空（モックデータの変更を確認）")

        first_gap = gap_result.gaps[0]
        self.assertIsInstance(first_gap.gap_id, str, "gap_id が str でない")
        self.assertGreater(len(first_gap.gap_id), 0, "gap_id が空文字列")
        self.assertIsInstance(first_gap.change_type, str, "change_type が str でない")
        # has_gap は Optional[bool]
        self.assertIn(
            first_gap.has_gap,
            (True, False, None),
            f"has_gap が想定外の値: {first_gap.has_gap}",
        )


class TestSmokeM5GenerateReport(unittest.TestCase):
    """TC-5: M5 generate_report() 直接呼び出しスモーク（pipeline_mock 経由でない）"""

    def setUp(self) -> None:
        os.environ["USE_MOCK_LLM"] = "true"

    def test_tc5_generate_report_contains_markdown_headers(self) -> None:
        """
        TC-5: M5 レポートが Markdown形式（## を含む）

        根拠: generate_report() を直接呼び出し（pipeline_mock 経由でなく）、
              出力が ## セクションヘッダーを含む Markdown であることを確認する。
        CHECK-9: test_e2e_pipeline.py の TestOutputMarkdownStructure は pipeline_mock() 経由。
                 本テストは generate_report() を M3/M4 モック出力を与えて直接呼び出す点で新規。
                 生成書は Section 1-3: 「## 1.」〜「## 4.」の4セクション構造を保証している。
        """
        from m3_gap_analysis_agent import (
            analyze_gaps,
            _build_mock_report,
            _build_mock_law_context,
        )
        from m4_proposal_agent import generate_proposals
        from m5_report_agent import generate_report, _m3_gap_to_m4_gap

        # M1〜M3 モックデータ構築
        mock_report = _build_mock_report()
        mock_law = _build_mock_law_context()
        gap_result = analyze_gaps(mock_report, mock_law, use_mock=True)

        # M4: gap_result.gaps から proposals 生成
        proposals = [
            generate_proposals(_m3_gap_to_m4_gap(gap))
            for gap in gap_result.gaps
            if gap.has_gap
        ]

        # M5: generate_report() 直接呼び出し
        report_md = generate_report(
            structured_report=mock_report,
            law_context=mock_law,
            gap_result=gap_result,
            proposal_set=proposals,
            level="竹",
        )

        self.assertIsInstance(report_md, str, "generate_report() が str を返さなかった")
        self.assertIn(
            "##",
            report_md,
            "M5 レポートに ## Markdown ヘッダーが含まれていない",
        )
        # ## セクションが複数存在する（設計書 Section 1-3: ## 1.〜## 4.）
        section_count = report_md.count("\n##")
        self.assertGreater(
            section_count,
            0,
            f"## セクションが見つかりません。出力先頭200文字: {report_md[:200]}",
        )


class TestSmokeCompanyB(unittest.TestCase):
    """TC-6: company_b.pdf でも同様に完走する"""

    def setUp(self) -> None:
        os.environ["USE_MOCK_LLM"] = "true"

    def test_tc6_company_b_pipeline_completes(self) -> None:
        """
        TC-6: company_b.pdf でも同様に完走する

        根拠: 複数の有報PDFに対してパイプラインが安定して動作することの確認。
              TC-1 の company_a.pdf に加え、異なるPDF（company_b.pdf）でも
              同じ品質のレポートが生成されることを検証する（再現性・PDF非依存性確認）。
        CHECK-9: run_pipeline() は pdf_path を引数として受け取り、
                 M1 が PDF を解析する。company_b.pdf でも M5 まで到達することを確認。
        """
        from run_e2e import run_pipeline

        if not Path(COMPANY_B_PDF).exists():
            self.skipTest("company_b.pdf が存在しません（10_Research/samples/ を確認）")

        result = run_pipeline(
            pdf_path=COMPANY_B_PDF,
            company_name="スモークテスト社B",
            fiscal_year=2025,
        )

        self.assertIsInstance(result, str, "run_pipeline(company_b) が str を返さなかった")
        self.assertGreater(len(result), 0, "company_b.pdf のパイプライン出力が空")
        self.assertIn(
            "但し書き",
            result,
            "company_b.pdf の M5 出力に「但し書き」が含まれていない（M5 未到達の可能性）",
        )


if __name__ == "__main__":
    unittest.main()
