"""tests/test_reports.py

T009: 月次コスト分析レポート生成のテスト

【検証対象】
  1. report_service.aggregate_monthly_cost() — 純粋関数ユニットテスト
  2. report_service.build_cost_trend()       — 純粋関数ユニットテスト
  3. report_service.serialize_to_csv()       — 純粋関数ユニットテスト
  4. GET  /api/reports/monthly-cost          — API エンドポイント
  5. GET  /api/reports/cost-trend            — API エンドポイント
  6. POST /api/reports/export/csv            — API エンドポイント

【設計方針】
  - report_service は DB 不要の純粋関数 → 直接テスト
  - API テストは TestClient + 一時 DB（既存パターン準拠）
  - 発注明細が存在しない場合も 200 を返すこと（graceful degradation）
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.services.report_service import (
    aggregate_monthly_cost,
    build_cost_trend,
    serialize_to_csv,
)


# ============================================================
# テスト用ヘルパー
# ============================================================

def _make_client(db_path: str) -> TestClient:
    os.environ["YUKA_DB_PATH"] = db_path
    from importlib import reload
    import api.services.db as db_mod
    reload(db_mod)
    import api.routers.reports as rpt_mod
    reload(rpt_mod)
    import api.main as main_mod
    reload(main_mod)
    from api.main import app
    return TestClient(app)


def _setup_db(db_path: str):
    """テスト用 DB を初期化し、発注書と発注明細データを投入する。"""
    schema_path = Path(__file__).parent.parent / "schema.sql"
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    # サプライヤー
    conn.execute(
        "INSERT OR IGNORE INTO suppliers (name, code) VALUES ('テストサプライヤー', 'TEST')"
    )
    # 部品
    conn.execute(
        "INSERT OR IGNORE INTO parts (part_number, description, category) VALUES "
        "('P-001', 'ボルト M6', 'ボルト')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO parts (part_number, description, category) VALUES "
        "('P-002', 'ナット M6', 'ナット')"
    )
    # 発注書: 2026-03 (2件)、2026-02 (1件)
    conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, issue_date, grand_total) "
        "VALUES ('PO-001', 1, 'confirmed', '2026-03-01', 10000.0)"
    )
    conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, issue_date, grand_total) "
        "VALUES ('PO-002', 1, 'confirmed', '2026-03-15', 5000.0)"
    )
    conn.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, issue_date, grand_total) "
        "VALUES ('PO-003', 1, 'confirmed', '2026-02-10', 3000.0)"
    )
    # 発注明細: PO-001 (P-001: 10個 × 500円 = 5000円、P-002: 5個 × 1000円 = 5000円)
    # PO-002 (P-001: 5個 × 500円 = 2500円、P-002: 5個 × 500円 = 2500円)
    # PO-003 (P-001: 10個 × 300円 = 3000円)
    conn.execute(
        "INSERT INTO purchase_order_items "
        "(po_id, item_no, part_number, description, quantity, unit_price, subtotal) "
        "SELECT id, 1, 'P-001', 'ボルト M6', 10, 500.0, 5000.0 FROM purchase_orders WHERE po_number='PO-001'"
    )
    conn.execute(
        "INSERT INTO purchase_order_items "
        "(po_id, item_no, part_number, description, quantity, unit_price, subtotal) "
        "SELECT id, 2, 'P-002', 'ナット M6', 5, 1000.0, 5000.0 FROM purchase_orders WHERE po_number='PO-001'"
    )
    conn.execute(
        "INSERT INTO purchase_order_items "
        "(po_id, item_no, part_number, description, quantity, unit_price, subtotal) "
        "SELECT id, 1, 'P-001', 'ボルト M6', 5, 500.0, 2500.0 FROM purchase_orders WHERE po_number='PO-002'"
    )
    conn.execute(
        "INSERT INTO purchase_order_items "
        "(po_id, item_no, part_number, description, quantity, unit_price, subtotal) "
        "SELECT id, 2, 'P-002', 'ナット M6', 5, 500.0, 2500.0 FROM purchase_orders WHERE po_number='PO-002'"
    )
    conn.execute(
        "INSERT INTO purchase_order_items "
        "(po_id, item_no, part_number, description, quantity, unit_price, subtotal) "
        "SELECT id, 1, 'P-001', 'ボルト M6', 10, 300.0, 3000.0 FROM purchase_orders WHERE po_number='PO-003'"
    )
    conn.commit()
    conn.close()


# ─── テストデータ（純粋関数テスト用）──────────────────────────────────────────

_ROWS = [
    # 2026-03: P-001 2行、P-002 2行
    {"part_number": "P-001", "description": "ボルト", "quantity": 10,
     "unit_price": 500.0, "subtotal": 5000.0, "year_month": "2026-03"},
    {"part_number": "P-002", "description": "ナット", "quantity": 5,
     "unit_price": 1000.0, "subtotal": 5000.0, "year_month": "2026-03"},
    {"part_number": "P-001", "description": "ボルト", "quantity": 5,
     "unit_price": 500.0, "subtotal": 2500.0, "year_month": "2026-03"},
    {"part_number": "P-002", "description": "ナット", "quantity": 5,
     "unit_price": 500.0, "subtotal": 2500.0, "year_month": "2026-03"},
    # 2026-02: P-001 1行
    {"part_number": "P-001", "description": "ボルト", "quantity": 10,
     "unit_price": 300.0, "subtotal": 3000.0, "year_month": "2026-02"},
]


# ============================================================
# ユニットテスト: aggregate_monthly_cost
# ============================================================

class TestAggregateMonthlyCost:

    def test_returns_items_only_for_target_month(self):
        """指定月のデータのみが集計される（他月は除外）。"""
        result = aggregate_monthly_cost(_ROWS, "2026-03")
        part_numbers = [r["part_number"] for r in result]
        assert "P-001" in part_numbers
        assert "P-002" in part_numbers

    def test_excludes_other_months(self):
        """指定月以外のデータは除外される。"""
        result = aggregate_monthly_cost(_ROWS, "2026-02")
        assert len(result) == 1
        assert result[0]["part_number"] == "P-001"
        # 2026-02 の P-001 は 3000円
        assert result[0]["total_amount"] == 3000.0

    def test_total_amount_is_sum_of_subtotals(self):
        """total_amount は subtotal の合計。P-001: 5000+2500=7500。"""
        result = aggregate_monthly_cost(_ROWS, "2026-03")
        p001 = next(r for r in result if r["part_number"] == "P-001")
        assert p001["total_amount"] == 7500.0

    def test_order_count_is_row_count(self):
        """order_count は当該部品の行数（発注回数）。P-001 は 2 回。"""
        result = aggregate_monthly_cost(_ROWS, "2026-03")
        p001 = next(r for r in result if r["part_number"] == "P-001")
        assert p001["order_count"] == 2

    def test_avg_unit_price_is_mean_of_unit_prices(self):
        """avg_unit_price は unit_price の平均。P-001: (500+500)/2=500。"""
        result = aggregate_monthly_cost(_ROWS, "2026-03")
        p001 = next(r for r in result if r["part_number"] == "P-001")
        assert p001["avg_unit_price"] == 500.0

    def test_sorted_by_total_amount_descending(self):
        """total_amount 降順でソートされる。"""
        result = aggregate_monthly_cost(_ROWS, "2026-03")
        assert result[0]["total_amount"] >= result[-1]["total_amount"]

    def test_empty_rows_returns_empty(self):
        """空リストを渡すと空リストが返る。"""
        assert aggregate_monthly_cost([], "2026-03") == []

    def test_no_matching_month_returns_empty(self):
        """該当月のデータがなければ空リストが返る。"""
        assert aggregate_monthly_cost(_ROWS, "2099-12") == []


# ============================================================
# ユニットテスト: build_cost_trend
# ============================================================

class TestBuildCostTrend:

    def test_returns_all_months_within_limit(self):
        """月数が上限以内なら全月返す。"""
        result = build_cost_trend(_ROWS, 12)
        year_months = [r["year_month"] for r in result]
        assert "2026-02" in year_months
        assert "2026-03" in year_months

    def test_sorted_ascending(self):
        """year_month 昇順でソートされる。"""
        result = build_cost_trend(_ROWS, 12)
        assert result[0]["year_month"] <= result[-1]["year_month"]

    def test_limits_to_n_months(self):
        """months=1 の場合は最新 1 件のみ返す。"""
        result = build_cost_trend(_ROWS, 1)
        assert len(result) == 1
        assert result[0]["year_month"] == "2026-03"

    def test_total_amount_aggregated_per_month(self):
        """月ごとに total_amount が集計される。2026-03: 5000+5000+2500+2500=15000。"""
        result = build_cost_trend(_ROWS, 12)
        march = next(r for r in result if r["year_month"] == "2026-03")
        assert march["total_amount"] == 15000.0

    def test_empty_rows_returns_empty(self):
        """空リストを渡すと空リストが返る。"""
        assert build_cost_trend([], 6) == []


# ============================================================
# ユニットテスト: serialize_to_csv
# ============================================================

class TestSerializeToCsv:

    def test_header_row_present(self):
        """ヘッダー行が含まれる。"""
        rows = [{"year_month": "2026-03", "total_amount": 1000.0, "order_count": 1}]
        csv_str = serialize_to_csv(["year_month", "total_amount", "order_count"], rows)
        assert "year_month" in csv_str
        assert "total_amount" in csv_str

    def test_data_row_present(self):
        """データ行が含まれる。"""
        rows = [{"year_month": "2026-03", "total_amount": 1000.0, "order_count": 1}]
        csv_str = serialize_to_csv(["year_month", "total_amount", "order_count"], rows)
        assert "2026-03" in csv_str
        assert "1000.0" in csv_str

    def test_empty_rows_has_header_only(self):
        """データが空でもヘッダー行は出力される。"""
        csv_str = serialize_to_csv(["year_month", "total_amount"], [])
        lines = [l for l in csv_str.strip().split("\n") if l]
        assert len(lines) == 1  # ヘッダーのみ
        assert "year_month" in lines[0]


# ============================================================
# API テスト: GET /api/reports/monthly-cost
# ============================================================

class TestMonthlyCostEndpoint:

    def test_returns_200_with_data(self, tmp_path):
        """正常系: 200 と発注データが返る。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/reports/monthly-cost?year_month=2026-03")
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        assert "count" in data
        assert "grand_total" in data
        assert "year_month" in data
        assert data["year_month"] == "2026-03"

    def test_grand_total_correct(self, tmp_path):
        """grand_total は月の合計金額（2026-03: 15000.0）。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/reports/monthly-cost?year_month=2026-03")
        data = res.json()
        assert data["grand_total"] == 15000.0

    def test_returns_422_for_invalid_year_month(self, tmp_path):
        """year_month が不正な場合は 422 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/reports/monthly-cost?year_month=invalid")
        assert res.status_code == 422

    def test_empty_month_returns_empty_items(self, tmp_path):
        """データがない月は空の items を返す（200）。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/reports/monthly-cost?year_month=2099-12")
        assert res.status_code == 200
        assert res.json()["count"] == 0
        assert res.json()["grand_total"] == 0.0


# ============================================================
# API テスト: GET /api/reports/cost-trend
# ============================================================

class TestCostTrendEndpoint:

    def test_returns_200(self, tmp_path):
        """正常系: 200 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/reports/cost-trend")
        assert res.status_code == 200

    def test_response_has_months_and_data(self, tmp_path):
        """レスポンスに months と data が含まれる。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/reports/cost-trend?months=12")
        data = res.json()
        assert "months" in data
        assert "data" in data
        assert data["months"] == 12

    def test_data_points_have_required_fields(self, tmp_path):
        """各データポイントに year_month, total_amount, order_count が含まれる。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.get("/api/reports/cost-trend")
        for point in res.json()["data"]:
            assert "year_month" in point
            assert "total_amount" in point
            assert "order_count" in point

    def test_empty_db_returns_empty_data(self, tmp_path):
        """発注データがなければ data は空リスト（200）。"""
        db_path = str(tmp_path / "yuka_empty.db")
        schema_path = Path(__file__).parent.parent / "schema.sql"
        conn = sqlite3.connect(db_path)
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        client = _make_client(db_path)
        res = client.get("/api/reports/cost-trend")
        assert res.status_code == 200
        assert res.json()["data"] == []


