"""
tests/test_cron_watchdog.py
===========================
cron_watchdog.sh のテスト（モック環境）

テスト戦略:
  1. bash -n でシンタックスチェック
  2. モック cron.log + WATCHDOG_TEST_ROOT でスクリプトを実行
  3. cron_watchdog.log の内容と終了コードを検証

環境変数:
  WATCHDOG_TEST_ROOT    : モックのプロジェクトルート
  WATCHDOG_NOW_OVERRIDE : 現在時刻を固定（"2026-03-01 12:00:00"）

(cmd_148k_sub4)
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "cron_watchdog.sh"
# 全テストで「締め切り後」となる固定時刻（stage1=07:00+3h=10:00 を超えている）
NOW_AFTERNOON = "2026-03-01 12:00:00"
TODAY_STR = "2026-03-01"


# ── ヘルパー関数 ──────────────────────────────────────────────────────────

def make_log_lines(entries: list[dict]) -> str:
    """モック cron.log のテキストを生成する。"""
    lines = []
    for e in entries:
        ts = e.get("ts", f"{TODAY_STR} 07:00:01")
        cmd = e["cmd"]
        exit_code = e.get("exit", 0)
        lines.append(f"{ts} [START] command={cmd} date=20260301")
        lines.append(f"{ts} [END] command={cmd} exit={exit_code}")
    return "\n".join(lines) + "\n"


def run_watchdog(
    cron_log_content: str,
    now_override: str = NOW_AFTERNOON,
    extra_env: dict | None = None,
) -> tuple[int, str, str]:
    """
    cron_watchdog.sh をモック環境で実行し (returncode, stdout+stderr, watchdog_log) を返す。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # ディレクトリ構造
        data_logs = Path(tmpdir) / "data" / "logs"
        scripts_dir = Path(tmpdir) / "scripts"
        data_logs.mkdir(parents=True)
        scripts_dir.mkdir()

        # cron.log を配置
        (data_logs / "cron.log").write_text(cron_log_content)

        # 環境変数
        env = os.environ.copy()
        env["WATCHDOG_TEST_ROOT"] = tmpdir
        env["WATCHDOG_NOW_OVERRIDE"] = now_override
        if extra_env:
            env.update(extra_env)

        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--dry-run"],
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

        watchdog_log_path = data_logs / "cron_watchdog.log"
        watchdog_log = watchdog_log_path.read_text() if watchdog_log_path.exists() else ""

        # --dry-run なので watchdog.log は書かれないが、stdout で確認できる
        return result.returncode, result.stdout + result.stderr, watchdog_log


# ── テストクラス ──────────────────────────────────────────────────────────

class TestCronWatchdogSyntax:
    """bash -n によるシンタックスチェック"""

    def test_script_exists(self):
        assert SCRIPT_PATH.exists(), f"watchdog.sh が見つかりません: {SCRIPT_PATH}"

    def test_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"シンタックスエラー:\n{result.stderr}"

    def test_script_is_readable(self):
        content = SCRIPT_PATH.read_text()
        assert "cron_watchdog" in content
        assert "WATCHDOG_TEST_ROOT" in content
        assert "WATCHDOG_NOW_OVERRIDE" in content


class TestCronWatchdogAllOk:
    """全ジョブ正常実行のケース"""

    def test_all_jobs_pass(self):
        """stage1/daily_refit/stage3 が全て正常実行済み → returncode=0"""
        log = make_log_lines([
            {"ts": f"{TODAY_STR} 07:01:00", "cmd": "stage1_keirin",       "exit": 0},
            {"ts": f"{TODAY_STR} 07:32:00", "cmd": "daily_refit_keirin",  "exit": 0},
            {"ts": f"{TODAY_STR} 18:01:00", "cmd": "stage3_keirin",       "exit": 0},
        ])
        rc, out, _ = run_watchdog(log)
        assert rc == 0, f"returncode={rc}\nout={out}"
        assert "ALERT" not in out
        assert "OK" in out or "SKIP" in out

    def test_all_jobs_ok_stdout_contains_summary(self):
        """SUMMARY に 全ジョブ正常 が表示される"""
        log = make_log_lines([
            {"ts": f"{TODAY_STR} 07:01:00", "cmd": "stage1_keirin",       "exit": 0},
            {"ts": f"{TODAY_STR} 07:32:00", "cmd": "daily_refit_keirin",  "exit": 0},
            {"ts": f"{TODAY_STR} 18:01:00", "cmd": "stage3_keirin",       "exit": 0},
        ])
        rc, out, _ = run_watchdog(log)
        assert "SUMMARY" in out
        assert "ALERT" not in out


