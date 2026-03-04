"""tests/test_suppliers.py
==============================
T008: サプライヤー比較・最安値探索テスト

【検証対象】
  1. supplier_service.get_supplier_list()             — DB から登録サプライヤーを返す
  2. supplier_service.get_supplier_price_comparison() — サプライヤー別最新価格比較
  3. supplier_service.get_cheapest_supplier()         — 最安値サプライヤー抽出
  4. GET /api/suppliers/list                          — API エンドポイント
  5. GET /api/suppliers/compare/{part_number}         — API エンドポイント
  6. GET /api/suppliers/cheapest/{part_number}        — API エンドポイント
  7. compare: 部品未登録 → 404
  8. cheapest: 価格データなし → 404
  9. compare: 複数サプライヤーの価格順（最安値が先頭、is_cheapest=True）

CHECK-9 根拠:
  - TC-S1: suppliers テーブルに2件登録 → /list が count=2 を返す
  - TC-S2: 同部品に2サプライヤーが価格登録 → compare が2件返し最安値をハイライト
  - TC-S3: cheapest が最安値サプライヤーを返す
  - TC-S4: 最新価格のみ取得（古い価格は反映されない）
  - TC-S5: 部品未登録 → compare が 404
  - TC-S6: 価格データなし（部品のみ）→ cheapest が 404
  - TC-S7: source のみ（supplier_id なし）のレコードも比較対象となる
  - TC-S8: 複数価格履歴がある場合、最新（max id）の価格を使用する
  - TC-S9: /list が空の場合、count=0 かつ suppliers=[] を返す

作成: 足軽6 cmd_285k_yukaai_T008
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ─── DB / クライアント初期化ヘルパー ────────────────────────────────────────────

SCHEMA_PATH = Path(__file__).parent.parent / "schema.sql"


def _make_client(db_path: str) -> TestClient:
    """一時 DB を指定して TestClient を生成する。"""
    os.environ["YUKA_DB_PATH"] = db_path
    from importlib import reload
    import api.services.db as db_mod
    reload(db_mod)
    import api.services.supplier_service as svc_mod
    reload(svc_mod)
    import api.routers.suppliers as sup_mod
    reload(sup_mod)
    import api.main as main_mod
    reload(main_mod)
    from api.main import app
    return TestClient(app)


def _init_db(db_path: str) -> sqlite3.Connection:
    """スキーマのみ初期化した DB 接続を返す。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def _seed_suppliers(conn: sqlite3.Connection) -> tuple[int, int]:
    """テスト用サプライヤー2件を追加し、(id_a, id_b) を返す。"""
    conn.execute(
        "INSERT INTO suppliers (name, code) VALUES ('ミスミ', 'MISUMI')"
    )
    conn.execute(
        "INSERT INTO suppliers (name, code) VALUES ('モノタロウ', 'MONO')"
    )
    conn.commit()
    id_a = conn.execute("SELECT id FROM suppliers WHERE code='MISUMI'").fetchone()["id"]
    id_b = conn.execute("SELECT id FROM suppliers WHERE code='MONO'").fetchone()["id"]
    return id_a, id_b


def _seed_part(conn: sqlite3.Connection, part_number: str = "TEST-001") -> int:
    """テスト用部品を追加し part_id を返す。"""
    conn.execute(
        "INSERT INTO parts (part_number, description, category) VALUES (?, ?, ?)",
        (part_number, "テスト部品", "テスト"),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM parts WHERE part_number=?", (part_number,)
    ).fetchone()["id"]


# ─── TC-S1: GET /api/suppliers/list ─────────────────────────────────────────────

