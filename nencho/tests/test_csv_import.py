"""tests/test_csv_import.py

CSV一括インポート API エンドポイントのテスト

対象エンドポイント:
  GET  /api/csv/template          - テンプレートダウンロード
  POST /api/csv/import/employees  - CSV一括インポート

対象サービス関数:
  generate_csv_template()
  parse_csv_employees()

テスト設計方針:
  - tmpdir の SecureStore を使用（実ファイルを汚染しない）
  - テンプレートは全必須列を含む事を確認
  - 正常CSV・不正CSV・バリデーションエラー・認証エラーを網羅
  - CP-7: 実DBは tmp_path 内のみ使用

テスト一覧（9件）:
  TestGenerateCsvTemplate:
    1. test_template_has_all_required_headers  - 全必須ヘッダー含む
    2. test_template_has_sample_row            - サンプル行が1行ある
  TestParseCsvEmployees:
    3. test_parse_valid_single_row             - 正常1行
    4. test_parse_missing_required_column      - 必須列欠落→ヘッダーエラー
    5. test_parse_empty_employee_id            - employee_id 空→エラー
    6. test_parse_invalid_tax_year             - tax_year 不正（範囲外）
    7. test_parse_partial_success              - 正常行+エラー行の混在
  TestCsvImportApi:
    8. test_get_template_endpoint              - GET /api/csv/template 200
    9. test_post_import_valid_csv              - POST /api/csv/import/employees 正常

手計算根拠（山田太郎 給与500万・社保72万・令和7年）:
  給与所得控除 = 500万 × 20% + 44万 = 144万 → 給与所得 = 356万
  基礎控除 = 48万
  課税所得 = 356 - 48 - 72 = 236万（正常CSVと整合）
"""
from __future__ import annotations

import io
import textwrap

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.csv_service import (
    CSV_REQUIRED_FIELDS,
    generate_csv_template,
    parse_csv_employees,
)

client = TestClient(app)

_PASSWORD = "test_pass_csv"

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

_MINIMAL_CSV_HEADER = "employee_id,employee_name,tax_year,salary_income,social_insurance_paid"
_YAMADA_ROW = "EMP001,山田太郎,7,5000000,720000"


def _make_csv(*rows: str) -> str:
    """ヘッダー行 + データ行を結合した CSV 文字列を返す。"""
    return "\n".join([_MINIMAL_CSV_HEADER] + list(rows)) + "\n"


# ---------------------------------------------------------------------------
# TestGenerateCsvTemplate
# ---------------------------------------------------------------------------


class TestGenerateCsvTemplate:
    def test_template_has_all_required_headers(self):
        """生成されたテンプレートに全必須列が含まれる。

        根拠: CSV_REQUIRED_FIELDS = {employee_id, employee_name, tax_year,
              salary_income, social_insurance_paid} が全て含まれることを確認。
        """
        csv_text = generate_csv_template()
        first_line = csv_text.splitlines()[0]
        headers = set(first_line.split(","))
        assert CSV_REQUIRED_FIELDS.issubset(headers), (
            f"必須ヘッダーが欠落: {CSV_REQUIRED_FIELDS - headers}"
        )

    def test_template_has_sample_row(self):
        """テンプレートにはヘッダーの他にサンプル行が1行以上ある。

        根拠: _TEMPLATE_EXAMPLE が1行分として書き込まれるため、
              splitlines() の長さが2以上になる。
        """
        csv_text = generate_csv_template()
        lines = [ln for ln in csv_text.splitlines() if ln.strip()]
        assert len(lines) >= 2, "ヘッダー + サンプル行が必要"
        # サンプル行の employee_id が空でないことを確認
        data_line = lines[1]
        employee_id = data_line.split(",")[0]
        assert employee_id.strip() != ""


# ---------------------------------------------------------------------------
# TestParseCsvEmployees
# ---------------------------------------------------------------------------


