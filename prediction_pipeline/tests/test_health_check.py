"""
tests/test_health_check.py
===========================
health_check.py の単体テスト

テスト根拠（CHECK-9）:
  check_output_freshness():
    - output_dir 非存在 → ok=False（ディレクトリ存在チェックは必須）
    - JSONなし → ok=False（出力ファイル不在は異常）
    - 最新ファイルが threshold_hours 以内 → ok=True
    - 最新ファイルが threshold_hours 超過 → ok=False
    - sport フィルタ：keirin_*.json のみ対象（kyotei はカウントしない）
    - sport="all" → *.json を対象
    - hours_since_update: 実際の経過時間と概一致することを確認
  check_log_freshness():
    - ログなし → ok=True（スキップ扱い）
    - 新鮮なログ → ok=True
    - 古いログ → ok=False

（cmd_150k_sub4）
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from health_check import check_output_freshness, check_log_freshness


# ─── ヘルパー ──────────────────────────────────────────────────────────────


def _write_json(path: Path, content: str = "{}") -> Path:
    """JSONファイルを tmp ディレクトリに書き込むヘルパー。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ─── check_output_freshness テスト ────────────────────────────────────────


class TestCheckOutputFreshness:
    """check_output_freshness() の動作テスト"""

    def test_dir_not_exist_returns_not_ok(self, tmp_path):
        """output_dir が存在しない場合 ok=False を返す。"""
        result = check_output_freshness(tmp_path / "nonexistent")
        assert result["ok"] is False

    def test_dir_not_exist_hours_is_inf(self, tmp_path):
        """output_dir が存在しない場合 hours_since_update=inf を返す。"""
        result = check_output_freshness(tmp_path / "nonexistent")
        assert result["hours_since_update"] == float("inf")

    def test_no_json_files_returns_not_ok(self, tmp_path):
        """JSONファイルが1件もない場合 ok=False を返す。"""
        date_dir = tmp_path / "20260301"
        date_dir.mkdir()
        result = check_output_freshness(tmp_path)
        assert result["ok"] is False

    def test_fresh_file_returns_ok(self, tmp_path):
        """最新ファイルが threshold_hours 以内なら ok=True を返す。"""
        _write_json(tmp_path / "20260301" / "keirin_岐阜_1.json")
        result = check_output_freshness(tmp_path, threshold_hours=24, sport="keirin")
        assert result["ok"] is True

    def test_stale_file_returns_not_ok(self, tmp_path):
        """最新ファイルが threshold_hours を超えていれば ok=False を返す。"""
        f = _write_json(tmp_path / "20260301" / "keirin_岐阜_1.json")
        # 50時間前に更新されたように偽装
        old_time = time.time() - 50 * 3600
        import os
        os.utime(f, (old_time, old_time))
        result = check_output_freshness(tmp_path, threshold_hours=24, sport="keirin")
        assert result["ok"] is False

    def test_sport_filter_keirin_excludes_kyotei(self, tmp_path):
        """sport=keirin の場合、kyotei_*.json は対象外になる。"""
        _write_json(tmp_path / "20260301" / "kyotei_若松_1.json")
        result = check_output_freshness(tmp_path, threshold_hours=24, sport="keirin")
        # keirin ファイルが存在しないので ok=False
        assert result["ok"] is False

    def test_sport_all_matches_any_json(self, tmp_path):
        """sport=all の場合、任意の *.json が対象になる。"""
        _write_json(tmp_path / "20260301" / "kyotei_若松_1.json")
        result = check_output_freshness(tmp_path, threshold_hours=24, sport="all")
        assert result["ok"] is True

    def test_returns_correct_keys(self, tmp_path):
        """戻り値に必要なキーが含まれること。"""
        _write_json(tmp_path / "20260301" / "keirin_岐阜_1.json")
        result = check_output_freshness(tmp_path, sport="keirin")
        for key in ("ok", "latest_file", "latest_mtime", "hours_since_update", "message"):
            assert key in result, f"キー '{key}' が戻り値に見つからない"

    def test_hours_since_update_is_small_for_fresh_file(self, tmp_path):
        """直前に書いたファイルなら hours_since_update < 1 であること。"""
        _write_json(tmp_path / "20260301" / "keirin_岐阜_1.json")
        result = check_output_freshness(tmp_path, sport="keirin")
        assert result["hours_since_update"] < 1.0

    def test_latest_file_is_most_recent(self, tmp_path):
        """複数ファイルがある場合、最新のものが latest_file に選ばれること。"""
        f_old = _write_json(tmp_path / "20260228" / "keirin_岐阜_1.json")
        f_new = _write_json(tmp_path / "20260301" / "keirin_岐阜_1.json")
        # f_old を 30分前に設定
        import os
        os.utime(f_old, (time.time() - 1800, time.time() - 1800))
        result = check_output_freshness(tmp_path, sport="keirin")
        assert Path(result["latest_file"]).name == f_new.name

    def test_message_contains_filename(self, tmp_path):
        """message にファイル名が含まれること。"""
        _write_json(tmp_path / "20260301" / "keirin_岐阜_1.json")
        result = check_output_freshness(tmp_path, sport="keirin")
        assert "keirin_岐阜_1.json" in result["message"]


# ─── check_log_freshness テスト ───────────────────────────────────────────


class TestCheckLogFreshness:
    """check_log_freshness() の動作テスト"""

    def test_no_log_file_returns_ok(self, tmp_path):
        """pipeline.log が存在しない場合 ok=True（スキップ扱い）を返す。"""
        result = check_log_freshness(tmp_path / "logs")
        assert result["ok"] is True

    def test_fresh_log_returns_ok(self, tmp_path):
        """直近更新されたログなら ok=True を返す。"""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "pipeline.log").write_text("latest entry\n", encoding="utf-8")
        result = check_log_freshness(log_dir, threshold_hours=28)
        assert result["ok"] is True

    def test_stale_log_returns_not_ok(self, tmp_path):
        """30時間以上更新されていないログは ok=False を返す。"""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "pipeline.log"
        log_file.write_text("old entry\n", encoding="utf-8")
        import os
        os.utime(log_file, (time.time() - 31 * 3600, time.time() - 31 * 3600))
        result = check_log_freshness(log_dir, threshold_hours=28)
        assert result["ok"] is False

    def test_no_log_message_says_skip(self, tmp_path):
        """pipeline.log がない場合のメッセージに 'スキップ' が含まれること。"""
        result = check_log_freshness(tmp_path / "logs")
        assert "スキップ" in result["message"]
