"""api/routers/reports.py

T009: 月次コスト分析レポート生成

エンドポイント:
  GET  /api/reports/monthly-cost   → 指定月の部品別コスト集計（合計金額・単価平均・注文件数）
  GET  /api/reports/cost-trend     → 過去Nヶ月のコスト推移（折れ線グラフ用データ）
  POST /api/reports/export/csv     → コスト分析データをCSVエクスポート
"""
from __future__ import annotations

import io

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.models.schemas import (
    CostTrendPoint,
    CostTrendResponse,
    ExportCsvRequest,
    MonthlyCostItem,
    MonthlyCostResponse,
)
from api.services.db import get_connection
from api.services.report_service import (
    aggregate_monthly_cost,
    build_cost_trend,
    serialize_to_csv,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


# ─── DB ヘルパー ───────────────────────────────────────────────────────────────

def _fetch_order_items_with_month() -> list[dict]:
    """purchase_order_items × purchase_orders を JOIN し year_month を付与して返す。

    発注日（issue_date）が設定されている発注書の明細のみ対象とする。
    """
    try:
        conn = get_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB接続エラー: {e}")
    try:
        cur = conn.execute(
            """
            SELECT
                poi.part_number,
                poi.description,
                poi.quantity,
                poi.unit_price,
                poi.subtotal,
                strftime('%Y-%m', po.issue_date) AS year_month
            FROM purchase_order_items poi
            JOIN purchase_orders po ON poi.po_id = po.id
            WHERE po.issue_date IS NOT NULL
            ORDER BY po.issue_date ASC
            """
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ─── エンドポイント ────────────────────────────────────────────────────────────

@router.get("/monthly-cost", response_model=MonthlyCostResponse)
def get_monthly_cost(
    year_month: str = Query(..., description="対象月 (YYYY-MM 形式, 例: 2026-03)"),
):
    """指定月の部品別コスト集計を返す。

    Returns:
        year_month: 対象月
        items: 部品別コスト一覧（total_amount 降順）
        count: 部品種類数
        grand_total: 月合計コスト
    """
    if len(year_month) != 7 or year_month[4] != "-":
        raise HTTPException(
            status_code=422,
            detail="year_month は YYYY-MM 形式で指定してください（例: 2026-03）",
        )

    rows = _fetch_order_items_with_month()
    items_data = aggregate_monthly_cost(rows, year_month)
    grand_total = round(sum(item["total_amount"] for item in items_data), 2)
    items = [MonthlyCostItem(**item) for item in items_data]

    return MonthlyCostResponse(
        year_month=year_month,
        items=items,
        count=len(items),
        grand_total=grand_total,
    )


@router.get("/cost-trend", response_model=CostTrendResponse)
def get_cost_trend(
    months: int = Query(6, ge=1, le=60, description="取得する月数（最大60ヶ月）"),
):
    """過去Nヶ月のコスト推移を返す（折れ線グラフ用データ）。

    Returns:
        months: リクエストされた月数
        data: 月別コスト推移リスト（year_month 昇順）
    """
    rows = _fetch_order_items_with_month()
    trend_data = build_cost_trend(rows, months)
    data = [CostTrendPoint(**point) for point in trend_data]

    return CostTrendResponse(months=months, data=data)


@router.post("/export/csv")
def export_csv(req: ExportCsvRequest):
    """コスト分析データをCSVファイルとしてエクスポートする。

    request body:
        report_type: "monthly_cost"（デフォルト）または "cost_trend"
        year_month: monthly_cost の対象月 (YYYY-MM)。None の場合は最新月を自動選択
        months: cost_trend の取得月数（デフォルト 6）

    Returns:
        text/csv ストリームレスポンス
    """
    rows = _fetch_order_items_with_month()

    if req.report_type == "cost_trend":
        data = build_cost_trend(rows, req.months)
        fieldnames = ["year_month", "total_amount", "order_count"]
        filename = f"cost_trend_{req.months}months.csv"
    else:
        # monthly_cost (デフォルト)
        year_month = req.year_month
        if year_month is None:
            # year_month 未指定: 最新月を自動選択
            available = [r["year_month"] for r in rows if r.get("year_month")]
            year_month = max(available) if available else ""
        data = aggregate_monthly_cost(rows, year_month)
        fieldnames = ["part_number", "description", "total_amount", "avg_unit_price", "order_count"]
        filename = f"monthly_cost_{year_month}.csv"

    csv_content = serialize_to_csv(fieldnames, data)

    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
