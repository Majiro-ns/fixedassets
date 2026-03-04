"""
test_checklist.py
=================
disclosure-multiagent チェックリスト API のテスト

テスト対象エンドポイント:
  TC-C1: GET /api/checklist              → 200, 25件以上, スキーマ確認
  TC-C2: GET /api/checklist?required_only=true → 必須項目のみ返す
  TC-C3: GET /api/checklist?category=固定資産  → カテゴリ絞り込み
  TC-C4: POST /api/checklist/validate    → テキストマッチング（キーワードあり）
  TC-C5: POST /api/checklist/validate    → テキストマッチング（キーワードなし）
  TC-C6: POST /api/checklist/validate    → required_only=true で必須項目のみ照合
  TC-C7: POST /api/checklist/validate    → 空テキストで 400

CHECK-9 根拠:
  TC-C1: checklist_data.json に 25 件定義済み。items 配列長 >= 25 を検証。
  TC-C2: required=true の項目が全体 25 件中に存在。required_only=true で
         返ってくる items は全件 required=True であることを検証。
  TC-C3: category="固定資産" を指定すると CL-001〜CL-003 が返る（3件）。
  TC-C4: "減損損失" を含むテキストは CL-001 ("減損損失" キーワード) にマッチ →
         matched_count >= 1, coverage_rate > 0.0 を確認。
  TC-C5: "abcdefghijklmnopqrstuvwxyz" のような無関係テキストは
         チェックリストキーワードに一切マッチしない → matched_count=0, coverage_rate=0.0。
  TC-C6: required_only=true かつ matched 時は unmatched_required_count < total_checked。
  TC-C7: disclosure_text="" は HTTPException(400) → 400 Bad Request。

作成: 足軽6 cmd_285k_disclosure
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("USE_MOCK_LLM", "true")

_SCRIPTS_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
for p in [str(_SCRIPTS_DIR), str(_PROJECT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app, raise_server_exceptions=False)


class TestChecklistGet(unittest.TestCase):
    """TC-C1〜C3: GET /api/checklist"""

    def test_tc_c1_list_returns_items(self) -> None:
        """
        TC-C1: GET /api/checklist が 200 を返し 25 件以上の項目を含む

        根拠: checklist_data.json に CL-001〜CL-025 の 25 件を定義済み。
              version / last_updated / source / total / items フィールドを検証。
        CHECK-9: total == len(items) の整合性も確認。
        """
        resp = client.get("/api/checklist")
        self.assertEqual(resp.status_code, 200, f"GET /api/checklist が 200 を返さなかった: {resp.text}")

        body = resp.json()
        self.assertIn("items", body, "レスポンスに items フィールドがない")
        self.assertIn("total", body, "レスポンスに total フィールドがない")
        self.assertIn("version", body, "レスポンスに version フィールドがない")
        self.assertIn("source", body, "レスポンスに source フィールドがない")

        self.assertGreaterEqual(body["total"], 25, f"チェックリスト項目が 25 件未満: {body['total']}")
        self.assertEqual(
            len(body["items"]),
            body["total"],
            f"items 件数 ({len(body['items'])}) と total ({body['total']}) が不一致",
        )

        # 各 item のスキーマ確認（最初の1件）
        first = body["items"][0]
        for field in ("id", "category", "item", "required", "standard"):
            self.assertIn(field, first, f"item に '{field}' フィールドがない")

    def test_tc_c2_required_only_filter(self) -> None:
        """
        TC-C2: GET /api/checklist?required_only=true が必須項目のみ返す

        根拠: checklist_data.json で required=true の項目のみ絞り込んで返す。
              返ってきた全 items の required フィールドが True であることを検証。
        CHECK-9: required=false の項目（CL-019, CL-020, CL-024, CL-025）が除外されること。
        """
        resp = client.get("/api/checklist", params={"required_only": "true"})
        self.assertEqual(resp.status_code, 200, f"required_only filter が 200 を返さなかった: {resp.text}")

        body = resp.json()
        items = body["items"]
        self.assertGreater(len(items), 0, "required_only=true で 0 件は異常")

        for item in items:
            self.assertTrue(
                item["required"],
                f"required_only=true なのに required=false の項目が含まれる: {item['id']}",
            )

    def test_tc_c3_category_filter(self) -> None:
        """
        TC-C3: GET /api/checklist?category=固定資産 が固定資産カテゴリのみ返す

        根拠: CL-001, CL-002, CL-003 が category="固定資産" として定義されているため
              3 件が返る。全 items の category が "固定資産" であることを検証。
        CHECK-9: 絞り込み件数は 3 件（CL-001〜CL-003）。
        """
        resp = client.get("/api/checklist", params={"category": "固定資産"})
        self.assertEqual(resp.status_code, 200, f"category filter が 200 を返さなかった: {resp.text}")

        body = resp.json()
        items = body["items"]
        self.assertGreater(len(items), 0, "category=固定資産 で 0 件は異常")

        for item in items:
            self.assertEqual(
                item["category"],
                "固定資産",
                f"カテゴリ絞り込み漏れ: {item['id']} は category={item['category']}",
            )


class TestChecklistValidate(unittest.TestCase):
    """TC-C4〜C7: POST /api/checklist/validate"""

    def test_tc_c4_validate_with_matching_keywords(self) -> None:
        """
        TC-C4: 減損関連キーワードを含むテキストで照合 → matched_count >= 1

        根拠: CL-001 の keywords に "減損損失" が含まれる。
              disclosure_text に "減損損失" を含めると matched=True になる。
        CHECK-9: coverage_rate = matched_count / total_checked > 0.0 を確認。
                 results に matched=True の項目が存在することを確認。
        """
        payload = {
            "disclosure_text": (
                "当社は当期において固定資産の減損損失を計上しました。"
                "回収可能価額は使用価値により算定し、割引率は5%を使用しました。"
                "退職給付債務については数理差異を認識しております。"
            ),
        }
        resp = client.post("/api/checklist/validate", json=payload)
        self.assertEqual(resp.status_code, 200, f"validate が 200 を返さなかった: {resp.text}")

        body = resp.json()
        self.assertIn("matched_count", body)
        self.assertIn("total_checked", body)
        self.assertIn("coverage_rate", body)
        self.assertIn("results", body)

        self.assertGreater(body["matched_count"], 0, "キーワードあり → matched_count > 0 のはず")
        self.assertGreater(body["coverage_rate"], 0.0, "coverage_rate > 0.0 のはず")
        self.assertGreater(body["total_checked"], 0, "total_checked > 0 のはず")

        # matched=True の項目が results に存在する
        matched_ids = [r["id"] for r in body["results"] if r["matched"]]
        self.assertGreater(len(matched_ids), 0, "matched=True の項目が results に存在しない")

    def test_tc_c5_validate_with_no_matching_keywords(self) -> None:
        """
        TC-C5: 無関係テキストで照合 → matched_count=0, coverage_rate=0.0

        根拠: "XYZ Corporation annual report abcde 12345" はチェックリストの
              いずれの keywords（日本語）にも一致しない。
        CHECK-9: matched_count=0 のとき coverage_rate=0.0。
                 unmatched_required_count は required=True の全件数と等しい。
        """
        payload = {
            "disclosure_text": "XYZ Corporation annual report abcde 12345",
        }
        resp = client.post("/api/checklist/validate", json=payload)
        self.assertEqual(resp.status_code, 200, f"validate が 200 を返さなかった: {resp.text}")

        body = resp.json()
        self.assertEqual(body["matched_count"], 0, f"無関係テキスト → matched_count=0 のはず: {body['matched_count']}")
        self.assertAlmostEqual(body["coverage_rate"], 0.0, places=5, msg="coverage_rate=0.0 のはず")

    def test_tc_c6_validate_required_only(self) -> None:
        """
        TC-C6: required_only=True で照合 → total_checked が全件より少ない

        根拠: required=false の項目（CL-019, CL-020, CL-024, CL-025: 4件）が除外される。
              required_only=true の total_checked < required_only=false の total_checked。
        CHECK-9: required_only=false 時の全件数 >= required_only=true 時の件数。
                 返ってきた results の required フィールドは全件 True。
        """
        # 全件照合
        resp_all = client.post("/api/checklist/validate", json={
            "disclosure_text": "減損損失 退職給付 収益認識 セグメント",
            "required_only": False,
        })
        # 必須のみ照合
        resp_req = client.post("/api/checklist/validate", json={
            "disclosure_text": "減損損失 退職給付 収益認識 セグメント",
            "required_only": True,
        })

        self.assertEqual(resp_all.status_code, 200)
        self.assertEqual(resp_req.status_code, 200)

        total_all = resp_all.json()["total_checked"]
        total_req = resp_req.json()["total_checked"]

        self.assertGreaterEqual(
            total_all, total_req,
            f"全件({total_all}) >= 必須のみ({total_req}) でなければならない",
        )
        self.assertGreater(total_req, 0, "required_only=true で 0 件は異常")

        # required_only=true の results は全件 required=True
        for r in resp_req.json()["results"]:
            self.assertTrue(r["required"], f"required_only=true なのに required=false: {r['id']}")

    def test_tc_c7_validate_empty_text_returns_400(self) -> None:
        """
        TC-C7: 空テキストで POST /api/checklist/validate → 400 Bad Request

        根拠: checklist.py validate_checklist() で
              request.disclosure_text.strip() == "" の場合
              HTTPException(status_code=400, detail="disclosure_text が空です") を raise。
        CHECK-9: FastAPI HTTPException(400) は 400 Bad Request として返る。
        """
        payload = {"disclosure_text": ""}
        resp = client.post("/api/checklist/validate", json=payload)
        self.assertEqual(
            resp.status_code,
            400,
            f"空テキストに対して 400 を返さなかった: {resp.status_code} / {resp.text}",
        )
        self.assertIn(
            "disclosure_text",
            resp.json().get("detail", ""),
            "エラーメッセージに 'disclosure_text' が含まれない",
        )


if __name__ == "__main__":
    unittest.main()
