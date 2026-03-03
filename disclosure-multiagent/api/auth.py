"""authentication and API key management for disclosure-multiagent.

本番デプロイ用セキュリティ。
- 環境変数 API_KEY で鍵を設定（ハードコード禁止）
- X-API-Key ヘッダーまたは Authorization: Bearer <token> で認証
- API_KEY 未設定時は認証をスキップ（開発環境向け）

CHECK-9 根拠:
  - 環境変数 API_KEY が設定済みの場合のみ認証を有効化
  - API_KEY 未設定（空文字）は開発モード: 全リクエストを通す
  - ヘッダー未送信または不一致 → HTTPException(401)
  - 有効なキー送信 → 認証通過（None を返す）
"""
from __future__ import annotations

import os
from fastapi import Header, HTTPException, Security
from fastapi.security import APIKeyHeader
from typing import Optional

# X-API-Key ヘッダースキーム
_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Authorization: Bearer <token> 用
_BEARER_HEADER = APIKeyHeader(name="Authorization", auto_error=False)


def _get_configured_api_key() -> str:
    """環境変数から API_KEY を取得する（ハードコード禁止）。"""
    return os.environ.get("API_KEY", "")


async def verify_api_key(
    x_api_key: Optional[str] = Security(_API_KEY_HEADER),
    authorization: Optional[str] = Security(_BEARER_HEADER),
) -> None:
    """FastAPI Dependency: APIキー認証を行う。

    認証ロジック:
      1. 環境変数 API_KEY が未設定（空文字）→ 認証スキップ（開発モード）
      2. X-API-Key ヘッダーと API_KEY が一致 → OK
      3. Authorization: Bearer <token> で token が API_KEY と一致 → OK
      4. いずれも一致しない → 401 Unauthorized

    CHECK-9 根拠: API_KEY="" の場合は開発・テスト環境での利便性のためスキップ。
                  本番では必ず API_KEY を設定する（.env.example に記載）。
    """
    configured_key = _get_configured_api_key()

    # API_KEY 未設定は開発モード: 認証スキップ
    if not configured_key:
        return

    # X-API-Key ヘッダーで認証
    if x_api_key and x_api_key == configured_key:
        return

    # Authorization: Bearer <token> で認証
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization[len("Bearer "):]
            if token == configured_key:
                return
        # Bearer プレフィックスなしでそのまま比較
        elif authorization == configured_key:
            return

    raise HTTPException(
        status_code=401,
        detail="Invalid or missing API key. Provide X-API-Key header or Authorization: Bearer <token>.",
        headers={"WWW-Authenticate": "Bearer"},
    )