class TestParseCsvEmployees:
    def test_parse_valid_single_row(self):
        """正常な1行CSVを解析すると success=1, errors=0 になる。

        根拠: EMP001 / 山田太郎 / tax_year=7(令和7年, 有効範囲1-20) /
              salary_income=5000000(正) / social_insurance_paid=720000(正)
              → 全必須フィールド充足・ドメインバリデーション通過
        """
        csv_text = _make_csv(_YAMADA_ROW)
        result = parse_csv_employees(csv_text)
        assert len(result.success) == 1, f"errors: {result.errors}"
        assert len(result.errors) == 0
        assert result.success[0].employee_id == "EMP001"

    def test_parse_missing_required_column(self):
        """必須列 salary_income が欠落しているとヘッダーエラー(row=0)になる。

        根拠: CSV_REQUIRED_FIELDS に salary_income が含まれ、
              parse_csv_employees は欠落列をrow=0のエラーとして返す。
        """
        bad_csv = "employee_id,employee_name,tax_year,social_insurance_paid\n"
        bad_csv += "EMP001,山田太郎,7,720000\n"
        result = parse_csv_employees(bad_csv)
        assert len(result.success) == 0
        assert len(result.errors) == 1
        assert result.errors[0].row == 0  # ヘッダーエラー
        assert "salary_income" in result.errors[0].message

    def test_parse_empty_employee_id(self):
        """employee_id が空白の行はエラーになる。

        根拠: employee_id は SecureStore のキーになるため空は許容しない。
              parse_csv_employees でチェックし、employee_id="" のエラーを返す。
        """
        csv_text = _make_csv(",山田太郎,7,5000000,720000")
        result = parse_csv_employees(csv_text)
        assert len(result.success) == 0
        assert len(result.errors) == 1
        assert result.errors[0].employee_id == ""
        assert "employee_id" in result.errors[0].message

    def test_parse_invalid_tax_year(self):
        """tax_year が有効範囲外（令和1〜20以外）の行はエラーになる。

        根拠: validate_employee_input の税年度チェック。
              tax_year=99 → 令和20年(20)超 → バリデーションエラー。
        """
        csv_text = _make_csv("EMP001,山田太郎,99,5000000,720000")
        result = parse_csv_employees(csv_text)
        assert len(result.success) == 0
        assert len(result.errors) == 1
        assert "税年度" in result.errors[0].message or "バリデーション" in result.errors[0].message

    def test_parse_partial_success(self):
        """正常行とエラー行が混在している場合、それぞれ正しく分類される。

        根拠:
          行2 EMP001: 全フィールド正常 → success
          行3 EMP002: employee_id 空 → error
          行4 EMP003: tax_year=0（令和1年未満） → validate_employee_input エラー
          合計: success=1, errors=2
        """
        csv_text = textwrap.dedent("""\
            employee_id,employee_name,tax_year,salary_income,social_insurance_paid
            EMP001,山田太郎,7,5000000,720000
            ,鈴木花子,7,4000000,576000
            EMP003,田中一郎,0,3000000,432000
        """)
        result = parse_csv_employees(csv_text)
        assert len(result.success) == 1, f"success={result.success}, errors={result.errors}"
        assert len(result.errors) == 2
        success_ids = [s.employee_id for s in result.success]
        assert "EMP001" in success_ids


# ---------------------------------------------------------------------------
# TestCsvImportApi
# ---------------------------------------------------------------------------


class TestCsvImportApi:
    def test_get_template_endpoint(self):
        """GET /api/csv/template が 200 を返し CSV を含む。

        根拠: router に GET /api/csv/template が登録済み。
              Content-Type に text/csv が含まれる。
              ボディに必須ヘッダー列が含まれる。
        """
        resp = client.get("/api/csv/template")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        body = resp.text
        for field in CSV_REQUIRED_FIELDS:
            assert field in body, f"テンプレートに {field} が含まれていない"

    def test_post_import_valid_csv(self, tmp_path):
        """POST /api/csv/import/employees が正常CSVで imported_count=1 を返す。

        根拠:
          - 新規 tmp_path DB（存在しない場合は SecureStore が自動作成）
          - EMP001 1行を正常に登録
          - imported_count=1, error_count=0 であることを確認
        """
        db_path = str(tmp_path / "csv_test.db")
        csv_content = _make_csv(_YAMADA_ROW)
        csv_bytes = csv_content.encode("utf-8")

        resp = client.post(
            "/api/csv/import/employees",
            data={"db_path": db_path, "password": _PASSWORD},
            files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["imported_count"] == 1
        assert body["error_count"] == 0
        assert body["errors"] == []

    def test_post_import_wrong_password(self, tmp_path):
        """既存DBに対して誤パスワードで 401 が返る。

        根拠: SecureStore は誤パスワードで InvalidTag 例外を上げる。
              csv_import ルーターがそれを 401 に変換する。
        """
        from src.core.storage.secure_store import SecureStore

        db_path = tmp_path / "csv_auth_test.db"
        # 正しいパスワードでDB作成
        with SecureStore(db_path, _PASSWORD):
            pass

        csv_content = _make_csv(_YAMADA_ROW)
        csv_bytes = csv_content.encode("utf-8")

        resp = client.post(
            "/api/csv/import/employees",
            data={"db_path": str(db_path), "password": "wrong_password"},
            files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
        assert resp.status_code == 401

    def test_post_import_missing_required_column_returns_400(self, tmp_path):
        """必須列欠落のCSVで 400 が返る。

        根拠: parse_csv_employees が row=0 のエラーを返し、
              csv_import ルーターが HTTPException(400) に変換する。
        """
        db_path = str(tmp_path / "csv_400_test.db")
        bad_csv = "employee_id,employee_name,tax_year\nEMP001,山田太郎,7\n"
        csv_bytes = bad_csv.encode("utf-8")

        resp = client.post(
            "/api/csv/import/employees",
            data={"db_path": db_path, "password": _PASSWORD},
            files={"file": ("bad.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
        assert resp.status_code == 400
