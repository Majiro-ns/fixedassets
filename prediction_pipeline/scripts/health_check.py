"""
パイプラインヘルスチェックスクリプト
======================================

output/ 配下の最終出力日を確認し、1日以上更新がなければDiscordにアラートを送る。
cronで毎日夜（21:00 JST）に実行することを想定。

使用例:
    python scripts/health_check.py
    python scripts/health_check.py --threshold-hours 24
    python scripts/health_check.py --sport keirin --dry-run
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# .env から環境変数をロード
ENV_FILE = ROOT / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value and key not in os.environ:
                    os.environ[key] = value


def check_output_freshness(
    output_dir: Path,
    threshold_hours: int = 24,
    sport: str = "keirin",
) -> dict:
    """
    output/ 配下の最新ファイルを確認し、鮮度を返す。

    Args:
        output_dir: output ディレクトリパス
        threshold_hours: アラート閾値（時間）
        sport: 対象スポーツ（keirin / kyotei / all）

    Returns:
        {
            "ok": bool,
            "latest_file": str,
            "latest_mtime": datetime,
            "hours_since_update": float,
            "message": str,
        }
    """
    if not output_dir.exists():
        return {
            "ok": False,
            "latest_file": "",
            "latest_mtime": None,
            "hours_since_update": float("inf"),
            "message": f"output/ ディレクトリが存在しません: {output_dir}",
        }

    # 最新のJSONファイルを探す（sport別フィルタ対応）
    pattern = f"{sport}_*.json" if sport != "all" else "*.json"
    json_files = []
    for date_dir in sorted(output_dir.iterdir()):
        if date_dir.is_dir():
            json_files.extend(date_dir.glob(pattern))

    if not json_files:
        return {
            "ok": False,
            "latest_file": "",
            "latest_mtime": None,
            "hours_since_update": float("inf"),
            "message": f"output/ に {sport} の出力ファイルが見つかりません",
        }

    # 最新ファイルの更新時刻を取得
    latest_file = max(json_files, key=lambda p: p.stat().st_mtime)
    mtime = datetime.fromtimestamp(latest_file.stat().st_mtime)
    hours_elapsed = (datetime.now() - mtime).total_seconds() / 3600

    if hours_elapsed > threshold_hours:
        message = (
            f"⚠ {sport} 最終出力から {hours_elapsed:.1f}時間 経過。"
            f" 最終ファイル: {latest_file.name} ({mtime.strftime('%Y-%m-%d %H:%M')})"
        )
        ok = False
    else:
        message = (
            f"✅ {sport} 出力は新鮮です。"
            f" 最終ファイル: {latest_file.name} ({mtime.strftime('%Y-%m-%d %H:%M')})"
            f" ({hours_elapsed:.1f}時間前)"
        )
        ok = True

    return {
        "ok": ok,
        "latest_file": str(latest_file),
        "latest_mtime": mtime,
        "hours_since_update": hours_elapsed,
        "message": message,
    }


def check_log_freshness(log_dir: Path, threshold_hours: int = 28) -> dict:
    """
    data/logs/pipeline.log の最終エントリ時刻を確認する。

    Args:
        log_dir: logs ディレクトリパス
        threshold_hours: アラート閾値（時間）

    Returns:
        鮮度チェック結果辞書
    """
    log_file = log_dir / "pipeline.log"
    if not log_file.exists():
        return {"ok": True, "message": "pipeline.log なし（スキップ）"}

    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
    hours_elapsed = (datetime.now() - mtime).total_seconds() / 3600

    if hours_elapsed > threshold_hours:
        return {
            "ok": False,
            "message": f"⚠ pipeline.log が {hours_elapsed:.1f}時間 更新されていません",
        }
    return {
        "ok": True,
        "message": f"✅ pipeline.log は {hours_elapsed:.1f}時間前 に更新済み",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="パイプラインヘルスチェック")
    parser.add_argument("--threshold-hours", type=int, default=24, help="アラート閾値（時間）")
    parser.add_argument(
        "--sport", default="keirin", choices=["keirin", "kyotei", "all"],
        help="チェック対象スポーツ"
    )
    parser.add_argument("--dry-run", action="store_true", help="Discord通知を送らずチェックのみ")
    args = parser.parse_args()

    output_dir = ROOT / "output"
    log_dir = ROOT / "data" / "logs"

    # チェック実行
    output_result = check_output_freshness(output_dir, args.threshold_hours, args.sport)
    log_result = check_log_freshness(log_dir, args.threshold_hours + 4)

    # ROI集計更新 + アラートチェック（月別ROI監視 cmd_089）
    roi_result = {"ok": True, "message": "ROI: スキップ"}
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "roi_tracker", ROOT / "scripts" / "roi_tracker.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.update_current_month()
        roi_ok, roi_msg = mod.check_roi_alert()
        roi_result = {"ok": roi_ok, "message": roi_msg}
    except Exception as e:
        roi_result = {"ok": True, "message": f"ROI集計スキップ: {e}"}

    print(output_result["message"])
    print(log_result["message"])
    print(roi_result["message"])

    # 問題があればDiscord通知
    has_alert = not output_result["ok"] or not log_result["ok"] or not roi_result["ok"]
    if has_alert and not args.dry_run:
        try:
            from scripts.discord_notify import send_discord_notification
        except ImportError:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "discord_notify",
                ROOT / "scripts" / "discord_notify.py"
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            send_discord_notification = mod.send_discord_notification

        alert_msg = "\n".join([
            output_result["message"],
            log_result["message"],
            roi_result["message"],
        ])
        last_success = ""
        if output_result.get("latest_mtime"):
            last_success = output_result["latest_mtime"].strftime("%Y-%m-%d %H:%M")

        send_discord_notification(
            notify_type="health_alert",
            message=alert_msg,
            script_name="health_check.py",
            last_success=last_success,
        )
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
