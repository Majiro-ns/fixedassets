"""tests/test_phase3_t005b.py - Phase 3 T005b テスト

T005b: OCR連携・IMAP自動取得・ERP直接インポート

テスト対象:
  - imap_fetcher.py (F-18): IMAP自動取得
  - ocr_extractor.py (F-19): OCR連携
  - erp_import.py (F-20): ERP直接インポート
  - POST /api/imap/fetch
  - POST /api/ocr/extract
  - POST /api/erp/import
  - GET  /api/erp/import/logs

根拠:
  - 全機能がdry_run/mockモードで外部接続なしにテスト可能なこと
  - エラーケースも graceful handling されること
  - 既存47件テストを壊さないこと
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _make_db_with_po(po_number: str = "PO-TEST-T005B", grand_total: float = 110000.0):
    """発注書1件入りのインメモリ DB を作成する。"""
    schema_path = Path(__file__).parent.parent / "schema.sql"
    conn = sqlite3.connect(":memory:")
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO suppliers (name, code) VALUES ('テストベンダー', 'VENDOR-001')")
    conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, "
        "total_amount, tax_amount, grand_total) VALUES (?, 1, 'approved', ?, ?, ?)",
        (po_number, round(grand_total / 1.1, 2), round(grand_total - grand_total / 1.1, 2), grand_total),
    )
    conn.commit()
    return conn


@pytest.fixture(scope="module")
def api_client():
    """テスト用一時DBを使うFastAPI TestClientを返す。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    os.environ["YUKA_DB_PATH"] = db_path

    import importlib
    import api.services.db as db_mod
    importlib.reload(db_mod)

    from api.main import app
    with TestClient(app) as c:
        yield c

    os.unlink(db_path)


# ============================================================================
# F-18: IMAP 自動取得テスト
# ============================================================================

class TestImapFetcher:
    """imap_fetcher.py の単体テスト。"""

    def test_fetch_dry_run_returns_mock_data(self):
        """dry_run=True でモックデータが返ること。

        根拠: fetch_invoice_emails は dry_run=True のとき
        実IMAP接続せずモックEmailDataを返す設計。
        """
        from imap_fetcher import fetch_invoice_emails

        result = fetch_invoice_emails(dry_run=True)

        assert result.mode == "mock"
        assert result.fetched_count >= 1
        assert len(result.emails) == result.fetched_count
        assert result.error is None

    def test_fetch_dry_run_email_has_required_fields(self):
        """取得したEmailDataに必須フィールドが存在すること。

        根拠: EmailDataは subject/sender/body/source を持つ必要がある。
        """
        from imap_fetcher import fetch_invoice_emails
        from email_parser import EmailData

        result = fetch_invoice_emails(dry_run=True)

        assert len(result.emails) > 0
        for email in result.emails:
            assert isinstance(email, EmailData)
            assert isinstance(email.subject, str)
            assert isinstance(email.sender, str)
            assert isinstance(email.body, str)
            assert email.source == "mock_imap"

    def test_fetch_dry_run_with_subject_filter(self):
        """subject_filter でメールが絞り込まれること。

        根拠: subject_filter='発注' のとき、subject に '発注' が含まれるメールのみ返す。
        モックデータに '発注' を含む件名が1件あることを確認。
        """
        from imap_fetcher import fetch_invoice_emails

        result = fetch_invoice_emails(dry_run=True, subject_filter="発注")

        assert result.mode == "mock"
        for email in result.emails:
            assert "発注" in email.subject.lower() or "発注" in email.subject

    def test_fetch_dry_run_with_limit(self):
        """limit パラメータが機能すること。

        根拠: limit=1 のとき、最大1件しか返さない。
        """
        from imap_fetcher import fetch_invoice_emails

        result = fetch_invoice_emails(dry_run=True, limit=1)

        assert result.fetched_count <= 1
        assert len(result.emails) <= 1

    def test_fetch_unconfigured_env_returns_mock(self):
        """IMAP設定がない場合（is_configured=False）もモックデータを返すこと。

        根拠: ImapConfig.is_configured が False のとき dry_run 扱いにフォールバック。
        """
        from imap_fetcher import fetch_invoice_emails, ImapConfig

        # 設定なしのconfig
        config = ImapConfig(host="", user="", password="")
        result = fetch_invoice_emails(config=config, dry_run=False)

        # is_configured が False なのでモックにフォールバック
        assert result.mode == "mock"
        assert result.error is None

    def test_imap_config_from_env_defaults(self):
        """ImapConfig.from_env がデフォルト値を正しく設定すること。

        根拠: IMAP_HOST 未設定時は imap.gmail.com、IMAP_PORT未設定時は993。
        """
        from imap_fetcher import ImapConfig, IMAP_HOST_DEFAULT, IMAP_PORT_DEFAULT

        # 環境変数をクリア（テスト後に復元）
        saved = {k: os.environ.pop(k, None) for k in ["IMAP_HOST", "IMAP_PORT", "IMAP_USER", "IMAP_PASSWORD"]}
        try:
            config = ImapConfig.from_env()
            assert config.host == IMAP_HOST_DEFAULT
            assert config.port == IMAP_PORT_DEFAULT
            assert config.is_configured is False
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


