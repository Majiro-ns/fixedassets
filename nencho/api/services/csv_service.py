"""CSVバッチ処理サービス

pandas を使わず csv モジュールで実装する（軽量依存）。

対応フォーマット:
  ヘッダー行必須。フィールド順序は任意。
  必須列: employee_id, employee_name, tax_year, salary_income, social_insurance_paid
  任意列: has_spouse, spouse_income, dependent_count, dependent_young_count,
          life_insurance_new, life_insurance_old, earthquake_insurance,
          has_housing_loan, housing_loan_amount, housing_type, housing_entry_year,
          entry_month, exit_month
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from src.input.employee_form import input_employee_from_dict, validate_employee_input

# ---------------------------------------------------------------------------
# CSVフィールド定義
# ---------------------------------------------------------------------------

CSV_REQUIRED_FIELDS = {
    "employee_id",
    "employee_name",
    "tax_year",
    "salary_income",
    "social_insurance_paid",
}

CSV_ALL_FIELDS = [
    "employee_id",
    "employee_name",
    "tax_year",
    "salary_income",
    "social_insurance_paid",
    "has_spouse",
    "spouse_income",
    "dependent_count",
    "dependent_young_count",
    "life_insurance_new",
    "life_insurance_old",
    "earthquake_insurance",
    "has_housing_loan",
    "housing_loan_amount",
    "housing_type",
    "housing_entry_year",
    "entry_month",
    "exit_month",
]

_TEMPLATE_EXAMPLE = {
    "employee_id": "EMP001",
    "employee_name": "山田太郎",
    "tax_year": "7",
    "salary_income": "5000000",
    "social_insurance_paid": "720000",
    "has_spouse": "false",
    "spouse_income": "0",
    "dependent_count": "0",
    "dependent_young_count": "0",
    "life_insurance_new": "0",
    "life_insurance_old": "0",
    "earthquake_insurance": "0",
    "has_housing_loan": "false",
    "housing_loan_amount": "0",
    "housing_type": "general",
    "housing_entry_year": "2024",
    "entry_month": "0",
    "exit_month": "0",
}


# ---------------------------------------------------------------------------
# 結果データクラス
# ---------------------------------------------------------------------------

@dataclass
class CsvRowSuccess:
    """CSV解析成功行。"""
    employee_id: str
    data: dict  # input_employee_from_dict に渡すフィールド


@dataclass
class CsvRowError:
    """CSV解析エラー行。"""
    row: int          # 行番号（1=ヘッダー, 2=データ1行目。0=ヘッダーエラー）
    employee_id: str  # 識別できた場合のみ
    message: str


@dataclass
class CsvParseResult:
    """CSV解析結果。"""
    success: list[CsvRowSuccess]
    errors: list[CsvRowError]


# ---------------------------------------------------------------------------
# パブリック関数
# ---------------------------------------------------------------------------

def generate_csv_template() -> str:
    """CSVテンプレート文字列を生成する（ヘッダー行 + サンプル1行）。

    Returns:
        UTF-8 CSVテキスト（BOMなし）
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_ALL_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerow(_TEMPLATE_EXAMPLE)
    return output.getvalue()


def parse_csv_employees(csv_text: str) -> CsvParseResult:
    """CSV文字列を解析して従業員データリストを返す。

    各行に対して:
      1. employee_id が空でないか確認
      2. input_employee_from_dict でデータ変換（型チェック・金額パース）
      3. validate_employee_input でドメインバリデーション

    Args:
        csv_text: CSVテキスト（ヘッダー行必須）

    Returns:
        CsvParseResult: 正常行と全エラー情報
    """
    success: list[CsvRowSuccess] = []
    errors: list[CsvRowError] = []

    reader = csv.DictReader(io.StringIO(csv_text))

    # ヘッダー確認
    if reader.fieldnames is None:
        return CsvParseResult(
            success=[],
            errors=[CsvRowError(row=0, employee_id="", message="CSVヘッダーが見つかりません")],
        )

    missing = CSV_REQUIRED_FIELDS - set(reader.fieldnames)
    if missing:
        return CsvParseResult(
            success=[],
            errors=[CsvRowError(
                row=0,
                employee_id="",
                message=f"必須列が不足しています: {sorted(missing)}",
            )],
        )

    for row_num, row in enumerate(reader, start=2):
        employee_id = (row.get("employee_id") or "").strip()

        if not employee_id:
            errors.append(CsvRowError(
                row=row_num,
                employee_id="",
                message="employee_id が空です",
            ))
            continue

        # employee_id を除いたデータ辞書を構築（空文字列フィールドも渡す）
        data = {k: v for k, v in row.items() if k != "employee_id"}

        # input_employee_from_dict で型変換・必須フィールドチェック
        try:
            emp = input_employee_from_dict(data)
        except (KeyError, ValueError) as exc:
            errors.append(CsvRowError(
                row=row_num,
                employee_id=employee_id,
                message=f"データエラー: {exc}",
            ))
            continue

        # ドメインバリデーション
        validation_errors = validate_employee_input(emp)
        if validation_errors:
            errors.append(CsvRowError(
                row=row_num,
                employee_id=employee_id,
                message=f"バリデーションエラー: {'; '.join(validation_errors)}",
            ))
            continue

        success.append(CsvRowSuccess(employee_id=employee_id, data=data))

    return CsvParseResult(success=success, errors=errors)
