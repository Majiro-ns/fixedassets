"""年末調整集計レポート API エンドポイント

POST /api/reports/year-end/summary     - 全従業員年末調整サマリー集計
POST /api/reports/year-end/employees   - 全従業員個人別結果一覧
POST /api/reports/year-end/export/csv  - 全従業員年末調整結果CSV出力

設計メモ:
  タスク仕様では GET を指定しているが、パスワードを URL クエリパラメータに
  含めるのはセキュリティリスクがあるため（ログ・履歴への漏洩）、
  employees.py の慣行に倣い全て POST + JSON ボディで実装する。
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from api.services.year_end_report_service import (
    compute_employee_report_list,
    compute_year_end_summary,
    serialize_report_to_csv,
)
from src.core.storage.secure_store import SecureStore
from src.pipeline.batch_pipeline import run_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])


# ---------------------------------------------------------------------------
# 共通スキーマ
# ---------------------------------------------------------------------------


class ReportRequest(BaseModel):
    """レポート取得リクエスト（全エンドポイント共通）。"""

    db_path: str = Field(..., description="SecureStore SQLiteファイルパス")
    password: str = Field(..., description="復号パスワード")


# ---------------------------------------------------------------------------
# レスポンススキーマ
# ---------------------------------------------------------------------------


class YearEndSummaryResponse(BaseModel):
    """年末調整サマリー集計レスポンス。"""

    total_count: int = Field(..., description="集計対象人数")
    avg_salary_income: int = Field(..., description="平均給与収入（円）")
    avg_income_tax: int = Field(..., description="平均所得税額（円）")
    avg_final_tax: int = Field(..., description="平均最終税額（円）")
    total_salary_income: int = Field(..., description="給与収入合計（円）")
    total_income_tax: int = Field(..., description="所得税合計（円）")
    refund_count: int = Field(..., description="還付件数（final_tax==0）")
    additional_count: int = Field(..., description="追加徴収件数（final_tax>0）")


class EmployeeReportItem(BaseModel):
    """個人別年末調整結果（1件）。"""

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


class EmployeeReportResponse(BaseModel):
    """全従業員個人別年末調整結果レスポンス。"""

    employees: list[EmployeeReportItem] = Field(
        ..., description="計算結果リスト（employee_id 昇順）"
    )
    total_count: int = Field(..., description="対象従業員総数")


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _open_store_or_401(db_path_str: str, password: str) -> Path:
    """db_path の存在確認とパスワード検証を行い、問題なければ Path を返す。"""
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
        logger.warning("year_end_report: パスワード認証失敗（db=%s）", db_path_str)
        raise HTTPException(status_code=401, detail="パスワードが正しくありません")
    return db_path


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------


@router.post("/year-end/summary", response_model=YearEndSummaryResponse)
async def year_end_summary(req: ReportRequest):
    """全従業員の年末調整サマリーを集計して返す。

    SecureStore に登録された全従業員を一括計算し、
    人数・平均給与・平均所得税・還付/追加徴収件数を集計する。

    Raises:
        404: db_path が存在しない
        401: パスワードが不正
    """
    db_path = _open_store_or_401(req.db_path, req.password)
    batch_results = run_batch(db_path, req.password)
    summary = compute_year_end_summary(batch_results)
    return YearEndSummaryResponse(**summary)


@router.post("/year-end/employees", response_model=EmployeeReportResponse)
async def year_end_employees(req: ReportRequest):
    """全従業員の個人別年末調整結果一覧を返す。

    SecureStore に登録された全従業員を一括計算し、
    individual 結果を employee_id 昇順で返す。

    Raises:
        404: db_path が存在しない
        401: パスワードが不正
    """
    db_path = _open_store_or_401(req.db_path, req.password)
    batch_results = run_batch(db_path, req.password)
    employee_rows = compute_employee_report_list(batch_results)

    return EmployeeReportResponse(
        employees=[EmployeeReportItem(**row) for row in employee_rows],
        total_count=len(employee_rows),
    )


@router.post("/year-end/export/csv", response_class=PlainTextResponse)
async def year_end_export_csv(req: ReportRequest):
    """全従業員の年末調整結果をCSVエクスポートする。

    SecureStore に登録された全従業員を一括計算し、
    CSV 形式でダウンロード提供する。

    Raises:
        404: db_path が存在しない
        401: パスワードが不正
    """
    db_path = _open_store_or_401(req.db_path, req.password)
    batch_results = run_batch(db_path, req.password)
    employee_rows = compute_employee_report_list(batch_results)
    csv_text = serialize_report_to_csv(employee_rows)

    return PlainTextResponse(
        content=csv_text,
        headers={
            "Content-Disposition": "attachment; filename=year_end_report.csv"
        },
        media_type="text/csv; charset=utf-8",
    )
