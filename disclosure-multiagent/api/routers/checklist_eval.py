"""チェックリスト評価履歴・バッチ評価 API ルーター (T010)

エンドポイント:
  POST /api/checklist/evaluate             → テキスト照合 + DB 保存 + 評価ID返却
  GET  /api/checklist/evaluations          → 過去の評価履歴一覧（最新20件）
  GET  /api/checklist/evaluations/{eval_id} → 特定評価の詳細
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.models.schemas import (
    ChecklistMatchResult,
    EvaluateRequest,
    EvaluateResponse,
    EvaluationDetailResponse,
    EvaluationsListResponse,
    EvaluateSummary,
)
from api.services import checklist_eval_service

router = APIRouter(prefix="/api/checklist", tags=["checklist-eval"])


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate_checklist(request: EvaluateRequest):
    """開示テキストを全チェックリスト項目と照合し、結果を DB に保存する。

    返り値: 評価ID（UUID4）・日時・照合サマリ
    """
    if not request.disclosure_text.strip():
        raise HTTPException(status_code=400, detail="disclosure_text が空です")
    try:
        result = checklist_eval_service.evaluate_and_save(
            disclosure_text=request.disclosure_text,
            categories=request.categories,
            required_only=request.required_only,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return EvaluateResponse(**result)


@router.get("/evaluations", response_model=EvaluationsListResponse)
async def list_evaluations():
    """過去の評価履歴一覧（最新20件）を返す。"""
    evals = checklist_eval_service.get_evaluations(limit=20)
    return EvaluationsListResponse(
        evaluations=[EvaluateSummary(**e) for e in evals],
        count=len(evals),
    )


@router.get("/evaluations/{eval_id}", response_model=EvaluationDetailResponse)
async def get_evaluation(eval_id: str):
    """特定評価の詳細（各チェックリスト項目の一致状況）を返す。"""
    detail = checklist_eval_service.get_evaluation_detail(eval_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"評価ID {eval_id} が見つかりません",
        )
    return EvaluationDetailResponse(
        **{k: v for k, v in detail.items() if k != "results"},
        results=[ChecklistMatchResult(**r) for r in detail["results"]],
    )
