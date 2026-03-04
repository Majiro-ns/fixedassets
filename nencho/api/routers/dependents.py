"""扶養控除申告書管理 API エンドポイント

POST   /api/dependents/{emp_id}                - 扶養親族登録
GET    /api/dependents/summary                 - 全従業員の扶養人数サマリー
GET    /api/dependents/{emp_id}                - 従業員の扶養親族一覧
DELETE /api/dependents/{emp_id}/{dep_index}    - 指定インデックスの扶養親族削除

ルーティング注意:
  GET /api/dependents/summary を GET /api/dependents/{emp_id} より前に定義する。
  FastAPI はルートを定義順にマッチングするため、先に定義した /summary が
  "summary" という emp_id として解釈されることを防ぐ。

認証設計:
  POST: db_path + password を JSON ボディに含める
  GET / DELETE: db_path + password を Query パラメータで渡す
  ※ GET/DELETE で Query パラメータにパスワードを含めることは
    内部ツールとして許容する（ログ管理・HTTPS 運用前提）
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.services.dependent_service import (
    add_dependent,
    delete_dependent,
    get_dependents,
    validate_dependent,
)
from src.core.storage.secure_store import SecureStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dependents", tags=["dependents"])


# ---------------------------------------------------------------------------
# スキーマ
# ---------------------------------------------------------------------------


class DependentItem(BaseModel):
    """扶養親族情報（1件）。"""

    dep_name: str = Field(..., description="扶養親族氏名")
    relation: str = Field(..., description="続柄: spouse / child / parent / other")
    birth_year: int = Field(0, description="生年（西暦。0=不明）")
    income: int = Field(0, description="所得金額（円。0=非課税扶養）")


class AddDependentRequest(BaseModel):
    """扶養親族登録リクエスト。"""

    db_path: str = Field(..., description="SecureStore SQLiteファイルパス")
    password: str = Field(..., description="復号パスワード")
    dependent: DependentItem = Field(..., description="登録する扶養親族情報")


class AddDependentResponse(BaseModel):
    """扶養親族登録レスポンス。"""

    emp_id: str
    dep_index: int = Field(..., description="追加された扶養親族のインデックス（0始まり）")
    dep_count: int = Field(..., description="登録後の扶養親族総数")
    message: str


class DependentListResponse(BaseModel):
    """扶養親族一覧レスポンス。"""

    emp_id: str
    dependents: list[DependentItem]
    dep_count: int


class DeleteDependentResponse(BaseModel):
    """扶養親族削除レスポンス。"""

    emp_id: str
    deleted_index: int
    dep_count: int = Field(..., description="削除後の扶養親族総数")
    message: str


class DependentSummaryResponse(BaseModel):
    """全従業員の扶養人数サマリーレスポンス。"""

    summary: dict[str, int] = Field(
        ..., description="{emp_id: 扶養親族数} のマップ（全登録従業員）"
    )
    total_employees: int
    total_dependents: int


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _open_store_or_raise(db_path_str: str, password: str) -> tuple[Path, SecureStore]:
    """db_path の存在確認とパスワード検証を行う。

    Returns:
        (db_path, open_store) のタプル。store は開いた状態で返す。
        呼び出し元でクローズすること（with文推奨）。

    Raises:
        HTTPException 404: db_path が存在しない
        HTTPException 401: パスワードが不正
    """
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
        logger.warning("dependents API: パスワード認証失敗（db=%s）", db_path_str)
        raise HTTPException(status_code=401, detail="パスワードが正しくありません")
    return db_path


# ---------------------------------------------------------------------------
# エンドポイント（summary を先に定義！）
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=DependentSummaryResponse)
async def get_dependents_summary(
    db_path: str = Query(..., description="SecureStore SQLiteファイルパス"),
    password: str = Query(..., description="復号パスワード"),
):
    """全従業員の扶養人数サマリーを返す。

    SecureStore に登録された全従業員の扶養親族数を集計する。

    Returns:
        {emp_id: dep_count} のマップ・総従業員数・総扶養人数

    Raises:
        404: db_path が存在しない
        401: パスワードが不正
    """
    store_path = _open_store_or_raise(db_path, password)

    with SecureStore(store_path, password) as store:
        emp_ids = store.list_employees()
        summary: dict[str, int] = {}
        for emp_id in emp_ids:
            try:
                data = store.load_employee(emp_id)
                deps = get_dependents(data)
                summary[emp_id] = len(deps)
            except Exception as e:
                logger.warning("dependents summary: %s スキップ（%s）", emp_id, e)

    return DependentSummaryResponse(
        summary=summary,
        total_employees=len(summary),
        total_dependents=sum(summary.values()),
    )


@router.post("/{emp_id}", response_model=AddDependentResponse)
async def add_dependent_endpoint(emp_id: str, req: AddDependentRequest):
    """従業員に扶養親族を登録する。

    SecureStore の従業員データに "dependents" リストとして扶養親族を追記する。

    Args:
        emp_id: 従業員ID（パスパラメータ）

    Raises:
        404: db_path または emp_id が存在しない
        401: パスワードが不正
        422: バリデーションエラー
    """
    store_path = _open_store_or_raise(req.db_path, req.password)

    dep_dict = req.dependent.model_dump()
    errors = validate_dependent(dep_dict)
    if errors:
        raise HTTPException(
            status_code=422,
            detail=f"バリデーションエラー: {'; '.join(errors)}",
        )

    with SecureStore(store_path, req.password) as store:
        try:
            data = store.load_employee(emp_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"従業員ID '{emp_id}' は登録されていません",
            )
        updated = add_dependent(data, dep_dict)
        store.save_employee(emp_id, updated)
        dep_count = len(updated["dependents"])

    return AddDependentResponse(
        emp_id=emp_id,
        dep_index=dep_count - 1,
        dep_count=dep_count,
        message=f"扶養親族を登録しました（{dep_dict['dep_name']}）",
    )


@router.get("/{emp_id}", response_model=DependentListResponse)
async def list_dependents_endpoint(
    emp_id: str,
    db_path: str = Query(..., description="SecureStore SQLiteファイルパス"),
    password: str = Query(..., description="復号パスワード"),
):
    """従業員の扶養親族一覧を返す。

    Raises:
        404: db_path または emp_id が存在しない
        401: パスワードが不正
    """
    store_path = _open_store_or_raise(db_path, password)

    with SecureStore(store_path, password) as store:
        try:
            data = store.load_employee(emp_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"従業員ID '{emp_id}' は登録されていません",
            )
        deps = get_dependents(data)

    return DependentListResponse(
        emp_id=emp_id,
        dependents=[DependentItem(**d) for d in deps],
        dep_count=len(deps),
    )


@router.delete("/{emp_id}/{dep_index}", response_model=DeleteDependentResponse)
async def delete_dependent_endpoint(
    emp_id: str,
    dep_index: int,
    db_path: str = Query(..., description="SecureStore SQLiteファイルパス"),
    password: str = Query(..., description="復号パスワード"),
):
    """指定インデックスの扶養親族を削除する。

    Args:
        emp_id: 従業員ID（パスパラメータ）
        dep_index: 削除するインデックス（0始まり）

    Raises:
        404: db_path・emp_id が存在しない、またはインデックスが範囲外
        401: パスワードが不正
    """
    store_path = _open_store_or_raise(db_path, password)

    with SecureStore(store_path, password) as store:
        try:
            data = store.load_employee(emp_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"従業員ID '{emp_id}' は登録されていません",
            )
        try:
            updated = delete_dependent(data, dep_index)
        except IndexError as e:
            raise HTTPException(status_code=404, detail=str(e))

        store.save_employee(emp_id, updated)
        remaining = len(updated.get("dependents", []))

    return DeleteDependentResponse(
        emp_id=emp_id,
        deleted_index=dep_index,
        dep_count=remaining,
        message=f"インデックス {dep_index} の扶養親族を削除しました",
    )
