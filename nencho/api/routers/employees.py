"""従業員管理・一括計算 API エンドポイント

F-06 複数従業員一括管理 の API 層。

SecureStore に登録された従業員データを:
  - 一覧取得 (POST /api/employees/list)
  - 個別計算 (POST /api/employees/{employee_id}/calculate)
  - 一括計算 (POST /api/employees/batch-calculate)

認証設計:
  各リクエストに db_path + password を含めるステートレス設計。
  セッション連携は将来拡張で対応可能（session.py の session_data に
  password を追加することで X-Session-Id ベースに移行可能）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.core.storage.secure_store import SecureStore
from src.input.employee_form import input_employee_from_dict
from src.pipeline.batch_pipeline import run_batch
from src.pipeline.year_end_adjustment import calculate_year_end_adjustment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/employees", tags=["employees"])


# ---------------------------------------------------------------------------
# 共通スキーマ
# ---------------------------------------------------------------------------


class StoreCredentials(BaseModel):
    """SecureStore 認証情報（全エンドポイント共通）。"""

    db_path: str = Field(..., description="SecureStore SQLite ファイルパス")
    password: str = Field(..., description="復号パスワード")


class EmployeeListRequest(StoreCredentials):
    """従業員一覧リクエスト。"""


class EmployeeListResponse(BaseModel):
    """従業員一覧レスポンス。"""

    employee_ids: list[str] = Field(..., description="登録済み従業員IDリスト（更新日時昇順）")
    count: int = Field(..., description="登録件数")


class EmployeeCalculateRequest(StoreCredentials):
    """個別従業員計算リクエスト。"""


class EmployeeCalculateResponse(BaseModel):
    """個別従業員計算レスポンス。"""

    employee_id: str
    employee_name: str
    tax_year: int
    salary_income: int
    employment_income: int
    total_deductions: int
    income_tax: int
    reconstruction_tax: int
    housing_loan_deduction: int
    final_tax: int
    basic_deduction: int
    spouse_deduction: int
    dependent_count: int
    social_insurance_paid: int
    life_insurance_deduction: int
    earthquake_deduction: int
    income_adjustment_deduction: int


class BatchCalculateRequest(StoreCredentials):
    """一括計算リクエスト。"""

    emp_ids: Optional[list[str]] = Field(
        None,
        description="計算対象の従業員IDリスト。省略時は全従業員を対象とする。",
    )


class BatchCalculateItem(BaseModel):
    """一括計算結果の1件分。"""

    employee_id: str
    employee_name: str
    tax_year: int
    salary_income: int
    final_tax: int
    income_tax: int
    reconstruction_tax: int
    housing_loan_deduction: int
    employment_income: int
    total_deductions: int
    basic_deduction: int
    spouse_deduction: int
    dependent_count: int
    social_insurance_paid: int
    life_insurance_deduction: int
    earthquake_deduction: int
    income_adjustment_deduction: int


class BatchCalculateResponse(BaseModel):
    """一括計算レスポンス。"""

    results: list[BatchCalculateItem] = Field(..., description="計算結果リスト（employee_id 昇順）")
    success_count: int = Field(..., description="計算成功件数")
    total_count: int = Field(..., description="対象従業員総数")


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _open_store_or_401(db_path_str: str, password: str) -> Path:
    """db_path の存在確認とパスワード検証を行い、問題なければ Path を返す。

    Raises:
        HTTPException 404: db_path が存在しない
        HTTPException 401: パスワードが不正（SecureStore が開けない）
    """
    db_path = Path(db_path_str)
    if not db_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"データベースファイルが見つかりません: {db_path_str}",
        )
    # パスワード検証: 開けるか試みる
    try:
        with SecureStore(db_path, password):
            pass
    except Exception:
        logger.warning("employees API: パスワード認証失敗（db=%s）", db_path_str)
        raise HTTPException(status_code=401, detail="パスワードが正しくありません")
    return db_path


def _result_to_item(employee_id: str, result) -> BatchCalculateItem:
    """YearEndAdjustmentResult → BatchCalculateItem に変換。"""
    return BatchCalculateItem(
        employee_id=employee_id,
        employee_name=result.employee_name,
        tax_year=result.tax_year,
        salary_income=result.salary_income,
        final_tax=result.final_tax,
        income_tax=result.income_tax,
        reconstruction_tax=result.reconstruction_tax,
        housing_loan_deduction=result.housing_loan_deduction,
        employment_income=result.employment_income,
        total_deductions=result.total_deductions,
        basic_deduction=result.basic_deduction,
        spouse_deduction=result.spouse_deduction,
        dependent_count=result.dependent_count,
        social_insurance_paid=result.social_insurance_paid,
        life_insurance_deduction=result.life_insurance_deduction,
        earthquake_deduction=result.earthquake_deduction,
        income_adjustment_deduction=result.income_adjustment_deduction,
    )


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------


@router.post("/list", response_model=EmployeeListResponse)
async def list_employees(req: EmployeeListRequest):
    """SecureStore に登録された従業員IDの一覧を取得する。

    Returns:
        登録済み従業員IDリスト（更新日時昇順）と件数

    Raises:
        404: db_path が存在しない
        401: パスワードが不正
    """
    db_path = _open_store_or_401(req.db_path, req.password)
    with SecureStore(db_path, req.password) as store:
        ids = store.list_employees()

    return EmployeeListResponse(employee_ids=ids, count=len(ids))


@router.post("/{employee_id}/calculate", response_model=EmployeeCalculateResponse)
async def calculate_employee(employee_id: str, req: EmployeeCalculateRequest):
    """指定従業員IDの年末調整を計算する。

    SecureStore から従業員データを取得し、年末調整を計算して返す。

    Args:
        employee_id: 従業員ID（パスパラメータ）

    Returns:
        計算結果

    Raises:
        404: db_path が存在しない、または employee_id が登録されていない
        401: パスワードが不正
        422: 計算エラー（入力データ不正）
    """
    db_path = _open_store_or_401(req.db_path, req.password)

    with SecureStore(db_path, req.password) as store:
        try:
            data = store.load_employee(employee_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"従業員ID '{employee_id}' は登録されていません",
            )

    try:
        emp = input_employee_from_dict(data)
        result = calculate_year_end_adjustment(emp)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return EmployeeCalculateResponse(
        employee_id=employee_id,
        employee_name=result.employee_name,
        tax_year=result.tax_year,
        salary_income=result.salary_income,
        employment_income=result.employment_income,
        total_deductions=result.total_deductions,
        income_tax=result.income_tax,
        reconstruction_tax=result.reconstruction_tax,
        housing_loan_deduction=result.housing_loan_deduction,
        final_tax=result.final_tax,
        basic_deduction=result.basic_deduction,
        spouse_deduction=result.spouse_deduction,
        dependent_count=result.dependent_count,
        social_insurance_paid=result.social_insurance_paid,
        life_insurance_deduction=result.life_insurance_deduction,
        earthquake_deduction=result.earthquake_deduction,
        income_adjustment_deduction=result.income_adjustment_deduction,
    )


@router.post("/batch-calculate", response_model=BatchCalculateResponse)
async def batch_calculate(req: BatchCalculateRequest):
    """複数従業員の年末調整を一括計算する。

    SecureStore に登録された全従業員（または emp_ids で指定した従業員）を
    一括で年末調整計算し、結果リストを返す。

    Args:
        req.emp_ids: 計算対象IDリスト。省略時は全従業員を対象とする。

    Returns:
        計算結果リスト（employee_id 昇順）と成功件数

    Raises:
        404: db_path が存在しない
        401: パスワードが不正
    """
    db_path = _open_store_or_401(req.db_path, req.password)

    # 対象件数を先に取得（total_count 用）
    with SecureStore(db_path, req.password) as store:
        if req.emp_ids is None:
            all_ids = store.list_employees()
        else:
            registered = set(store.list_employees())
            all_ids = [eid for eid in req.emp_ids if eid in registered]
    total_count = len(all_ids)

    # 一括計算（run_batch は内部でエラーをスキップする）
    batch_results = run_batch(db_path, req.password, emp_ids=req.emp_ids)

    items = sorted(
        [_result_to_item(eid, res) for eid, res in batch_results.items()],
        key=lambda x: x.employee_id,
    )

    return BatchCalculateResponse(
        results=items,
        success_count=len(items),
        total_count=total_count,
    )
