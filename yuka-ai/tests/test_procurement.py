"""tests/test_procurement.py

T007: 発注自動化ワークフローのテスト

【検証対象】
  1. procurement_service.filter_low_stock() — 純粋関数ユニットテスト
  2. procurement_service.build_auto_order_candidates() — 純粋関数ユニットテスト
  3. GET  /api/procurement/low-stock       — API エンドポイント
  4. POST /api/procurement/auto-order-candidates — API エンドポイント
  5. GET  /api/procurement/pending-approvals — API エンドポイント

【設計方針】
  - procurement_service は DB 不要の純粋関数 → 直接テスト
  - API テストは TestClient + 一時 DB（既存パターン準拠）
  - approval_requests テーブルが存在しない場合も pending-approvals は 200 を返すこと
"""
from __future__ import annotations

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from api.services.procurement_service import (
    filter_low_stock,
    build_auto_order_candidates,
)


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
    """テスト用 DB を初期化し、部品と在庫データを投入する。"""
    import sqlite3
    from pathlib import Path
    schema_path = Path(__file__).parent.parent / "schema.sql"
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    # サプライヤー
    conn.execute(
        "INSERT OR IGNORE INTO suppliers (name, code) VALUES ('テストサプライヤー', 'TEST')"
    )
    # 部品 3 件
    conn.execute(
        "INSERT OR IGNORE INTO parts (part_number, description, category) VALUES "
        "('P-001', 'ボルト M6', 'ボルト')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO parts (part_number, description, category) VALUES "
        "('P-002', 'ナット M6', 'ナット')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO parts (part_number, description, category) VALUES "
        "('P-003', '六角レンチ', '工具')"
    )
    # 在庫: P-001 は在庫少（3 < 10）、P-002 は十分（15 >= 10）、P-003 は inventory なし
    conn.execute(
        "INSERT OR IGNORE INTO inventory (part_id, current_stock, reorder_point) "
        "SELECT id, 3, 10 FROM parts WHERE part_number='P-001'"
    )
    conn.execute(
        "INSERT OR IGNORE INTO inventory (part_id, current_stock, reorder_point) "
        "SELECT id, 15, 10 FROM parts WHERE part_number='P-002'"
    )
    # P-001 に価格履歴（底値圏: BUY_NOW になる条件）
    conn.execute(
        "INSERT INTO price_history (part_id, price, source) "
        "SELECT id, 100, 'manual' FROM parts WHERE part_number='P-001'"
    )
    conn.execute(
        "INSERT INTO price_history (part_id, price, source) "
        "SELECT id, 102, 'manual' FROM parts WHERE part_number='P-001'"
    )
    conn.execute(
        "INSERT INTO price_history (part_id, price, source) "
        "SELECT id, 101, 'manual' FROM parts WHERE part_number='P-001'"
    )
    conn.commit()
    conn.close()


# ============================================================
# ユニットテスト: filter_low_stock
# ============================================================

class TestFilterLowStock:
    """filter_low_stock() の純粋関数テスト"""

    def test_returns_only_low_stock(self):
        """current_stock < reorder_point の行のみ返す。"""
        rows = [
            {"part_number": "A", "description": "A部品", "category": None,
             "current_stock": 3, "reorder_point": 10},
            {"part_number": "B", "description": "B部品", "category": None,
             "current_stock": 15, "reorder_point": 10},
        ]
        result = filter_low_stock(rows)
        assert len(result) == 1
        assert result[0]["part_number"] == "A"

    def test_shortage_is_computed(self):
        """shortage = reorder_point - current_stock が付与される。"""
        rows = [
            {"part_number": "A", "description": "A", "category": None,
             "current_stock": 2, "reorder_point": 10}
        ]
        result = filter_low_stock(rows)
        assert result[0]["shortage"] == 8

    def test_empty_input_returns_empty(self):
        """空リストを渡すと空リストが返る。"""
        assert filter_low_stock([]) == []

    def test_exactly_at_reorder_point_is_not_low(self):
        """current_stock == reorder_point はアラート対象外。"""
        rows = [
            {"part_number": "A", "description": "A", "category": None,
             "current_stock": 10, "reorder_point": 10}
        ]
        assert filter_low_stock(rows) == []


# ============================================================
# ユニットテスト: build_auto_order_candidates
# ============================================================

