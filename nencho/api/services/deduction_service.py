"""扶養控除額自動計算サービス

src.core.calculation.{deductions, allowances} を活用して
従業員データ + 扶養親族リスト（T010）から控除額を計算する純粋関数群。

令和7年（2025年）税制改正後の計算を使用:
  - 基礎控除: 58万円（合計所得655万円以下は上乗せ特例あり）
    ※ タスク仕様記載の「48万円」は改正前の値。改正後は58万が正しい。
  - 扶養控除: 一般38万 / 特定(19〜22歳)63万 / 老人48万 / 同居老親58万
  - 配偶者控除: 最大38万（本人所得900万以下・配偶者所得48万以下）
  - 配偶者特別控除: 配偶者所得48万超〜133万以下の場合に適用

TV-4 verification_source:
  - 国税庁 No.1180 扶養控除
    https://www.nta.go.jp/taxanswer/shotoku/1180.htm
  - 国税庁 No.1191 配偶者控除
    https://www.nta.go.jp/taxanswer/shotoku/1191.htm
  - 国税庁 令和7年分 基礎控除の改正内容
    https://www.nta.go.jp/users/gensen/2025kiso/index.htm
"""
from __future__ import annotations

from src.core.calculation.allowances import (
    DependentPerson,
    calc_dependent_deduction,
    calc_spouse_deduction,
    calc_spouse_special_deduction,
)
from src.core.calculation.deductions import (
    TaxYear,
    calc_basic_deduction,
    calc_employment_income,
)


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

# 令和N年 → 西暦 変換定数
_REIWA_OFFSET = 2018  # 令和1年 = 2019年 = 1 + 2018


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _to_bool(val) -> bool:
    """bool / 文字列 "true"/"false" を bool に変換する。"""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return bool(val)


def _resolve_tax_year(tax_year_n: int) -> TaxYear:
    """令和N年のN → TaxYear に変換する。

    現在 TaxYear.R7（令和7年）のみ実装済み。
    その他の年度は R7 にフォールバックする（近年は同じ税制を使用）。
    """
    return TaxYear.R7


def _calendar_year(tax_year_n: int) -> int:
    """令和N年のN → 西暦年を返す。"""
    return _REIWA_OFFSET + tax_year_n


def _dependents_to_persons(dependents: list[dict], cal_year: int) -> list[DependentPerson]:
    """扶養親族 dict リスト → DependentPerson リスト変換（配偶者を除く）。

    age = cal_year - birth_year（12月31日時点の年齢）
    birth_year == 0（不明）の場合は一般扶養（age=25）として処理する。
    """
    persons = []
    for dep in dependents:
        if dep.get("relation") == "spouse":
            continue  # 配偶者は別途処理
        birth_year = int(dep.get("birth_year", 0))
        if birth_year == 0 or birth_year >= cal_year:
            # 生年不明 or 未来生まれ → 一般扶養（GENERAL）として計上
            persons.append(DependentPerson.from_age(25))
        else:
            age = cal_year - birth_year
            persons.append(DependentPerson.from_age(age))
    return persons


def _find_spouse(dependents: list[dict], employee_data: dict) -> tuple[bool, int]:
    """配偶者の有無と所得金額を返す。

    優先度:
      1. dependents リスト（T010）に relation="spouse" があれば使用
      2. employee_data の has_spouse / spouse_income をフォールバック

    Returns:
        (has_spouse: bool, spouse_income: int)
    """
    for dep in dependents:
        if dep.get("relation") == "spouse":
            return True, int(dep.get("income", 0))

    # フォールバック: EmployeeInput の has_spouse / spouse_income
    if _to_bool(employee_data.get("has_spouse", False)):
        return True, int(employee_data.get("spouse_income", 0))

    return False, 0


# ---------------------------------------------------------------------------
# メイン計算関数
# ---------------------------------------------------------------------------

def compute_deductions(employee_data: dict, dependents: list[dict]) -> dict:
    """従業員データと扶養親族リストから控除額を計算する。

    Args:
        employee_data: SecureStore から取得した従業員データ dict
        dependents: T010 形式の扶養親族 dict リスト

    Returns:
        dict with keys:
          basic_deduction         : 基礎控除額（令和7年改正後）
          dependent_deduction     : 扶養控除額（配偶者除く）
          spouse_deduction        : 配偶者控除額
          spouse_special_deduction: 配偶者特別控除額（配偶者控除と排他）
          total_deduction         : 合計控除額
          employment_income       : 給与所得（基礎控除計算の中間値）
          tax_year                : 適用年度（例: "R7"）

    CHECK-7b 手計算例（salary=5,000,000 / tax_year=7）:
      給与所得控除 = 5,000,000 × 20% + 440,000 = 1,440,000
      給与所得 = 5,000,000 - 1,440,000 = 3,560,000
      合計所得3,560,000: 336万超〜489万以下 → 基礎控除 = 58万+10万 = 68万 ✓
    """
    salary_income = int(employee_data.get("salary_income", 0))
    tax_year_n = int(employee_data.get("tax_year", 7))
    cal_year = _calendar_year(tax_year_n)
    tax_year = _resolve_tax_year(tax_year_n)

    # 給与所得（基礎控除の計算基準）
    employment_income = calc_employment_income(salary_income, tax_year)

    # 基礎控除（令和7年改正後: 58万+上乗せ特例）
    basic_result = calc_basic_deduction(employment_income, tax_year)
    basic_deduction = basic_result.total_amount

    # 扶養控除（配偶者除く。年齢に応じて38万/63万/48万/0円）
    dep_persons = _dependents_to_persons(dependents, cal_year)
    dependent_deduction = calc_dependent_deduction(dep_persons, tax_year)

    # 配偶者控除 / 配偶者特別控除
    has_spouse, spouse_income = _find_spouse(dependents, employee_data)
    spouse_deduction = 0
    spouse_special_deduction = 0
    if has_spouse:
        spouse_deduction = calc_spouse_deduction(
            taxpayer_total_income=employment_income,
            spouse_total_income=spouse_income,
            tax_year=tax_year,
        )
        spouse_special_deduction = calc_spouse_special_deduction(
            taxpayer_total_income=employment_income,
            spouse_total_income=spouse_income,
            tax_year=tax_year,
        )

    total_deduction = (
        basic_deduction
        + dependent_deduction
        + spouse_deduction
        + spouse_special_deduction
    )

    return {
        "basic_deduction": basic_deduction,
        "dependent_deduction": dependent_deduction,
        "spouse_deduction": spouse_deduction,
        "spouse_special_deduction": spouse_special_deduction,
        "total_deduction": total_deduction,
        "employment_income": employment_income,
        "tax_year": tax_year.name,
    }
