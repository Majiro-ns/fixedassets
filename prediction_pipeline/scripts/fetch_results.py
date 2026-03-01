"""
レース結果取得スクリプト

KEIRIN.JP の結果ページから指定日・会場のレース結果を取得し、
JSON ファイルとして保存する。

使用例:
    python scripts/fetch_results.py --date 20260224 --venue 川崎
    python scripts/fetch_results.py --date 20260224 --venue 川崎 --output data/results/
    python scripts/fetch_results.py --date 20260224  # 全会場取得
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# src/ / feedback_engine/ をパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.keirin_scraper import KeirinScraper
from feedback_engine.predictions_log import PredictionsLog


# ─── デフォルト設定 ────────────────────────────────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    "keirin": {
        "base_url": "https://keirin.jp/pc",
        "request_delay": 2.0,
    }
}

DEFAULT_OUTPUT_DIR = "data/results"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="KEIRIN.JP からレース結果を取得して JSON に保存する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python scripts/fetch_results.py --date 20260224 --venue 川崎
  python scripts/fetch_results.py --date 20260224  # 全会場（スケジュール取得後に全会場を処理）
  python scripts/fetch_results.py --date 20260224 --venue 川崎 --output data/results/
        """,
    )
    parser.add_argument(
        "--date",
        required=True,
        help="取得対象の日付 (YYYYMMDD 形式, 例: 20260224)",
    )
    parser.add_argument(
        "--venue",
        default=None,
        help="会場名 (例: 川崎)。省略時は開催全会場を取得する",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_DIR,
        help=f"出力ディレクトリ (デフォルト: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="取得のみ行い、ファイルに保存しない（動作確認用）",
    )
    parser.add_argument(
        "--log-dir",
        default="data/logs",
        help="predictions_log.jsonl の格納ディレクトリ (デフォルト: data/logs)",
    )
    parser.add_argument(
        "--no-log-update",
        action="store_true",
        help="predictions_log.jsonl への結果反映をスキップする",
    )
    return parser.parse_args()


def validate_date(date_str: str) -> None:
    """日付文字列が YYYYMMDD 形式かバリデーションする。

    Args:
        date_str: 検証する日付文字列

    Raises:
        ValueError: 形式が正しくない場合
    """
    try:
        datetime.strptime(date_str, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"日付の形式が不正です: {date_str!r}（YYYYMMDD 形式で指定してください）") from exc


def fetch_results_for_date_venue(
    scraper: KeirinScraper,
    date: str,
    venue_name: str,
) -> dict[str, Any]:
    """指定日・会場のレース結果を取得する。

    Args:
        scraper: KeirinScraper のインスタンス
        date: 日付文字列 YYYYMMDD
        venue_name: 会場名

    Returns:
        レース結果を含む辞書。date, venue_name, fetched_at, results を含む。
    """
    print(f"  → {venue_name} の結果を取得中...", flush=True)
    results = scraper.fetch_results(date=date, venue_name=venue_name)
    return {
        "date": date,
        "venue_name": venue_name,
        "fetched_at": datetime.now().isoformat(),
        "results": results,
    }


