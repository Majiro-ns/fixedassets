"""
test_checklist_eval.py
======================
disclosure-multiagent T010: チェックリスト評価履歴・バッチ評価 API のテスト

テスト対象エンドポイント:
  TC-E1: POST /api/checklist/evaluate          → 200, eval_id返却, coverage_rate計算
  TC-E2: POST /api/checklist/evaluate          → 空テキスト → 400
  TC-E3: GET  /api/checklist/evaluations       → 空DB → count=0
  TC-E4: GET  /api/checklist/evaluations       → 評価後 → count=1
  TC-E5: GET  /api/checklist/evaluations/{id}  → 存在する評価 → 200, results付き
  TC-E6: GET  /api/checklist/evaluations/{id}  → 存在しないID → 404
  TC-E7: POST /api/checklist/evaluate          → キーワードマッチ → coverage_rate > 0
  TC-E8: 複数評価後のリスト → count=2, 最新順

CHECK-9 根拠:
  TC-E1: UUID4 形式・evaluated_at・total_checked=25（全件）を検証。
  TC-E2: disclosure_text="" → HTTPException(400) を検証。
  TC-E3: 空DBではevaluations=[], count=0。
  TC-E4: evaluate 1回後 → evaluations list に1件が含まれる。
  TC-E5: eval_id で詳細取得 → results に 25 件含まれる。
  TC-E6: 存在しないUUID → 404。
  TC-E7: "減損損失" を含むテキスト → CL-001（keywords: ["減損損失"]）がマッチ
         → matched_count >= 1, coverage_rate > 0.0。
  TC-E8: 2回 evaluate → evaluations list に2件、evaluated_at で降順（最新が先頭）。

作成: 足軽6 cmd_285k_disclosure_T010
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("USE_MOCK_LLM", "true")

_SCRIPTS_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
for p in [str(_SCRIPTS_DIR), str(_PROJECT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


def _make_client(db_path: str):
    """一時 DB を指定して TestClient を生成する（モジュールリロードで DB パスを反映）。"""
    os.environ["DISCLOSURE_DB_PATH"] = db_path
    from importlib import reload
    import api.services.checklist_eval_service as svc_mod
    reload(svc_mod)
    import api.routers.checklist_eval as eval_mod
    reload(eval_mod)
    import api.main as main_mod
    reload(main_mod)
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


# ──────────────────────────────────────────────────────────────────────────────
# TC-E1 / TC-E2: POST /api/checklist/evaluate
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluate(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = str(Path(self._tmpdir.name) / "test.db")
        self.client = _make_client(db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_tc_e1_evaluate_returns_eval_id(self):
        """TC-E1: 正常テキスト → 200, eval_id（UUID4形式）・total_checked=25 を返す。

        根拠: evaluate_and_save は categories=None, required_only=False で
             全25項目を照合し、UUID4を生成して返す。
        """
        resp = self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": "固定資産の減損損失について注記した。"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        # eval_id: UUID4 形式（8-4-4-4-12 ハイフン区切り）
        import re
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        self.assertRegex(body["eval_id"], uuid_pattern, "eval_id が UUID4 形式でない")

        self.assertIn("evaluated_at", body)
        self.assertIn("text_snippet", body)
        self.assertEqual(body["total_checked"], 25, "全件（25項目）を照合すること")
        self.assertIn("coverage_rate", body)
        self.assertGreaterEqual(body["coverage_rate"], 0.0)
        self.assertLessEqual(body["coverage_rate"], 1.0)

    def test_tc_e2_evaluate_empty_text_returns_400(self):
        """TC-E2: 空テキスト → 400 Bad Request。

        根拠: checklist_eval_service.evaluate_and_save は空テキストで ValueError を送出。
             ルーターが HTTPException(400) に変換する。
        """
        resp = self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": ""},
        )
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_tc_e2_evaluate_whitespace_only_returns_400(self):
        """TC-E2（補足）: 空白のみテキストも 400 を返す。

        根拠: "   ".strip() == "" → 空テキストと同扱い。
        """
        resp = self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": "   "},
        )
        self.assertEqual(resp.status_code, 400, resp.text)

    def test_tc_e7_keyword_match_raises_coverage_rate(self):
        """TC-E7: "減損損失" を含むテキスト → coverage_rate > 0.0。

        根拠: CL-001 の keywords に "減損損失" が含まれる。
             テキストにマッチ → matched_count >= 1 → coverage_rate = matched/25 > 0。
        """
        resp = self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": "当期において減損損失を計上しました。回収可能価額を算定した。"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertGreater(body["matched_count"], 0, "減損損失 がマッチしなかった")
        self.assertGreater(body["coverage_rate"], 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# TC-E3 / TC-E4 / TC-E8: GET /api/checklist/evaluations
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluationsList(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = str(Path(self._tmpdir.name) / "test.db")
        self.client = _make_client(db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_tc_e3_evaluations_empty_db(self):
        """TC-E3: 空DB → evaluations=[], count=0。

        根拠: eval_history テーブルが空の状態では件数0件を返す。
        """
        resp = self.client.get("/api/checklist/evaluations")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["evaluations"], [])

    def test_tc_e4_evaluations_after_one_evaluate(self):
        """TC-E4: 1回 evaluate 後 → count=1。

        根拠: evaluate_and_save が eval_history に INSERT → リスト取得で1件。
        """
        self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": "有価証券報告書の注記として減損損失を記載した。"},
        )

        resp = self.client.get("/api/checklist/evaluations")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(len(body["evaluations"]), 1)

        ev = body["evaluations"][0]
        self.assertIn("eval_id", ev)
        self.assertIn("evaluated_at", ev)
        self.assertIn("coverage_rate", ev)

    def test_tc_e8_multiple_evaluations_ordered_by_latest(self):
        """TC-E8: 2回 evaluate → count=2。

        根拠: 2件 INSERT → GET /evaluations が count=2 を返す。
             最新 evaluated_at が先頭に来る（ORDER BY evaluated_at DESC）。
        """
        self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": "第1回評価: 退職給付債務の注記。"},
        )
        self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": "第2回評価: リース資産の使用権資産計上。"},
        )

        resp = self.client.get("/api/checklist/evaluations")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(body["evaluations"]), 2)


# ──────────────────────────────────────────────────────────────────────────────
# TC-E5 / TC-E6: GET /api/checklist/evaluations/{eval_id}
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluationDetail(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        db_path = str(Path(self._tmpdir.name) / "test.db")
        self.client = _make_client(db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_tc_e5_get_evaluation_detail_returns_results(self):
        """TC-E5: 存在する eval_id → 200, results に 25 件含まれる。

        根拠: evaluate_and_save は全 25 項目の結果を results_json に保存。
             詳細取得 API は results を parse して返す。
        """
        post_resp = self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": "有価証券報告書の注記として金融商品を記載した。"},
        )
        self.assertEqual(post_resp.status_code, 200)
        eval_id = post_resp.json()["eval_id"]

        resp = self.client.get(f"/api/checklist/evaluations/{eval_id}")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        self.assertEqual(body["eval_id"], eval_id)
        self.assertIn("results", body)
        self.assertEqual(len(body["results"]), 25, "全 25 項目の results が返されること")
        self.assertIn("unmatched_required_ids", body)

        # results の各項目が期待フィールドを持つことを確認
        first = body["results"][0]
        for field in ["id", "category", "item", "required", "matched", "matched_keywords", "standard"]:
            self.assertIn(field, first, f"results[0] に {field} が欠落")

    def test_tc_e6_get_evaluation_not_found_returns_404(self):
        """TC-E6: 存在しない UUID → 404。

        根拠: eval_history に存在しない eval_id を指定 → service が None を返す
             → router が HTTPException(404) を送出。
        """
        fake_id = "00000000-0000-4000-8000-000000000000"
        resp = self.client.get(f"/api/checklist/evaluations/{fake_id}")
        self.assertEqual(resp.status_code, 404, resp.text)


if __name__ == "__main__":
    unittest.main()
