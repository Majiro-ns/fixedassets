"""tests/test_procurement_approval.py

T010: 発注承認・却下ワークフロー API のテスト

【検証対象】
  1. POST /api/procurement/approve/{order_id}   — 承認
  2. POST /api/procurement/reject/{order_id}    — 却下
  3. GET  /api/procurement/orders/history       — 全履歴

【設計方針】
  - approval_requests テーブルは schema.sql に含まれないため、テストで直接作成
  - approve/reject は status='pending' のレコードのみ更新可（それ以外は 404）
  - orders/history はテーブル未存在でも 200 を返す（graceful degradation）
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ============================================================
# テスト用ヘルパー
# ============================================================

def _make_client(db_path: str) -> TestClient:
    os.environ["YUKA_DB_PATH"] = db_path
    from importlib import reload
    import api.services.db as db_mod
    reload(db_mod)
    import api.routers.procurement as proc_mod
    reload(proc_mod)
    import api.main as main_mod
    reload(main_mod)
    from api.main import app
    return TestClient(app)


def _setup_db(db_path: str):
    """スキーマ初期化 + approval_requests テーブル作成 + テストデータ投入。"""
    schema_path = Path(__file__).parent.parent / "schema.sql"
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    # approval_requests テーブルは schema.sql に含まれないため手動作成
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number TEXT NOT NULL,
            requester TEXT NOT NULL DEFAULT 'system',
            reason TEXT DEFAULT '',
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            requested_at TEXT DEFAULT (datetime('now','localtime')),
            resolved_at TEXT,
            resolver TEXT,
            comment TEXT
        )
        """
    )
    # テストデータ: pending 2件、approved 1件、rejected 1件
    conn.execute(
        "INSERT INTO approval_requests (po_number, requester, reason, amount, status) "
        "VALUES ('PO-A001', 'system', '在庫補充', 50000.0, 'pending')"
    )
    conn.execute(
        "INSERT INTO approval_requests (po_number, requester, reason, amount, status) "
        "VALUES ('PO-A002', 'user1', '緊急発注', 120000.0, 'pending')"
    )
    conn.execute(
        "INSERT INTO approval_requests (po_number, requester, reason, amount, status) "
        "VALUES ('PO-A003', 'system', '定期発注', 30000.0, 'approved')"
    )
    conn.execute(
        "INSERT INTO approval_requests (po_number, requester, reason, amount, status) "
        "VALUES ('PO-A004', 'system', '予算超過', 200000.0, 'rejected')"
    )
    conn.commit()
    conn.close()


def _setup_empty_db(db_path: str):
    """approval_requests テーブルなしの空 DB（graceful degradation テスト用）。"""
    schema_path = Path(__file__).parent.parent / "schema.sql"
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()


# ============================================================
# API テスト: POST /api/procurement/approve/{order_id}
# ============================================================

