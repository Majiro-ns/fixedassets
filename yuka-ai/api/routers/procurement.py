"""api/routers/procurement.py

発注自動化ワークフロー API（T007）。

エンドポイント:
  GET  /api/procurement/low-stock
      → 在庫低下アラート一覧（current_stock < reorder_point のもの）

  POST /api/procurement/auto-order-candidates
      → 在庫低下 + 買い推奨（BUY_NOW）の部品を自動発注候補リストとして生成

  GET  /api/procurement/pending-approvals
      → 承認待ち発注リスト（approval_requests テーブルから status='pending' を取得）
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.models.schemas import (
    LowStockResponse,
    LowStockItem,
    AutoOrderCandidatesResponse,
    AutoOrderCandidate,
    PendingApprovalsResponse,
    PendingApprovalItem,
)
from api.services.db import get_connection
from api.services.analytics_service import compute_price_trend, compute_buy_recommendation
from api.services.procurement_service import filter_low_stock, build_auto_order_candidates

router = APIRouter(prefix="/api/procurement", tags=["procurement"])


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------


def _fetch_inventory_rows(conn) -> list[dict]:
    """inventory テーブルを parts と LEFT JOIN して全在庫行を返す。"""
    cur = conn.execute(
        """
        SELECT
            p.id         AS part_id,
            p.part_number,
            p.description,
            p.category,
            COALESCE(inv.current_stock, 0) AS current_stock,
            COALESCE(inv.reorder_point, 10) AS reorder_point
        FROM parts p
        LEFT JOIN inventory inv ON inv.part_id = p.id
        WHERE p.is_active = 1
        ORDER BY p.part_number
        """
    )
    return [dict(r) for r in cur.fetchall()]


def _fetch_price_history_for_part(conn, part_number: str, limit: int = 90) -> list[dict]:
    """品番の価格履歴を古い順で返す。"""
    cur = conn.execute(
        """
        SELECT ph.price, ph.fetched_at, ph.source
        FROM price_history ph
        JOIN parts p ON p.id = ph.part_id
        WHERE p.part_number = ? AND p.is_active = 1
        ORDER BY ph.fetched_at ASC, ph.id ASC
        LIMIT ?
        """,
        (part_number, limit),
    )
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------


@router.get("/low-stock", response_model=LowStockResponse)
async def get_low_stock():
    """在庫低下アラート一覧を返す。

    current_stock < reorder_point の部品を全件返す。
    inventory テーブルに登録のない部品は current_stock=0, reorder_point=10 として扱う。

    Returns:
        items: 在庫不足部品リスト
        count: 件数
    """
    try:
        conn = get_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB接続エラー: {e}")

    try:
        rows = _fetch_inventory_rows(conn)
    finally:
        conn.close()

    low = filter_low_stock(rows)
    items = [LowStockItem(**{k: r[k] for k in LowStockItem.model_fields}) for r in low]
    return LowStockResponse(items=items, count=len(items))


@router.post("/auto-order-candidates", response_model=AutoOrderCandidatesResponse)
async def get_auto_order_candidates():
    """在庫低下 + 買い推奨（BUY_NOW）の部品を自動発注候補として返す。

    在庫不足かつ価格トレンド分析で「今が買い時（BUY_NOW）」と判定された部品を返す。
    価格履歴がない部品は NEUTRAL として扱われ、候補から除外される。

    Returns:
        candidates: 自動発注候補リスト（score 降順）
        count:      候補件数
    """
    try:
        conn = get_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB接続エラー: {e}")

    try:
        inventory_rows = _fetch_inventory_rows(conn)
        low_stock = filter_low_stock(inventory_rows)

        # 在庫不足品番ごとに買い推奨を取得
        recommendations: dict[str, dict] = {}
        for row in low_stock:
            pn = row["part_number"]
            history = _fetch_price_history_for_part(conn, pn)
            if not history:
                recommendations[pn] = {"action": "NEUTRAL", "reason": "価格データなし", "score": 50.0}
                continue
            trend = compute_price_trend(history)
            rec = compute_buy_recommendation(
                trend_direction=trend["trend_direction"],
                trend_pct=trend["trend_pct"],
                current_price=trend["latest_price"],
                min_price=trend["min_price"],
                avg_price=trend["avg_price"],
            )
            recommendations[pn] = {
                **rec,
                "current_price": trend["latest_price"],
                "avg_price": trend["avg_price"],
                "trend_pct": trend["trend_pct"],
            }
    finally:
        conn.close()

    raw = build_auto_order_candidates(low_stock, recommendations)
    candidates = [AutoOrderCandidate(**c) for c in raw]
    return AutoOrderCandidatesResponse(candidates=candidates, count=len(candidates))


@router.get("/pending-approvals", response_model=PendingApprovalsResponse)
async def get_pending_approvals():
    """承認待ち発注リストを返す。

    approval_requests テーブルから status='pending' のレコードを返す。
    テーブルが存在しない場合は空リストを返す（初期化前の安全対応）。

    Returns:
        items: 承認待ちレコードリスト
        count: 件数
    """
    try:
        conn = get_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB接続エラー: {e}")

    try:
        # approval_requests テーブルは approval_workflow.py が初期化するため
        # 存在しない場合は空を返す
        try:
            cur = conn.execute(
                """
                SELECT id, po_number, requester, reason, amount, status,
                       requested_at, resolved_at, resolver, comment
                FROM approval_requests
                WHERE status = 'pending'
                ORDER BY id DESC
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
        except Exception:
            rows = []
    finally:
        conn.close()

    items = [PendingApprovalItem(**r) for r in rows]
    return PendingApprovalsResponse(items=items, count=len(items))