class TestBuildAutoOrderCandidates:
    """build_auto_order_candidates() の純粋関数テスト"""

    def _low_stock_row(self, pn: str) -> dict:
        return {
            "part_number": pn, "description": f"{pn}部品", "category": None,
            "current_stock": 3, "reorder_point": 10, "shortage": 7,
        }

    def test_only_buy_now_parts_included(self):
        """BUY_NOW のみ候補に含まれる。WAIT/NEUTRAL は除外。"""
        low_stock = [self._low_stock_row("A"), self._low_stock_row("B"), self._low_stock_row("C")]
        recs = {
            "A": {"action": "BUY_NOW", "reason": "底値圏", "score": 85.0,
                  "current_price": 100.0, "avg_price": 110.0, "trend_pct": -5.0},
            "B": {"action": "WAIT", "reason": "下落中", "score": 25.0,
                  "current_price": 90.0, "avg_price": 100.0, "trend_pct": -8.0},
            "C": {"action": "NEUTRAL", "reason": "安定", "score": 50.0,
                  "current_price": 100.0, "avg_price": 100.0, "trend_pct": 0.0},
        }
        result = build_auto_order_candidates(low_stock, recs)
        assert len(result) == 1
        assert result[0]["part_number"] == "A"

    def test_sorted_by_score_descending(self):
        """score 降順でソートされる。"""
        low_stock = [self._low_stock_row("A"), self._low_stock_row("B")]
        recs = {
            "A": {"action": "BUY_NOW", "reason": "r", "score": 70.0,
                  "current_price": 100.0, "avg_price": 110.0, "trend_pct": 5.0},
            "B": {"action": "BUY_NOW", "reason": "r", "score": 90.0,
                  "current_price": 100.0, "avg_price": 110.0, "trend_pct": 8.0},
        }
        result = build_auto_order_candidates(low_stock, recs)
        assert result[0]["part_number"] == "B"  # score=90 が先
        assert result[1]["part_number"] == "A"

    def test_empty_low_stock_returns_empty(self):
        """在庫不足がなければ候補は空。"""
        assert build_auto_order_candidates([], {}) == []

    def test_no_recommendation_for_part_is_excluded(self):
        """recommendations に含まれない部品は候補から除外（NEUTRAL 扱い）。"""
        low_stock = [self._low_stock_row("UNKNOWN")]
        result = build_auto_order_candidates(low_stock, {})
        assert result == []


# ============================================================
# API テスト: GET /api/procurement/low-stock
# ============================================================

class TestLowStockEndpoint:
    """GET /api/procurement/low-stock のエンドポイントテスト"""

    def test_returns_200_with_low_stock_items(self, tmp_path):
        """在庫不足品番が返る。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/procurement/low-stock")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert "count" in data
        # P-001 (stock=3 < reorder=10) が含まれる
        part_numbers = [item["part_number"] for item in data["items"]]
        assert "P-001" in part_numbers

    def test_sufficient_stock_not_included(self, tmp_path):
        """十分な在庫（P-002: 15>=10）はアラート対象外。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/procurement/low-stock")
        data = res.json()
        part_numbers = [item["part_number"] for item in data["items"]]
        assert "P-002" not in part_numbers

    def test_shortage_field_present(self, tmp_path):
        """shortage フィールドが各アイテムに含まれる。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/procurement/low-stock")
        for item in res.json()["items"]:
            assert "shortage" in item
            assert item["shortage"] >= 1


# ============================================================
# API テスト: POST /api/procurement/auto-order-candidates
# ============================================================

class TestAutoOrderCandidatesEndpoint:
    """POST /api/procurement/auto-order-candidates のエンドポイントテスト"""

    def test_returns_200(self, tmp_path):
        """正常系: 200 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post("/api/procurement/auto-order-candidates")
        assert res.status_code == 200

    def test_response_has_candidates_and_count(self, tmp_path):
        """レスポンスに candidates と count が含まれる。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post("/api/procurement/auto-order-candidates")
        data = res.json()
        assert "candidates" in data
        assert "count" in data
        assert data["count"] == len(data["candidates"])

    def test_candidates_are_buy_now_only(self, tmp_path):
        """候補の action は全て BUY_NOW。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post("/api/procurement/auto-order-candidates")
        for cand in res.json()["candidates"]:
            assert cand["action"] == "BUY_NOW"

    def test_empty_db_returns_empty_candidates(self, tmp_path):
        """部品が登録されていなければ候補は空。"""
        db_path = str(tmp_path / "yuka_empty.db")
        # 空の DB（schema だけ）
        import sqlite3
        from pathlib import Path
        schema_path = Path(__file__).parent.parent / "schema.sql"
        conn = sqlite3.connect(db_path)
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        client = _make_client(db_path)
        res = client.post("/api/procurement/auto-order-candidates")
        assert res.status_code == 200
        assert res.json()["count"] == 0


# ============================================================
# API テスト: GET /api/procurement/pending-approvals
# ============================================================

class TestPendingApprovalsEndpoint:
    """GET /api/procurement/pending-approvals のエンドポイントテスト"""

    def test_returns_200_even_without_approval_table(self, tmp_path):
        """approval_requests テーブルがなくても 200 を返す（graceful degradation）。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/procurement/pending-approvals")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert data["count"] == len(data["items"])

    def test_returns_pending_approvals_when_table_exists(self, tmp_path):
        """approval_requests テーブルがあれば pending 行を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        # approval_requests テーブルを手動作成して pending レコードを投入
        import sqlite3
        conn = sqlite3.connect(db_path)
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
        conn.execute(
            "INSERT INTO approval_requests (po_number, requester, reason, amount, status) "
            "VALUES ('PO-9001', 'system', 'テスト', 150000.0, 'pending')"
        )
        conn.execute(
            "INSERT INTO approval_requests (po_number, requester, reason, amount, status) "
            "VALUES ('PO-9002', 'system', '承認済み', 80000.0, 'approved')"
        )
        conn.commit()
        conn.close()
        client = _make_client(db_path)
        res = client.get("/api/procurement/pending-approvals")
        assert res.status_code == 200
        data = res.json()
        # pending は 1 件のみ（approved は含まれない）
        assert data["count"] == 1
        assert data["items"][0]["po_number"] == "PO-9001"
        assert data["items"][0]["status"] == "pending"
