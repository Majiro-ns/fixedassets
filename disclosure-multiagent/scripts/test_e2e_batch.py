"""
test_e2e_batch.py
=================
disclosure-multiagent E2E バッチ処理テスト

担当: 足軽4 subtask_070a4b_disclosure_real_api_prep
作成日: 2026-02-27

テスト仕様:
  TC-1: --batch モード（run_batch）で2社処理成功（モック）
  TC-2: --output-json 相当：run_batch の結果にJSONシリアライズ可能なフィールドが含まれる
  TC-3: 1社エラーでも他社は続行（エラーハンドリング）
  TC-4: 処理時間（elapsed_sec）が結果に含まれる
  TC-5: 既存の単一PDFモード（run_pipeline）が壊れていない（回帰テスト）
  TC-6: run_batch の返り値フォーマット確認
  TC-7: バッチ全エラーでも処理が中断しない

USE_MOCK_LLM=true 必須（実LLM APIキー不要）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
import unittest

# USE_MOCK_LLM=true を強制
os.environ.setdefault("USE_MOCK_LLM", "true")

# scriptsディレクトリをパスに追加
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_SAMPLES_DIR = _SCRIPTS_DIR.parent / "10_Research" / "samples"
COMPANY_A_PDF = str(_SAMPLES_DIR / "company_a.pdf")
COMPANY_B_PDF = str(_SAMPLES_DIR / "company_b.pdf")


class TestRunBatchFunction(unittest.TestCase):
    """run_batch() 関数の直接テスト"""

    def setUp(self):
        """USE_MOCK_LLM を確実に設定"""
        os.environ["USE_MOCK_LLM"] = "true"

    def test_tc1_batch_two_pdfs_success(self):
        """
        TC-1: --batch モードで2社処理（モック）→ 2件成功
        根拠: run_batch() が複数PDFを順次処理し、全件結果を返す
        """
        from run_e2e import run_batch

        if not Path(COMPANY_A_PDF).exists() or not Path(COMPANY_B_PDF).exists():
            self.skipTest("サンプルPDFが存在しません（10_Research/samples/）")

        results = run_batch(
            pdf_paths=[COMPANY_A_PDF, COMPANY_B_PDF],
            company_names=["テスト社A", "テスト社B"],
            fiscal_year=2025,
        )

        self.assertEqual(len(results), 2, "2社分の結果が返ること")
        ok_results = [r for r in results if r["status"] == "ok"]
        self.assertEqual(len(ok_results), 2, "2社とも成功すること")

    def test_tc2_output_json_serializable(self):
        """
        TC-2: --output-json 相当: run_batch の結果がJSONシリアライズ可能
        根拠: バッチ結果をJSONに保存するためシリアライズ可能であること
        """
        from run_e2e import run_batch

        if not Path(COMPANY_A_PDF).exists():
            self.skipTest("サンプルPDFが存在しません")

        results = run_batch(
            pdf_paths=[COMPANY_A_PDF],
            fiscal_year=2025,
        )

        # JSON シリアライズできること
        try:
            json_str = json.dumps(results, ensure_ascii=False)
            parsed = json.loads(json_str)
            self.assertEqual(len(parsed), 1)
        except (TypeError, ValueError) as e:
            self.fail(f"run_batch の結果がJSONシリアライズできません: {e}")

    def test_tc3_error_continues_other_pdfs(self):
        """
        TC-3: 1社エラーでも他社は続行
        根拠: 存在しないPDFをリストに混ぜても、存在するPDFの処理が完了すること
        """
        from run_e2e import run_batch

        if not Path(COMPANY_A_PDF).exists():
            self.skipTest("サンプルPDFが存在しません")

        non_existent = "/non/existent/path/fake.pdf"
        results = run_batch(
            pdf_paths=[non_existent, COMPANY_A_PDF],
            fiscal_year=2025,
        )

        self.assertEqual(len(results), 2, "エラーが発生しても2件の結果が返ること")
        # 1件目はエラー
        self.assertEqual(results[0]["status"], "error")
        self.assertIsNotNone(results[0]["error"])
        # 2件目は成功
        self.assertEqual(results[1]["status"], "ok")
        self.assertGreater(len(results[1]["report_md"]), 0)

    def test_tc4_elapsed_sec_in_result(self):
        """
        TC-4: 処理時間（elapsed_sec）が結果に含まれる
        根拠: バッチ処理の進捗・性能管理のため処理時間が必要
        """
        from run_e2e import run_batch

        if not Path(COMPANY_A_PDF).exists():
            self.skipTest("サンプルPDFが存在しません")

        results = run_batch(
            pdf_paths=[COMPANY_A_PDF],
            fiscal_year=2025,
        )

        self.assertIn("elapsed_sec", results[0], "elapsed_sec フィールドが存在すること")
        self.assertIsInstance(results[0]["elapsed_sec"], float)
        self.assertGreaterEqual(results[0]["elapsed_sec"], 0.0)

    def test_tc5_single_pdf_mode_not_broken(self):
        """
        TC-5: 既存の単一PDFモード（run_pipeline）が壊れていない（回帰テスト）
        根拠: バッチモード追加で既存のrun_pipeline()が破壊されないこと
        """
        from run_e2e import run_pipeline

        if not Path(COMPANY_A_PDF).exists():
            self.skipTest("サンプルPDFが存在しません")

        result = run_pipeline(
            pdf_path=COMPANY_A_PDF,
            company_name="回帰テスト社",
            fiscal_year=2025,
        )

        self.assertIsInstance(result, str, "run_pipeline() が文字列を返すこと")
        self.assertGreater(len(result), 0, "空でないMarkdownが返ること")

    def test_tc6_batch_result_format(self):
        """
        TC-6: run_batch の返り値フォーマット確認
        根拠: 必須フィールド（pdf_path/company_name/status/report_md/elapsed_sec/error）が含まれること
        """
        from run_e2e import run_batch

        if not Path(COMPANY_A_PDF).exists():
            self.skipTest("サンプルPDFが存在しません")

        results = run_batch(
            pdf_paths=[COMPANY_A_PDF],
            company_names=["フォーマット確認社"],
            fiscal_year=2025,
        )

        required_keys = {"pdf_path", "company_name", "status", "report_md", "elapsed_sec", "error"}
        self.assertTrue(
            required_keys.issubset(results[0].keys()),
            f"必須フィールドが不足: {required_keys - results[0].keys()}",
        )
        self.assertEqual(results[0]["company_name"], "フォーマット確認社")
        self.assertIn(results[0]["status"], ("ok", "error"))

    def test_tc7_all_error_batch_no_crash(self):
        """
        TC-7: バッチ全エラーでも処理が中断しない
        根拠: 全社エラーの場合でもlen(results) == len(pdf_paths)が保証されること
        """
        from run_e2e import run_batch

        fake_paths = [
            "/fake/path/a.pdf",
            "/fake/path/b.pdf",
            "/fake/path/c.pdf",
        ]

        results = run_batch(pdf_paths=fake_paths, fiscal_year=2025)

        self.assertEqual(len(results), 3, "全エラーでも3件の結果が返ること")
        for r in results:
            self.assertEqual(r["status"], "error")
            self.assertIsNotNone(r["error"])
            self.assertEqual(r["report_md"], "")
            self.assertIsInstance(r["elapsed_sec"], float)


class TestRunBatchOutputJson(unittest.TestCase):
    """--output-json ファイル出力の統合テスト"""

    def setUp(self):
        os.environ["USE_MOCK_LLM"] = "true"

    def test_json_file_output(self):
        """
        TC-2b: save_report + JSON出力の統合確認
        run_batch の結果を JSON ファイルに書き出せること
        """
        from run_e2e import run_batch

        if not Path(COMPANY_A_PDF).exists():
            self.skipTest("サンプルPDFが存在しません")

        results = run_batch(
            pdf_paths=[COMPANY_A_PDF],
            fiscal_year=2025,
        )

        # JSON ファイルに保存
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            temp_path = f.name
            json.dump(
                {"total": len(results), "results": results},
                f, ensure_ascii=False, indent=2,
            )

        # 読み込んで検証
        with open(temp_path, encoding="utf-8") as f:
            loaded = json.load(f)

        self.assertEqual(loaded["total"], 1)
        self.assertIn("results", loaded)
        self.assertEqual(len(loaded["results"]), 1)

        # 後片付け
        Path(temp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