class TestSupplierList:
    """GET /api/suppliers/list のテスト"""

    def test_list_returns_registered_suppliers(self, tmp_path):
        """TC-S1: 登録サプライヤー2件が正しく返される。

        根拠: suppliers テーブルに2件 INSERT → count=2, name に MISUMI/MONO を含む。
        """
        db_path = str(tmp_path / "test.db")
        conn = _init_db(db_path)
        _seed_suppliers(conn)
        conn.close()

        client = _make_client(db_path)
        resp = client.get("/api/suppliers/list")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        names = {s["name"] for s in body["suppliers"]}
        assert "ミスミ" in names
        assert "モノタロウ" in names

    def test_list_empty_when_no_suppliers(self, tmp_path):
        """TC-S9: サプライヤー未登録の場合、count=0 かつ suppliers=[] を返す。

        根拠: suppliers テーブルが空 → count=0。
        """
        db_path = str(tmp_path / "test.db")
        _init_db(db_path).close()

        client = _make_client(db_path)
        resp = client.get("/api/suppliers/list")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["suppliers"] == []


# ─── TC-S2, TC-S4: GET /api/suppliers/compare/{part_number} ─────────────────────

class TestSupplierCompare:
    """GET /api/suppliers/compare/{part_number} のテスト"""

    def test_compare_two_suppliers_highlights_cheapest(self, tmp_path):
        """TC-S2: 2サプライヤーの比較で最安値（is_cheapest=True）が先頭に来る。

        根拠:
          - ミスミ: 1000円, モノタロウ: 800円
          - compare 結果: suppliers[0].supplier_name == "モノタロウ"（800円）
          - suppliers[0].is_cheapest == True
          - cheapest_price == 800
        """
        db_path = str(tmp_path / "test.db")
        conn = _init_db(db_path)
        sid_a, sid_b = _seed_suppliers(conn)
        part_id = _seed_part(conn)

        conn.execute(
            "INSERT INTO price_history (part_id, supplier_id, price, source) VALUES (?,?,?,?)",
            (part_id, sid_a, 1000.0, "misumi"),
        )
        conn.execute(
            "INSERT INTO price_history (part_id, supplier_id, price, source) VALUES (?,?,?,?)",
            (part_id, sid_b, 800.0, "monotaro"),
        )
        conn.commit()
        conn.close()

        client = _make_client(db_path)
        resp = client.get("/api/suppliers/compare/TEST-001")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["suppliers"]) == 2
        assert body["cheapest_price"] == pytest.approx(800.0)
        assert body["cheapest_supplier"] == "モノタロウ"
        # 先頭が最安値
        first = body["suppliers"][0]
        assert first["is_cheapest"] is True
        assert first["latest_price"] == pytest.approx(800.0)
        # 2番目は is_cheapest=False
        assert body["suppliers"][1]["is_cheapest"] is False

    def test_compare_uses_latest_price_only(self, tmp_path):
        """TC-S4: 同一サプライヤーに複数履歴がある場合、最新（最大 id）の価格のみ使用。

        根拠:
          - ミスミに 1200円（古）と 900円（新）を登録
          - compare 結果: ミスミの latest_price == 900
        """
        db_path = str(tmp_path / "test.db")
        conn = _init_db(db_path)
        sid_a, _ = _seed_suppliers(conn)
        part_id = _seed_part(conn)

        # 古い価格
        conn.execute(
            "INSERT INTO price_history (part_id, supplier_id, price, source, fetched_at)"
            " VALUES (?,?,?,?,?)",
            (part_id, sid_a, 1200.0, "misumi", "2026-01-01T10:00:00"),
        )
        # 新しい価格（id が大きい）
        conn.execute(
            "INSERT INTO price_history (part_id, supplier_id, price, source, fetched_at)"
            " VALUES (?,?,?,?,?)",
            (part_id, sid_a, 900.0, "misumi", "2026-02-01T10:00:00"),
        )
        conn.commit()
        conn.close()

        client = _make_client(db_path)
        resp = client.get("/api/suppliers/compare/TEST-001")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["suppliers"]) == 1
        assert body["suppliers"][0]["latest_price"] == pytest.approx(900.0)
        assert body["cheapest_price"] == pytest.approx(900.0)

    def test_compare_includes_source_only_records(self, tmp_path):
        """TC-S7: supplier_id なし・source のみのレコードも比較対象に含まれる。

        根拠:
          - price_tracker.py は supplier_id を設定しない（source のみ）
          - compare 結果: source='askul' のレコードも suppliers に含まれる
        """
        db_path = str(tmp_path / "test.db")
        conn = _init_db(db_path)
        _seed_suppliers(conn)  # テーブル存在確認のみ
        part_id = _seed_part(conn)

        # supplier_id なし（price_tracker.py パターン）
        conn.execute(
            "INSERT INTO price_history (part_id, supplier_id, price, source) VALUES (?,?,?,?)",
            (part_id, None, 750.0, "askul"),
        )
        conn.commit()
        conn.close()

        client = _make_client(db_path)
        resp = client.get("/api/suppliers/compare/TEST-001")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["suppliers"]) == 1
        assert body["suppliers"][0]["supplier_name"] == "askul"
        assert body["suppliers"][0]["latest_price"] == pytest.approx(750.0)

    def test_compare_not_found_returns_404(self, tmp_path):
        """TC-S5: 未登録部品番号 → 404 を返す。

        根拠: parts テーブルに 'UNKNOWN-999' が存在しない → service が None を返す
              → router が HTTPException(404) を送出。
        """
        db_path = str(tmp_path / "test.db")
        _init_db(db_path).close()

        client = _make_client(db_path)
        resp = client.get("/api/suppliers/compare/UNKNOWN-999")

        assert resp.status_code == 404