# ============================================================
# API テスト: POST /api/reports/export/csv
# ============================================================

class TestExportCsvEndpoint:

    def test_monthly_cost_csv_returns_200(self, tmp_path):
        """monthly_cost タイプで CSV が返る。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post(
            "/api/reports/export/csv",
            json={"report_type": "monthly_cost", "year_month": "2026-03"},
        )
        assert res.status_code == 200
        assert "text/csv" in res.headers["content-type"]

    def test_cost_trend_csv_returns_200(self, tmp_path):
        """cost_trend タイプで CSV が返る。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post(
            "/api/reports/export/csv",
            json={"report_type": "cost_trend", "months": 6},
        )
        assert res.status_code == 200
        assert "text/csv" in res.headers["content-type"]

    def test_csv_content_has_header(self, tmp_path):
        """CSV レスポンスにヘッダー行が含まれる。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post(
            "/api/reports/export/csv",
            json={"report_type": "monthly_cost", "year_month": "2026-03"},
        )
        content = res.text
        assert "part_number" in content
        assert "total_amount" in content

    def test_auto_latest_month_when_year_month_omitted(self, tmp_path):
        """year_month 省略時は最新月が自動選択され 200 を返す。"""
        db_path = str(tmp_path / "yuka.db")
        _setup_db(db_path)
        client = _make_client(db_path)
        res = client.post(
            "/api/reports/export/csv",
            json={"report_type": "monthly_cost"},
        )
        assert res.status_code == 200
