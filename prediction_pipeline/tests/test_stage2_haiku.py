"""
tests/test_stage2_haiku.py
==========================
stage2_haiku.get_pending_requests() のF10フィルターテスト。

#T002対策案1 cmd_132k_sub3: f10_passed=False のリクエストをスキップする実装の検証。

テスト期待値の根拠（CHECK-9）:
  - f10_passed=False → ashigaru_predict.py でフラグが立ったレース（confidence_score < min_confidence_score）
    2月分析: hit_prob<0.9の的中率9.1%。除外すべき。
  - f10_passed=True → 閾値を超えたレース。処理対象。
  - f10_passed キーなし → 旧フォーマットYAML（Stage1改修前）。後方互換で処理対象。
"""

import sys
from pathlib import Path

import pytest
import yaml

# scripts/ をパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import stage2_haiku


# ─── テスト用ヘルパー ────────────────────────────────────────────

def _write_req(req_dir: Path, task_id: str, f10_passed, conf_score: int = 2) -> Path:
    """テスト用リクエストYAMLを書き出す。f10_passed=None の場合はキーを省略（後方互換テスト用）。"""
    req: dict = {
        "task_id": task_id,
        "status": "pending",
        "venue": "川崎",
        "race_no": 9,
        "grade": "S1",
        "stage": "特選",
        "sport": "keirin",
        "filter_passed": True,
        "filter_reasons": [],
        "confidence_score": conf_score,
    }
    if f10_passed is not None:
        req["f10_passed"] = f10_passed
    req_file = req_dir / f"{task_id}.yaml"
    req_file.write_text(yaml.dump(req, allow_unicode=True), encoding="utf-8")
    return req_file


# ─── F10フィルターテスト ─────────────────────────────────────────

class TestGetPendingRequestsF10Filter:
    """get_pending_requests() の F10フィルター動作テスト。"""

    def test_f10_passed_false_skipped(self, tmp_path, monkeypatch):
        """f10_passed=False のリクエストがスキップされること。
        根拠: confidence_score < min_confidence_score のレース。
              2月分析で hit_prob<0.9の的中率9.1% → 除外正当。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_haiku, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_haiku, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=False, conf_score=1)

        result = stage2_haiku.get_pending_requests()
        assert result == [], "f10_passed=False のリクエストは除外されるべき"

    def test_f10_passed_true_included(self, tmp_path, monkeypatch):
        """f10_passed=True のリクエストが処理対象に含まれること。
        根拠: confidence_score >= min_confidence_score のレース。
              2月分析で hit_prob>=0.9の的中率32.2% → 処理対象。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_haiku, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_haiku, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=True, conf_score=3)

        result = stage2_haiku.get_pending_requests()
        assert len(result) == 1, "f10_passed=True のリクエストは処理対象になるべき"
        task_id, req, _ = result[0]
        assert task_id == "pred_keirin_川崎_9"

    def test_f10_passed_missing_included(self, tmp_path, monkeypatch):
        """f10_passed キーが存在しない（旧フォーマット）場合は後方互換で処理対象に含まれること。
        根拠: Stage1改修前のYAMLはf10_passedキーを持たない。
              req.get("f10_passed", True) → True（デフォルト）で処理対象。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_haiku, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_haiku, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=None)  # キー省略

        result = stage2_haiku.get_pending_requests()
        assert len(result) == 1, "f10_passed キーなし（旧フォーマット）は後方互換で処理対象になるべき"

    def test_mixed_f10_passed(self, tmp_path, monkeypatch):
        """f10_passed=True/False が混在する場合、True のみが返ること。
        手計算: 3件投入（True/False/キーなし）→ True1件 + キーなし1件 = 2件返却。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_haiku, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_haiku, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=True, conf_score=3)
        _write_req(req_dir, "pred_keirin_川崎_10", f10_passed=False, conf_score=1)
        _write_req(req_dir, "pred_keirin_川崎_11", f10_passed=None)  # キーなし

        result = stage2_haiku.get_pending_requests()
        assert len(result) == 2, "True1件 + キーなし1件 = 2件"
        task_ids = [r[0] for r in result]
        assert "pred_keirin_川崎_9" in task_ids
        assert "pred_keirin_川崎_11" in task_ids
        assert "pred_keirin_川崎_10" not in task_ids, "f10_passed=False は除外"

    def test_already_processed_skipped(self, tmp_path, monkeypatch):
        """results/ に対応ファイルがある場合はスキップされること（既存動作の回帰テスト）。"""
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_haiku, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_haiku, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=True)
        # 既に処理済みの結果ファイルを作成
        (res_dir / "pred_keirin_川崎_9.yaml").write_text("status: done", encoding="utf-8")

        result = stage2_haiku.get_pending_requests()
        assert result == [], "処理済みリクエストは返却されないべき"

    def test_req_dir_not_exists(self, tmp_path, monkeypatch):
        """REQ_DIR が存在しない場合は空リストを返すこと（既存動作の回帰テスト）。"""
        req_dir = tmp_path / "nonexistent"
        monkeypatch.setattr(stage2_haiku, "REQ_DIR", req_dir)

        result = stage2_haiku.get_pending_requests()
        assert result == []
