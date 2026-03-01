"""
競艇一撃予想 boatrace.jp 結果照合スクリプト（fetch_kyotei_results.py）
====================================================================

enriched.json の各予想について boatrace.jp から3連単結果を取得し、
buy_tickets と照合して hit/payout を記録する。

使用例:
    python scripts/fetch_kyotei_results.py --year 2023
    python scripts/fetch_kyotei_results.py --year 2023 --start-index 50
    python scripts/fetch_kyotei_results.py --year 2023 --dry-run
"""

import argparse
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False
    import subprocess

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 定数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATA_PATH = "/mnt/c/Users/owner/Documents/Obsidian Vault/10_Projects/keirin-expansion/kyotei_ichigeki_predictions_full_enriched.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REQUEST_INTERVAL = 5      # リクエスト間隔（秒）
SESSION_MAX = 20          # 1セッションの上限件数
SESSION_BREAK = 60        # セッション間休憩（秒）
SAVE_INTERVAL = 100       # 途中保存間隔（件）

VENUE_CODE: Dict[str, str] = {
    "桐生": "01", "戸田": "02", "江戸川": "03", "平和島": "04",
    "多摩川": "05", "浜名湖": "06", "蒲郡": "07", "常滑": "08",
    "津":   "09", "三国": "10", "びわこ": "11", "住之江": "12",
    "尼崎": "13", "鳴門": "14", "丸亀": "15", "児島": "16",
    "宮島": "17", "徳山": "18", "下関": "19", "若松": "20",
    "芦屋": "21", "福岡": "22", "唐津": "23", "大村": "24",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTTP フェッチ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def fetch_html(url: str, timeout: int = 15) -> str:
    """
    指定 URL の HTML を取得して文字列で返す。

    requests が利用可能な場合は requests、なければ subprocess + curl を使用。

    Args:
        url: 取得対象 URL。
        timeout: タイムアウト秒数。

    Returns:
        HTML 文字列。取得失敗時は空文字列。
    """
    headers = {"User-Agent": UA}
    if REQUESTS_OK:
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error("requests エラー %s: %s", url, e)
            return ""
    else:
        result = subprocess.run(
            ["curl", "-s", "-L", "-m", str(timeout), "-A", UA, url],
            capture_output=True,
        )
        try:
            return result.stdout.decode("utf-8", errors="replace")
        except Exception as e:
            logger.error("curl エラー %s: %s", url, e)
            return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HTML パース
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def parse_trifecta_result(html: str) -> Tuple[Optional[str], Optional[int]]:
    """
    boatrace.jp の結果ページ HTML から3連単着順と配当を抽出する。

    HTML 構造:
        <td>3連単</td>
        ... <span class="numberSet1_number is-typeX">N</span> ...
        ... 4,500 ...

    Args:
        html: boatrace.jp レース結果ページの HTML 文字列。

    Returns:
        (order_str, payout) のタプル。
        order_str は "1-6-3" 形式。取得失敗時は (None, None)。
    """
    if not html:
        return None, None

    # 3連単ブロックを切り出す
    block_m = re.search(r'3連単</td>(.*?)(?:3連複|</tbody>)', html, re.DOTALL)
    if not block_m:
        logger.debug("3連単ブロックが見つかりません")
        return None, None

    block = block_m.group(1)

    # 着順（1-6-3 形式）を抽出
    nums = re.findall(r'numberSet1_number[^>]+>(\d+)', block)
    if len(nums) < 3:
        logger.debug("着順数字が不足: %s", nums)
        return None, None
    order_str = f"{nums[0]}-{nums[1]}-{nums[2]}"

    # 配当（"4,500" → 4500）を抽出
    pay_m = re.search(r'([\d,]{3,})', block)
    payout = int(pay_m.group(1).replace(",", "")) if pay_m else None

    return order_str, payout


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 照合ロジック
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def normalize_ticket(ticket: str) -> str:
    """
    買い目文字列を "X-Y-Z" 形式に正規化する（全角→半角、スペース除去）。

    Args:
        ticket: 買い目文字列（例: "1-3-2", "132", "１－３－２"）。

    Returns:
        "X-Y-Z" 形式の文字列。変換不可の場合はそのまま返す。
    """
    zen2han = str.maketrans("１２３４５６－", "123456-")
    t = ticket.translate(zen2han).replace(" ", "").strip()
    # "132" → "1-3-2" 変換（3桁数字）
    if re.match(r"^[1-6]{3}$", t):
        return f"{t[0]}-{t[1]}-{t[2]}"
    return t


def is_hit(buy_tickets: List[str], order_str: str) -> bool:
    """
    買い目リストのいずれかが3連単結果と一致するか判定する。

    Args:
        buy_tickets: 買い目リスト（例: ["1-3-2", "1-3-5"]）。
        order_str: 3連単着順（例: "1-6-3"）。

    Returns:
        1点でも的中なら True。
    """
    normalized_order = normalize_ticket(order_str)
    for t in buy_tickets:
        if normalize_ticket(t) == normalized_order:
            return True
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン照合処理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def run(
    year: str = "2023",
    start_index: int = 0,
    dry_run: bool = False,
    data_path: str = DATA_PATH,
) -> Dict[str, Any]:
    """
    指定年の予想レコードについて boatrace.jp から結果を取得・照合する。

    Args:
        year: 照合対象年（例: "2023"）。
        start_index: 対象レコードの開始インデックス（再開用）。
        dry_run: True の場合 HTTP リクエストを送らずにシミュレーション。
        data_path: enriched.json のファイルパス。

    Returns:
        実行サマリー辞書。
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # データ読み込み
    with open(data_path, encoding="utf-8") as f:
        all_data: List[Dict[str, Any]] = json.load(f)
    logger.info("データ読み込み完了: %d 件", len(all_data))

    # 対象レコードをインデックス付きで抽出（全データ上のインデックスを保持）
    targets: List[Tuple[int, Dict[str, Any]]] = [
        (i, d) for i, d in enumerate(all_data)
        if str(d.get("date", "")).startswith(year)
        and d.get("venue") and d.get("venue") not in ("不明", None)
        and d.get("race_number") and d.get("race_number") not in ("不明", None)
        and "??" not in str(d.get("date", ""))
    ]
    logger.info("照合対象: %d 件 (year=%s, start_index=%d)", len(targets), year, start_index)

    if start_index > 0:
        targets = targets[start_index:]
        logger.info("再開: %d 件をスキップ、残り %d 件", start_index, len(targets))

    # 統計
    stats = {
        "year": year,
        "total_targets": len(targets) + start_index,
        "processed": 0,
        "skipped": 0,
        "hit": 0,
        "miss": 0,
        "parse_error": 0,
        "http_error": 0,
    }

    session_count = 0
    item_in_session = 0

    for seq, (global_idx, record) in enumerate(targets):
        venue = record.get("venue", "")
        jcd = VENUE_CODE.get(venue)
        if not jcd:
            logger.warning("[SKIP] venue未対応: %s", venue)
            stats["skipped"] += 1
            continue

        raw_rn = str(record.get("race_number", "")).replace("R", "").strip()
        if not raw_rn.isdigit():
            logger.warning("[SKIP] race_number不正: %s", record.get("race_number"))
            stats["skipped"] += 1
            continue

        date_str = str(record.get("date", "")).replace("-", "")
        if len(date_str) < 8:
            logger.warning("[SKIP] date不正: %s", record.get("date"))
            stats["skipped"] += 1
            continue

        url = (
            f"https://www.boatrace.jp/owpc/pc/race/raceresult"
            f"?rno={raw_rn}&jcd={jcd}&hd={date_str}"
        )
        buy_tickets = record.get("buy_tickets") or []

        logger.info(
            "[%d/%d] %s %s %sR url=%s",
            seq + 1, len(targets),
            record.get("date"), venue, raw_rn, url,
        )

        if dry_run:
            logger.info("  [DRY RUN] スキップ（HTTP未送信）")
            stats["processed"] += 1
            continue

        # セッション管理
        if item_in_session >= SESSION_MAX:
            logger.info("--- セッション%d完了（%d件）。%d秒休憩 ---",
                        session_count + 1, SESSION_MAX, SESSION_BREAK)
            time.sleep(SESSION_BREAK)
            session_count += 1
            item_in_session = 0

        # HTTP 取得
        html = fetch_html(url)
        if not html:
            logger.warning("  HTML取得失敗: %s", url)
            stats["http_error"] += 1
            item_in_session += 1
            time.sleep(REQUEST_INTERVAL)
            continue

        # パース
        order_str, payout = parse_trifecta_result(html)
        if order_str is None:
            logger.warning("  3連単パース失敗 (url=%s)", url)
            stats["parse_error"] += 1
            all_data[global_idx]["result"] = "parse_error"
        else:
            hit = is_hit(buy_tickets, order_str)
            all_data[global_idx]["result"] = "hit" if hit else "miss"
            all_data[global_idx]["payout"] = payout if hit else 0
            all_data[global_idx]["actual_order"] = order_str
            if hit:
                stats["hit"] += 1
                logger.info("  ★的中★ 着順=%s 配当=%s 買い目=%s",
                            order_str, payout, buy_tickets)
            else:
                stats["miss"] += 1
                logger.info("  不的中 着順=%s 買い目=%s", order_str, buy_tickets)

        stats["processed"] += 1
        item_in_session += 1

        # 途中保存
        if stats["processed"] % SAVE_INTERVAL == 0:
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            logger.info("  ★中間保存: %d 件処理済み", stats["processed"])

        time.sleep(REQUEST_INTERVAL)

    # 最終保存
    if not dry_run:
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        logger.info("最終保存完了: %s", data_path)

    # サマリー出力
    processed_non_skip = stats["hit"] + stats["miss"] + stats["parse_error"] + stats["http_error"]
    hit_rate = (
        f"{stats['hit'] / processed_non_skip * 100:.1f}%"
        if processed_non_skip > 0 else "N/A"
    )
    print(
        f"\n{'=' * 50}\n"
        f"[fetch_kyotei_results] 完了\n"
        f"  year       : {year}\n"
        f"  対象       : {stats['total_targets']} 件\n"
        f"  処理済み   : {stats['processed']} 件\n"
        f"  スキップ   : {stats['skipped']} 件\n"
        f"  的中       : {stats['hit']} 件\n"
        f"  不的中     : {stats['miss']} 件\n"
        f"  的中率     : {hit_rate}\n"
        f"  パースErr  : {stats['parse_error']} 件\n"
        f"  HTTPErr    : {stats['http_error']} 件\n"
        f"{'=' * 50}\n"
    )
    return stats


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI エントリーポイント
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def main() -> None:
    """コマンドライン引数を解析して run() を呼び出すエントリーポイント。"""
    parser = argparse.ArgumentParser(
        description="競艇一撃予想 boatrace.jp 結果照合スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用例:\n"
            "  python scripts/fetch_kyotei_results.py --year 2023\n"
            "  python scripts/fetch_kyotei_results.py --year 2023 --start-index 50\n"
            "  python scripts/fetch_kyotei_results.py --year 2023 --dry-run\n"
        ),
    )
    parser.add_argument(
        "--year",
        default="2023",
        help="照合対象年（デフォルト: 2023）",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        metavar="N",
        help="対象レコードの開始インデックス（再開用、デフォルト: 0）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="HTTP リクエストを送らずにシミュレーション",
    )
    parser.add_argument(
        "--data",
        default=DATA_PATH,
        metavar="PATH",
        help=f"enriched.json のパス（デフォルト: {DATA_PATH}）",
    )

    args = parser.parse_args()
    run(
        year=args.year,
        start_index=args.start_index,
        dry_run=args.dry_run,
        data_path=args.data,
    )


if __name__ == "__main__":
    main()
