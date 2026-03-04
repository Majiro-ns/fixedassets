"""tests/test_deductions_api.py

扶養控除額自動計算 API のテスト

対象エンドポイント:
  POST /api/deductions/calculate/{emp_id} - 控除額計算
  POST /api/deductions/summary            - 全従業員サマリー

対象サービス関数:
  compute_deductions()

TV-4 verification_source:
  - 国税庁 No.1180 扶養控除 https://www.nta.go.jp/taxanswer/shotoku/1180.htm
  - 国税庁 No.1191 配偶者控除 https://www.nta.go.jp/taxanswer/shotoku/1191.htm
  - 国税庁 令和7年分 基礎控除改正 https://www.nta.go.jp/users/gensen/2025kiso/index.htm

テスト一覧（10件）:
  TestComputeDeductionsService:
    1. test_basic_deduction_standard_income    - 基礎控除 令和7年改正後（58万+10万=68万）手計算
    2. test_basic_deduction_low_income         - 低所得: 132万以下 → 58万+37万=95万
    3. test_no_dependents                      - 扶養なし → 扶養控除0
    4. test_specific_dependent_19_to_22        - 特定扶養（19〜22歳）→ 63万
    5. test_general_dependent_over_23          - 一般扶養（23〜69歳）→ 38万
    6. test_minor_dependent_under_16           - 年少扶養（16歳未満）→ 0円（控除対象外）
    7. test_spouse_deduction_standard          - 配偶者(income=0, taxpayer<900万) → 38万
    8. test_spouse_deduction_high_income       - 本人所得>1000万 → 配偶者控除0
  TestDeductionsApi:
    9. test_calculate_endpoint                 - POST /api/deductions/calculate/{emp_id}
   10. test_summary_endpoint                   - POST /api/deductions/summary

手計算検証（TV-4 根拠付き）:
  salary=5,000,000 / tax_year=7（令和7年=2025年）:
    給与所得控除 = 5,000,000×20% + 440,000 = 1,440,000
      (根拠: 給与収入360万超660万以下: 収入×20%+44万 / 国税庁給与所得控除額表)
    給与所得 = 5,000,000 - 1,440,000 = 3,560,000
    合計所得3,560,000: 336万超〜489万以下 → 基礎控除 = 58万+10万 = 68万
      (根拠: 令和7年改正後テーブル / 国税庁令和7年分基礎控除改正内容)
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.deduction_service import compute_deductions
from api.services.dependent_service import add_dependent
from src.core.storage.secure_store import SecureStore

client = TestClient(app)

_PASSWORD = "test_pass_ded"

# ---------------------------------------------------------------------------
# テストデータ
# ---------------------------------------------------------------------------

_EMP_YAMADA = {
    "employee_name": "山田太郎",
    "tax_year": 7,
    "salary_income": 5_000_000,
    "social_insurance_paid": 720_000,
    "has_spouse": False,
}

_EMP_SUZUKI = {
    "employee_name": "鈴木花子",
    "tax_year": 7,
    "salary_income": 4_000_000,
    "social_insurance_paid": 576_000,
    "has_spouse": False,
}

# 特定扶養（2025年に20歳 → birth_year=2005）
_DEP_SPECIFIC = {"dep_name": "山田二郎", "relation": "child", "birth_year": 2005, "income": 0}
# 一般扶養（2025年に45歳 → birth_year=1980）
_DEP_GENERAL = {"dep_name": "山田三郎", "relation": "parent", "birth_year": 1980, "income": 0}
# 年少扶養（2025年に10歳 → birth_year=2015）
_DEP_MINOR = {"dep_name": "山田四郎", "relation": "child", "birth_year": 2015, "income": 0}
# 配偶者（income=0: 非課税）
_DEP_SPOUSE = {"dep_name": "山田花子", "relation": "spouse", "birth_year": 1990, "income": 0}


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture
def db_yamada(tmp_path):
    """山田太郎（扶養なし）が登録済みの SecureStore パスを返す。"""
    db_path = tmp_path / "ded_test.db"
    with SecureStore(db_path, _PASSWORD) as store:
        store.save_employee("EMP001", _EMP_YAMADA)
    return db_path


@pytest.fixture
def db_two_employees(tmp_path):
    """山田太郎・鈴木花子が登録済みの SecureStore パスを返す。"""
    db_path = tmp_path / "ded_two.db"
    with SecureStore(db_path, _PASSWORD) as store:
        store.save_employee("EMP001", _EMP_YAMADA)
        store.save_employee("EMP002", _EMP_SUZUKI)
    return db_path


# ---------------------------------------------------------------------------
# TestComputeDeductionsService — 純粋関数テスト
# ---------------------------------------------------------------------------


class TestComputeDeductionsService:
    def test_basic_deduction_standard_income(self):
        """salary=5,000,000 → 給与所得3,560,000 → 基礎控除68万（令和7年改正後）。

        手計算（TV-4 根拠: 国税庁令和7年分基礎控除改正内容）:
          給与所得控除 = 5,000,000×20% + 440,000 = 1,440,000
          給与所得 = 5,000,000 - 1,440,000 = 3,560,000
          合計所得3,560,000（336万超489万以下）
            → 基礎控除 = 580,000 + 100,000 = 680,000円 ✓
        """
        result = compute_deductions(_EMP_YAMADA, [])
        assert result["employment_income"] == 3_560_000  # 手計算 ✓
        assert result["basic_deduction"] == 680_000       # 58万+10万=68万 ✓

    def test_basic_deduction_low_income(self):
        """salary=1,000,000 → 給与所得450,000 → 基礎控除95万（132万以下）。

        手計算（TV-4 根拠: 国税庁令和7年分基礎控除改正内容）:
          給与収入1,000,000 ≤ 1,625,000 → 給与所得控除=550,000
          給与所得 = max(0, 1,000,000 - 550,000) = 450,000
          合計所得450,000 ≤ 1,320,000（132万以下）
            → 基礎控除 = 580,000 + 370,000 = 950,000円 ✓
        """
        emp = {**_EMP_YAMADA, "salary_income": 1_000_000}
        result = compute_deductions(emp, [])
        assert result["employment_income"] == 450_000    # 手計算 ✓
        assert result["basic_deduction"] == 950_000      # 58万+37万=95万 ✓

    def test_no_dependents(self):
        """扶養親族なし → 扶養控除・配偶者控除ともに0。"""
        result = compute_deductions(_EMP_YAMADA, [])
        assert result["dependent_deduction"] == 0
        assert result["spouse_deduction"] == 0
        assert result["spouse_special_deduction"] == 0

    def test_specific_dependent_19_to_22(self):
        """特定扶養（2005年生 = 2025年に20歳）→ 扶養控除63万。

        根拠（TV-4 / 国税庁 No.1180）:
          19歳〜22歳 = 特定扶養親族 → 控除額 630,000円 ✓
        """
        result = compute_deductions(_EMP_YAMADA, [_DEP_SPECIFIC])
        assert result["dependent_deduction"] == 630_000  # 特定扶養63万 ✓

    def test_general_dependent_over_23(self):
        """一般扶養（1980年生 = 2025年に45歳）→ 扶養控除38万。

        根拠（TV-4 / 国税庁 No.1180）:
          23歳〜69歳 = 一般扶養親族 → 控除額 380,000円 ✓
        """
        result = compute_deductions(_EMP_YAMADA, [_DEP_GENERAL])
        assert result["dependent_deduction"] == 380_000  # 一般扶養38万 ✓

    def test_minor_dependent_under_16(self):
        """年少扶養（2015年生 = 2025年に10歳）→ 扶養控除0円（控除対象外）。

        根拠（TV-4 / 国税庁 No.1180）:
          16歳未満 = 年少扶養（扶養控除の対象外）→ 控除額 0円 ✓
          ※ 児童手当の対象になるため扶養控除は廃止されている
        """
        result = compute_deductions(_EMP_YAMADA, [_DEP_MINOR])
        assert result["dependent_deduction"] == 0  # 年少扶養は控除対象外 ✓

    def test_spouse_deduction_standard(self):
        """配偶者(income=0) / 本人所得3,560,000（900万以下）→ 配偶者控除38万。

        根拠（TV-4 / 国税庁 No.1191）:
          配偶者合計所得 0 ≤ 480,000（48万以下）
          本人合計所得 3,560,000 ≤ 9,000,000（900万以下）
            → 配偶者控除 = 380,000円 ✓
        """
        result = compute_deductions(_EMP_YAMADA, [_DEP_SPOUSE])
        assert result["spouse_deduction"] == 380_000     # 配偶者控除38万 ✓
        assert result["spouse_special_deduction"] == 0   # 配偶者特別控除は適用なし ✓

    def test_spouse_deduction_high_income(self):
        """本人所得>1000万 → 配偶者控除0円。

        根拠（TV-4 / 国税庁 No.1191）:
          本人合計所得 > 10,000,000（1000万超）→ 配偶者控除 = 0円 ✓
          給与収入13,000,000 → 給与所得 = 13,000,000 - 1,950,000 = 11,050,000 > 10,000,000
        """
        emp = {**_EMP_YAMADA, "salary_income": 13_000_000}
        result = compute_deductions(emp, [_DEP_SPOUSE])
        # 給与所得 = 13,000,000 - 1,950,000 = 11,050,000 > 10,000,000
        assert result["employment_income"] == 11_050_000  # 手計算 ✓
        assert result["spouse_deduction"] == 0             # 1000万超 → 0 ✓


# ---------------------------------------------------------------------------
# TestDeductionsApi — APIエンドポイントテスト
# ---------------------------------------------------------------------------


class TestDeductionsApi:
    def test_calculate_endpoint(self, db_yamada):
        """POST /api/deductions/calculate/{emp_id} が 200 を返し正しい控除額を返す。

        根拠: salary=5,000,000 → basic_deduction=680,000 (手計算済み)
        """
        resp = client.post(
            "/api/deductions/calculate/EMP001",
            json={"db_path": str(db_yamada), "password": _PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["emp_id"] == "EMP001"
        assert body["basic_deduction"] == 680_000   # 手計算 ✓
        assert body["dependent_deduction"] == 0     # 扶養なし ✓
        assert body["spouse_deduction"] == 0        # 配偶者なし ✓

    def test_summary_endpoint(self, db_two_employees):
        """POST /api/deductions/summary が 200 を返し total_employees=2 になる。

        根拠: db_two_employees に EMP001・EMP002 の2名が登録済み。
              emp_id昇順なので results[0]=EMP001, results[1]=EMP002。
        """
        resp = client.post(
            "/api/deductions/summary",
            json={"db_path": str(db_two_employees), "password": _PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_employees"] == 2
        assert body["error_count"] == 0
        assert body["results"][0]["emp_id"] == "EMP001"   # 昇順 ✓
        assert body["results"][1]["emp_id"] == "EMP002"
        # EMP001: salary=5M → basic=68万
        assert body["results"][0]["basic_deduction"] == 680_000
