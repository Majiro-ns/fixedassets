"""T006: 暗号化セッション管理 Web版 テスト

CHECK-9: テスト期待値の根拠は以下の通り。
- AES-256-GCM: セッションデータは暗号化されメモリに保持される（NIST SP 800-38D準拠）
- セッションID: secrets.token_hex(16) = 32文字 hex 文字列
- タイムアウト: 設定分数経過後は None を返す
- 鍵: 環境変数 NENCHO_SESSION_KEY (64文字hex=32バイト) または自動生成

対象:
  - WebSessionManager: 暗号化セッション CRUD
  - session API エンドポイント: /api/session/create, /status, /refresh, /destroy
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.auth.web_session_manager import WebSessionManager, _load_or_generate_key
from src.core.storage.secure_store import SecureStore


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _make_store(db_path: Path, password: str = "test_password_ok") -> None:
    """テスト用 SecureStore を指定パスワードで初期化する。"""
    with SecureStore(db_path, password):
        pass


def _make_test_key() -> bytes:
    """テスト用 32バイト鍵を返す。"""
    return b"\x01" * 32


# ---------------------------------------------------------------------------
# WebSessionManager テスト
# ---------------------------------------------------------------------------


class TestWebSessionManagerCreate:
    """セッション作成テスト"""

    def test_create_session_returns_session_id(self):
        """create_session() がセッションIDを返す。

        CHECK-9: secrets.token_hex(16) は 32文字の hex 文字列を返す（Python 標準ライブラリ仕様）
        """
        manager = WebSessionManager(key=_make_test_key())
        session_id = manager.create_session({"user": "admin"})
        assert isinstance(session_id, str)
        assert len(session_id) == 32  # 16バイト = 32文字 hex

    def test_create_session_ids_are_unique(self):
        """セッションIDは呼び出しごとに一意である。

        CHECK-9: secrets.token_hex は暗号論的乱数を使用。衝突確率は無視できるほど小さい。
        """
        manager = WebSessionManager(key=_make_test_key())
        ids = {manager.create_session({"i": i}) for i in range(10)}
        assert len(ids) == 10  # 全て一意

    def test_active_count_increases_on_create(self):
        """セッション作成でアクティブ数が増加する。

        CHECK-9: active_count は _sessions dict のサイズを返す
        """
        manager = WebSessionManager(key=_make_test_key())
        assert manager.active_count == 0
        manager.create_session({"a": 1})
        assert manager.active_count == 1
        manager.create_session({"b": 2})
        assert manager.active_count == 2

    def test_invalid_key_length_raises(self):
        """32バイト以外の鍵で ValueError が発生する。

        CHECK-9: 鍵長チェックは AES-256 要件（32バイト=256bit）
        """
        with pytest.raises(ValueError, match="32バイト"):
            WebSessionManager(key=b"\x00" * 16)


class TestWebSessionManagerGetSession:
    """セッション取得テスト"""

    def test_get_session_returns_original_data(self):
        """get_session() が保存時のデータを返す。

        CHECK-9: AES-256-GCM は認証付き暗号化。復号後のデータは改ざんなしを保証。
        """
        manager = WebSessionManager(key=_make_test_key())
        original = {"user_id": "EMP001", "role": "hr", "name": "山田太郎"}
        session_id = manager.create_session(original)
        result = manager.get_session(session_id)
        assert result == original

    def test_get_session_unknown_id_returns_none(self):
        """存在しないセッションIDは None を返す。

        CHECK-9: _sessions dict に存在しないキーは None
        """
        manager = WebSessionManager(key=_make_test_key())
        result = manager.get_session("nonexistent_session_id_xxxxx")
        assert result is None

    def test_get_session_after_timeout_returns_none(self):
        """タイムアウト後は None を返す。

        CHECK-9: timeout_minutes=0.001分(≈0.06秒)で sleep 後に None を期待
        """
        manager = WebSessionManager(key=_make_test_key(), timeout_minutes=0.001)
        session_id = manager.create_session({"user": "test"})
        time.sleep(0.1)  # タイムアウト（0.001分≈0.06秒）を超えて待機
        result = manager.get_session(session_id)
        assert result is None

    def test_get_session_no_timeout_persists(self):
        """timeout_minutes=0 の場合タイムアウトしない。

        CHECK-9: timeout_minutes=0 のブランチは elapsed チェックをスキップする
        """
        manager = WebSessionManager(key=_make_test_key(), timeout_minutes=0)
        session_id = manager.create_session({"user": "persist"})
        time.sleep(0.05)
        result = manager.get_session(session_id)
        assert result is not None
        assert result["user"] == "persist"

    def test_get_session_with_japanese_data(self):
        """日本語を含むセッションデータが正しく復元される。

        CHECK-9: JSON は ensure_ascii=False で UTF-8 エンコード。AES-GCM はバイト列を暗号化。
        """
        manager = WebSessionManager(key=_make_test_key())
        original = {"氏名": "田中花子", "部署": "総務部", "年収": 5_000_000}
        session_id = manager.create_session(original)
        result = manager.get_session(session_id)
        assert result == original


class TestWebSessionManagerUpdate:
    """セッション更新テスト"""

    def test_update_session_succeeds_for_valid_session(self):
        """有効なセッションの update_session() は True を返す。

        CHECK-9: get_session が None でなければ更新成功
        """
        manager = WebSessionManager(key=_make_test_key())
        session_id = manager.create_session({"count": 0})
        result = manager.update_session(session_id, {"count": 1})
        assert result is True

    def test_update_session_changes_data(self):
        """update_session() 後に get_session() で新しいデータが返る。"""
        manager = WebSessionManager(key=_make_test_key())
        session_id = manager.create_session({"count": 0})
        manager.update_session(session_id, {"count": 99})
        result = manager.get_session(session_id)
        assert result is not None
        assert result["count"] == 99

    def test_update_session_invalid_id_returns_false(self):
        """存在しないセッションの update は False を返す。

        CHECK-9: get_session が None → update は False
        """
        manager = WebSessionManager(key=_make_test_key())
        result = manager.update_session("nonexistent_xxxx_xxxxxxxxxxxxxx", {"x": 1})
        assert result is False


class TestWebSessionManagerDelete:
    """セッション削除テスト"""

    def test_delete_session_returns_true(self):
        """存在するセッションの delete_session() は True を返す。

        CHECK-9: _sessions dict から削除成功
        """
        manager = WebSessionManager(key=_make_test_key())
        session_id = manager.create_session({"x": 1})
        result = manager.delete_session(session_id)
        assert result is True

    def test_delete_session_removes_from_store(self):
        """delete_session() 後は get_session() が None を返す。"""
        manager = WebSessionManager(key=_make_test_key())
        session_id = manager.create_session({"x": 1})
        manager.delete_session(session_id)
        assert manager.get_session(session_id) is None

    def test_delete_nonexistent_session_returns_false(self):
        """存在しないセッションの削除は False を返す。

        CHECK-9: _sessions dict にキーなし → False
        """
        manager = WebSessionManager(key=_make_test_key())
        result = manager.delete_session("nonexistent_xxxx_xxxxxxxxxxxxxx")
        assert result is False

    def test_active_count_decreases_on_delete(self):
        """削除でアクティブ数が減少する。"""
        manager = WebSessionManager(key=_make_test_key())
        sid1 = manager.create_session({"a": 1})
        sid2 = manager.create_session({"b": 2})
        assert manager.active_count == 2
        manager.delete_session(sid1)
        assert manager.active_count == 1
        manager.delete_session(sid2)
        assert manager.active_count == 0


class TestWebSessionManagerIsValid:
    """is_valid テスト"""

    def test_is_valid_for_existing_session(self):
        """作成直後のセッションは is_valid() == True。

        CHECK-9: 作成後すぐはタイムアウトしていない
        """
        manager = WebSessionManager(key=_make_test_key())
        session_id = manager.create_session({"ok": True})
        assert manager.is_valid(session_id) is True

    def test_is_valid_false_after_delete(self):
        """削除後は is_valid() == False。"""
        manager = WebSessionManager(key=_make_test_key())
        session_id = manager.create_session({"ok": True})
        manager.delete_session(session_id)
        assert manager.is_valid(session_id) is False

    def test_is_valid_false_for_unknown(self):
        """不明なセッションIDは is_valid() == False。"""
        manager = WebSessionManager(key=_make_test_key())
        assert manager.is_valid("unknown_id_xxxxxxxxxxxxxxxxxxxxx") is False


class TestWebSessionManagerCleanup:
    """クリーンアップテスト"""

    def test_cleanup_expired_removes_timed_out_sessions(self):
        """cleanup_expired() がタイムアウト済みセッションを削除する。

        CHECK-9: timeout_minutes=0.001 で sleep 後に cleanup_expired() を呼ぶと削除数 > 0
        """
        manager = WebSessionManager(key=_make_test_key(), timeout_minutes=0.001)
        manager.create_session({"x": 1})
        manager.create_session({"y": 2})
        time.sleep(0.1)
        removed = manager.cleanup_expired()
        assert removed == 2
        assert manager.active_count == 0

    def test_cleanup_expired_returns_zero_when_no_timeout(self):
        """timeout_minutes=0 の場合 cleanup_expired() は 0 を返す。

        CHECK-9: タイムアウトなし設定 → 削除対象なし
        """
        manager = WebSessionManager(key=_make_test_key(), timeout_minutes=0)
        manager.create_session({"x": 1})
        removed = manager.cleanup_expired()
        assert removed == 0


class TestKeyLoading:
    """環境変数からの鍵読み込みテスト"""

    def test_load_key_from_env_session_key(self, monkeypatch):
        """NENCHO_SESSION_KEY 環境変数から鍵を読み込む。

        CHECK-9: 64文字 hex = 32バイト。bytes.fromhex で正確に変換される。
        """
        test_key = os.urandom(32)
        monkeypatch.setenv("NENCHO_SESSION_KEY", test_key.hex())
        loaded = _load_or_generate_key()
        assert loaded == test_key

    def test_load_key_invalid_hex_raises(self, monkeypatch):
        """不正な hex 文字列は ValueError を発生させる。

        CHECK-9: bytes.fromhex("xyz...") は ValueError を発生させる
        """
        monkeypatch.setenv("NENCHO_SESSION_KEY", "not_valid_hex_xxx")
        with pytest.raises(ValueError):
            _load_or_generate_key()

    def test_load_key_wrong_length_raises(self, monkeypatch):
        """32バイト以外の hex は ValueError を発生させる。

        CHECK-9: 16バイト(32文字hex)では AES-256 鍵長不足
        """
        monkeypatch.setenv("NENCHO_SESSION_KEY", "aa" * 16)  # 16バイト
        with pytest.raises(ValueError, match="32バイト"):
            _load_or_generate_key()

    def test_load_key_generates_random_when_no_env(self, monkeypatch):
        """環境変数未設定時はランダム鍵を生成する（32バイト）。

        CHECK-9: os.urandom(32) = 32バイト
        """
        monkeypatch.delenv("NENCHO_SESSION_KEY", raising=False)
        monkeypatch.delenv("NENCHO_SESSION_KEY_PASS", raising=False)
        key = _load_or_generate_key()
        assert len(key) == 32

    def test_load_key_from_passphrase(self, monkeypatch):
        """NENCHO_SESSION_KEY_PASS からPBKDF2で鍵導出できる。

        CHECK-9: PBKDF2 は決定論的。同じパスフレーズ → 同じ鍵（固定salt使用時）
        """
        monkeypatch.delenv("NENCHO_SESSION_KEY", raising=False)
        monkeypatch.setenv("NENCHO_SESSION_KEY_PASS", "my-secret-passphrase")
        key1 = _load_or_generate_key()
        key2 = _load_or_generate_key()
        assert len(key1) == 32
        assert key1 == key2  # 決定論的

    def test_two_random_keys_differ(self, monkeypatch):
        """環境変数未設定時の2回のランダム鍵は異なる（高確率）。

        CHECK-9: os.urandom(32) は暗号論的乱数。同一値の確率は 1/2^256
        """
        monkeypatch.delenv("NENCHO_SESSION_KEY", raising=False)
        monkeypatch.delenv("NENCHO_SESSION_KEY_PASS", raising=False)
        key1 = _load_or_generate_key()
        key2 = _load_or_generate_key()
        assert key1 != key2


# ---------------------------------------------------------------------------
# Session API エンドポイントテスト
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(tmp_path):
    """テスト用 FastAPI クライアントとセッションマネージャーを提供する。"""
    # テスト用の WebSessionManager をシングルトンに設定
    from api.routers import session as session_router
    test_manager = WebSessionManager(key=_make_test_key())
    session_router._web_session_manager = test_manager

    from api.main import app
    client = TestClient(app)
    yield client, tmp_path

    # クリーンアップ
    session_router._web_session_manager = None


@pytest.fixture
def test_db(tmp_path):
    """テスト用 SecureStore DB を作成する。"""
    db_path = tmp_path / "session_test.db"
    _make_store(db_path, "correct_password")
    return db_path


class TestSessionAPI:
    """セッション API エンドポイントテスト"""

    def test_create_session_success(self, api_client, test_db):
        """正しいパスワードでセッション作成が成功する。

        CHECK-9: SessionManager.unlock() が True を返した場合に session_id を生成
        """
        client, _ = api_client
        res = client.post(
            "/api/session/create",
            json={
                "db_path": str(test_db),
                "password": "correct_password",
                "timeout_minutes": 10,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "created"
        assert "session_id" in data
        assert len(data["session_id"]) == 32
        assert data["timeout_minutes"] == 10

    def test_create_session_wrong_password(self, api_client, test_db):
        """誤ったパスワードでセッション作成が 401 を返す。

        CHECK-9: SessionManager.unlock() が False を返した場合に HTTP 401
        """
        client, _ = api_client
        res = client.post(
            "/api/session/create",
            json={
                "db_path": str(test_db),
                "password": "wrong_password",
                "timeout_minutes": 10,
            },
        )
        assert res.status_code == 401

    def test_session_status_valid(self, api_client, test_db):
        """作成済みセッションの状態確認が valid=True を返す。

        CHECK-9: create 直後はタイムアウトしていないため is_valid() == True
        """
        client, _ = api_client
        # セッション作成
        create_res = client.post(
            "/api/session/create",
            json={
                "db_path": str(test_db),
                "password": "correct_password",
                "timeout_minutes": 10,
            },
        )
        session_id = create_res.json()["session_id"]

        # 状態確認
        status_res = client.get(
            "/api/session/status",
            headers={"X-Session-Id": session_id},
        )
        assert status_res.status_code == 200
        data = status_res.json()
        assert data["valid"] is True
        assert data["status"] == "active"

    def test_session_status_invalid(self, api_client):
        """不明なセッションIDの状態確認が valid=False を返す。

        CHECK-9: _sessions dict にないキー → is_valid() == False
        """
        client, _ = api_client
        status_res = client.get(
            "/api/session/status",
            headers={"X-Session-Id": "unknown_session_id_xxxxxxxxxxxxxx"},
        )
        assert status_res.status_code == 200
        data = status_res.json()
        assert data["valid"] is False
        assert data["status"] == "expired_or_not_found"

    def test_session_refresh_success(self, api_client, test_db):
        """有効なセッションの refresh が成功する。

        CHECK-9: get_session() が None でなければ update_session() で時刻更新
        """
        client, _ = api_client
        create_res = client.post(
            "/api/session/create",
            json={
                "db_path": str(test_db),
                "password": "correct_password",
                "timeout_minutes": 10,
            },
        )
        session_id = create_res.json()["session_id"]

        refresh_res = client.post(
            "/api/session/refresh",
            headers={"X-Session-Id": session_id},
        )
        assert refresh_res.status_code == 200
        data = refresh_res.json()
        assert data["refreshed"] is True
        assert data["status"] == "refreshed"

    def test_session_refresh_unknown(self, api_client):
        """不明なセッションの refresh は refreshed=False を返す。

        CHECK-9: get_session() が None → update_session() は False → refreshed=False
        """
        client, _ = api_client
        refresh_res = client.post(
            "/api/session/refresh",
            headers={"X-Session-Id": "unknown_session_id_xxxxxxxxxxxxxx"},
        )
        assert refresh_res.status_code == 200
        data = refresh_res.json()
        assert data["refreshed"] is False

    def test_session_destroy_success(self, api_client, test_db):
        """有効なセッションの destroy が成功する。

        CHECK-9: delete_session() が True を返す
        """
        client, _ = api_client
        create_res = client.post(
            "/api/session/create",
            json={
                "db_path": str(test_db),
                "password": "correct_password",
                "timeout_minutes": 10,
            },
        )
        session_id = create_res.json()["session_id"]

        destroy_res = client.delete(
            "/api/session/destroy",
            headers={"X-Session-Id": session_id},
        )
        assert destroy_res.status_code == 200
        data = destroy_res.json()
        assert data["destroyed"] is True
        assert data["status"] == "destroyed"

    def test_session_destroy_removes_session(self, api_client, test_db):
        """destroy 後は状態確認が valid=False になる。

        CHECK-9: delete_session 後は _sessions から削除 → is_valid() == False
        """
        client, _ = api_client
        create_res = client.post(
            "/api/session/create",
            json={
                "db_path": str(test_db),
                "password": "correct_password",
                "timeout_minutes": 10,
            },
        )
        session_id = create_res.json()["session_id"]

        client.delete(
            "/api/session/destroy",
            headers={"X-Session-Id": session_id},
        )

        status_res = client.get(
            "/api/session/status",
            headers={"X-Session-Id": session_id},
        )
        assert status_res.json()["valid"] is False

    def test_session_destroy_unknown(self, api_client):
        """不明なセッションの destroy は destroyed=False を返す。

        CHECK-9: _sessions に存在しない → delete_session() は False
        """
        client, _ = api_client
        destroy_res = client.delete(
            "/api/session/destroy",
            headers={"X-Session-Id": "unknown_session_id_xxxxxxxxxxxxxx"},
        )
        assert destroy_res.status_code == 200
        data = destroy_res.json()
        assert data["destroyed"] is False
