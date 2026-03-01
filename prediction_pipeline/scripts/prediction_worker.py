#!/usr/bin/env python3
"""
競輪予測ワーカー — Claude Code足軽用
=====================================

queue/predictions/requests/ のYAMLリクエストを監視し、
Claude Code（自分自身）で予測テキストを生成して
queue/predictions/results/ に結果を書き込む。

使い方（足軽がtmuxペイン内で実行）:
    python scripts/prediction_worker.py --once       # 1件処理して終了
    python scripts/prediction_worker.py --watch      # 常駐モード（新リクエストを待ち続ける）
    python scripts/prediction_worker.py --list       # 未処理リクエストを一覧表示
"""

import argparse
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQ_DIR = ROOT / "queue" / "predictions" / "requests"
RES_DIR = ROOT / "queue" / "predictions" / "results"


def list_pending() -> list[Path]:
    """未処理リクエストを返す。"""
    pending = []
    for f in sorted(REQ_DIR.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if data and data.get("status") == "pending":
            res_file = RES_DIR / f.name
            if not res_file.exists():
                pending.append(f)
    return pending


def show_request(req_path: Path) -> dict:
    """リクエストの内容を表示用に読む。"""
    data = yaml.safe_load(req_path.read_text(encoding="utf-8"))
    return data


def write_result(task_id: str, prediction_text: str) -> Path:
    """予測結果をYAMLに書き出す。"""
    RES_DIR.mkdir(parents=True, exist_ok=True)
    res_file = RES_DIR / f"{task_id}.yaml"
    result = {
        "task_id": task_id,
        "status": "done",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "prediction_text": prediction_text,
        "model_used": "claude-code-agent",
    }
    res_file.write_text(
        yaml.dump(result, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return res_file


def process_request(req_path: Path) -> None:
    """1件のリクエストを処理する。

    Claude Codeエージェント（足軽）は、このスクリプトを直接実行するのではなく、
    リクエストYAMLの system_prompt + user_prompt を読んで
    自分自身の推論能力で予測テキストを生成し、
    write_result() 相当の結果YAMLを手動で書き出す。

    このスクリプトはあくまで「インタラクティブモード」のヘルパー。
    """
    data = show_request(req_path)
    task_id = data["task_id"]
    venue = data.get("venue", "?")
    race_no = data.get("race_no", "?")
    filter_type = data.get("filter_type", "A")

    print(f"\n{'='*60}")
    print(f"タスク: {task_id}")
    print(f"会場: {venue} {race_no}R  フィルター: {filter_type}")
    print(f"{'='*60}")
    print("\n--- system_prompt ---")
    print(data.get("system_prompt", "(なし)")[:500])
    print("\n--- user_prompt ---")
    print(data.get("user_prompt", "(なし)"))
    print(f"\n{'='*60}")
    print("上記のプロンプトをもとに予測テキストを生成してください。")
    print("フォーマット:")
    print("  軸: N番")
    print("  相手: N番、N番、N番")
    print("  買い目: 3連複ながし N-NNN")
    print("  根拠: [200字以内]")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="競輪予測ワーカー（Claude Code足軽用）")
    parser.add_argument("--once", action="store_true", help="未処理リクエストを1件表示して終了")
    parser.add_argument("--watch", action="store_true", help="常駐モード（新リクエストを待ち続ける）")
    parser.add_argument("--list", action="store_true", help="未処理リクエストを一覧表示")
    args = parser.parse_args()

    REQ_DIR.mkdir(parents=True, exist_ok=True)
    RES_DIR.mkdir(parents=True, exist_ok=True)

    if args.list:
        pending = list_pending()
        if not pending:
            print("未処理リクエストはありません。")
            return
        for p in pending:
            data = show_request(p)
            print(f"  {data['task_id']}  {data.get('venue','?')} {data.get('race_no','?')}R  [{data.get('filter_type','?')}]")
        print(f"\n合計: {len(pending)}件")
        return

    if args.once:
        pending = list_pending()
        if not pending:
            print("未処理リクエストはありません。")
            return
        process_request(pending[0])
        return

    if args.watch:
        print(f"常駐モード開始。{REQ_DIR} を監視中...")
        while True:
            pending = list_pending()
            for p in pending:
                process_request(p)
            time.sleep(5)

    parser.print_help()


if __name__ == "__main__":
    main()