class TestCronWatchdogMissingJobs:
    """ジョブ未実行のケース"""

    def test_daily_refit_missing(self):
        """daily_refit_keirin が未実行 → returncode > 0, ALERT が出る"""
        log = make_log_lines([
            {"ts": f"{TODAY_STR} 07:01:00", "cmd": "stage1_keirin",  "exit": 0},
            {"ts": f"{TODAY_STR} 18:01:00", "cmd": "stage3_keirin",  "exit": 0},
        ])
        rc, out, _ = run_watchdog(log)
        assert rc > 0, f"ALERT のはずが returncode={rc}"
        assert "ALERT" in out
        assert "daily_refit_keirin" in out

    def test_stage1_missing(self):
        """stage1_keirin が未実行 → ALERT"""
        log = make_log_lines([
            {"ts": f"{TODAY_STR} 18:01:00", "cmd": "stage3_keirin", "exit": 0},
        ])
        rc, out, _ = run_watchdog(log)
        assert rc > 0
        assert "stage1_keirin" in out

    def test_all_jobs_missing(self):
        """全ジョブ未実行 → returncode >= 2 (stage3は12:00時点でdeadline未到達のためSKIP)"""
        log = "# empty log\n"
        rc, out, _ = run_watchdog(log)
        # 12:00時点: stage1(deadline10:00)・daily_refit(deadline11:30)はALERT
        # stage3(deadline21:00)はSKIPのため rc=2
        assert rc >= 2, f"2件以上のALERTのはずが returncode={rc}"

    def test_previous_day_run_not_counted(self):
        """昨日の実行は今日分としてカウントされない"""
        yesterday = "2026-02-28"
        log = make_log_lines([
            {"ts": f"{yesterday} 07:01:00", "cmd": "stage1_keirin",      "exit": 0},
            {"ts": f"{yesterday} 07:32:00", "cmd": "daily_refit_keirin", "exit": 0},
            {"ts": f"{yesterday} 18:01:00", "cmd": "stage3_keirin",      "exit": 0},
        ])
        rc, out, _ = run_watchdog(log)
        assert rc > 0, f"昨日分は今日としてカウントされてはならない (rc={rc})"


class TestCronWatchdogErrorExit:
    """ジョブがエラー終了したケース"""

    def test_job_error_exit_is_alerted(self):
        """exit=1 のジョブは WARN/ALERT で通知される"""
        log = make_log_lines([
            {"ts": f"{TODAY_STR} 07:01:00", "cmd": "stage1_keirin",       "exit": 1},
            {"ts": f"{TODAY_STR} 07:32:00", "cmd": "daily_refit_keirin",  "exit": 0},
            {"ts": f"{TODAY_STR} 18:01:00", "cmd": "stage3_keirin",       "exit": 0},
        ])
        rc, out, _ = run_watchdog(log)
        assert rc > 0
        assert "stage1_keirin" in out


class TestCronWatchdogDeadlineNotReached:
    """締め切り前（チェック不要）のケース"""

    def test_stage3_not_checked_before_deadline(self):
        """09:00 時点では stage3 (18:00+3h=21:00) はまだチェック不要"""
        log = make_log_lines([
            {"ts": f"{TODAY_STR} 07:01:00", "cmd": "stage1_keirin",       "exit": 0},
            {"ts": f"{TODAY_STR} 07:32:00", "cmd": "daily_refit_keirin",  "exit": 0},
            # stage3 はまだ実行時刻でない
        ])
        rc, out, _ = run_watchdog(log, now_override=f"{TODAY_STR} 09:00:00")
        # stage3 は SKIP されるべき
        assert "stage3_keirin" not in out or "SKIP" in out
        # stage1/daily_refit は OK のはず
        assert rc == 0, f"returncode={rc}\nout={out}"


class TestCronWatchdogMissingLogFile:
    """cron.log が存在しないケース"""

    def test_no_cron_log_triggers_alert(self):
        """cron.log が存在しない場合は ALERT"""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "data" / "logs").mkdir(parents=True)
            (Path(tmpdir) / "scripts").mkdir()
            # cron.log を作らない

            env = os.environ.copy()
            env["WATCHDOG_TEST_ROOT"] = tmpdir
            env["WATCHDOG_NOW_OVERRIDE"] = NOW_AFTERNOON

            result = subprocess.run(
                ["bash", str(SCRIPT_PATH), "--dry-run"],
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )
            assert result.returncode > 0
            assert "ALERT" in result.stdout + result.stderr
