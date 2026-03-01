"""
tests/test_stage2_process_f10.py
=================================
stage2_process.py の F10フィルター動作テスト（cmd_149k_sub4）。

テスト期待値の根拠（CHECK-9）:
  - write_result() は f10_passed=False のリクエストに対して処理を拒否すること
  - list_requests() は f10_passed=False のリクエストを「未処理(処理可能)」カウントに含めないこと
  - f10_passed=True → 正常に処理対象

  根拠: stage2_haiku.py の get_pending_requests() と同一の f10_passed 扱い。
        手動モード(stage2_process.py)でもF10除外レースがbetされないようにする。
"""

import sys
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest
import yaml

# scripts/ をパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import stage2_process


# ─── テスト用ヘルパー ────────────────────────────────────────────

def _write_req(req_dir: Path, task_id: str, f10_passed, conf_score: int = 2) -> Path:
    """テスト用リクエストYAMLを書き出す。f10_passed=None の場合はキーを省略（後方互換テスト用）。"""
    req: dict = {
        "task_id": task_id,
        "status": "pending",
        "date": "20260301",
        "venue": "川崎",
        "race_no": 9,
        "grade": "S1",
        "stage": "特選",
        "sport": "keirin",
        "filter_type": "A",
        "filter_passed": True,
        "filter_reasons": [],
        "confidence_score": conf_score,
        "system_prompt": "system",
        "user_prompt": "user",
    }
    if f10_passed is not None:
        req["f10_passed"] = f10_passed
    req_file = req_dir / f"{task_id}.yaml"
    req_file.write_text(yaml.dump(req, allow_unicode=True), encoding="utf-8")
    return req_file


# ─── write_result() F10フィルターテスト ────────────────────────

class TestWriteResultF10Filter:
    """write_result() の F10フィルター動作テスト。"""

    def test_f10_passed_false_rejected(self, tmp_path, monkeypatch):
        """f10_passed=False のリクエストに write_result() を呼ぶと sys.exit(1) になること。
        根拠: stage2_haiku.py の get_pending_requests() と同一の除外ルール。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_process, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_process, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=False, conf_score=1)

        with pytest.raises(SystemExit) as exc_info:
            stage2_process.write_result("pred_keirin_川崎_9")
        assert exc_info.value.code == 1, "f10_passed=False は sys.exit(1) で終了すべき"

    def test_f10_passed_false_no_result_written(self, tmp_path, monkeypatch):
        """f10_passed=False の場合、結果YAMLが書き出されないこと。
        根拠: F10除外レースの bet 生成を防ぐ。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_process, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_process, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=False, conf_score=1)

        with pytest.raises(SystemExit):
            stage2_process.write_result("pred_keirin_川崎_9")

        res_file = res_dir / "pred_keirin_川崎_9.yaml"
        assert not res_file.exists(), "f10_passed=False では結果YAMLが作られてはならない"

    def test_f10_passed_missing_not_rejected(self, tmp_path, monkeypatch):
        """f10_passed キーが存在しない（旧フォーマット）場合は拒否されないこと。
        根拠: 旧フォーマットYAMLは後方互換で処理対象（req.get("f10_passed", True) → True）。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_process, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_process, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=None)  # キー省略

        # write_result は stdin を読もうとするが、sys.exit(1) にはならないこと
        # stdin をモックしてテキストを渡す
        prediction_text = "本命: 3番（古性優作）\n軸相手: 1番、5番\n買い目: 3連複 3-15 ながし\n根拠: 強い"
        with mock.patch("sys.stdin", StringIO(prediction_text)):
            # sys.exit(1) が発生しないことを確認（正常処理）
            stage2_process.write_result("pred_keirin_川崎_9")

        res_file = res_dir / "pred_keirin_川崎_9.yaml"
        assert res_file.exists(), "f10_passed キーなし（旧フォーマット）は正常に結果YAMLが書き出されるべき"


# ─── list_requests() F10フィルターテスト ───────────────────────

class TestListRequestsF10Filter:
    """list_requests() の F10フィルター表示テスト。"""

    def test_f10_passed_false_not_counted_as_pending(self, tmp_path, monkeypatch, capsys):
        """f10_passed=False のリクエストが「未処理(処理可能)」カウントに含まれないこと。
        根拠: F10除外レースは処理対象外。手動モードでも件数に含めない。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_process, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_process, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=False, conf_score=1)

        stage2_process.list_requests()
        out = capsys.readouterr().out

        # 「未処理(処理可能): 0件」になること
        assert "未処理(処理可能): 0件" in out, "F10除外レースはpending件数に含まれない"

    def test_f10_passed_true_counted_as_pending(self, tmp_path, monkeypatch, capsys):
        """f10_passed=True のリクエストが「未処理(処理可能)」カウントに含まれること。
        根拠: F10通過レースのみが処理対象。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_process, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_process, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=True, conf_score=3)

        stage2_process.list_requests()
        out = capsys.readouterr().out

        assert "未処理(処理可能): 1件" in out, "F10通過レースはpending件数に含まれる"

    def test_f10_label_shown_in_output(self, tmp_path, monkeypatch, capsys):
        """f10_passed=False のリクエストに [F10除外] ラベルが表示されること。
        根拠: 人間オペレーターに除外理由を明示する。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_process, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_process, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=False, conf_score=1)

        stage2_process.list_requests()
        out = capsys.readouterr().out

        assert "F10除外" in out, "f10_passed=False には [F10除外] ラベルが表示される"

    def test_mixed_f10_pending_count(self, tmp_path, monkeypatch, capsys):
        """True/False 混在時、Trueのみが未処理件数にカウントされること。
        手計算: True=2件, False=1件 → 未処理(処理可能)=2件。
        """
        req_dir = tmp_path / "requests"
        req_dir.mkdir()
        res_dir = tmp_path / "results"
        res_dir.mkdir()
        monkeypatch.setattr(stage2_process, "REQ_DIR", req_dir)
        monkeypatch.setattr(stage2_process, "RES_DIR", res_dir)

        _write_req(req_dir, "pred_keirin_川崎_9", f10_passed=True, conf_score=3)
        _write_req(req_dir, "pred_keirin_川崎_10", f10_passed=False, conf_score=1)
        _write_req(req_dir, "pred_keirin_川崎_11", f10_passed=True, conf_score=2)

        stage2_process.list_requests()
        out = capsys.readouterr().out

        assert "未処理(処理可能): 2件" in out
        assert "全体: 3件" in out
