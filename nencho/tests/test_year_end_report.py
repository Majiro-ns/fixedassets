"""tests/test_year_end_report.py

年末調整集計レポート API エンドポイントのテスト

対象エンドポイント:
  POST /api/reports/year-end/summary    - サマリー集計
  POST /api/reports/year-end/employees  - 個人別一覧
  POST /api/reports/year-end/export/csv - CSV出力

対象サービス関数:
  compute_year_end_summary()
  compute_employee_report_list()
  serialize_report_to_csv()

テスト設計方針:
  - tmpdir の SecureStore を使用（実ファイルを汚染しない）
  - TestClient (HTTPX) でエンドポイントを直接呼び出す
  - サービス関数の純粋関数テスト（DBなし）を優先
  - 正常系・異常系（空DB/401）を網羅

テスト一覧（9件）:
  TestComputeYearEndSummary:
    1. test_summary_empty                - 空resultは全ゼロ
    2. test_summary_two_employees        - 2名の集計値を手計算で検証
  TestComputeEmployeeReportList:
    3. test_employee_list_sorted         - employee_id昇順ソート確認
    4. test_employee_list_fields         - 必須フィールドが全て含まれる
  TestSerializeReportToCsv:
    5. test_csv_has_header               - ヘッダー行が存在する
    6. test_csv_row_count                - データ行数が一致する
  TestYearEndReportApi:
    7. test_summary_endpoint             - POST /year-end/summary 正常
    8. test_employees_endpoint           - POST /year-end/employees 正常
    9. test_export_csv_endpoint          - POST /year-end/export/csv 正常

手計算根拠（山田太郎 給与500万・社保72万・令和7年）:
  給与所得控除 = 500万 × 20% + 44万 = 144万 → 給与所得 = 356万
  基礎控除 = 48万
  課税所得 = 356 - 48 - 72 = 236万
  所得税 = 236万 × 10% - 97,500 = 138,500円
  復興税 = 138,500 × 2.1% ≈ 2,908円
  final_tax ≈ 141,408円 → > 0 → 追加徴収
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.year_end_report_service import (
    EXPORT_FIELDS,
    compute_employee_report_list,
    compute_year_end_summary,
    serialize_report_to_csv,
)
from src.core.storage.secure_store import SecureStore

client = TestClient(app)

_PASSWORD = "test_pass_report"

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
def db_two_employees(tmp_path):
    """山田太郎・鈴木花子が登録済みの SecureStore パスを返す。"""
    db_path = tmp_path / "report_test.db"
    with SecureStore(db_path, _PASSWORD) as store:
        store.save_employee("EMP001", _EMP_YAMADA)
        store.save_employee("EMP002", _EMP_SUZUKI)
    return db_path


@pytest.fixture
def db_empty(tmp_path):
    """従業員ゼロの SecureStore パスを返す。"""
    db_path = tmp_path / "empty_report.db"
    with SecureStore(db_path, _PASSWORD):
        pass  # DB作成のみ（従業員登録なし）
    return db_path


# ---------------------------------------------------------------------------
# モック YearEndAdjustmentResult（純粋関数テスト用）
# ---------------------------------------------------------------------------


class _MockResult:
    """YearEndAdjustmentResult のモック（サービス関数のテスト用）。"""

    def __init__(self, **kwargs):
        defaults = {
            "employee_name": "テスト太郎",
            "tax_year": 7,
            "salary_income": 5_000_000,
            "employment_income": 3_560_000,
            "total_deductions": 1_680_000,
            "income_tax": 138_500,
            "reconstruction_tax": 2_908,
            "housing_loan_deduction": 0,
            "final_tax": 141_408,
            "basic_deduction": 480_000,
            "spouse_deduction": 0,
            "dependent_count": 0,
            "social_insurance_paid": 720_000,
            "life_insurance_deduction": 0,
            "earthquake_deduction": 0,
            "income_adjustment_deduction": 0,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# TestComputeYearEndSummary
# ---------------------------------------------------------------------------


class TestComputeYearEndSummary:
    def test_summary_empty(self):
        """空の batch_results は全ゼロのサマリーを返す。

        根拠: ZeroDivisionError を防ぐための空ハンドリング。
              total_count=0 のとき avg 計算は不能なので全ゼロで返す。
        """
        summary = compute_year_end_summary({})
        assert summary["total_count"] == 0
        assert summary["avg_salary_income"] == 0
        assert summary["avg_income_tax"] == 0
        assert summary["refund_count"] == 0
        assert summary["additional_count"] == 0

    def test_summary_two_employees(self):
        """2名分の集計値を手計算で検証する。

        根拠（手計算）:
          EMP001: salary=5,000,000, income_tax=138,500, final_tax=141,408 > 0
          EMP002: salary=4,000,000, income_tax=100,000, final_tax=102,100 > 0
          total_count = 2
          avg_salary = (5,000,000 + 4,000,000) // 2 = 4,500,000
          total_salary = 9,000,000
          refund_count = 0 (どちらも final_tax > 0)
          additional_count = 2
        """
        batch = {
            "EMP001": _MockResult(salary_income=5_000_000, income_tax=138_500, final_tax=141_408),
            "EMP002": _MockResult(salary_income=4_000_000, income_tax=100_000, final_tax=102_100),
        }
        s = compute_year_end_summary(batch)
        assert s["total_count"] == 2
        assert s["avg_salary_income"] == 4_500_000  # (5M+4M)//2=4.5M ✓
        assert s["total_salary_income"] == 9_000_000  # 5M+4M ✓
        assert s["refund_count"] == 0   # どちらも final_tax > 0 ✓
        assert s["additional_count"] == 2  # 両名とも final_tax > 0 ✓


# ---------------------------------------------------------------------------
# TestComputeEmployeeReportList
# ---------------------------------------------------------------------------


class TestComputeEmployeeReportList:
    def test_employee_list_sorted(self):
        """employee_id 昇順でソートされる。

        根拠: compute_employee_report_list は sorted(batch_results.items())
              を使用するため、EMP001 が EMP002 より先に来る。
        """
        batch = {
            "EMP002": _MockResult(employee_name="鈴木花子"),
            "EMP001": _MockResult(employee_name="山田太郎"),
        }
        rows = compute_employee_report_list(batch)
        assert len(rows) == 2
        assert rows[0]["employee_id"] == "EMP001"
        assert rows[1]["employee_id"] == "EMP002"

    def test_employee_list_fields(self):
        """全必須フィールドが含まれる。

        根拠: EXPORT_FIELDS の全フィールドが compute_employee_report_list の
              返値 dict に含まれることを確認。employee_id は EXPORT_FIELDS に含まれる。
        """
        batch = {"EMP001": _MockResult()}
        rows = compute_employee_report_list(batch)
        assert len(rows) == 1
        row = rows[0]
        for field in EXPORT_FIELDS:
            assert field in row, f"フィールド {field} が欠落"


# ---------------------------------------------------------------------------
# TestSerializeReportToCsv
# ---------------------------------------------------------------------------


class TestSerializeReportToCsv:
    def test_csv_has_header(self):
        """CSVの先頭行はヘッダー行である。

        根拠: serialize_report_to_csv は DictWriter.writeheader() を呼ぶため
              1行目は EXPORT_FIELDS のカンマ結合になる。
        """
        rows = [{"employee_id": "EMP001", **{f: 0 for f in EXPORT_FIELDS if f != "employee_id" and f != "employee_name"}, "employee_name": "山田太郎", "tax_year": 7}]
        # 実際の compute_employee_report_list の返値形式で渡す
        batch = {"EMP001": _MockResult()}
        report_rows = compute_employee_report_list(batch)
        csv_text = serialize_report_to_csv(report_rows)
        first_line = csv_text.splitlines()[0]
        assert "employee_id" in first_line
        assert "salary_income" in first_line
        assert "final_tax" in first_line

    def test_csv_row_count(self):
        """データ行数が従業員数と一致する。

        根拠: 2名 → ヘッダー1行 + データ2行 = 3行。
              空行は除いて確認。
        """
        batch = {
            "EMP001": _MockResult(employee_name="山田太郎"),
            "EMP002": _MockResult(employee_name="鈴木花子"),
        }
        rows = compute_employee_report_list(batch)
        csv_text = serialize_report_to_csv(rows)
        non_empty_lines = [ln for ln in csv_text.splitlines() if ln.strip()]
        assert len(non_empty_lines) == 3  # ヘッダー + 2件 ✓


# ---------------------------------------------------------------------------
# TestYearEndReportApi
# ---------------------------------------------------------------------------


class TestYearEndReportApi:
    def test_summary_endpoint(self, db_two_employees):
        """POST /api/reports/year-end/summary が 200 を返し total_count=2 になる。

        根拠:
          db_two_employees に山田太郎・鈴木花子の2名が登録済み。
          run_batch() で2名分を計算 → total_count=2
          山田・鈴木ともに final_tax > 0 → additional_count=2, refund_count=0
        """
        resp = client.post(
            "/api/reports/year-end/summary",
            json={"db_path": str(db_two_employees), "password": _PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_count"] == 2
        assert body["additional_count"] == 2  # 両名 final_tax > 0 ✓
        assert body["refund_count"] == 0
        assert body["total_salary_income"] == 9_000_000  # 5M + 4M ✓

    def test_employees_endpoint(self, db_two_employees):
        """POST /api/reports/year-end/employees が 200 を返し 2件の結果を返す。

        根拠: db_two_employees に2名登録済み → employees 2件 (EMP001, EMP002)。
              employee_id 昇順なので EMP001 が先頭。
        """
        resp = client.post(
            "/api/reports/year-end/employees",
            json={"db_path": str(db_two_employees), "password": _PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_count"] == 2
        assert len(body["employees"]) == 2
        # employee_id昇順確認
        assert body["employees"][0]["employee_id"] == "EMP001"
        assert body["employees"][1]["employee_id"] == "EMP002"

    def test_export_csv_endpoint(self, db_two_employees):
        """POST /api/reports/year-end/export/csv が 200 を返しCSVを含む。

        根拠: db_two_employees に2名登録済み。
              ヘッダー行 + データ2行 = 計3行以上。
              Content-Type に text/csv が含まれる。
        """
        resp = client.post(
            "/api/reports/year-end/export/csv",
            json={"db_path": str(db_two_employees), "password": _PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        assert "text/csv" in resp.headers["content-type"]
        lines = [ln for ln in resp.text.splitlines() if ln.strip()]
        assert len(lines) >= 3  # ヘッダー + 2件以上 ✓
        assert "employee_id" in lines[0]  # ヘッダー行確認

    def test_summary_wrong_password(self, db_two_employees):
        """誤パスワードで 401 が返る。"""
        resp = client.post(
            "/api/reports/year-end/summary",
            json={"db_path": str(db_two_employees), "password": "wrong"},
        )
        assert resp.status_code == 401

    def test_summary_empty_db(self, db_empty):
        """従業員ゼロのDBでも 200 を返し total_count=0 になる。

        根拠: compute_year_end_summary は空 dict を受け取ると全ゼロを返す設計。
              空DB → run_batch → {} → summary 全ゼロ。
        """
        resp = client.post(
            "/api/reports/year-end/summary",
            json={"db_path": str(db_empty), "password": _PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_count"] == 0
        assert body["avg_salary_income"] == 0
