"""セッション管理 API エンドポイント

T006: 暗号化セッション管理のWeb対応

エンドポイント:
  POST   /api/session/create   - セッション作成（パスワード認証）
  GET    /api/session/status   - セッション状態確認
  POST   /api/session/refresh  - セッション更新（タイムアウトリセット）
  DELETE /api/session/destroy  - セッション破棄
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from src.auth.session_manager import SessionManager
from src.auth.web_session_manager import WebSessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["session"])

# アプリケーション共有の WebSessionManager（シングルトン）
# 本番環境では依存性注入で差し替え可能
_web_session_manager: Optional[WebSessionManager] = None


def get_web_session_manager() -> WebSessionManager:
    """WebSessionManager のシングルトンを返す。"""
    global _web_session_manager
    if _web_session_manager is None:
        _web_session_manager = WebSessionManager()
    return _web_session_manager


# ---------------------------------------------------------------------------
# スキーマ
# ---------------------------------------------------------------------------


class SessionCreateRequest(BaseModel):
    """セッション作成リクエスト。"""

    db_path: str = Field(..., description="SecureStore SQLite ファイルパス")
    password: str = Field(..., description="セッション解除パスワード")
    timeout_minutes: int = Field(
        10,
        ge=0,
        le=1440,
        description="タイムアウト分数（0 = タイムアウトなし）",
    )


class SessionCreateResponse(BaseModel):
    """セッション作成レスポンス。"""

    session_id: str = Field(..., description="作成されたセッションID")
    status: str = Field(..., description="'created' 固定")
    timeout_minutes: int = Field(..., description="設定されたタイムアウト分数")


class SessionStatusResponse(BaseModel):
    """セッション状態レスポンス。"""

    valid: bool = Field(..., description="セッションが有効かどうか")
    status: str = Field(..., description="'active' / 'expired_or_not_found'")


class SessionRefreshResponse(BaseModel):
    """セッション更新レスポンス。"""

    refreshed: bool = Field(..., description="更新成功なら True")
    status: str = Field(..., description="'refreshed' / 'session_not_found'")


class SessionDestroyResponse(BaseModel):
    """セッション破棄レスポンス。"""

    destroyed: bool = Field(..., description="破棄成功なら True")
    status: str = Field(..., description="'destroyed' / 'session_not_found'")


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------


@router.post("/create", response_model=SessionCreateResponse)
async def create_session(req: SessionCreateRequest):
    """パスワード認証を行い、成功したらセッションを作成する。

    SecureStore のパスワードを使って認証し、
    認証成功後にセッションデータを AES-256-GCM で暗号化してメモリ保持する。

    Returns:
        セッションID と状態

    Raises:
        401: パスワードが誤っている場合
        422: db_path が存在しない場合（SecureStore が新規作成を試みる）
    """
    db_path = Path(req.db_path)

    # SessionManager でパスワード検証
    sm = SessionManager(db_path, timeout_minutes=req.timeout_minutes)
    authenticated = sm.unlock(req.password)

    if not authenticated:
        # パスワード誤りはログに詳細を残さない（セキュリティ）
        logger.warning("WebSession: パスワード認証に失敗しました")
        raise HTTPException(status_code=401, detail="パスワードが正しくありません")

    # セッションデータを暗号化して保存
    session_data = {
        "db_path": str(db_path),
        "timeout_minutes": req.timeout_minutes,
        "authenticated": True,
    }
    manager = get_web_session_manager()
    session_id = manager.create_session(session_data)

    logger.info("WebSession: セッションを作成しました（IDはログに記録しません）")
    return SessionCreateResponse(
        session_id=session_id,
        status="created",
        timeout_minutes=req.timeout_minutes,
    )


@router.get("/status", response_model=SessionStatusResponse)
async def get_session_status(
    x_session_id: str = Header(..., description="セッションID（X-Session-Id ヘッダー）"),
):
    """セッションの有効性を確認する。

    Args:
        x_session_id: リクエストヘッダー X-Session-Id に含めるセッションID

    Returns:
        セッションの有効状態
    """
    manager = get_web_session_manager()
    valid = manager.is_valid(x_session_id)

    return SessionStatusResponse(
        valid=valid,
        status="active" if valid else "expired_or_not_found",
    )


@router.post("/refresh", response_model=SessionRefreshResponse)
async def refresh_session(
    x_session_id: str = Header(..., description="セッションID（X-Session-Id ヘッダー）"),
):
    """セッションのタイムアウトをリセットする（touch）。

    Args:
        x_session_id: リクエストヘッダー X-Session-Id に含めるセッションID

    Returns:
        更新状態
    """
    manager = get_web_session_manager()
    data = manager.get_session(x_session_id)

    if data is None:
        return SessionRefreshResponse(refreshed=False, status="session_not_found")

    # データを再暗号化して時刻を更新（update_session 内で touch される）
    refreshed = manager.update_session(x_session_id, data)
    return SessionRefreshResponse(
        refreshed=refreshed,
        status="refreshed" if refreshed else "session_not_found",
    )


@router.delete("/destroy", response_model=SessionDestroyResponse)
async def destroy_session(
    x_session_id: str = Header(..., description="セッションID（X-Session-Id ヘッダー）"),
):
    """セッションを破棄する。

    Args:
        x_session_id: リクエストヘッダー X-Session-Id に含めるセッションID

    Returns:
        破棄状態
    """
    manager = get_web_session_manager()
    destroyed = manager.delete_session(x_session_id)

    return SessionDestroyResponse(
        destroyed=destroyed,
        status="destroyed" if destroyed else "session_not_found",
    )
