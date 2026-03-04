"""tests/test_dependents.py

扶養控除申告書管理 API エンドポイントのテスト

対象エンドポイント:
  POST   /api/dependents/{emp_id}             - 扶養親族登録
  GET    /api/dependents/summary              - 全従業員扶養人数サマリー
  GET    /api/dependents/{emp_id}             - 扶養親族一覧
  DELETE /api/dependents/{emp_id}/{dep_index} - 扶養親族削除

対象サービス関数:
  validate_dependent()
  add_dependent()
  get_dependents()
  delete_dependent()

テスト一覧（10件）:
  TestDependentServiceFunctions:
    1. test_add_dependent_pure       - add_dependent() の純粋関数テスト
    2. test_delete_dependent_pure    - delete_dependent() の純粋関数テスト
    3. test_delete_out_of_range      - 範囲外インデックスで IndexError
    4. test_validate_invalid_relation - 無効な続柄でバリデーションエラー
    5. test_validate_negative_income  - 負の所得でバリデーションエラー
  TestDependentsApi:
    6. test_post_add_dependent        - POST /api/dependents/{emp_id} 正常
    7. test_get_dependents_list       - GET /api/dependents/{emp_id} 正常
    8. test_delete_dependent_api      - DELETE /api/dependents/{emp_id}/{dep_index} 正常
    9. test_get_summary               - GET /api/dependents/summary 正常
   10. test_post_dep_not_found        - 存在しない従業員IDで 404

根拠（手計算）:
  add_dependent 後の dep_count:
    初期 dependents=[] → 追加後 dependents=[dep1] → dep_count=1 ✓
    さらに追加 → dependents=[dep1, dep2] → dep_count=2 ✓
  delete 後の dep_count:
    2件 → インデックス0を削除 → 1件 ✓
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.dependent_service import (
    add_dependent,
    delete_dependent,
    get_dependents,
    validate_dependent,
)
from src.core.storage.secure_store import SecureStore

client = TestClient(app)

_PASSWORD = "test_pass_dep"

_EMP_YAMADA = {
    "employee_name": "山田太郎",
    "tax_year": 7,
    "salary_income": 5_000_000,
    "social_insurance_paid": 720_000,
}

_DEP_SPOUSE = {
    "dep_name": "山田花子",
    "relation": "spouse",
    "birth_year": 1990,
    "income": 0,
}

_DEP_CHILD = {
    "dep_name": "山田一郎",
    "relation": "child",
    "birth_year": 2015,
    "income": 0,
}


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_yamada(tmp_path):
    """山田太郎が登録済み（扶養なし）の SecureStore パスを返す。"""
    db_path = tmp_path / "dep_test.db"
    with SecureStore(db_path, _PASSWORD) as store:
        store.save_employee("EMP001", _EMP_YAMADA)
    return db_path


@pytest.fixture
def db_with_yamada_and_deps(tmp_path):
    """山田太郎（扶養2名）が登録済みの SecureStore パスを返す。"""
    db_path = tmp_path / "dep2_test.db"
    emp_data = dict(_EMP_YAMADA)
    emp_data = add_dependent(emp_data, _DEP_SPOUSE)
    emp_data = add_dependent(emp_data, _DEP_CHILD)
    with SecureStore(db_path, _PASSWORD) as store:
        store.save_employee("EMP001", emp_data)
    return db_path


# ---------------------------------------------------------------------------
# TestDependentServiceFunctions
# ---------------------------------------------------------------------------


class TestDependentServiceFunctions:
    def test_add_dependent_pure(self):
        """add_dependent() が新しい dict を返し元は変更されない。

        根拠:
          初期 dependents=[] → 追加後 dependents=[spouse1] → dep_count=1
          元のemployee_dataは変更なし（純粋関数）
        """
        original = dict(_EMP_YAMADA)
        updated = add_dependent(original, _DEP_SPOUSE)
        # 純粋関数: 元は変更されない
        assert "dependents" not in original or original.get("dependents") == []
        # 追加後: dependents に1件
        deps = get_dependents(updated)
        assert len(deps) == 1  # 0→1件 ✓
        assert deps[0]["dep_name"] == "山田花子"
        assert deps[0]["relation"] == "spouse"

    def test_delete_dependent_pure(self):
        """delete_dependent() がインデックス0を削除し1件残す。

        根拠:
          2件(spouse, child) → インデックス0(spouse)削除 → 1件(child)残る
        """
        emp = dict(_EMP_YAMADA)
        emp = add_dependent(emp, _DEP_SPOUSE)
        emp = add_dependent(emp, _DEP_CHILD)
        assert len(get_dependents(emp)) == 2  # 前提確認

        updated = delete_dependent(emp, 0)  # spouse を削除
        deps = get_dependents(updated)
        assert len(deps) == 1  # 2→1件 ✓
        assert deps[0]["dep_name"] == "山田一郎"  # child が残る ✓

    def test_delete_out_of_range(self):
        """範囲外インデックスで IndexError が発生する。

        根拠: dependents=[] のときインデックス0は範囲外 → IndexError
        """
        emp = dict(_EMP_YAMADA)
        with pytest.raises(IndexError):
            delete_dependent(emp, 0)

    def test_validate_invalid_relation(self):
        """無効な relation でバリデーションエラーが返る。

        根拠: VALID_RELATIONS = {"spouse", "child", "parent", "other"}
              "sibling" はセットに含まれない → エラー
        """
        dep = {**_DEP_SPOUSE, "relation": "sibling"}
        errors = validate_dependent(dep)
        assert len(errors) >= 1
        assert any("relation" in e for e in errors)

    def test_validate_negative_income(self):
        """負の income でバリデーションエラーが返る。

        根拠: income < 0 → "income は 0 以上" エラー
        """
        dep = {**_DEP_SPOUSE, "income": -1}
        errors = validate_dependent(dep)
        assert len(errors) >= 1
        assert any("income" in e for e in errors)


# ---------------------------------------------------------------------------
# TestDependentsApi
# ---------------------------------------------------------------------------


class TestDependentsApi:
    def test_post_add_dependent(self, db_with_yamada):
        """POST /api/dependents/{emp_id} が 200 を返し dep_count=1 になる。

        根拠:
          EMP001（扶養なし）に配偶者を追加 → dep_count=1, dep_index=0
        """
        resp = client.post(
            "/api/dependents/EMP001",
            json={
                "db_path": str(db_with_yamada),
                "password": _PASSWORD,
                "dependent": _DEP_SPOUSE,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dep_count"] == 1   # 0→1件 ✓
        assert body["dep_index"] == 0   # インデックス0 ✓
        assert body["emp_id"] == "EMP001"

    def test_get_dependents_list(self, db_with_yamada_and_deps):
        """GET /api/dependents/{emp_id} が 200 を返し 2件のリストを返す。

        根拠: db_with_yamada_and_deps に spouse + child の 2件が登録済み。
              dep_count=2 であることを確認。
        """
        resp = client.get(
            "/api/dependents/EMP001",
            params={"db_path": str(db_with_yamada_and_deps), "password": _PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dep_count"] == 2          # 2件登録済み ✓
        assert body["dependents"][0]["dep_name"] == "山田花子"  # spouse先頭 ✓
        assert body["dependents"][1]["dep_name"] == "山田一郎"  # child2番目 ✓

    def test_delete_dependent_api(self, db_with_yamada_and_deps):
        """DELETE /api/dependents/{emp_id}/{dep_index} が 200 を返し dep_count=1 になる。

        根拠: 2件(spouse at 0, child at 1) → インデックス0(spouse)削除 → 1件残る。
              deleted_index=0, dep_count=1 を確認。
        """
        resp = client.delete(
            "/api/dependents/EMP001/0",
            params={"db_path": str(db_with_yamada_and_deps), "password": _PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["deleted_index"] == 0  # インデックス0を削除 ✓
        assert body["dep_count"] == 1      # 2→1件 ✓

    def test_get_summary(self, db_with_yamada_and_deps):
        """GET /api/dependents/summary が 200 を返し正しいサマリーを返す。

        根拠: db に EMP001（扶養2名）が登録済み。
              summary = {"EMP001": 2}, total_employees=1, total_dependents=2
        """
        resp = client.get(
            "/api/dependents/summary",
            params={"db_path": str(db_with_yamada_and_deps), "password": _PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_employees"] == 1        # 1名 ✓
        assert body["total_dependents"] == 2       # 扶養2名 ✓
        assert body["summary"]["EMP001"] == 2      # EMP001: 2件 ✓

    def test_post_dep_not_found(self, db_with_yamada):
        """存在しない従業員IDで 404 が返る。

        根拠: EMP999 は db_with_yamada に登録されていない。
              store.load_employee("EMP999") が KeyError → 404 に変換。
        """
        resp = client.post(
            "/api/dependents/EMP999",
            json={
                "db_path": str(db_with_yamada),
                "password": _PASSWORD,
                "dependent": _DEP_SPOUSE,
            },
        )
        assert resp.status_code == 404
