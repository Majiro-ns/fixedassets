"""年末調整集計レポートサービス

SecureStore の全従業員データを一括計算し、集計・シリアライズする純粋関数群。
pandas を使わず csv 標準モジュールで実装する（依存追加ゼロ）。

定義:
  還付件数   (refund_count):     final_tax == 0（住宅ローン控除等で全額控除）
  追加徴収件数 (additional_count): final_tax > 0（残税額あり）
"""
from __future__ import annotations

import csv
import io

# ---------------------------------------------------------------------------
# 出力CSVのフィールド定義
# ---------------------------------------------------------------------------

EXPORT_FIELDS = [
    "employee_id",
    "employee_name",
    "tax_year",
    "salary_income",
    "employment_income",
    "total_deductions",
    "income_tax",
    "reconstruction_tax",
    "housing_loan_deduction",
    "final_tax",
    "basic_deduction",
    "spouse_deduction",
    "dependent_count",
    "social_insurance_paid",
    "life_insurance_deduction",
    "earthquake_deduction",
    "income_adjustment_deduction",
]


# ---------------------------------------------------------------------------
# 集計関数
# ---------------------------------------------------------------------------

def compute_year_end_summary(batch_results: dict) -> dict:
    """全従業員の年末調整サマリーを集計する。

    Args:
        batch_results: {employee_id: YearEndAdjustmentResult} の dict

    Returns:
        集計結果 dict。キー:
          total_count         : 集計対象人数
          avg_salary_income   : 平均給与収入（切り捨て整数）
          avg_income_tax      : 平均所得税額（切り捨て整数）
          avg_final_tax       : 平均最終税額（切り捨て整数）
          total_salary_income : 給与収入合計
          total_income_tax    : 所得税合計
          refund_count        : final_tax == 0 の件数（還付）
          additional_count    : final_tax > 0 の件数（追加徴収）

    Note:
        batch_results が空の場合はゼロ埋めの dict を返す（ZeroDivisionError防止）。
    """
    if not batch_results:
        return {
            "total_count": 0,
            "avg_salary_income": 0,
            "avg_income_tax": 0,
            "avg_final_tax": 0,
            "total_salary_income": 0,
            "total_income_tax": 0,
            "refund_count": 0,
            "additional_count": 0,
        }

    results = list(batch_results.values())
    n = len(results)

    total_salary = sum(r.salary_income for r in results)
    total_income_tax = sum(r.income_tax for r in results)
    total_final_tax = sum(r.final_tax for r in results)
    refund_count = sum(1 for r in results if r.final_tax == 0)
    additional_count = sum(1 for r in results if r.final_tax > 0)

    return {
        "total_count": n,
        "avg_salary_income": total_salary // n,
        "avg_income_tax": total_income_tax // n,
        "avg_final_tax": total_final_tax // n,
        "total_salary_income": total_salary,
        "total_income_tax": total_income_tax,
        "refund_count": refund_count,
        "additional_count": additional_count,
    }


def compute_employee_report_list(batch_results: dict) -> list[dict]:
    """全従業員の個人別年末調整結果リストを返す（employee_id 昇順）。

    Args:
        batch_results: {employee_id: YearEndAdjustmentResult} の dict

    Returns:
        各従業員の計算結果 dict のリスト
    """
    rows = []
    for emp_id, result in sorted(batch_results.items()):
        rows.append({
            "employee_id": emp_id,
            "employee_name": result.employee_name,
            "tax_year": result.tax_year,
            "salary_income": result.salary_income,
            "employment_income": result.employment_income,
            "total_deductions": result.total_deductions,
            "income_tax": result.income_tax,
            "reconstruction_tax": result.reconstruction_tax,
            "housing_loan_deduction": result.housing_loan_deduction,
            "final_tax": result.final_tax,
            "basic_deduction": result.basic_deduction,
            "spouse_deduction": result.spouse_deduction,
            "dependent_count": result.dependent_count,
            "social_insurance_paid": result.social_insurance_paid,
            "life_insurance_deduction": result.life_insurance_deduction,
            "earthquake_deduction": result.earthquake_deduction,
            "income_adjustment_deduction": result.income_adjustment_deduction,
        })
    return rows


def serialize_report_to_csv(employee_rows: list[dict]) -> str:
    """従業員年末調整結果リストをCSV文字列にシリアライズする。

    Args:
        employee_rows: compute_employee_report_list() の返値

    Returns:
        UTF-8 CSVテキスト（ヘッダー行 + データ行。BOMなし）
    """
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=EXPORT_FIELDS,
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in employee_rows:
        writer.writerow(row)
    return output.getvalue()
