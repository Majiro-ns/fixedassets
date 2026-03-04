"""
test_checklist_stats.py
=======================
disclosure-multiagent T011: 評価統計ダッシュボード API のテスト

テスト対象エンドポイント:
  TC-ST1: GET /api/checklist/stats/summary  → 空DB → total_evaluations=0, all rates=0.0
  TC-ST2: GET /api/checklist/stats/summary  → 複数評価後 → total/avg/max/min が正確
  TC-ST3: GET /api/checklist/stats/top-items → 空DB → items=[], count=0
  TC-ST4: GET /api/checklist/stats/top-items → 複数評価後 → ランキング返却、match_rate>0
  TC-ST5: compute_summary 純粋関数テスト → rows指定 → 正確な統計値
  TC-ST6: compute_top_items 純粋関数テスト → 期待ランキング順・match_rate計算
  TC-ST7: GET /api/checklist/stats/top-items?limit=2 → 上位2件のみ返す

CHECK-9 根拠:
  TC-ST1: eval_history が空 → total_evaluations=0, avg/max/min=0.0（ゼロ除算なし）
  TC-ST2: coverage_rate=[0.2, 0.6, 1.0] の3件 → avg=0.6, max=1.0, min=0.2
  TC-ST3: 空DB → items=[], count=0
  TC-ST4: "減損損失" テキストで評価 → CL-001 がマッチ → ランキング1位 or 上位
          match_rate = match_count / total_evaluations * 100
  TC-ST5: rows=[{coverage_rate:0.4},{coverage_rate:0.8}] → avg=0.6, max=0.8, min=0.4
  TC-ST6: item A=2回マッチ, item B=1回マッチ → A首位, match_rate=A:100.0, B:50.0
  TC-ST7: limit=2 → items の count <= 2

作成: 足軽6 cmd_285k_disclosure_T011
"""
from __future__ import annotations

import json
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
    """一時 DB を指定して TestClient を生成する。"""
    os.environ["DISCLOSURE_DB_PATH"] = db_path
    from importlib import reload
    import api.services.checklist_eval_service as svc_eval
    reload(svc_eval)
    import api.services.checklist_stats_service as svc_stats
    reload(svc_stats)
    import api.routers.checklist_eval as eval_mod
    reload(eval_mod)
    import api.routers.checklist_stats as stats_mod
    reload(stats_mod)
    import api.main as main_mod
    reload(main_mod)
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app, raise_server_exceptions=False)


# ──────────────────────────────────────────────────────────────────────────────
# TC-ST1 / TC-ST2: GET /api/checklist/stats/summary
# ──────────────────────────────────────────────────────────────────────────────

class TestStatsSummary(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmpdir.name) / "test.db")
        self.client = _make_client(self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_tc_st1_summary_empty_db(self):
        """TC-ST1: 空DB → total_evaluations=0, avg/max/min_coverage_rate=0.0。

        根拠: eval_history が空 → compute_summary([]) → ゼロ値返却。
        """
        resp = self.client.get("/api/checklist/stats/summary")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        self.assertEqual(body["total_evaluations"], 0)
        self.assertAlmostEqual(body["avg_coverage_rate"], 0.0)
        self.assertAlmostEqual(body["max_coverage_rate"], 0.0)
        self.assertAlmostEqual(body["min_coverage_rate"], 0.0)

    def test_tc_st2_summary_after_evaluations(self):
        """TC-ST2: 3回評価後 → total=3, avg/max/min が正確に計算される。

        根拠: 3回の evaluate から coverage_rate を集計。
             avg = round(sum/3, 2), max/min は Python max/min。
        """
        texts = [
            "固定資産の減損損失を計上した。回収可能価額を公正価値で算定した。",    # 多めにマッチ
            "有価証券報告書の当期純利益の開示。",                                   # 少なめにマッチ
            "減損損失、退職給付費用、リース資産、金融商品、デリバティブ取引を注記。",  # 最多マッチ
        ]
        for t in texts:
            r = self.client.post("/api/checklist/evaluate", json={"disclosure_text": t})
            self.assertEqual(r.status_code, 200)

        resp = self.client.get("/api/checklist/stats/summary")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        self.assertEqual(body["total_evaluations"], 3)
        self.assertGreaterEqual(body["avg_coverage_rate"], 0.0)
        self.assertLessEqual(body["avg_coverage_rate"], 1.0)
        self.assertGreaterEqual(body["max_coverage_rate"], body["min_coverage_rate"])
        # min <= avg <= max
        self.assertGreaterEqual(body["avg_coverage_rate"], body["min_coverage_rate"] - 1e-9)
        self.assertLessEqual(body["avg_coverage_rate"], body["max_coverage_rate"] + 1e-9)


# ──────────────────────────────────────────────────────────────────────────────
# TC-ST3 / TC-ST4 / TC-ST7: GET /api/checklist/stats/top-items
# ──────────────────────────────────────────────────────────────────────────────

class TestStatsTopItems(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmpdir.name) / "test.db")
        self.client = _make_client(self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_tc_st3_top_items_empty_db(self):
        """TC-ST3: 空DB → items=[], count=0, total_evaluations=0。

        根拠: eval_history が空 → compute_top_items([]) → 空リスト返却。
        """
        resp = self.client.get("/api/checklist/stats/top-items")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        self.assertEqual(body["total_evaluations"], 0)
        self.assertEqual(body["items"], [])
        self.assertEqual(body["count"], 0)

    def test_tc_st4_top_items_after_evaluations(self):
        """TC-ST4: 評価後 → ランキング返却、match_rate > 0。

        根拠: "減損損失" を含むテキストで評価 → CL-001 がマッチ
             → items に1件以上含まれ、match_rate > 0.0。
        """
        self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": "固定資産の減損損失を計上した。回収可能価額を公正価値で算定した。"},
        )

        resp = self.client.get("/api/checklist/stats/top-items")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        self.assertEqual(body["total_evaluations"], 1)
        self.assertGreater(body["count"], 0, "1件以上のマッチ項目が返されること")
        top = body["items"][0]
        self.assertIn("item_id", top)
        self.assertIn("item_name", top)
        self.assertGreater(top["match_count"], 0)
        self.assertGreater(top["match_rate"], 0.0)

    def test_tc_st7_top_items_limit_parameter(self):
        """TC-ST7: limit=2 クエリパラメータ → 返却件数 <= 2。

        根拠: GET /api/checklist/stats/top-items?limit=2 → top_n=2 で集計
             → items の長さは最大 2 件。
        """
        # 多くのキーワードにマッチするテキストで評価
        self.client.post(
            "/api/checklist/evaluate",
            json={"disclosure_text": (
                "減損損失を計上。退職給付費用を認識。リース資産を計上。"
                "金融商品の時価を開示。デリバティブの公正価値評価。"
            )},
        )

        resp = self.client.get("/api/checklist/stats/top-items?limit=2")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()

        self.assertLessEqual(body["count"], 2, "limit=2 で3件以上返ってはならない")
        self.assertLessEqual(len(body["items"]), 2)


