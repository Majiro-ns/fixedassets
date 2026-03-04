"""api/services/report_service.py

T009: 月次コスト分析レポートの純粋ビジネスロジック。

DBアクセスは行わず、データリストを受け取って集計結果を返す。
テスト容易性のため、DBと分離して設計する（analytics_service.py と同パターン）。
"""
from __future__ import annotations

import csv
import io
from typing import Any


# ─── 月次コスト集計 ────────────────────────────────────────────────────────────

def aggregate_monthly_cost(
    order_item_rows: list[dict[str, Any]],
    year_month: str,
) -> list[dict[str, Any]]:
    """指定月の部品別コスト集計を返す。

    Args:
        order_item_rows: JOIN済みの発注明細行。各要素に以下のキーを含む:
            part_number, description, quantity, unit_price, subtotal, year_month
        year_month: "YYYY-MM" 形式の対象月

    Returns:
        [{"part_number": str, "description": str, "total_amount": float,
          "avg_unit_price": float, "order_count": int}, ...]
        total_amount 降順でソート
    """
    aggregated: dict[str, dict[str, Any]] = {}
    for row in order_item_rows:
        if row.get("year_month") != year_month:
            continue
        pn = str(row.get("part_number") or "")
        if not pn:
            continue
        if pn not in aggregated:
            aggregated[pn] = {
                "part_number": pn,
                "description": str(row.get("description") or ""),
                "total_amount": 0.0,
                "sum_unit_price": 0.0,
                "order_count": 0,
            }
        qty = int(row.get("quantity") or 1)
        unit_price = float(row.get("unit_price") or 0.0)
        subtotal = float(row.get("subtotal") or (unit_price * qty))
        aggregated[pn]["total_amount"] += subtotal
        aggregated[pn]["sum_unit_price"] += unit_price
        aggregated[pn]["order_count"] += 1

    result = []
    for data in aggregated.values():
        count = data["order_count"]
        avg_unit_price = data["sum_unit_price"] / count if count > 0 else 0.0
        result.append({
            "part_number": data["part_number"],
            "description": data["description"],
            "total_amount": round(data["total_amount"], 2),
            "avg_unit_price": round(avg_unit_price, 2),
            "order_count": count,
        })
    return sorted(result, key=lambda x: x["total_amount"], reverse=True)


# ─── コスト推移集計 ────────────────────────────────────────────────────────────

def build_cost_trend(
    order_item_rows: list[dict[str, Any]],
    months: int,
) -> list[dict[str, Any]]:
    """過去N ヶ月のコスト推移集計を返す（折れ線グラフ用データ）。

    Args:
        order_item_rows: JOIN済みの発注明細行（year_month フィールドを含む）
        months: 取得月数の上限

    Returns:
        [{"year_month": str, "total_amount": float, "order_count": int}, ...]
        year_month 昇順。データが months 件を超える場合は最新 months 件のみ返す。
    """
    monthly: dict[str, dict[str, Any]] = {}
    for row in order_item_rows:
        ym = str(row.get("year_month") or "")
        if not ym:
            continue
        if ym not in monthly:
            monthly[ym] = {"year_month": ym, "total_amount": 0.0, "order_count": 0}
        qty = int(row.get("quantity") or 1)
        unit_price = float(row.get("unit_price") or 0.0)
        subtotal = float(row.get("subtotal") or (unit_price * qty))
        monthly[ym]["total_amount"] += subtotal
        monthly[ym]["order_count"] += 1

    sorted_months = sorted(monthly.values(), key=lambda x: x["year_month"])
    # 最新 months 件のみ返す
    result = sorted_months[-months:] if len(sorted_months) > months else sorted_months
    for item in result:
        item["total_amount"] = round(item["total_amount"], 2)
    return result


# ─── CSV シリアライザ ──────────────────────────────────────────────────────────

def serialize_to_csv(fieldnames: list[str], rows: list[dict[str, Any]]) -> str:
    """データリストをCSV文字列にシリアライズする。

    Args:
        fieldnames: CSV列名リスト（ヘッダー行の順序に従う）
        rows: データ行リスト（各要素は dict）

    Returns:
        UTF-8 CSV文字列（改行コード CRLF）
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=fieldnames,
        extrasaction="ignore",
        lineterminator="\r\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
