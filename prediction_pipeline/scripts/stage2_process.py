#!/usr/bin/env python3
"""
Stage 2 ヘルパースクリプト — Claude Code 足軽による予測テキスト生成
======================================================================

【役割】
このスクリプトは queue/predictions/requests/ にある pending な
リクエストYAMLを一覧表示し、足軽（Claude Code エージェント）が
予測テキストを生成して結果YAMLを書き出す作業をサポートする。

【使い方】

Step A: リクエスト一覧を確認する
    python scripts/stage2_process.py --list

Step B: 特定のリクエストを表示する（足軽が読んで予測を考える）
    python scripts/stage2_process.py --show pred_keirin_大垣_12

Step C: 予測テキストをYAMLに書き出す（対話モード）
    python scripts/stage2_process.py --write pred_keirin_大垣_12

Step D: 予測テキストをファイルから書き出す
    python scripts/stage2_process.py --write pred_keirin_大垣_12 --text-file /tmp/pred.txt

【足軽の作業手順（Stage 2）】

1. --list でリクエスト一覧を確認
2. --show {task_id} でプロンプトを確認し、競輪データを分析
3. 分析結果として以下の形式で予測テキストを作成:
   本命: X番（選手名）
   軸相手: Y番、Z番
   買い目: 3連単 X-YZ ながし（N点）
   根拠: [200字以内で簡潔に記述。ライン構成と脚質を明示すること]
4. --write で結果YAMLを生成
5. Stage 3 で bet 計算に繋げる
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _parse_axis_partners(prediction_text: str) -> tuple[int | None, list[int]]:
    """予測テキストから軸番号と相手番号リストを抽出する（dedup済み）。

    Args:
        prediction_text: 「本命: X番 / 軸相手: Y番、Z番 / 買い目: ...」形式のテキスト

    Returns:
        (axis, partners): axis は軸番号（None の場合は解析失敗）、
                          partners は相手番号リスト（重複・軸番号除去済み、最大4名）
    """
    axis: int | None = None
    partners: list[int] = []

    axis_match = re.search(r"(?:軸|本命)[：:]\s*(\d+)番?", prediction_text)
    if axis_match:
        axis = int(axis_match.group(1))
        # 「買い目:」行や改行手前までを相手欄として抽出（单行・複数行どちらも対応）
        partner_match = re.search(
            r"(?:軸相手|相手)[：:](.*?)(?:\n|買い目|$)",
            prediction_text,
            re.DOTALL,
        )
        if partner_match:
            raw = [int(n) for n in re.findall(r"\d+", partner_match.group(1))]
            seen_p: set[int] = set()
            for p in raw:
                if p != axis and p not in seen_p:
                    partners.append(p)
                    seen_p.add(p)
            partners = partners[:4]
    else:
        # フォールバック: テキスト全体から 1-7 の数字を探し、最初を軸とする
        nums = re.findall(r"\b([1-7])\b", prediction_text)
        if len(nums) >= 2:
            axis = int(nums[0])
            seen_p = {axis}
            for n in nums[1:5]:
                v = int(n)
                if v not in seen_p:
                    partners.append(v)
                    seen_p.add(v)

    return axis, partners


REQ_DIR = ROOT / "queue" / "predictions" / "requests"
RES_DIR = ROOT / "queue" / "predictions" / "results"


def list_requests() -> None:
    """pending なリクエストを一覧表示する。"""
    req_files = sorted(REQ_DIR.glob("*.yaml"))
    if not req_files:
        print("queue/predictions/requests/ にリクエストYAMLがありません。")
        print("先に Stage 1 を実行してください:")
        print("  python scripts/ashigaru_predict.py --date YYYYMMDD --stage 1")
        return

    print(f"{'='*60}")
    print(f"  Stage 2 リクエスト一覧 ({len(req_files)}件)")
    print(f"{'='*60}")

    for req_file in req_files:
        req = yaml.safe_load(req_file.read_text(encoding="utf-8"))
        task_id = req.get("task_id", req_file.stem)
        status = req.get("status", "?")
        venue = req.get("venue", "?")
        race_no = req.get("race_no", "?")
        grade = req.get("grade", "?")
        stage = req.get("stage", "?")
        filter_type = req.get("filter_type", "?")
        conf = req.get("confidence_score", "?")
        date = req.get("date", "?")

        # 結果ファイルの存在確認
        res_file = RES_DIR / f"{task_id}.yaml"
        result_status = "✅ 完了" if res_file.exists() else "⏳ 未処理"

        # F10フィルター状態確認（cmd_149k_sub4）
        f10_passed = req.get("f10_passed", True)  # キーなし → 後方互換でTrue
        f10_label = "" if f10_passed else "  ⛔ [F10除外] confidence_score不足"

        print(f"\n  [{result_status}] {task_id}{f10_label}")
        print(f"    日付: {date} / {venue} {race_no}R / {grade}級 {stage}")
        print(f"    フィルター: {filter_type} / 信頼度スコア: {conf}")
        if not f10_passed:
            print(f"    ⚠ このリクエストはF10フィルター不通過のため --write 不可")
        else:
            print(f"    コマンド: python scripts/stage2_process.py --show {task_id}")

    print(f"\n{'='*60}")
    # pending カウント: F10除外レースは「未処理」に含めない（stage2_haiku.py と同一の扱い）
    pending = []
    for f in req_files:
        if (RES_DIR / f"{f.stem}.yaml").exists():
            continue
        req = yaml.safe_load(f.read_text(encoding="utf-8"))
        if req.get("f10_passed", True):
            pending.append(f)
    print(f"  未処理(処理可能): {len(pending)}件 / 全体: {len(req_files)}件")
    print(f"{'='*60}")


def show_request(task_id: str) -> None:
    """指定されたリクエストのプロンプトを表示する。"""
    req_file = REQ_DIR / f"{task_id}.yaml"
    if not req_file.exists():
        print(f"エラー: {req_file} が見つかりません。")
        sys.exit(1)

    req = yaml.safe_load(req_file.read_text(encoding="utf-8"))

    print(f"\n{'='*60}")
    print(f"  タスクID: {task_id}")
    print(f"  開催: {req.get('venue')} {req.get('race_no')}R")
    print(f"  フィルター: {req.get('filter_type')} / 信頼度: {req.get('confidence_score')}")
    print(f"{'='*60}\n")

    print("【SYSTEM PROMPT】")
    print("-" * 40)
    print(req.get("system_prompt", ""))
    print()

    print("【USER PROMPT】")
    print("-" * 40)
    print(req.get("user_prompt", ""))
    print()

    print(f"{'='*60}")
    print(f"  予測を生成後、以下のコマンドで書き出してください:")
    print(f"  python scripts/stage2_process.py --write {task_id}")
    print(f"{'='*60}")


def write_result(task_id: str, text_file: str | None = None) -> None:
    """予測テキストを結果YAMLとして書き出す。"""
    req_file = REQ_DIR / f"{task_id}.yaml"
    if not req_file.exists():
        print(f"エラー: {req_file} が見つかりません。")
        sys.exit(1)

    req = yaml.safe_load(req_file.read_text(encoding="utf-8"))

    # F10フィルターチェック（cmd_149k_sub4）: stage2_haiku.py の get_pending_requests() と同一の扱い
    if not req.get("f10_passed", True):
        conf = req.get("confidence_score", "?")
        print(f"[F10除外] {task_id}: f10_passed=False（confidence_score={conf} < min_confidence_score）")
        print("  このレースはF10フィルターで除外されています。予測生成をスキップします。")
        sys.exit(1)

    if text_file:
        prediction_text = Path(text_file).read_text(encoding="utf-8").strip()
    else:
        print(f"\n予測テキストを入力してください（完了したら Ctrl+D または EOF）:")
        print(f"形式: 本命: X番（選手名）/ 軸相手: Y番、Z番 / 買い目: ... / 根拠: ...\n")
        lines = sys.stdin.readlines()
        prediction_text = "".join(lines).strip()

    if not prediction_text:
        print("エラー: 予測テキストが空です。")
        sys.exit(1)

    RES_DIR.mkdir(parents=True, exist_ok=True)
    res_file = RES_DIR / f"{task_id}.yaml"

    # 軸・相手を構造化データとして抽出（stage3_aggregate でのテキストパース精度向上）
    axis, partners = _parse_axis_partners(prediction_text)

    result = {
        "task_id": task_id,
        "status": "done",
        "timestamp": datetime.now().isoformat(),
        "model_used": "claude-code-agent",
        "sport": req.get("sport", "keirin"),
        "venue": req.get("venue", ""),
        "race_no": req.get("race_no", ""),
        "filter_type": req.get("filter_type", "A"),
        "prediction_text": prediction_text,
        "axis": axis,       # 構造化: 軸番号（解析失敗時は null）
        "partners": partners,  # 構造化: 相手番号リスト（dedup済み、最大4名）
    }

    res_file.write_text(
        yaml.dump(result, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"\n✅ 結果を書き出しました: {res_file}")
    print(f"\n次のステップ: Stage 3 で bet 計算を実行")
    print(f"  python scripts/ashigaru_predict.py --date {req.get('date', 'YYYYMMDD')} --stage 3")


def main():
    parser = argparse.ArgumentParser(description="Stage 2 ヘルパー — Claude Code 足軽による予測生成")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="リクエスト一覧を表示")
    group.add_argument("--show", metavar="TASK_ID", help="リクエストのプロンプトを表示")
    group.add_argument("--write", metavar="TASK_ID", help="予測テキストを結果YAMLに書き出す")
    parser.add_argument("--text-file", help="予測テキストを含むファイルパス（--write と組み合わせて使用）")
    args = parser.parse_args()

    if args.list:
        list_requests()
    elif args.show:
        show_request(args.show)
    elif args.write:
        write_result(args.write, args.text_file)


if __name__ == "__main__":
    main()