def save_results(data: dict[str, Any], output_dir: str, date: str, venue_name: str) -> str:
    """レース結果を JSON ファイルに保存する。

    Args:
        data: 保存するデータ辞書
        output_dir: 出力先ディレクトリ
        date: 日付文字列 YYYYMMDD（ファイル名に使用）
        venue_name: 会場名（ファイル名に使用）

    Returns:
        保存したファイルのパス
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # ファイル名: results_YYYYMMDD.json または results_YYYYMMDD_会場名.json
    if venue_name:
        filename = f"results_{date}_{venue_name}.json"
    else:
        filename = f"results_{date}.json"

    filepath = output_path / filename

    with open(filepath, mode="w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return str(filepath)


def update_predictions_log(
    all_data: list[dict[str, Any]],
    log_dir: str,
    date_str: str,
    sport: str = "keirin",
) -> int:
    """
    取得したレース結果を PredictionsLog.update_result() で教師データに反映する。

    fetch_results.py が取得した results を predictions_log.jsonl に書き戻す。
    prediction_id は "{sport}_{date}_{venue}_{race_number}R" 形式で構築する。

    Args:
        all_data:  fetch_results_for_date_venue() が返したデータのリスト。
                   各要素は {"date": str, "venue_name": str, "results": list} を含む。
        log_dir:   predictions_log.jsonl の格納ディレクトリ（例: "data/logs"）
        date_str:  YYYYMMDD 形式の日付文字列
        sport:     スポーツ種別（現状 "keirin" 固定）

    Returns:
        更新に成功したレコード数
    """
    plog = PredictionsLog(log_dir)
    # YYYYMMDD → YYYYMMDD（prediction_id内では8桁で使用）
    updated_count = 0

    for venue_data in all_data:
        venue_name = venue_data.get("venue_name", "")
        results = venue_data.get("results", [])

        for race_result in results:
            race_number = race_result.get("race_no") or race_result.get("race_number")
            if race_number is None:
                continue

            # prediction_id 形式: "keirin_20260224_熊本_11R"
            prediction_id = f"{sport}_{date_str}_{venue_name}_{race_number}R"

            # result フィールドを構築
            winning_numbers = race_result.get("winning_numbers", [])
            payout = race_result.get("payout") or race_result.get("odds")
            result_dict: dict[str, Any] = {
                "fetched":     True,
                "result_rank": winning_numbers if winning_numbers else None,
                "hit":         None,   # predictor が生成時の買い目と照合が必要
                "payout":      int(payout * 100) if isinstance(payout, float) else payout,
                "roi":         None,   # 払戻/投資額は PredictionsLog 側の情報が必要
                "popular_hit": None,
                "upset_level": None,
            }

            if plog.update_result(prediction_id, sport, result_dict):
                updated_count += 1

    return updated_count


def main() -> int:
    """メインエントリーポイント。

    Returns:
        終了コード (0: 成功, 1: エラー)
    """
    args = parse_args()

    # 日付バリデーション
    try:
        validate_date(args.date)
    except ValueError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    scraper = KeirinScraper(DEFAULT_CONFIG)
    all_data: list[dict[str, Any]] = []

    if args.venue:
        # 指定会場のみ取得
        print(f"[fetch_results] {args.date} / {args.venue} の結果を取得します")
        try:
            data = fetch_results_for_date_venue(scraper, args.date, args.venue)
            all_data.append(data)
        except Exception as exc:
            print(f"エラー: 結果の取得に失敗しました: {exc}", file=sys.stderr)
            return 1
    else:
        # 全会場: まずスケジュールを取得して会場一覧を取得
        print(f"[fetch_results] {args.date} の開催会場一覧を取得します")
        try:
            schedule = scraper.fetch_schedule(date=args.date)
        except Exception as exc:
            print(f"エラー: スケジュールの取得に失敗しました: {exc}", file=sys.stderr)
            return 1

        venues = list({item["venue_name"] for item in schedule})
        print(f"  開催会場: {', '.join(venues)} ({len(venues)} 会場)")

        for venue in venues:
            try:
                data = fetch_results_for_date_venue(scraper, args.date, venue)
                all_data.append(data)
                time.sleep(1.0)  # 会場切り替え時に追加待機
            except Exception as exc:
                print(f"  警告: {venue} の取得をスキップ: {exc}", file=sys.stderr)

    # 結果の確認
    if not all_data:
        print("警告: 取得できた結果がありません", file=sys.stderr)
        return 1

    # 保存（dry-run の場合は表示のみ）
    if args.dry_run:
        print("\n[dry-run] 以下のデータを取得しました（保存はしません）:")
        for data in all_data:
            print(f"  {data['venue_name']}: {len(data['results'])} レース")
        return 0

    # 全会場まとめて1ファイルに保存する場合
    if len(all_data) == 1:
        venue_name = all_data[0]["venue_name"]
        output_data = all_data[0]
    else:
        venue_name = ""
        output_data = {
            "date": args.date,
            "fetched_at": datetime.now().isoformat(),
            "venues": all_data,
        }

    filepath = save_results(output_data, args.output, args.date, venue_name)
    print(f"\n✅ 保存完了: {filepath}")

    # サマリー表示
    total_races = sum(len(d.get("results", [])) for d in all_data)
    print(f"   取得会場: {len(all_data)} 会場 / 合計 {total_races} レース")

    # predictions_log.jsonl への結果反映
    if not args.no_log_update:
        try:
            updated = update_predictions_log(
                all_data,
                log_dir=args.log_dir,
                date_str=args.date,
                sport="keirin",
            )
            if updated > 0:
                print(f"📝 predictions_log 更新: {updated} 件を反映しました")
            else:
                print("📝 predictions_log: 該当する予想レコードなし（新規レースは翌日の予想生成後に反映）")
        except Exception as exc:
            print(f"⚠️  predictions_log 更新中にエラー: {exc}", file=sys.stderr)
            # ログ更新の失敗はメイン処理の失敗とはしない

    return 0


if __name__ == "__main__":
    sys.exit(main())
