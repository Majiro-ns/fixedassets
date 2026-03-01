"""
Discord Webhook 通知スクリプト
================================

パイプライン失敗時やヘルスチェックアラートをDiscordに送信する。
Webhook URLは .env の DISCORD_WEBHOOK_URL から読み込む。

使用例:
    python scripts/discord_notify.py --type error --message "エラーメッセージ" --script daily_run.py
    python scripts/discord_notify.py --type health_alert --message "1日以上更新なし"
    python scripts/discord_notify.py --type success --message "パイプライン正常完了"
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# .env から環境変数をロード
ROOT = Path(__file__).resolve().parent.parent
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

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# 通知タイプ別の色コード（Discord embed color）
COLORS = {
    "error": 0xFF0000,       # 赤
    "health_alert": 0xFF8C00, # オレンジ
    "success": 0x00AA00,     # 緑
    "info": 0x0099FF,        # 青
}

# 通知タイプ別のアイコン
ICONS = {
    "error": "🚨",
    "health_alert": "⚠️",
    "success": "✅",
    "info": "ℹ️",
}


def send_discord_notification(
    notify_type: str,
    message: str,
    script_name: str = "",
    last_success: str = "",
) -> bool:
    """
    Discord Webhook に通知を送信する。

    Args:
        notify_type: 通知タイプ（error / health_alert / success / info）
        message: 通知メッセージ本文
        script_name: 失敗したスクリプト名（errorの場合）
        last_success: 最終成功日時（health_alertの場合）

    Returns:
        送信成功なら True、失敗なら False
    """
    if not DISCORD_WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL が未設定。.env を確認してください。", file=sys.stderr)
        return False

    color = COLORS.get(notify_type, 0x808080)
    icon = ICONS.get(notify_type, "📢")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S JST")

    # フィールド構築
    fields = [
        {"name": "メッセージ", "value": message, "inline": False},
        {"name": "時刻", "value": timestamp, "inline": True},
    ]
    if script_name:
        fields.append({"name": "スクリプト", "value": script_name, "inline": True})
    if last_success:
        fields.append({"name": "最終成功", "value": last_success, "inline": True})

    payload = {
        "embeds": [
            {
                "title": f"{icon} 競輪予測パイプライン {notify_type.upper()}",
                "color": color,
                "fields": fields,
                "footer": {"text": "prediction_pipeline / keirin_prediction"},
            }
        ]
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                print(f"Discord通知送信完了: {notify_type}")
                return True
            else:
                print(f"Discord通知エラー: status={resp.status}", file=sys.stderr)
                return False
    except urllib.error.HTTPError as e:
        # 403: webhook URLが無効または権限不足。通知失敗はパイプライン継続を妨げない
        print(f"Discord HTTPエラー: {e.code} {e.reason} (webhook URL/権限を確認してください)", file=sys.stderr)
        return False
    except urllib.error.URLError as e:
        print(f"Discord URLエラー: {e.reason}", file=sys.stderr)
        return False
    except Exception as e:
        # 予期しない例外（JSON化失敗、ネットワーク異常等）もキャッチして非致命的扱いに
        print(f"Discord通知 予期しないエラー: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Discord Webhook 通知スクリプト")
    parser.add_argument(
        "--type",
        choices=["error", "health_alert", "success", "info"],
        default="info",
        help="通知タイプ",
    )
    parser.add_argument("--message", required=True, help="通知メッセージ")
    parser.add_argument("--script", default="", help="失敗したスクリプト名")
    parser.add_argument("--last-success", default="", help="最終成功日時")
    args = parser.parse_args()

    success = send_discord_notification(
        notify_type=args.type,
        message=args.message,
        script_name=args.script,
        last_success=args.last_success,
    )
    # 通知失敗はパイプライン継続を妨げない（非致命的）。
    # cron_pipeline.sh では `|| true` で保護しているが、明示的に 0 で終了する。
    if not success:
        print("Discord通知失敗: パイプラインは継続します。", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