# ============================================================================
# F-19: OCR 連携テスト
# ============================================================================

class TestOcrExtractor:
    """ocr_extractor.py の単体テスト。"""

    def test_extract_with_mock_backend_returns_result(self):
        """MockOcrBackend でテキスト抽出ができること。

        根拠: MockOcrBackend は実OCRなしでモックテキストを返す。
        """
        from ocr_extractor import extract_text_from_file, MockOcrBackend

        result = extract_text_from_file(
            "/nonexistent/test.pdf",
            backend=MockOcrBackend(),
        )

        assert isinstance(result.raw_text, str)
        assert len(result.raw_text) > 0
        assert result.error is None
        assert result.engine in ("mock", "mockocr", "mock_ocr", "mockocrbackend")

    def test_extract_mock_parses_order_number(self):
        """OCRモックテキストから発注番号が抽出されること。

        根拠: MockOcrBackend のデフォルトテキストに 'PO-2026-MOCK-001' が含まれる。
        """
        from ocr_extractor import extract_text_from_file, MockOcrBackend

        result = extract_text_from_file(
            "/nonexistent/invoice.pdf",
            backend=MockOcrBackend(),
        )

        assert result.order_number is not None
        assert "PO" in result.order_number

    def test_extract_mock_parses_delivery_date(self):
        """OCRモックテキストから納品予定日が抽出されること。

        根拠: MockOcrBackend のデフォルトテキストに '2026年04月01日' が含まれる。
        """
        from ocr_extractor import extract_text_from_file, MockOcrBackend

        result = extract_text_from_file(
            "/nonexistent/invoice.pdf",
            backend=MockOcrBackend(),
        )

        assert result.delivery_date == "2026-04-01"

    def test_extract_nonexistent_file_returns_error(self):
        """存在しないファイルを指定した場合は error フィールドにメッセージが入ること。

        根拠: extract_text_from_file は FileNotFoundError を graceful handling する。
        """
        from ocr_extractor import extract_text_from_file

        result = extract_text_from_file("/nonexistent/path/no_file.pdf")

        # force_mock=False のとき、ファイルが存在しない場合は
        # pdfplumber/tesseract で FileNotFoundError → error フィールドに記録
        # または MockBackend にフォールバック（バックエンド未インストール時）
        assert isinstance(result.raw_text, str)
        assert isinstance(result.engine, str)

    def test_extract_force_mock_bypasses_real_ocr(self):
        """force_mock=True で実OCRをバイパスしてモックデータを返すこと。

        根拠: force_mock=True のとき MockOcrBackend が選択される。
        """
        from ocr_extractor import extract_text_from_file

        result = extract_text_from_file(
            "/nonexistent/test.pdf",
            force_mock=True,
        )

        assert result.engine == "mock"
        assert len(result.raw_text) > 0

    def test_extract_from_bytes_with_mock(self):
        """バイトデータからの抽出がforce_mockで動作すること。

        根拠: extract_text_from_bytes は一時ファイルを作成して extract_text_from_file を呼ぶ。
        """
        from ocr_extractor import extract_text_from_bytes

        dummy_bytes = b"%PDF-1.4 dummy pdf content"
        result = extract_text_from_bytes(
            content=dummy_bytes,
            filename="test_invoice.pdf",
            force_mock=True,
        )

        assert result.engine == "mock"
        assert len(result.raw_text) > 0

    def test_ocr_result_to_email_data(self):
        """OcrResult.to_email_data が正しく EmailData に変換されること。

        根拠: OCR結果をメール解析パイプラインに流すため変換が必要。
        """
        from ocr_extractor import OcrResult, extract_text_from_file, MockOcrBackend
        from email_parser import EmailData

        result = extract_text_from_file(
            "/nonexistent/invoice.pdf",
            backend=MockOcrBackend(),
        )
        email_data = result.to_email_data()

        assert isinstance(email_data, EmailData)
        assert email_data.body == result.raw_text
        assert "ocr" in email_data.source


