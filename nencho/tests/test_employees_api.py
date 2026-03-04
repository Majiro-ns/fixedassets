"""tests/test_employees_api.py

従業員管理・一括計算 API エンドポイントのテスト

対象エンドポイント:
  POST /api/employees/list              - 従業員一覧
  POST /api/employees/{emp_id}/calculate - 個別計算
  POST /api/employees/batch-calculate   - 一括計算

テスト設計方針:
  - tmpdir の SecureStore を使用（実ファイルを汚染しない）
  - TestClient (HTTPX) でエンドポイントを直接呼び出す
  - 正常系・異常系（404/401/422）を網羅
  - 計算値の妥当性はドメイン知識で手確認

手計算根拠（山田太郎 給与500万・社保72万・令和7年）:
  給与所得控除 = 500万 × 20% + 44万 = 144万 → 給与所得 = 356万
  基礎控除 = 48万（合計所得356万超 → 通常控除）
  社保控除 = 72万
  課税所得 = 356 - 48 - 72 = 236万
  所得税 = 236万 × 10% - 97,500 = 138,500円（超過累進）
  復興税 = 138,500 × 2.1% ≈ 2,908円
  最終税額 ≈ 141,408円 (端数処理あり、± 数千円の誤差許容)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.core.storage.secure_store import SecureStore

client = TestClient(app)

_PASSWORD = "test_pass_employees"

_EMP_YAMADA = {
    "employee_name": "山田太郎",
    "tax_year": 7,
    "salary_income": 5_000_000,
    "social_insurance_paid": 720_000,
}
_EMP_SUZUKI = {
    "employee_name": "鈴木花子",
    "tax_year": 7,
    "salary_income": 4_000_000,
    "social_insurance_paid": 576_000,
}


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_two_employees(tmp_path):
    """山田太郎・鈴木花子が登録済みの SecureStore パスを返す。"""
    db_path = tmp_path / "nencho.db"
    with SecureStore(db_path, _PASSWORD) as store:
        store.save_employee("EMP001", _EMP_YAMADA)
        store.save_employee("EMP002", _EMP_SUZUKI)
    return str(db_path)


@pytest.fixture
def db_empty(tmp_path):
    """従業員なしの SecureStore パスを返す。"""
    db_path = tmp_path / "empty.db"
    with SecureStore(db_path, _PASSWORD):
        pass
    return str(db_path)


# ===========================================================================
# POST /api/employees/list
# ===========================================================================


class TestEmployeeList:
    """従業員一覧エンドポイントのテスト"""

    def test_list_two_employees(self, db_with_two_employees):
        """登録済み2件を返す。"""
        res = client.post(
            "/api/employees/list",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 2
        assert "EMP001" in data["employee_ids"]
        assert "EMP002" in data["employee_ids"]

    def test_list_empty_db(self, db_empty):
        """従業員なしのDBでは count=0・employee_ids=[] を返す。"""
        res = client.post(
            "/api/employees/list",
            json={"db_path": db_empty, "password": _PASSWORD},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 0
        assert data["employee_ids"] == []

    def test_list_wrong_password_returns_401(self, db_with_two_employees):
        """パスワード不正 → 401。"""
        res = client.post(
            "/api/employees/list",
            json={"db_path": db_with_two_employees, "password": "wrong_pass"},
        )
        assert res.status_code == 401

    def test_list_nonexistent_db_returns_404(self, tmp_path):
        """存在しない db_path → 404。"""
        res = client.post(
            "/api/employees/list",
            json={"db_path": str(tmp_path / "nonexistent.db"), "password": _PASSWORD},
        )
        assert res.status_code == 404

    def test_list_response_schema(self, db_with_two_employees):
        """レスポンスが employee_ids: list と count: int を持つ。"""
        res = client.post(
            "/api/employees/list",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        data = res.json()
        assert isinstance(data["employee_ids"], list)
        assert isinstance(data["count"], int)


# ===========================================================================
# POST /api/employees/{employee_id}/calculate
# ===========================================================================


class TestEmployeeCalculate:
    """個別従業員計算エンドポイントのテスト"""

    def test_calculate_employee_basic(self, db_with_two_employees):
        """EMP001（山田太郎）の計算結果が返る。"""
        res = client.post(
            "/api/employees/EMP001/calculate",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["employee_id"] == "EMP001"
        assert data["employee_name"] == "山田太郎"
        assert data["salary_income"] == 5_000_000
        assert data["final_tax"] >= 0

    def test_calculate_final_tax_roughly_correct(self, db_with_two_employees):
        """山田太郎の最終税額が手計算根拠と概ね一致する（±3万円許容）。

        手計算:
          給与所得 = 500万 - 144万（控除）= 356万
          課税所得 = 356 - 48（基礎）- 72（社保） = 236万
          所得税 ≈ 138,500円（超過累進）
          最終税額（復興税込） ≈ 141,408円
        """
        res = client.post(
            "/api/employees/EMP001/calculate",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        data = res.json()
        # ±30,000円の範囲に収まれば合格
        assert 110_000 <= data["final_tax"] <= 175_000, (
            f"山田太郎の最終税額が想定範囲外: {data['final_tax']}円"
        )

    def test_calculate_response_has_all_fields(self, db_with_two_employees):
        """レスポンスに必要フィールドが全て含まれる。"""
        res = client.post(
            "/api/employees/EMP001/calculate",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        data = res.json()
        required_fields = [
            "employee_id", "employee_name", "tax_year",
            "salary_income", "employment_income", "total_deductions",
            "income_tax", "reconstruction_tax", "housing_loan_deduction",
            "final_tax", "basic_deduction", "spouse_deduction",
            "dependent_count", "social_insurance_paid",
            "life_insurance_deduction", "earthquake_deduction",
            "income_adjustment_deduction",
        ]
        for field in required_fields:
            assert field in data, f"レスポンスに '{field}' がない"

    def test_calculate_nonexistent_employee_returns_404(self, db_with_two_employees):
        """未登録 employee_id → 404。"""
        res = client.post(
            "/api/employees/NONEXISTENT/calculate",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        assert res.status_code == 404

    def test_calculate_wrong_password_returns_401(self, db_with_two_employees):
        """パスワード不正 → 401。"""
        res = client.post(
            "/api/employees/EMP001/calculate",
            json={"db_path": db_with_two_employees, "password": "bad_pass"},
        )
        assert res.status_code == 401

    def test_calculate_second_employee(self, db_with_two_employees):
        """EMP002（鈴木花子）も計算できる。"""
        res = client.post(
            "/api/employees/EMP002/calculate",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["employee_id"] == "EMP002"
        assert data["employee_name"] == "鈴木花子"
        assert data["salary_income"] == 4_000_000


# ===========================================================================
# POST /api/employees/batch-calculate
# ===========================================================================


class TestBatchCalculate:
    """一括計算エンドポイントのテスト"""

    def test_batch_all_employees(self, db_with_two_employees):
        """emp_ids 省略 → 全2件を計算する。"""
        res = client.post(
            "/api/employees/batch-calculate",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success_count"] == 2
        assert data["total_count"] == 2
        assert len(data["results"]) == 2

    def test_batch_partial_emp_ids(self, db_with_two_employees):
        """emp_ids 指定 → 指定分のみ計算する。"""
        res = client.post(
            "/api/employees/batch-calculate",
            json={
                "db_path": db_with_two_employees,
                "password": _PASSWORD,
                "emp_ids": ["EMP001"],
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success_count"] == 1
        emp_ids_in_result = [r["employee_id"] for r in data["results"]]
        assert "EMP001" in emp_ids_in_result
        assert "EMP002" not in emp_ids_in_result

    def test_batch_empty_db(self, db_empty):
        """従業員なし → results=[]・success_count=0。"""
        res = client.post(
            "/api/employees/batch-calculate",
            json={"db_path": db_empty, "password": _PASSWORD},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success_count"] == 0
        assert data["total_count"] == 0
        assert data["results"] == []

    def test_batch_results_sorted_by_employee_id(self, db_with_two_employees):
        """結果が employee_id 昇順で返る。"""
        res = client.post(
            "/api/employees/batch-calculate",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        data = res.json()
        ids = [r["employee_id"] for r in data["results"]]
        assert ids == sorted(ids), f"employee_id 昇順でない: {ids}"

    def test_batch_each_result_has_final_tax(self, db_with_two_employees):
        """各結果に final_tax が含まれ、0以上である。"""
        res = client.post(
            "/api/employees/batch-calculate",
            json={"db_path": db_with_two_employees, "password": _PASSWORD},
        )
        data = res.json()
        for item in data["results"]:
            assert "final_tax" in item
            assert item["final_tax"] >= 0

    def test_batch_wrong_password_returns_401(self, db_with_two_employees):
        """パスワード不正 → 401。"""
        res = client.post(
            "/api/employees/batch-calculate",
            json={"db_path": db_with_two_employees, "password": "wrong"},
        )
        assert res.status_code == 401

    def test_batch_nonexistent_db_returns_404(self, tmp_path):
        """存在しない db_path → 404。"""
        res = client.post(
            "/api/employees/batch-calculate",
            json={"db_path": str(tmp_path / "nope.db"), "password": _PASSWORD},
        )
        assert res.status_code == 404

    def test_batch_nonexistent_emp_ids_skipped(self, db_with_two_employees):
        """存在しない emp_id は results から除外される。"""
        res = client.post(
            "/api/employees/batch-calculate",
            json={
                "db_path": db_with_two_employees,
                "password": _PASSWORD,
                "emp_ids": ["EMP001", "NONEXISTENT"],
            },
        )
        assert res.status_code == 200
        data = res.json()
        emp_ids = [r["employee_id"] for r in data["results"]]
        assert "EMP001" in emp_ids
        assert "NONEXISTENT" not in emp_ids

    def test_batch_total_count_reflects_registered(self, db_with_two_employees):
        """total_count は対象従業員数（存在するもの）を反映する。"""
        res = client.post(
            "/api/employees/batch-calculate",
            json={
                "db_path": db_with_two_employees,
                "password": _PASSWORD,
                "emp_ids": ["EMP001", "NONEXISTENT"],
            },
        )
        data = res.json()
        # EMP001 のみ存在 → total=1
        assert data["total_count"] == 1
