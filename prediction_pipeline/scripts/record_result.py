#!/usr/bin/env python3
"""
scripts/record_result.py
========================
競輪レース結果を手動で monthly_roi.json に記録するCLIツール。

【使い方】
  # 基本: 日付_会場_レース番号 形式でレースIDを指定
  python scripts/record_result.py --race 20260228_和歌山_12 --payout 5400
  python scripts/record_result.py --race 20260228_和歌山_12 --payout 0    # 不的中

  # 個別指定版（race-id の代わりに個別フラグを使う）
  python scripts/record_result.py --venue 和歌山 --race-no 12 --date 20260228 --payout 5400

  # --result で着順メモを追加（任意）
  python scripts/record_result.py --race 20260228_和歌山_12 --payout 5400 --result "4-6-2"

  # 動作確認（実際には書き込まない）
  python scripts/record_result.py --race 20260228_和歌山_12 --payout 5400 --dry-run

  # 本日のbetレース一覧表示（記録すべきレースを確認）
  python scripts/record_result.py --list

  # 月次集計を表示
  python scripts/record_result.py --summary

作成: 足軽7 / subtask_keirin_result_feed / 2026-02-28
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
ROI_LOG = ROOT / "data" / "logs" / "monthly_roi.json"

# roi_trackerのrecord_result関数を再利用
sys.path.insert(0, str(ROOT / "scripts"))
from roi_tracker import record_result as _record_result, load_roi_log


# ─── 補助関数 ─────────────────────────────────────────────────────

def parse_race_id(race_id: str) -> tuple[str, str, int]:
    """
    race_id から (date_str, venue, race_no) を抽出する。

    対応フォーマット:
      "20260228_和歌山_12"  → ("20260228", "和歌山", 12)
      "20260228_大垣_12"    → ("20260228", "大垣", 12)
    """
    parts = race_id.split("_")
    if len(parts) < 3:
        raise ValueError(
            f"race_id の形式が不正: '{race_id}'\n"
            "正しい形式: YYYYMMDD_会場名_レース番号\n"
            "例: 20260228_和歌山_12"
        )
    date_str = parts[0]
    if not (len(date_str) == 8 and date_str.isdigit()):
        raise ValueError(
            f"race_id の日付部分が不正: '{date_str}'\n"
            "正しい形式: YYYYMMDD_会場名_レース番号\n"
            "例: 20260228_和歌山_12"
        )
    venue = parts[1]
    try:
        race_no = int(parts[2])
    except ValueError:
        raise ValueError(f"race_id のレース番号が数値でない: '{parts[2]}'")
    return date_str, venue, race_no


def get_bet_races_for_date(date_str: str) -> list[dict]:
    """指定日の output/ から BET レース一覧を返す。"""
    date_dir = OUTPUT_DIR / date_str
    if not date_dir.exists():
        return []

    races = []
    for json_file in sorted(date_dir.glob("keirin_*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            bet = data.get("bet", {})
            if bet.get("bet_type") != "skip":
                races.append({
                    "date": date_str,
                    "venue": data.get("race_info", {}).get("venue_name", "?"),
                    "race_no": data.get("race_info", {}).get("race_no", "?"),
                    "investment": bet.get("total_investment", 0),
                    "bet_type": bet.get("bet_type", "?"),
                    "display": bet.get("display", "?"),
                    "filter_type": data.get("filter_type", "?"),
                    "file": str(json_file),
                })
        except Exception:
            pass
    return races


def list_unrecorded_races() -> None:
    """output/ 配下の BET レース一覧と記録状況を表示する。"""
    log_data = load_roi_log()

    # 全月の記録済みrace_idを集める
    recorded_ids: set[str] = set()
    for month_data in log_data.values():
        for r in month_data.get("race_results", []):
            recorded_ids.add(r.get("race_id", ""))

    print("=== BETレース一覧（結果記録状況）===")
    print()

    if not OUTPUT_DIR.exists():
        print("output/ ディレクトリが存在しません")
        return

    found_any = False
    for date_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        races = get_bet_races_for_date(date_dir.name)
        if not races:
            continue

        print(f"📅 {date_dir.name}")
        for r in races:
            race_id = f"{r['date']}_{r['venue']}_{r['race_no']}"
            status = "✅ 記録済" if race_id in recorded_ids else "❌ 未記録"
            print(
                f"  {status}  {r['venue']}{r['race_no']}R  "
                f"Filter={r['filter_type']}  "
                f"投資={r['investment']:,}円  "
                f"買い目={r['display']}"
            )
            if race_id not in recorded_ids:
                print(
                    f"          → 記録コマンド: "
                    f"python scripts/record_result.py "
                    f"--race {race_id} --payout <払戻額>"
                )
        print()
        found_any = True

    if not found_any:
        print("BETレースが見つかりません（output/ が空）")


def show_summary() -> None:
    """月次集計サマリーを表示する。"""
    log_data = load_roi_log()
    if not log_data:
        print("月次データなし")
        return

    print("=== 月次ROIサマリー ===")
    for month, data in sorted(log_data.items()):
        roi = data.get("actual_roi", 0.0)
        investment = data.get("total_investment", 0)
        payout = data.get("total_payout", 0)
        bet_count = data.get("bet_count", 0)
        hit_count = data.get("hit_count", 0)
        race_results = data.get("race_results", [])
        recorded = len(race_results)

        roi_str = f"{roi:.1f}%" if payout > 0 else "未記録"
        print(
            f"{month}: BET={bet_count}件 的中={hit_count}件 "
            f"投資={investment:,}円 払戻={payout:,}円 "
            f"ROI={roi_str} (結果記録={recorded}件)"
        )

    print()
    print("詳細は data/logs/monthly_roi.json を参照")


# ─── main ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="競輪レース結果を monthly_roi.json に手動記録するツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # 和歌山12R 払戻5400円（的中）
  python scripts/record_result.py --race 20260228_和歌山_12 --payout 5400

  # 大垣12R 不的中
  python scripts/record_result.py --race 20260228_大垣_12 --payout 0

  # 着順メモ付き
  python scripts/record_result.py --race 20260228_和歌山_12 --payout 5400 --result "4-6-2"

  # 動作確認のみ（書き込まない）
  python scripts/record_result.py --race 20260228_和歌山_12 --payout 5400 --dry-run

  # 記録すべきレース一覧を表示
  python scripts/record_result.py --list

  # 月次集計を確認
  python scripts/record_result.py --summary
""",
    )

    # 操作モード
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--list", action="store_true",
                            help="記録すべきBETレース一覧を表示")
    mode_group.add_argument("--summary", action="store_true",
                            help="月次集計サマリーを表示")

    # レース指定（--race か --venue/--race-no/--date のどちらか）
    parser.add_argument("--race", metavar="YYYYMMDD_会場_R番号",
                        help="レースID（例: 20260228_和歌山_12）")
    parser.add_argument("--venue", metavar="会場名",
                        help="競輪場名（例: 和歌山）")
    parser.add_argument("--race-no", type=int, metavar="R番号",
                        help="レース番号（例: 12）")
    parser.add_argument("--date", metavar="YYYYMMDD",
                        help="開催日（デフォルト: 今日）",
                        default=datetime.now().strftime("%Y%m%d"))

    # 結果
    parser.add_argument("--payout", type=int, metavar="払戻額",
                        help="払戻金額（円）。不的中の場合は 0")
    parser.add_argument("--result", metavar="着順",
                        help="着順メモ（例: 4-6-2）。参考情報として表示")

    # オプション
    parser.add_argument("--dry-run", action="store_true",
                        help="動作確認のみ（monthly_roi.json に書き込まない）")

    args = parser.parse_args()

    # ─── listモード ───
    if args.list:
        list_unrecorded_races()
        return

    # ─── summaryモード ───
    if args.summary:
        show_summary()
        return

    # ─── 記録モード ───

    # race_id の解決
    if args.race:
        try:
            date_str, venue, race_no = parse_race_id(args.race)
        except ValueError as e:
            print(f"❌ エラー: {e}", file=sys.stderr)
            sys.exit(1)
        race_id = args.race
    elif args.venue and args.race_no:
        date_str = args.date
        venue = args.venue
        race_no = args.race_no
        race_id = f"{date_str}_{venue}_{race_no}"
    else:
        print("❌ エラー: --race か (--venue + --race-no) のどちらかを指定してください",
              file=sys.stderr)
        print("  例: --race 20260228_和歌山_12", file=sys.stderr)
        print("  または: --venue 和歌山 --race-no 12 --date 20260228", file=sys.stderr)
        sys.exit(1)

    # payout の確認
    if args.payout is None:
        print("❌ エラー: --payout を指定してください（不的中の場合は 0）", file=sys.stderr)
        print("  例: --payout 5400  （的中・払戻5400円）", file=sys.stderr)
        print("  例: --payout 0     （不的中）", file=sys.stderr)
        sys.exit(1)

    payout = args.payout
    hit = payout > 0

    # 入力内容を表示
    print("=== レース結果記録 ===")
    print(f"  レースID : {race_id}")
    print(f"  会場     : {venue}")
    print(f"  レース番号: {race_no}R")
    print(f"  日付     : {date_str}")
    print(f"  払戻額   : {payout:,}円")
    print(f"  的中     : {'✅ 的中' if hit else '❌ 不的中'}")
    if args.result:
        print(f"  着順メモ : {args.result}")
    print()

    # 投資額の確認（output JSON から）
    output_json = OUTPUT_DIR / date_str / f"keirin_{venue}_{race_no}.json"
    if output_json.exists():
        try:
            data = json.loads(output_json.read_text(encoding="utf-8"))
            bet_info = data.get("bet", {})
            investment = bet_info.get("total_investment", 0)
            print(f"  投資額（output JSON より）: {investment:,}円")
            if investment > 0 and payout > 0:
                roi = payout / investment * 100
                print(f"  このレースのROI          : {roi:.1f}%")
        except Exception:
            pass
        print()
    else:
        print(f"  ⚠ output JSON が見つかりません: {output_json}")
        print("  （投資額は monthly_roi.json の total_investment から参照）")
        print()

    if args.dry_run:
        print("【dry-run モード】monthly_roi.json には書き込みません")
        return

    # 記録実行
    try:
        updated = _record_result(
            race_id=race_id,
            venue=venue,
            race_no=race_no,
            payout=payout,
            hit=hit,
        )
    except Exception as e:
        print(f"❌ 記録に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    month_str = date_str[:6]
    print(f"✅ 記録完了 ({month_str}月累計)")
    print(f"  投資合計 : {updated.get('total_investment', 0):,}円")
    print(f"  払戻合計 : {updated.get('total_payout', 0):,}円")
    actual_roi = updated.get("actual_roi", 0.0)
    print(f"  実ROI    : {actual_roi:.1f}%")
    print(f"  的中件数 : {updated.get('hit_count', 0)}/{updated.get('bet_count', 0)}件")
    print()
    print(f"  記録先: {ROI_LOG}")
    print()
    print("【次のステップ】")
    print("  他のレース結果も記録: python scripts/record_result.py --list")
    print("  バックテスト実行: python scripts/backtest_real.py")


if __name__ == "__main__":
    main()