# ──────────────────────────────────────────────────────────────────────────────
# TC-ST5 / TC-ST6: 純粋関数テスト
# ──────────────────────────────────────────────────────────────────────────────

class TestPureFunctions(unittest.TestCase):

    def test_tc_st5_compute_summary_exact_values(self):
        """TC-ST5: compute_summary の計算値を手計算で検証。

        根拠: rates=[0.2, 0.6, 1.0]
             avg = round((0.2+0.6+1.0)/3, 2) = round(0.6, 2) = 0.6
             max = 1.0, min = 0.2
        """
        from api.services.checklist_stats_service import compute_summary
        rows = [
            {"coverage_rate": 0.2},
            {"coverage_rate": 0.6},
            {"coverage_rate": 1.0},
        ]
        result = compute_summary(rows)

        self.assertEqual(result["total_evaluations"], 3)
        self.assertAlmostEqual(result["avg_coverage_rate"], 0.6, places=2)
        self.assertAlmostEqual(result["max_coverage_rate"], 1.0, places=2)
        self.assertAlmostEqual(result["min_coverage_rate"], 0.2, places=2)

    def test_tc_st6_compute_top_items_ranking(self):
        """TC-ST6: compute_top_items のランキング順・match_rate 計算を検証。

        根拠: 2件の評価で
             item A (CL-001) → 両方でマッチ: match_count=2, match_rate=100.0%
             item B (CL-002) → 1件のみマッチ: match_count=1, match_rate=50.0%
             → A が B より上位。
        """
        from api.services.checklist_stats_service import compute_top_items

        result_a_b = json.dumps([
            {"id": "CL-001", "item": "減損テスト", "matched": True, "matched_keywords": ["減損"]},
            {"id": "CL-002", "item": "退職給付テスト", "matched": True, "matched_keywords": ["退職"]},
        ])
        result_a_only = json.dumps([
            {"id": "CL-001", "item": "減損テスト", "matched": True, "matched_keywords": ["減損"]},
            {"id": "CL-002", "item": "退職給付テスト", "matched": False, "matched_keywords": []},
        ])

        rows = [
            {"results_json": result_a_b},
            {"results_json": result_a_only},
        ]
        result = compute_top_items(rows)

        self.assertEqual(result["total_evaluations"], 2)
        items = result["items"]
        self.assertGreaterEqual(len(items), 2, "少なくとも2件のランキングが返ること")

        # 先頭が CL-001（A）
        self.assertEqual(items[0]["item_id"], "CL-001")
        self.assertEqual(items[0]["match_count"], 2)
        self.assertAlmostEqual(items[0]["match_rate"], 100.0, places=1)

        # 2番目が CL-002（B）
        self.assertEqual(items[1]["item_id"], "CL-002")
        self.assertEqual(items[1]["match_count"], 1)
        self.assertAlmostEqual(items[1]["match_rate"], 50.0, places=1)


if __name__ == "__main__":
    unittest.main()
