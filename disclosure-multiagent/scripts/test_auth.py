"""
test_auth.py
============
disclosure-multiagent APIキー認証テスト

テスト対象:
  TC-C1: API_KEY 未設定時は全エンドポイントが認証スキップ → 200
  TC-C2: API_KEY 設定済み + 正しい X-API-Key ヘッダー → 200
  TC-C3: API_KEY 設定済み + 正しい Bearer トークン → 200
  TC-C4: API_KEY 設定済み + キーなし → 401
  TC-C5: API_KEY 設定済み + 不正なキー → 401
  TC-C6: GET /api/health は認証不要（常に 200）
  TC-C7: API_KEY 設定済み + /api/edinet/search に正しいキー → 200
  TC-C8: API_KEY 設定済み + /api/edinet/search にキーなし → 401
  TC-C9: API_KEY 設定済み + X-API-Key Bearer プレフィックス混在 → 401

CHECK-9 根拠（期待値の根拠）:
  TC-C1: API_KEY="" → verify_api_key() が早期 return → 認証バイパス
  TC-C2: x_api_key == configured_key → return（pass）
  TC-C3: authorization.startswith("Bearer ") → token == configured_key → return
  TC-C4: configured_key != "" && x_api_key is None && authorization is None → HTTPException(401)
  TC-C5: configured_key != x_api_key && token != configured_key → HTTPException(401)
  TC-C6: /api/health は Depends(verify_api_key) を持たない → 常に 200
  TC-C7: /api/edinet/search + 正しい X-API-Key → 認証通過（ただし name 未指定で 400）
         → 本テストでは name="テスト" 付きで 200 を確認
  TC-C8: /api/edinet/search + キーなし → 401（認証より先に弾かれる）
  TC-C9: "Bearer " プレフィックスなしで X-API-Key ヘッダーに "Bearer <key>" を渡す →
         "Bearer xxx" != configured_key なので 401

作成: 足軽7 / T008 認証・APIキー管理
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# USE_MOCK_LLM=true を強制（実 LLM API 呼び出しをしない）
os.environ.setdefault("USE_MOCK_LLM", "true")

# scripts/ をインポートパスに追加
_SCRIPTS_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
for p in [str(_SCRIPTS_DIR), str(_PROJECT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# NOTE: TestClient は各テストメソッド内で生成し、環境変数の変更を反映させる。
# FastAPI の Depends は関数呼び出し時に評価されるが、
# verify_api_key 内の os.environ.get() は呼び出し毎に評価されるため、
# 環境変数変更後に新しい TestClient を生成することで正しくテストできる。
from fastapi.testclient import TestClient

_VALID_KEY = "test-secret-key-for-t008"


def _make_client() -> TestClient:
    """api.main を再インポートせず既存の app を使う。"""
    # api.main のキャッシュを無効化して再インポート（環境変数変更を反映）
    import importlib
    import api.auth as auth_module
    importlib.reload(auth_module)

    # routers を再インポート
    import api.routers.analyze as analyze_module
    import api.routers.edinet as edinet_module
    import api.routers.status as status_module
    importlib.reload(analyze_module)
    importlib.reload(edinet_module)
    importlib.reload(status_module)

    import api.main as main_module
    importlib.reload(main_module)
    return TestClient(main_module.app, raise_server_exceptions=False)


class TestApiKeyAuthDisabled(unittest.TestCase):
    """TC-C1, TC-C6: API_KEY 未設定時（開発モード）のテスト"""

    def setUp(self):
        """API_KEY を環境変数から削除して開発モードにする。"""
        os.environ.pop("API_KEY", None)
        self.client = _make_client()

    def tearDown(self):
        os.environ.pop("API_KEY", None)

    def test_tc_c1_no_api_key_env_analyze_returns_200(self) -> None:
        """
        TC-C1: API_KEY 未設定時は POST /api/analyze が認証なしで 200 を返す

        根拠: verify_api_key() は configured_key="" のとき早期 return。
              認証ミドルウェアはスキップされる（開発モード）。
        CHECK-9: API_KEY="" → HTTPException を raise しない → エンドポイントが正常動作。
        """
        payload = {
            "company_name": "認証テスト社",
            "fiscal_year": 2025,
            "level": "梅",
            "use_mock": True,
        }
        resp = self.client.post("/api/analyze", json=payload)
        self.assertEqual(
            resp.status_code,
            200,
            f"API_KEY 未設定時に 200 が返らなかった: {resp.status_code} / {resp.text}",
        )
        self.assertIn("task_id", resp.json(), "task_id がレスポンスにない")

    def test_tc_c6_health_always_200_no_auth(self) -> None:
        """
        TC-C6: GET /api/health は認証不要。常に 200 を返す

        根拠: health() エンドポイントには Depends(verify_api_key) がない。
              API_KEY が設定されていても health は通過する。
        CHECK-9: api/main.py の @app.get("/api/health") に依存なし。
        """
        resp = self.client.get("/api/health")
        self.assertEqual(
            resp.status_code,
            200,
            f"/api/health が 200 を返さなかった: {resp.status_code}",
        )
        self.assertEqual(resp.json().get("status"), "ok")


class TestApiKeyAuthEnabled(unittest.TestCase):
    """TC-C2〜C5, TC-C7〜C9: API_KEY 設定済み時の認証テスト"""

    def setUp(self):
        """有効な API_KEY を設定する。"""
        os.environ["API_KEY"] = _VALID_KEY
        self.client = _make_client()

    def tearDown(self):
        os.environ.pop("API_KEY", None)

    def test_tc_c2_valid_x_api_key_header_returns_200(self) -> None:
        """
        TC-C2: API_KEY 設定済み + 正しい X-API-Key ヘッダー → POST /api/analyze が 200

        根拠: verify_api_key() で x_api_key == configured_key → return（pass）。
              エンドポイントが正常実行される。
        CHECK-9: X-API-Key: test-secret-key-for-t008 == API_KEY → 認証通過。
        """
        payload = {
            "company_name": "X-API-Key 認証テスト社",
            "fiscal_year": 2025,
            "level": "梅",
            "use_mock": True,
        }
        resp = self.client.post(
            "/api/analyze",
            json=payload,
            headers={"X-API-Key": _VALID_KEY},
        )
        self.assertEqual(
            resp.status_code,
            200,
            f"正しい X-API-Key で 200 が返らなかった: {resp.status_code} / {resp.text}",
        )
        self.assertIn("task_id", resp.json())

    def test_tc_c3_valid_bearer_token_returns_200(self) -> None:
        """
        TC-C3: API_KEY 設定済み + Authorization: Bearer <token> → 200

        根拠: verify_api_key() で authorization.startswith("Bearer ") &&
              token == configured_key → return（pass）。
        CHECK-9: "Bearer " + "test-secret-key-for-t008" → token 抽出 → 一致 → 認証通過。
        """
        payload = {
            "company_name": "Bearer 認証テスト社",
            "fiscal_year": 2025,
            "level": "梅",
            "use_mock": True,
        }
        resp = self.client.post(
            "/api/analyze",
            json=payload,
            headers={"Authorization": f"Bearer {_VALID_KEY}"},
        )
        self.assertEqual(
            resp.status_code,
            200,
            f"正しい Bearer トークンで 200 が返らなかった: {resp.status_code} / {resp.text}",
        )
        self.assertIn("task_id", resp.json())

    def test_tc_c4_no_key_returns_401(self) -> None:
        """
        TC-C4: API_KEY 設定済み + ヘッダーなし → POST /api/analyze が 401

        根拠: configured_key != "" && x_api_key is None && authorization is None
              → HTTPException(401, "Invalid or missing API key...")
        CHECK-9: ヘッダー送信なし → 全チェック失敗 → 401 Unauthorized。
        """
        payload = {
            "company_name": "認証なしテスト社",
            "fiscal_year": 2025,
            "level": "梅",
            "use_mock": True,
        }
        resp = self.client.post("/api/analyze", json=payload)
        self.assertEqual(
            resp.status_code,
            401,
            f"ヘッダーなしで 401 が返らなかった: {resp.status_code} / {resp.text}",
        )
        detail = resp.json().get("detail", "")
        self.assertIn(
            "Invalid or missing API key",
            detail,
            f"エラーメッセージが期待値と異なる: {detail}",
        )

    def test_tc_c5_invalid_key_returns_401(self) -> None:
        """
        TC-C5: API_KEY 設定済み + 不正なキー → 401

        根拠: x_api_key = "wrong-key" != configured_key → 一致せず。
              authorization も None → 全チェック失敗 → HTTPException(401)。
        CHECK-9: "wrong-key" != "test-secret-key-for-t008" → 401。
        """
        payload = {
            "company_name": "不正キーテスト社",
            "fiscal_year": 2025,
            "level": "梅",
            "use_mock": True,
        }
        resp = self.client.post(
            "/api/analyze",
            json=payload,
            headers={"X-API-Key": "wrong-key-that-does-not-match"},
        )
        self.assertEqual(
            resp.status_code,
            401,
            f"不正キーで 401 が返らなかった: {resp.status_code} / {resp.text}",
        )

    def test_tc_c7_edinet_search_with_valid_key_returns_200(self) -> None:
        """
        TC-C7: API_KEY 設定済み + /api/edinet/search に正しい X-API-Key → 200

        根拠: edinet.py の search_company() にも Depends(verify_api_key) を追加済み。
              正しいキーで name="テスト" を渡すと 200 + CompanySearchResponse が返る。
        CHECK-9: search_by_name("テスト") は 0件以上を返す。total == len(results)。
        """
        resp = self.client.get(
            "/api/edinet/search",
            params={"name": "テスト"},
            headers={"X-API-Key": _VALID_KEY},
        )
        self.assertEqual(
            resp.status_code,
            200,
            f"/api/edinet/search 正しいキーで 200 が返らなかった: {resp.status_code} / {resp.text}",
        )
        body = resp.json()
        self.assertIn("results", body)
        self.assertIn("total", body)

    def test_tc_c8_edinet_search_without_key_returns_401(self) -> None:
        """
        TC-C8: API_KEY 設定済み + /api/edinet/search にキーなし → 401

        根拠: search_company() の Depends(verify_api_key) が先に評価され、
              キー未送信のため HTTPException(401) を raise。
              パラメータバリデーション（name 未指定で 400）よりも認証が先。
        CHECK-9: FastAPI の Depends は関数実行前に評価される → 認証失敗 → 401。
        """
        resp = self.client.get("/api/edinet/search", params={"name": "テスト"})
        self.assertEqual(
            resp.status_code,
            401,
            f"/api/edinet/search キーなしで 401 が返らなかった: {resp.status_code} / {resp.text}",
        )

    def test_tc_c9_bearer_prefix_in_x_api_key_header_returns_401(self) -> None:
        """
        TC-C9: X-API-Key ヘッダーに "Bearer <key>" を渡すと 401

        根拠: X-API-Key ヘッダーの値は "Bearer test-secret-key-for-t008"。
              configured_key = "test-secret-key-for-t008" と一致しない。
              Authorization ヘッダーは未送信。
              → 全チェック失敗 → HTTPException(401)。
        CHECK-9: X-API-Key には "Bearer " プレフィックスなしの生のキーを渡すべき。
                 誤って Bearer を付けると 401 になる（セキュリティ上正しい動作）。
        """
        payload = {
            "company_name": "プレフィックス混在テスト社",
            "fiscal_year": 2025,
            "level": "梅",
            "use_mock": True,
        }
        resp = self.client.post(
            "/api/analyze",
            json=payload,
            headers={"X-API-Key": f"Bearer {_VALID_KEY}"},
        )
        self.assertEqual(
            resp.status_code,
            401,
            f"Bearer プレフィックス混在で 401 が返らなかった: {resp.status_code} / {resp.text}",
        )


if __name__ == "__main__":
    unittest.main()
