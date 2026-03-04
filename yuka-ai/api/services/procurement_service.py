"""api/services/procurement_service.py

発注自動化ワークフローの純粋ビジネスロジック（T007）。

DBアクセスは行わず、データを受け取って処理結果を返す。
analytics_service.py と同様に DB と分離して設計することで
テスト容易性を確保する。
"""
from __future__ import annotations

from typing import Any


def filter_low_stock(inventory_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """在庫低下アラート対象の行を抽出する。

    Args:
        inventory_rows: [{"part_id", "part_number", "description", "category",
                          "current_stock", "reorder_point"}, ...] のリスト

    Returns:
        current_stock < reorder_point の行のみ（shortage = reorder_point - current_stock 付き）
    """
    result = []
    for row in inventory_rows:
        current = int(row.get("current_stock", 0))
        reorder = int(row.get("reorder_point", 10))
        if current < reorder:
            result.append(
                {
                    **row,
                    "current_stock": current,
                    "reorder_point": reorder,
                    "shortage": reorder - current,
                }
            )
    return result


def build_auto_order_candidates(
    low_stock_rows: list[dict[str, Any]],
    recommendations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """在庫低下 + 買い推奨（BUY_NOW）の部品を自動発注候補リストとして生成する。

    「在庫が少ない」かつ「今が買い時（BUY_NOW）」の部品だけを候補として返す。

    Args:
        low_stock_rows:  filter_low_stock() の戻り値
        recommendations: {part_number: {"action": str, "reason": str, "score": float,
                           "current_price": float, ...}} のマッピング

    Returns:
        [{"part_number", "description", "category", "current_stock", "reorder_point",
          "shortage", "action", "reason", "score", "current_price"}, ...]
        action == "BUY_NOW" のもののみ。score 降順ソート済み。
    """
    candidates = []
    for row in low_stock_rows:
        pn = row.get("part_number", "")
        rec = recommendations.get(pn, {})
        if rec.get("action") == "BUY_NOW":
            candidates.append(
                {
                    "part_number": pn,
                    "description": row.get("description", ""),
                    "category": row.get("category"),
                    "current_stock": row.get("current_stock", 0),
                    "reorder_point": row.get("reorder_point", 10),
                    "shortage": row.get("shortage", 0),
                    "action": rec.get("action", ""),
                    "reason": rec.get("reason", ""),
                    "score": float(rec.get("score", 0.0)),
                    "current_price": float(rec.get("current_price") or 0.0),
                    "avg_price": float(rec.get("avg_price") or 0.0),
                    "trend_pct": float(rec.get("trend_pct") or 0.0),
                }
            )
    return sorted(candidates, key=lambda x: x["score"], reverse=True)