class TestApproveEndpoint:

    def test_approve_pending_returns_200(self, tmp_path):
        """pending の発注を承認すると 200 と approved ステータスが返る。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post("/api/procurement/approve/1")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "approved"
        assert data["order_id"] == 1
        assert "approved_at" in data
        assert data["approved_at"] != ""

    def test_approve_updates_db_status(self, tmp_path):
        """承認後、DBの status が 'approved' に変わっている。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        client.post("/api/procurement/approve/1")
        # DBを直接確認
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT status, resolved_at FROM approval_requests WHERE id=1"
        ).fetchone()
        conn.close()
        assert row[0] == "approved"
        assert row[1] is not None  # resolved_at が設定されている

    def test_approve_already_approved_returns_404(self, tmp_path):
        """すでに approved のレコードを再承認しようとすると 404 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        # id=3 は既に approved
        res = client.post("/api/procurement/approve/3")
        assert res.status_code == 404

    def test_approve_nonexistent_id_returns_404(self, tmp_path):
        """存在しない order_id を承認しようとすると 404 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post("/api/procurement/approve/9999")
        assert res.status_code == 404

    def test_approve_rejected_returns_404(self, tmp_path):
        """rejected 済みのレコードを承認しようとすると 404 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        # id=4 は既に rejected
        res = client.post("/api/procurement/approve/4")
        assert res.status_code == 404


# ============================================================
# API テスト: POST /api/procurement/reject/{order_id}
# ============================================================

class TestRejectEndpoint:

    def test_reject_pending_returns_200(self, tmp_path):
        """pending の発注を却下すると 200 と rejected ステータスが返る。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post(
            "/api/procurement/reject/2",
            json={"reason": "予算超過のため"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "rejected"
        assert data["order_id"] == 2
        assert data["reason"] == "予算超過のため"
        assert "rejected_at" in data
        assert data["rejected_at"] != ""

    def test_reject_without_reason_returns_200(self, tmp_path):
        """reason 省略（空文字）でも 200 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post("/api/procurement/reject/1", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "rejected"
        assert data["reason"] == ""

    def test_reject_updates_db_status(self, tmp_path):
        """却下後、DBの status が 'rejected' に変わっている。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        client.post("/api/procurement/reject/1", json={"reason": "テスト却下"})
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT status, comment FROM approval_requests WHERE id=1"
        ).fetchone()
        conn.close()
        assert row[0] == "rejected"
        assert row[1] == "テスト却下"

    def test_reject_nonexistent_id_returns_404(self, tmp_path):
        """存在しない order_id を却下しようとすると 404 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post("/api/procurement/reject/9999", json={"reason": "不明"})
        assert res.status_code == 404

    def test_reject_already_approved_returns_404(self, tmp_path):
        """すでに approved のレコードを却下しようとすると 404 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        # id=3 は既に approved
        res = client.post("/api/procurement/reject/3", json={"reason": "後から却下不可"})
        assert res.status_code == 404


# ============================================================
# API テスト: GET /api/procurement/orders/history
# ============================================================

class TestOrdersHistoryEndpoint:

    def test_returns_200_with_all_statuses(self, tmp_path):
        """全ステータスのレコードが返る（pending/approved/rejected）。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/procurement/orders/history")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert "count" in data
        # 4件投入 → 4件返る
        assert data["count"] == 4

    def test_returns_all_required_fields(self, tmp_path):
        """各アイテムに必須フィールドが含まれる。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/procurement/orders/history")
        for item in res.json()["items"]:
            assert "id" in item
            assert "po_number" in item
            assert "status" in item
            assert "amount" in item

    def test_returns_descending_order(self, tmp_path):
        """id 降順でソートされる（最新が先頭）。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/procurement/orders/history")
        items = res.json()["items"]
        ids = [item["id"] for item in items]
        assert ids == sorted(ids, reverse=True)

    def test_empty_table_returns_200(self, tmp_path):
        """approval_requests テーブルが空でも 200 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        # テーブルはあるがレコードなし
        schema_path = Path(__file__).parent.parent / "schema.sql"
        conn = sqlite3.connect(db_path)
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_number TEXT NOT NULL,
                requester TEXT NOT NULL DEFAULT 'system',
                reason TEXT DEFAULT '',
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                requested_at TEXT DEFAULT (datetime('now','localtime')),
                resolved_at TEXT,
                resolver TEXT,
                comment TEXT
            )
            """
        )
        conn.commit()
        conn.close()
        client = _make_client(db_path)
        res = client.get("/api/procurement/orders/history")
        assert res.status_code == 200
        assert res.json()["count"] == 0

    def test_no_table_returns_200_empty(self, tmp_path):
        """approval_requests テーブルが存在しなくても 200 と空リストを返す（graceful degradation）。"""
        db_path = str(tmp_path / "yuka_notbl.db")
        _setup_empty_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/procurement/orders/history")
        assert res.status_code == 200
        assert res.json()["items"] == []

    def test_history_reflects_approved_status(self, tmp_path):
        """承認操作後、history に approved ステータスで反映される。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        # id=1 を承認
        client.post("/api/procurement/approve/1")
        res = client.get("/api/procurement/orders/history")
        items = res.json()["items"]
        item1 = next(i for i in items if i["id"] == 1)
        assert item1["status"] == "approved"
