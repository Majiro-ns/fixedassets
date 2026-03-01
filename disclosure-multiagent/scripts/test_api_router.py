"""
test_api_router.py
==================
disclosure-multiagent FastAPI ルーター結合テスト

テスト対象エンドポイント:
  TC-A1: GET /api/health           → 200, status=ok
  TC-A2: POST /api/analyze         → 200, task_id 返却
  TC-A3: GET /api/status/{task_id} → 200, status in (queued/running/done/error)
  TC-A4: GET /api/status/invalid   → 404
  TC-A5: GET /api/edinet/search    （パラメータなし）→ 400
  TC-A6: GET /api/edinet/search?name=テスト → 200, results リスト形式
  TC-A7: POST /api/analyze         level バリデーション違反 → 422
  TC-B1: POST /api/analyze/upload  （有効PDF）→ 200, task_id 返却
  TC-B2: POST /api/analyze/upload  （ファイルなし）→ 422
  TC-B3: POST /api/analyze/upload  （.txt 拡張子）→ 400（拡張子バリデーション）
  TC-B4: POST /api/analyze/upload  （.txt拡張子・application/pdf型）→ 400（拡張子チェック優先）
  TC-B5: POST /api/analyze/upload  （.pdf拡張子・text/plain型）→ 400（Content-Typeチェック）
  TC-B6: POST /api/analyze/upload  （.pdf・application/pdf・%PDFマジックなし）→ 400（マジックバイトチェック）
  TC-B7: POST /api/analyze/upload  （21MBファイル）→ 413（サイズ上限チェック）

差分（既存テストとの重複回避）:
  test_e2e_pipeline.py: M1〜M5 スクリプト層の単体・結合テスト
  test_e2e_smoke.py:    M1〜M5 スモーク・直接呼び出しテスト
  本テスト:             FastAPI HTTPレイヤー（router/schema/service 連携）のみ

CHECK-9 根拠（期待値の根拠）:
  TC-A1: health() は {"status": "ok", "service": "disclosure-multiagent"} をハードコード返却
  TC-A2: create_task() が UUID形式の task_id を生成する（pipeline.py 参照）
  TC-A3: 直前の POST で生成した task_id が pipeline._tasks dict に存在するため 404 にならない
  TC-A4: pipeline._tasks に存在しない key → get_task() が None → HTTPException(404)
  TC-A5: edinet.py search_company() がいずれのパラメータも None → HTTPException(400)
  TC-A6: search_by_name() は CompanyInfo のリストを返す。空でも CompanySearchResponse 形式
  TC-A7: AnalyzeRequest.level の pattern=r"^(松|竹|梅)$" バリデーション → 422
  TC-B1: start_analysis_with_upload() は create_task() → AnalyzeResponse(task_id) を返す
  TC-B2: file: UploadFile = File(...) が必須のため未送信は 422 Unprocessable Entity
  TC-B3: filename.lower().endswith(".pdf") チェックで .txt は 400 Bad Request
  TC-B4: 拡張子チェックは Content-Type に関係なく filename ベースで判定 → .txt は常に 400
  TC-B5: .pdf 拡張子でも content_type != "application/pdf" なら 400
  TC-B6: .pdf + application/pdf でも先頭4バイトが b"%PDF" でなければ 400
  TC-B7: コンテンツが 20MB 超（20*1024*1024+1 バイト）なら 413

作成: 足軽7
  subtask_disclosure_integration_test: TC-A1〜A7
  subtask_disclosure_upload_test:      TC-B1〜B3
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# USE_MOCK_LLM=true を強制（実 LLM API 呼び出しをしない）
os.environ.setdefault("USE_MOCK_LLM", "true")

# scripts/ をインポートパスに追加（M1〜M9 モジュール参照のため）
_SCRIPTS_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
for p in [str(_SCRIPTS_DIR), str(_PROJECT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint(unittest.TestCase):
    """TC-A1: GET /api/health"""

    def test_tc_a1_health_returns_ok(self) -> None:
        """
        TC-A1: /api/health が 200 を返し status=ok を含む

        根拠: api/main.py health() は {"status": "ok", "service": "disclosure-multiagent"}
              をハードコードで返却する。外部依存なし。
        CHECK-9: status フィールドの値 "ok" はコードに直書きされているため変動しない。
        """
        resp = client.get("/api/health")
        self.assertEqual(resp.status_code, 200, f"health が 200 を返さなかった: {resp.text}")
        body = resp.json()
        self.assertEqual(body.get("status"), "ok", "health レスポンスに status=ok がない")
        self.assertEqual(
            body.get("service"),
            "disclosure-multiagent",
            "health レスポンスに service フィールドがない",
        )


class TestAnalyzeEndpoint(unittest.TestCase):
    """TC-A2, TC-A7: POST /api/analyze"""

    def test_tc_a2_analyze_returns_task_id(self) -> None:
        """
        TC-A2: POST /api/analyze がタスクIDを返す

        根拠: start_analysis() は create_task() を呼び、UUID形式の task_id を生成する。
              use_mock=True / pdf_doc_id=None の場合、サンプルPDFを使用するか
              プレースホルダーのパスを設定し、バックグラウンドタスクに委譲する。
        CHECK-9: AnalyzeResponse のフィールド: task_id (str), status="queued", message=str
        """
        payload = {
            "company_name": "テスト社A",
            "fiscal_year": 2025,
            "fiscal_month_end": 3,
            "level": "竹",
            "use_mock": True,
        }
        resp = client.post("/api/analyze", json=payload)
        self.assertEqual(resp.status_code, 200, f"POST /api/analyze が 200 を返さなかった: {resp.text}")
        body = resp.json()
        self.assertIn("task_id", body, "レスポンスに task_id がない")
        task_id = body["task_id"]
        self.assertIsInstance(task_id, str, "task_id が str でない")
        self.assertGreater(len(task_id), 0, "task_id が空文字列")
        self.assertEqual(body.get("status"), "queued", "status が queued でない")

    def test_tc_a7_analyze_invalid_level_returns_422(self) -> None:
        """
        TC-A7: POST /api/analyze で無効な level を送ると 422 Unprocessable Entity

        根拠: AnalyzeRequest.level の pattern=r"^(松|竹|梅)$" により FastAPI が自動バリデーション。
              "invalid" は松/竹/梅に該当しないため 422 を返す。
        CHECK-9: FastAPI の Pydantic バリデーションエラーは常に 422 を返す（仕様）。
        """
        payload = {
            "company_name": "テスト社",
            "fiscal_year": 2025,
            "level": "invalid",
            "use_mock": True,
        }
        resp = client.post("/api/analyze", json=payload)
        self.assertEqual(
            resp.status_code,
            422,
            f"無効な level に対して 422 を返さなかった: {resp.status_code} / {resp.text}",
        )


class TestStatusEndpoint(unittest.TestCase):
    """TC-A3, TC-A4: GET /api/status/{task_id}"""

    def _create_task(self) -> str:
        """POST /api/analyze でタスクを作成し task_id を返すヘルパー。"""
        resp = client.post(
            "/api/analyze",
            json={
                "company_name": "ステータステスト社",
                "fiscal_year": 2025,
                "level": "梅",
                "use_mock": True,
            },
        )
        return resp.json()["task_id"]

    def test_tc_a3_status_returns_pipeline_status(self) -> None:
        """
        TC-A3: 存在する task_id に対して GET /api/status/{task_id} が 200 を返す

        根拠: POST /api/analyze 直後にタスクが pipeline._tasks に登録されるため、
              /api/status/{task_id} は 200 を返す。
              status フィールドは "queued" / "running" / "done" / "error" のいずれか。
        CHECK-9: PipelineStatus.status の値は pipeline.py の VALID_STATUSES で管理。
                 直後のアクセスなら "queued" か "running" になる（モック実行が完了する前）。
        """
        task_id = self._create_task()
        resp = client.get(f"/api/status/{task_id}")
        self.assertEqual(
            resp.status_code,
            200,
            f"GET /api/status/{task_id} が 200 を返さなかった: {resp.text}",
        )
        body = resp.json()
        self.assertEqual(body.get("task_id"), task_id, "レスポンスの task_id が一致しない")
        self.assertIn(
            body.get("status"),
            ("queued", "running", "done", "error"),
            f"status が想定外の値: {body.get('status')}",
        )

    def test_tc_a4_status_unknown_task_returns_404(self) -> None:
        """
        TC-A4: 存在しない task_id に対して GET /api/status/{task_id} が 404 を返す

        根拠: pipeline.get_task() が None を返す → HTTPException(404, "Task not found: ...")
        CHECK-9: 存在しない UUID を指定することで、_tasks dict のキー不一致を確実に発生させる。
                 "00000000-nonexistent-taskid-0000" は有効な UUID ではなく _tasks に存在しない。
        """
        resp = client.get("/api/status/00000000-nonexistent-taskid-0000")
        self.assertEqual(
            resp.status_code,
            404,
            f"存在しない task_id に対して 404 を返さなかった: {resp.status_code}",
        )


class TestEdinetSearchEndpoint(unittest.TestCase):
    """TC-A5, TC-A6: GET /api/edinet/search"""

    def test_tc_a5_search_no_params_returns_400(self) -> None:
        """
        TC-A5: GET /api/edinet/search（パラメータなし）が 400 を返す

        根拠: search_company() で sec_code/edinet_code/name が全て None のとき
              HTTPException(400, "sec_code, edinet_code, or name is required") を raise する。
        CHECK-9: FastAPI では HTTPException(400) は 400 Bad Request として返される。
        """
        resp = client.get("/api/edinet/search")
        self.assertEqual(
            resp.status_code,
            400,
            f"パラメータなしに対して 400 を返さなかった: {resp.status_code} / {resp.text}",
        )

    def test_tc_a6_search_by_name_returns_valid_schema(self) -> None:
        """
        TC-A6: GET /api/edinet/search?name=テスト が 200 を返し CompanySearchResponse 形式

        根拠: search_by_name("テスト") が list[CompanyInfo] を返す（0件でも可）。
              CompanySearchResponse = {results: [...], total: int} 形式を確認する。
        CHECK-9: EdinetcodeDlInfo.csv が api/data/ に存在するため search_by_name() は
                 正常動作する（T001 で配置済み）。0件でもスキーマは正しく返る。
        """
        resp = client.get("/api/edinet/search", params={"name": "テスト"})
        self.assertEqual(
            resp.status_code,
            200,
            f"GET /api/edinet/search?name=テスト が 200 を返さなかった: {resp.text}",
        )
        body = resp.json()
        self.assertIn("results", body, "レスポンスに results フィールドがない")
        self.assertIn("total", body, "レスポンスに total フィールドがない")
        self.assertIsInstance(body["results"], list, "results が list でない")
        self.assertIsInstance(body["total"], int, "total が int でない")
        # results と total の整合性確認
        self.assertEqual(
            len(body["results"]),
            body["total"],
            f"results の件数({len(body['results'])})と total({body['total']})が一致しない",
        )


class TestAnalyzeUploadEndpoint(unittest.TestCase):
    """TC-B1〜B3: POST /api/analyze/upload"""

    # 最小限の有効 PDF バイト（%PDF ヘッダーを持つ最小 PDF）
    _MINIMAL_PDF = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f\n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
    )

    def test_tc_b1_upload_valid_pdf_returns_task_id(self) -> None:
        """
        TC-B1: POST /api/analyze/upload（有効PDF、use_mock=True）が task_id を返す

        根拠: start_analysis_with_upload() は
              1. _UPLOAD_DIR にファイル保存
              2. create_task() で task_id 生成
              3. background_tasks.add_task() でパイプライン起動
              4. AnalyzeResponse(task_id=task_id) を返す
              TestClient では BackgroundTask が同期的に実行されるが、
              レスポンスは create_task() 直後に確定するため 200 + task_id が返る。
        CHECK-9: AnalyzeResponse フィールド: task_id (str, len>0), status="queued"
                 multipart: files={"file": (name, bytes, content_type)}, data={Form fields}
        """
        files = {"file": ("test.pdf", self._MINIMAL_PDF, "application/pdf")}
        data = {
            "company_name": "アップロードテスト社",
            "fiscal_year": "2025",
            "fiscal_month_end": "3",
            "level": "竹",
            "use_mock": "true",
        }
        resp = client.post("/api/analyze/upload", files=files, data=data)
        self.assertEqual(
            resp.status_code,
            200,
            f"POST /api/analyze/upload が 200 を返さなかった: {resp.status_code} / {resp.text}",
        )
        body = resp.json()
        self.assertIn("task_id", body, "レスポンスに task_id がない")
        task_id = body["task_id"]
        self.assertIsInstance(task_id, str, "task_id が str でない")
        self.assertGreater(len(task_id), 0, "task_id が空文字列")
        self.assertEqual(body.get("status"), "queued", "status が queued でない")

    def test_tc_b2_upload_no_file_returns_422(self) -> None:
        """
        TC-B2: POST /api/analyze/upload（ファイルなし）が 422 を返す

        根拠: file: UploadFile = File(...) は必須パラメータ。
              multipart で file フィールドを送らない場合、FastAPI が自動的に
              422 Unprocessable Entity を返す（Required field missing）。
        CHECK-9: File(...) の必須制約は FastAPI の form/file バリデーション機構が処理。
                 Pydantic モデルとは別レイヤーだが同じく 422 を返す。
        """
        data = {"company_name": "テスト社", "use_mock": "true"}
        resp = client.post("/api/analyze/upload", data=data)
        self.assertEqual(
            resp.status_code,
            422,
            f"ファイルなし upload に対して 422 を返さなかった: {resp.status_code} / {resp.text}",
        )

    def test_tc_b3_upload_txt_extension_returns_400(self) -> None:
        """
        TC-B3: POST /api/analyze/upload（.txt 拡張子 + text/plain）が 400 を返す

        根拠: start_analysis_with_upload() は拡張子チェック（第1段階）で
              .pdf 以外を弾く。filename.lower().endswith(".pdf") が False の場合
              HTTPException(400, "Invalid file type. Only PDF files are accepted.") を送出。
        CHECK-9: 拡張子チェックは Content-Type・マジックバイトチェックより先に実行。
                 "not_a_pdf.txt" → endswith(".pdf") = False → 即時 400。
        """
        text_content = b"This is not a PDF file. Just plain text content."
        files = {"file": ("not_a_pdf.txt", text_content, "text/plain")}
        data = {
            "company_name": "非PDFテスト社",
            "fiscal_year": "2025",
            "level": "梅",
            "use_mock": "true",
        }
        resp = client.post("/api/analyze/upload", files=files, data=data)
        self.assertEqual(
            resp.status_code,
            400,
            f"拡張子チェックで 400 が返らなかった: {resp.status_code} / {resp.text}",
        )
        self.assertIn(
            "Invalid file type",
            resp.json().get("detail", ""),
            "エラーメッセージに 'Invalid file type' が含まれない",
        )

    def test_tc_b4_upload_txt_extension_with_pdf_content_type_returns_400(self) -> None:
        """
        TC-B4: POST /api/analyze/upload（.txt 拡張子 + application/pdf）が 400 を返す

        根拠: 拡張子チェック（第1段階）が Content-Type より先に実行される。
              filename = "fake.txt" → endswith(".pdf") = False → 400。
              Content-Type が application/pdf であっても拡張子で弾かれる。
        CHECK-9: 拡張子と Content-Type が矛盾する場合、拡張子チェックが優先。
        """
        pdf_content = b"%PDF-1.4 fake content with correct magic bytes"
        files = {"file": ("fake.txt", pdf_content, "application/pdf")}
        data = {"company_name": "テスト社", "use_mock": "true"}
        resp = client.post("/api/analyze/upload", files=files, data=data)
        self.assertEqual(
            resp.status_code,
            400,
            f"拡張子チェック（.txt + application/pdf）で 400 が返らなかった: {resp.status_code} / {resp.text}",
        )
        self.assertIn(
            "Invalid file type",
            resp.json().get("detail", ""),
            "エラーメッセージに 'Invalid file type' が含まれない",
        )

    def test_tc_b5_upload_pdf_extension_text_content_type_returns_400(self) -> None:
        """
        TC-B5: POST /api/analyze/upload（.pdf 拡張子 + text/plain）が 400 を返す

        根拠: 拡張子チェック（第1段階）は通過するが、Content-Type チェック（第2段階）で弾かれる。
              file.content_type = "text/plain" != "application/pdf" → 400。
        CHECK-9: 拡張子 OK でも Content-Type が不正なら 400。2段階目のチェックが機能すること確認。
        """
        text_content = b"This is not really a PDF despite the filename."
        files = {"file": ("disguised.pdf", text_content, "text/plain")}
        data = {"company_name": "テスト社", "use_mock": "true"}
        resp = client.post("/api/analyze/upload", files=files, data=data)
        self.assertEqual(
            resp.status_code,
            400,
            f"Content-Type チェック（.pdf + text/plain）で 400 が返らなかった: {resp.status_code} / {resp.text}",
        )
        self.assertIn(
            "Invalid file type",
            resp.json().get("detail", ""),
            "エラーメッセージに 'Invalid file type' が含まれない",
        )

    def test_tc_b6_upload_pdf_no_magic_bytes_returns_400(self) -> None:
        """
        TC-B6: POST /api/analyze/upload（.pdf 拡張子 + application/pdf + マジックバイトなし）が 400 を返す

        根拠: 拡張子・Content-Type チェックは通過するが、マジックバイトチェック（第5段階）で弾かれる。
              content.startswith(b"%PDF") = False → 400。
        CHECK-9: 拡張子・Content-Type が正しくても実ファイル内容が PDF でなければ弾く。
                 先頭が "FAKE" で始まるバイト列を使用。
        """
        fake_content = b"FAKE content that is not a real PDF file at all."
        files = {"file": ("fake.pdf", fake_content, "application/pdf")}
        data = {"company_name": "テスト社", "use_mock": "true"}
        resp = client.post("/api/analyze/upload", files=files, data=data)
        self.assertEqual(
            resp.status_code,
            400,
            f"マジックバイトチェックで 400 が返らなかった: {resp.status_code} / {resp.text}",
        )
        self.assertIn(
            "File content does not match PDF format",
            resp.json().get("detail", ""),
            "エラーメッセージに 'File content does not match PDF format' が含まれない",
        )

    def test_tc_b7_upload_oversized_file_returns_413(self) -> None:
        """
        TC-B7: POST /api/analyze/upload（21MB ファイル）が 413 を返す

        根拠: ファイルサイズ上限チェック（第4段階）で弾かれる。
              _MAX_FILE_SIZE = 20 * 1024 * 1024 = 20971520 バイト。
              len(content) > 20971520 → HTTPException(413, "File too large. Maximum size is 20MB.")
        CHECK-9: 21MB = 22020096 バイト（20MB 上限を 1MB 超過）。
                 先頭 4 バイトを %PDF にしてマジックバイトチェックを通過させた上でサイズチェックを確認。
                 拡張子・Content-Type チェックは通過する構成にして第4段階の動作を確認。
        """
        # 21MB: %PDF で始まる + 0x00 パディング（21 * 1024 * 1024 = 22020096 bytes）
        oversized_content = b"%PDF" + b"\x00" * (21 * 1024 * 1024 - 4)
        files = {"file": ("large.pdf", oversized_content, "application/pdf")}
        data = {"company_name": "テスト社", "use_mock": "true"}
        resp = client.post("/api/analyze/upload", files=files, data=data)
        self.assertEqual(
            resp.status_code,
            413,
            f"サイズ上限チェックで 413 が返らなかった: {resp.status_code} / {resp.text}",
        )
        self.assertIn(
            "File too large",
            resp.json().get("detail", ""),
            "エラーメッセージに 'File too large' が含まれない",
        )


if __name__ == "__main__":
    unittest.main()