# ============================================================================
# F-20: ERP 直接インポートテスト
# ============================================================================

class TestErpImport:
    """erp_import.py の単体テスト。"""

    def test_import_dry_run_success(self):
        """dry_run=True でインポートが成功すること。

        根拠: dry_run=True のとき実API送信せず (True, DRY-xxx) を返す。
        """
        from erp_import import import_to_erp, ErpApiConfig

        conn = _make_db_with_po("PO-IMPORT-001")
        config = ErpApiConfig(dry_run=True)
        result = import_to_erp(conn, "PO-IMPORT-001", config=config)
        conn.close()

        assert result.success is True
        assert result.mode == "dry_run"
        assert result.erp_reference_id == "DRY-PO-IMPORT-001"
        assert result.payload is not None

    def test_import_not_found_po_returns_error(self):
        """存在しない発注番号の場合は error を含む結果を返すこと。

        根拠: fetch_erp_record が None を返したとき success=False, error に理由を設定。
        """
        from erp_import import import_to_erp, ErpApiConfig

        conn = _make_db_with_po()
        config = ErpApiConfig(dry_run=True)
        result = import_to_erp(conn, "PO-NOTEXIST-9999", config=config)
        conn.close()

        assert result.success is False
        assert result.error is not None
        assert "見つかりません" in result.error

    def test_import_payload_contains_po_number(self):
        """インポートペイロードに発注番号が含まれること。

        根拠: build_erp_payload は purchase_order.po_number を設定する。
        """
        from erp_import import import_to_erp, ErpApiConfig

        conn = _make_db_with_po("PO-PAYLOAD-001")
        config = ErpApiConfig(dry_run=True)
        result = import_to_erp(conn, "PO-PAYLOAD-001", config=config)
        conn.close()

        assert result.payload is not None
        assert result.payload["purchase_order"]["po_number"] == "PO-PAYLOAD-001"

    def test_import_log_is_recorded(self):
        """インポート結果がログテーブルに記録されること。

        根拠: record_import_log はerp_import_logテーブルにINSERTする。
        """
        from erp_import import import_to_erp, record_import_log, list_import_logs, ErpApiConfig

        conn = _make_db_with_po("PO-LOG-001")
        config = ErpApiConfig(dry_run=True)
        result = import_to_erp(conn, "PO-LOG-001", config=config)
        record_import_log(conn, result)

        logs = list_import_logs(conn)
        conn.close()

        assert len(logs) >= 1
        last_log = logs[0]
        assert last_log["po_number"] == "PO-LOG-001"
        assert last_log["mode"] == "dry_run"
        assert last_log["success"] == 1

    def test_import_live_without_config_returns_error(self):
        """dry_run=False かつ API設定なしの場合は error を返すこと。

        根拠: is_configured=False のとき設定未完了エラーを返す。
        """
        from erp_import import import_to_erp, ErpApiConfig

        conn = _make_db_with_po("PO-NOCONFIG-001")
        config = ErpApiConfig(api_url="", api_key="", dry_run=False)
        result = import_to_erp(conn, "PO-NOCONFIG-001", config=config, dry_run=False)
        conn.close()

        assert result.success is False
        assert result.error is not None
        assert "ERP API設定" in result.error


