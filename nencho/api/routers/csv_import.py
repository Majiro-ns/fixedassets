"""CSV一括インポート API エンドポイント

POST /api/csv/import/employees  - CSVから従業員データを一括登録
GET  /api/csv/template          - CSVテンプレートダウンロード
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from api.services.csv_service import generate_csv_template, parse_csv_employees
from src.core.storage.secure_store import SecureStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/csv", tags=["csv"])


# ---------------------------------------------------------------------------
# スキーマ
# ---------------------------------------------------------------------------


class CsvImportError(BaseModel):
    """インポートエラー情報（1行分）。"""

    row: int
    employee_id: str
    message: str


class CsvImportResponse(BaseModel):
    """CSV一括インポートレスポンス。"""

    imported_count: int
    error_count: int
    errors: list[CsvImportError]


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------


@router.get("/template", response_class=PlainTextResponse)
async def get_csv_template():
    """CSVテンプレートファイルをダウンロードする。

    Returns:
        ヘッダー行 + サンプル1行を含む CSV テキスト
    """
    content = generate_csv_template()
    return PlainTextResponse(
        content=content,
        headers={
            "Content-Disposition": "attachment; filename=employees_template.csv"
        },
        media_type="text/csv; charset=utf-8",
    )


@router.post("/import/employees", response_model=CsvImportResponse)
async def import_employees_csv(
    file: UploadFile = File(..., description="従業員データCSVファイル"),
    db_path: str = Form(..., description="SecureStore SQLiteファイルパス"),
    password: str = Form(..., description="復号パスワード"),
):
    """CSVから従業員データを一括登録する。

    CSVフォーマット（ヘッダー行必須）:
      employee_id, employee_name, tax_year, salary_income, social_insurance_paid,
      [has_spouse, spouse_income, dependent_count, ...（省略可）]

    Args:
        file: CSV ファイル（multipart/form-data）
        db_path: SecureStore データベースファイルのパス
        password: 復号パスワード

    Returns:
        インポート件数・エラー件数・エラー詳細

    Raises:
        400: CSVフォーマットエラー（ヘッダー不正など）
        401: パスワード不正
    """
    store_path = Path(db_path)

    # 既存DBの場合はパスワード検証
    if store_path.exists():
        try:
            with SecureStore(store_path, password):
                pass
        except Exception:
            logger.warning("csv_import: パスワード認証失敗（db=%s）", db_path)
            raise HTTPException(status_code=401, detail="パスワードが正しくありません")

    # CSV読み込み（BOM付きUTF-8・CP932両対応）
    raw_bytes = await file.read()
    try:
        csv_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        csv_text = raw_bytes.decode("cp932", errors="replace")

    # CSV解析
    result = parse_csv_employees(csv_text)

    # ヘッダーエラーは 400 を返す
    if result.errors and result.errors[0].row == 0:
        raise HTTPException(status_code=400, detail=result.errors[0].message)

    # SecureStore へ一括登録
    imported_count = 0
    import_errors = [
        {"row": e.row, "employee_id": e.employee_id, "message": e.message}
        for e in result.errors
    ]

    if result.success:
        with SecureStore(store_path, password) as store:
            for item in result.success:
                try:
                    store.save_employee(item.employee_id, item.data)
                    imported_count += 1
                except Exception as exc:
                    import_errors.append({
                        "row": -1,
                        "employee_id": item.employee_id,
                        "message": f"保存エラー: {exc}",
                    })

    return CsvImportResponse(
        imported_count=imported_count,
        error_count=len(import_errors),
        errors=[
            CsvImportError(
                row=e["row"],
                employee_id=e["employee_id"],
                message=e["message"],
            )
            for e in import_errors
        ],
    )
