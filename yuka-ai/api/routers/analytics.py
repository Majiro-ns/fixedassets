"""api/routers/analytics.py

価格トレンド分析・発注タイミング推奨 API。

エンドポイント:
  GET /api/analytics/price-trend/{part_number}
      → 品番の価格トレンド（上昇/下落/安定）と統計情報を返す

  GET /api/analytics/buy-recommendation/{part_number}
      → 「今が買い時か？」の推奨アクションを返す
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.models.schemas import (
    PriceTrendResponse,
    PriceTrendItem,
    BuyRecommendationResponse,
)
from api.services.db import get_connection
from api.services.analytics_service import compute_price_trend, compute_buy_recommendation

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _get_price_history_rows(part_number: str, limit: int) -> list[dict]:
    """DB から品番の価格履歴を取得して返す（古い順）。"""
    try:
        conn = get_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB接続エラー: {e}")
    try:
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
    finally:
        conn.close()


@router.get("/price-trend/{part_number}", response_model=PriceTrendResponse)
async def get_price_trend(
    part_number: str,
    limit: int = Query(90, ge=1, le=365, description="取得する価格履歴の最大件数"),
):
    """品番の価格トレンドを分析して返す。

    価格履歴が存在しない場合は 404 を返す。

    Returns:
        trend_direction: "rising"（上昇）/ "falling"（下落）/ "stable"（安定）
        trend_pct: 最古〜最新の変動率(%)
        volatility_pct: 変動係数（ボラティリティ）(%)
        history: 価格履歴リスト（古い順）
    """
    rows = _get_price_history_rows(part_number, limit)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"品番 {part_number} の価格履歴が見つかりません。先に価格を登録してください。",
        )

    trend = compute_price_trend(rows)

    return PriceTrendResponse(
        part_number=part_number,
        trend_direction=trend["trend_direction"],
        trend_pct=trend["trend_pct"],
        avg_price=trend["avg_price"],
        min_price=trend["min_price"],
        max_price=trend["max_price"],
        latest_price=trend["latest_price"],
        data_points=trend["data_points"],
        volatility_pct=trend["volatility_pct"],
        history=[
            PriceTrendItem(
                price=r["price"],
                fetched_at=r["fetched_at"],
                source=r.get("source"),
            )
            for r in rows
        ],
    )


@router.get("/buy-recommendation/{part_number}", response_model=BuyRecommendationResponse)
async def get_buy_recommendation(
    part_number: str,
    limit: int = Query(90, ge=1, le=365, description="分析に使う価格履歴の最大件数"),
):
    """品番の発注タイミング推奨を返す。

    価格履歴が存在しない場合は 404 を返す。

    Returns:
        action: "BUY_NOW"（今すぐ発注）/ "WAIT"（様子見）/ "NEUTRAL"（通常タイミング）
        reason: 推奨理由（日本語）
        score: 0〜100（高いほど「今すぐ買い」が推奨される）
    """
    rows = _get_price_history_rows(part_number, limit)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"品番 {part_number} の価格履歴が見つかりません。先に価格を登録してください。",
        )

    trend = compute_price_trend(rows)
    rec = compute_buy_recommendation(
        trend_direction=trend["trend_direction"],
        trend_pct=trend["trend_pct"],
        current_price=trend["latest_price"],
        min_price=trend["min_price"],
        avg_price=trend["avg_price"],
    )

    return BuyRecommendationResponse(
        part_number=part_number,
        action=rec["action"],
        reason=rec["reason"],
        score=rec["score"],
        current_price=trend["latest_price"],
        avg_price=trend["avg_price"],
        trend_pct=trend["trend_pct"],
        trend_direction=trend["trend_direction"],
    )
