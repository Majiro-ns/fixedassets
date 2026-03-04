"""扶養控除額自動計算 API エンドポイント

POST /api/deductions/calculate/{emp_id} - 従業員の控除額を自動計算
POST /api/deductions/summary            - 全従業員の控除額サマリー一覧

認証設計:
  全エンドポイント: db_path + password を JSON ボディで渡す（employees.py と同様）
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.services.deduction_service import compute_deductions
from api.services.dependent_service import get_dependents
from src.core.storage.secure_store import SecureStore
from src.pipeline.batch_pipeline import run_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deductions", tags=["deductions"])


# ---------------------------------------------------------------------------
# スキーマ
# ---------------------------------------------------------------------------


class DeductionRequest(BaseModel):
    """控除額計算リクエスト（全エンドポイント共通）。"""

    db_path: str = Field(..., description="SecureStore SQLiteファイルパス")
    password: str = Field(..., description="復号パスワード")


class DeductionResult(BaseModel):
    """控除額計算結果（1従業員分）。"""

    basic_deduction: int = Field(..., description="基礎控除額（令和7年改正後）")
    dependent_deduction: int = Field(..., description="扶養控除額（配偶者除く）")
    spouse_deduction: int = Field(..., description="配偶者控除額")
    spouse_special_deduction: int = Field(..., description="配偶者特別控除額")
    total_deduction: int = Field(..., description="合計控除額")
    employment_income: int = Field(..., description="給与所得（計算中間値）")
    tax_year: str = Field(..., description="適用年度（例: R7）")


class EmployeeDeductionResult(DeductionResult):
    """個人別控除額計算結果。"""

    emp_id: str
    employee_name: str


class DeductionSummaryResponse(BaseModel):
    """全従業員の控除額サマリー。"""

    results: list[EmployeeDeductionResult] = Field(
        ..., description="計算結果リスト（emp_id 昇順）"
    )
    total_employees: int
    error_count: int = Field(..., description="計算エラーが発生した従業員数")


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _open_store_or_raise(db_path_str: str, password: str) -> Path:
    """db_path の存在確認とパスワード検証を行う。"""
    db_path = Path(db_path_str)
    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"データベースファイルが見つかりません: {db_path_str}",
        )
    try:
        with SecureStore(db_path, password):
            pass
    except Exception:
        logger.warning("deductions API: パスワード認証失敗（db=%s）", db_path_str)
        raise HTTPException(status_code=401, detail="パスワードが正しくありません")
    return db_path


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------


@router.post("/calculate/{emp_id}", response_model=EmployeeDeductionResult)
async def calculate_deductions(emp_id: str, req: DeductionRequest):
    """従業員の扶養控除額を自動計算する。

    SecureStore から従業員データと扶養親族リスト（T010）を取得し、
    令和7年税制に基づいて各種控除額を計算して返す。

    Args:
        emp_id: 従業員ID（パスパラメータ）

    Returns:
        EmployeeDeductionResult: 各種控除額と合計

    Raises:
        404: db_path または emp_id が存在しない
        401: パスワードが不正
    """
    store_path = _open_store_or_raise(req.db_path, req.password)

    with SecureStore(store_path, req.password) as store:
        try:
            data = store.load_employee(emp_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"従業員ID '{emp_id}' は登録されていません",
            )

    dependents = get_dependents(data)
    result = compute_deductions(data, dependents)

    return EmployeeDeductionResult(
        emp_id=emp_id,
        employee_name=str(data.get("employee_name", "")),
        **result,
    )


@router.post("/summary", response_model=DeductionSummaryResponse)
async def deductions_summary(req: DeductionRequest):
    """全従業員の扶養控除額サマリーを返す。

    SecureStore に登録された全従業員の控除額を一括計算し、
    emp_id 昇順のリストで返す。

    Raises:
        404: db_path が存在しない
        401: パスワードが不正
    """
    store_path = _open_store_or_raise(req.db_path, req.password)

    results: list[EmployeeDeductionResult] = []
    error_count = 0

    with SecureStore(store_path, req.password) as store:
        emp_ids = store.list_employees()
        for emp_id in sorted(emp_ids):
            try:
                data = store.load_employee(emp_id)
                dependents = get_dependents(data)
                deduction = compute_deductions(data, dependents)
                results.append(EmployeeDeductionResult(
                    emp_id=emp_id,
                    employee_name=str(data.get("employee_name", "")),
                    **deduction,
                ))
            except Exception as e:
                logger.warning("deductions summary: %s スキップ（%s）", emp_id, e)
                error_count += 1

    return DeductionSummaryResponse(
        results=results,
        total_employees=len(results),
        error_count=error_count,
    )
