"""評価統計ダッシュボード API ルーター (T011)

エンドポイント:
  GET /api/checklist/stats/summary   → StatsSummaryResponse
  GET /api/checklist/stats/top-items → TopItemsResponse
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from api.models.schemas import StatsSummaryResponse, TopItemsResponse, TopItem
from api.services.checklist_stats_service import get_summary, get_top_items

router = APIRouter(prefix="/api/checklist/stats", tags=["checklist-stats"])


@router.get("/summary", response_model=StatsSummaryResponse)
def stats_summary() -> StatsSummaryResponse:
    """評価統計サマリーを返す。

    - total_evaluations: 総評価回数
    - avg_coverage_rate: 平均一致率（小数点2桁）
    - max_coverage_rate: 最高一致率
    - min_coverage_rate: 最低一致率（0件時は 0.0）
    """
    data = get_summary()
    return StatsSummaryResponse(**data)


@router.get("/top-items", response_model=TopItemsResponse)
def stats_top_items(
    limit: int = Query(default=10, ge=1, le=50, description="返す件数（上限50）"),
) -> TopItemsResponse:
    """最も多くマッチされたチェックリスト項目ランキングを返す。

    - item_id: チェックリスト ID（例: CL-001）
    - item_name: 項目名
    - match_count: マッチ回数
    - match_rate: 全評価中のマッチ率（%）
    """
    data = get_top_items(top_n=limit)
    items = [TopItem(**it) for it in data["items"]]
    return TopItemsResponse(
        total_evaluations=data["total_evaluations"],
        items=items,
        count=data["count"],
    )
