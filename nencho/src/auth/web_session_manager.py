"""Web版 AES-256-GCM 暗号化セッション管理モジュール

T006: 暗号化セッション管理のWeb対応

設計方針:
- セッションIDごとにセッションデータを AES-256-GCM で暗号化してメモリ保持
- 鍵は環境変数 NENCHO_SESSION_KEY（32バイト hex エンコード）から取得
- 環境変数未設定時はアプリ起動時にランダム鍵を生成（再起動でセッション無効化）
- タイムアウト（自動失効）対応
- スレッドセーフ（FastAPI の async 環境を考慮）

禁止事項:
- 鍵のハードコード禁止
- セッションデータの平文ログ出力禁止
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.core.crypto.encrypt import decrypt, encrypt
from src.core.crypto.key_derivation import derive_key, generate_salt

logger = logging.getLogger(__name__)

# 環境変数名
ENV_SESSION_KEY = "NENCHO_SESSION_KEY"
ENV_SESSION_KEY_PASS = "NENCHO_SESSION_KEY_PASS"

# セッションIDのバイト長（128bit）
SESSION_ID_BYTES = 16

# デフォルトタイムアウト（分）
DEFAULT_SESSION_TIMEOUT_MINUTES = 30


def _load_or_generate_key() -> bytes:
    """セッション暗号化鍵を環境変数から取得、または生成する。

    優先順位:
    1. NENCHO_SESSION_KEY に 64文字 hex 文字列（32バイト）が設定されている場合
    2. NENCHO_SESSION_KEY_PASS にパスフレーズが設定されている場合（PBKDF2で導出）
    3. どちらも未設定の場合はランダム鍵を生成（再起動でセッション無効化）

    Returns:
        32バイトの暗号化鍵

    Raises:
        ValueError: NENCHO_SESSION_KEY が設定されているが形式が不正な場合
    """
    raw_key = os.environ.get(ENV_SESSION_KEY, "").strip()
    if raw_key:
        try:
            key_bytes = bytes.fromhex(raw_key)
        except ValueError as e:
            raise ValueError(
                f"{ENV_SESSION_KEY} は64文字のhex文字列（32バイト）で指定してください: {e}"
            ) from e
        if len(key_bytes) != 32:
            raise ValueError(
                f"{ENV_SESSION_KEY} は32バイト（64文字hex）である必要があります。"
                f"実際: {len(key_bytes)}バイト"
            )
        logger.info("WebSessionManager: 環境変数 %s から鍵を読み込みました", ENV_SESSION_KEY)
        return key_bytes

    passphrase = os.environ.get(ENV_SESSION_KEY_PASS, "").strip()
    if passphrase:
        # パスフレーズからPBKDF2で鍵を導出（salt固定 = アプリ固有のsaltをenv経由で）
        # ここでは固定saltとして環境変数名のハッシュを利用
        fixed_salt = ENV_SESSION_KEY_PASS.encode("utf-8").ljust(32, b"\x00")[:32]
        key = derive_key(passphrase, fixed_salt, iterations=100_000)
        logger.info(
            "WebSessionManager: 環境変数 %s からPBKDF2で鍵を導出しました",
            ENV_SESSION_KEY_PASS,
        )
        return key

    # どちらも未設定: ランダム生成（開発環境向け）
    key = os.urandom(32)
    logger.warning(
        "WebSessionManager: %s / %s が未設定です。ランダム鍵を使用します（再起動でセッション無効化）",
        ENV_SESSION_KEY,
        ENV_SESSION_KEY_PASS,
    )
    return key


class WebSessionManager:
    """Web版 AES-256-GCM 暗号化セッション管理。

    FastAPI などの Web フレームワークで使用するセッション管理クラス。
    セッションデータは AES-256-GCM で暗号化してメモリ内に保持する。

    Usage:
        manager = WebSessionManager()
        session_id = manager.create_session({"user_id": "admin", "role": "hr"})
        data = manager.get_session(session_id)
        manager.delete_session(session_id)
    """

    def __init__(
        self,
        key: Optional[bytes] = None,
        timeout_minutes: int = DEFAULT_SESSION_TIMEOUT_MINUTES,
    ) -> None:
        """
        Args:
            key: 32バイトの暗号化鍵。None の場合は環境変数から取得または生成。
            timeout_minutes: セッションタイムアウト（分）。0 でタイムアウトなし。
        """
        if key is not None:
            if len(key) != 32:
                raise ValueError(
                    f"鍵は32バイト(256bit)でなければなりません。実際: {len(key)}バイト"
                )
            self._key = key
        else:
            self._key = _load_or_generate_key()

        self._timeout_minutes = timeout_minutes
        # セッションID -> (暗号化データ, 最終アクティビティ日時)
        self._sessions: dict[str, tuple[bytes, datetime]] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def create_session(self, data: dict[str, Any]) -> str:
        """新規セッションを作成し、セッションIDを返す。

        セッションデータは AES-256-GCM で暗号化してメモリ内に保持する。

        Args:
            data: セッションに保存する任意のデータ（JSON シリアライズ可能なもの）

        Returns:
            セッションID（32文字 hex 文字列）

        Raises:
            ValueError: data が JSON シリアライズ不可能な場合
        """
        session_id = secrets.token_hex(SESSION_ID_BYTES)
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        encrypted = encrypt(self._key, plaintext)
        self._sessions[session_id] = (encrypted, datetime.now(timezone.utc))
        logger.debug("WebSessionManager: セッションを作成しました（IDはログに記録しません）")
        return session_id

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """セッションデータを取得して復号する。

        タイムアウト済みのセッションは自動削除し None を返す。

        Args:
            session_id: create_session() が返したセッションID

        Returns:
            セッションデータの dict。セッションが存在しない・タイムアウトの場合は None。
        """
        entry = self._sessions.get(session_id)
        if entry is None:
            return None

        encrypted, last_activity = entry

        # タイムアウトチェック
        if self._timeout_minutes > 0:
            elapsed = datetime.now(timezone.utc) - last_activity
            if elapsed >= timedelta(minutes=self._timeout_minutes):
                self.delete_session(session_id)
                logger.debug("WebSessionManager: セッションがタイムアウトしました")
                return None

        # 復号
        try:
            plaintext = decrypt(self._key, encrypted)
        except Exception:
            # 改ざん・鍵不一致などは None として処理
            logger.warning("WebSessionManager: セッションデータの復号に失敗しました")
            self.delete_session(session_id)
            return None

        # アクティビティ更新（タッチ）
        self._sessions[session_id] = (encrypted, datetime.now(timezone.utc))
        return json.loads(plaintext.decode("utf-8"))

    def update_session(self, session_id: str, data: dict[str, Any]) -> bool:
        """既存セッションのデータを更新する。

        Args:
            session_id: 更新対象のセッションID
            data: 新しいセッションデータ

        Returns:
            更新成功なら True。セッションが存在しない・タイムアウトの場合は False。
        """
        # get_session でタイムアウトチェック済み
        if self.get_session(session_id) is None:
            return False

        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        encrypted = encrypt(self._key, plaintext)
        self._sessions[session_id] = (encrypted, datetime.now(timezone.utc))
        return True

    def delete_session(self, session_id: str) -> bool:
        """セッションを削除する。

        Args:
            session_id: 削除対象のセッションID

        Returns:
            削除成功なら True。存在しない場合は False。
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def is_valid(self, session_id: str) -> bool:
        """セッションが有効（存在かつタイムアウトしていない）か確認する。

        Args:
            session_id: 確認対象のセッションID

        Returns:
            有効なら True。
        """
        return self.get_session(session_id) is not None

    def cleanup_expired(self) -> int:
        """タイムアウト済みセッションを一括削除する。

        Returns:
            削除したセッション数
        """
        if self._timeout_minutes <= 0:
            return 0

        now = datetime.now(timezone.utc)
        expired = [
            sid
            for sid, (_, last_activity) in self._sessions.items()
            if (now - last_activity) >= timedelta(minutes=self._timeout_minutes)
        ]
        for sid in expired:
            del self._sessions[sid]

        if expired:
            logger.info(
                "WebSessionManager: %d 件のタイムアウトセッションを削除しました", len(expired)
            )
        return len(expired)

    @property
    def active_count(self) -> int:
        """現在のアクティブセッション数を返す（タイムアウト未チェック）。"""
        return len(self._sessions)