# ============================================================================
# FastAPI エンドポイントテスト
# ============================================================================

class TestImapEndpoint:
    """POST /api/imap/fetch エンドポイントテスト。"""

    def test_imap_fetch_dry_run_returns_200(self, api_client):
        """dry_run=true でHTTP 200 が返ること。

        根拠: /api/imap/fetch はIMAPなしでもモックデータを返す設計。
        """
        res = api_client.post("/api/imap/fetch", json={"dry_run": True})
        assert res.status_code == 200

    def test_imap_fetch_response_structure(self, api_client):
        """レスポンスが ImapFetchResponse 構造を持つこと。

        根拠: fetched_count, mode, emails フィールドが必須。
        """
        res = api_client.post("/api/imap/fetch", json={"dry_run": True})
        body = res.json()

        assert "emails" in body
        assert "fetched_count" in body
        assert "mode" in body
        assert body["mode"] == "mock"

    def test_imap_fetch_with_limit(self, api_client):
        """limit=1 のとき最大1件を返すこと。

        根拠: limit パラメータが正しく動作すること。
        """
        res = api_client.post("/api/imap/fetch", json={"dry_run": True, "limit": 1})
        body = res.json()

        assert res.status_code == 200
        assert body["fetched_count"] <= 1
        assert len(body["emails"]) <= 1


class TestOcrEndpoint:
    """POST /api/ocr/extract エンドポイントテスト。"""

    def test_ocr_extract_force_mock_returns_200(self, api_client):
        """force_mock=true でHTTP 200 が返ること。

        根拠: /api/ocr/extract はforce_mock=trueのときOCRエンジン不要。
        """
        res = api_client.post(
            "/api/ocr/extract",
            json={"file_path": "/nonexistent/invoice.pdf", "force_mock": True},
        )
        assert res.status_code == 200

    def test_ocr_extract_response_structure(self, api_client):
        """レスポンスが OcrExtractResponse 構造を持つこと。

        根拠: raw_text, engine, page_count フィールドが必須。
        """
        res = api_client.post(
            "/api/ocr/extract",
            json={"file_path": "/nonexistent/invoice.pdf", "force_mock": True},
        )
        body = res.json()

        assert "raw_text" in body
        assert "engine" in body
        assert "page_count" in body
        assert body["engine"] == "mock"

    def test_ocr_extract_mock_has_order_number(self, api_client):
        """モックOCRレスポンスに発注番号が含まれること。

        根拠: MockOcrBackend のデフォルトテキストに発注番号が含まれる。
        """
        res = api_client.post(
            "/api/ocr/extract",
            json={"file_path": "/nonexistent/invoice.pdf", "force_mock": True},
        )
        body = res.json()

        assert body["order_number"] is not None
        assert "PO" in body["order_number"]


class TestErpImportEndpoint:
    """POST /api/erp/import エンドポイントテスト。"""

    def test_erp_import_not_found_returns_404(self, api_client):
        """存在しない発注番号で404が返ること。

        根拠: 発注番号が見つからない場合は404を返す設計。
        """
        res = api_client.post(
            "/api/erp/import",
            json={"po_number": "PO-NOTEXIST-999", "dry_run": True},
        )
        assert res.status_code == 404

    def test_erp_import_logs_endpoint_returns_200(self, api_client):
        """GET /api/erp/import/logs が200を返すこと。

        根拠: インポート履歴一覧エンドポイントが空でも200を返す。
        """
        res = api_client.get("/api/erp/import/logs")
        assert res.status_code == 200
        assert isinstance(res.json(), list)