# ─── TC-S3, TC-S6: GET /api/suppliers/cheapest/{part_number} ────────────────────

class TestSupplierCheapest:
    """GET /api/suppliers/cheapest/{part_number} のテスト"""

    def test_cheapest_returns_lowest_price_supplier(self, tmp_path):
        """TC-S3: 2サプライヤーのうち最安値を返す。

        根拠:
          - ミスミ: 1000円, モノタロウ: 700円
          - cheapest の supplier_name == "モノタロウ", latest_price == 700
        """
        db_path = str(tmp_path / "test.db")
        conn = _init_db(db_path)
        sid_a, sid_b = _seed_suppliers(conn)
        part_id = _seed_part(conn)

        conn.execute(
            "INSERT INTO price_history (part_id, supplier_id, price, source) VALUES (?,?,?,?)",
            (part_id, sid_a, 1000.0, "misumi"),
        )
        conn.execute(
            "INSERT INTO price_history (part_id, supplier_id, price, source) VALUES (?,?,?,?)",
            (part_id, sid_b, 700.0, "monotaro"),
        )
        conn.commit()
        conn.close()

        client = _make_client(db_path)
        resp = client.get("/api/suppliers/cheapest/TEST-001")

        assert resp.status_code == 200
        body = resp.json()
        assert body["supplier_name"] == "モノタロウ"
        assert body["latest_price"] == pytest.approx(700.0)
        assert body["part_number"] == "TEST-001"

    def test_cheapest_no_price_data_returns_404(self, tmp_path):
        """TC-S6: 部品は登録済みだが価格データなし → 404 を返す。

        根拠: price_history に該当部品のレコードなし → service が None を返す
              → router が HTTPException(404) を送出。
        """
        db_path = str(tmp_path / "test.db")
        conn = _init_db(db_path)
        _seed_part(conn)
        conn.close()

        client = _make_client(db_path)
        resp = client.get("/api/suppliers/cheapest/TEST-001")

        assert resp.status_code == 404

    def test_cheapest_multiple_sources_returns_lowest(self, tmp_path):
        """TC-S8: source のみ3件から最安値を選択する。

        根拠:
          - monotaro: 500, misumi: 800, askul: 650
          - cheapest == monotaro (500)
        """
        db_path = str(tmp_path / "test.db")
        conn = _init_db(db_path)
        _seed_suppliers(conn)
        part_id = _seed_part(conn)

        for src, price in [("monotaro", 500.0), ("misumi", 800.0), ("askul", 650.0)]:
            conn.execute(
                "INSERT INTO price_history (part_id, supplier_id, price, source) VALUES (?,?,?,?)",
                (part_id, None, price, src),
            )
        conn.commit()
        conn.close()

        client = _make_client(db_path)
        resp = client.get("/api/suppliers/cheapest/TEST-001")

        assert resp.status_code == 200
        body = resp.json()
        assert body["supplier_name"] == "monotaro"
        assert body["latest_price"] == pytest.approx(500.0)
