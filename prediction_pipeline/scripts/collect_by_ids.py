#!/usr/bin/env python3
"""
既知のIDリスト（mrt_known_ids.json）を使ってMr.T予想を高速収集する。

Playwrightで取得したIDリストを元に、各IDの予想ページを順次取得。
ブルートフォースの75時間 → 850件 × 2.5秒 = 35分で完了。
"""

import json
import sys
import time
from pathlib import Path

# scrape_mrt_netkeiba.py のモジュールをインポート
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_mrt_netkeiba import (
    fetch_page, parse_prediction_page, init_db, save_prediction,
    export_xlsx, get_stats, PREDICTOR_ID
)

IDS_FILE = Path(__file__).resolve().parent.parent / "data" / "mrt_known_ids.json"
RATE_LIMIT = 2.5  # 秒


def main():
    if not IDS_FILE.exists():
        print(f"ERROR: {IDS_FILE} not found. Run Playwright ID collector first.")
        return

    with open(IDS_FILE) as f:
        known_ids = json.load(f)

    # 文字列→int
    known_ids = [int(x) for x in known_ids]
    print(f"Known IDs: {len(known_ids)}")
    print(f"Range: b{min(known_ids)} → b{max(known_ids)}")

    conn = init_db()

    # 既にDB内にあるIDを除外
    existing = set()
    for row in conn.execute("SELECT race_id FROM mrt_predictions"):
        existing.add(row[0])
    print(f"Already in DB: {len(existing)}")

    to_fetch = [x for x in known_ids if x not in existing]
    print(f"To fetch: {len(to_fetch)}")
    print(f"ETA: {len(to_fetch) * RATE_LIMIT / 60:.0f} minutes")
    print("-" * 60)

    saved = 0
    errors = 0

    for i, race_id in enumerate(to_fetch):
        time.sleep(RATE_LIMIT)

        html = fetch_page(race_id)
        if html is None:
            errors += 1
            if i % 50 == 0:
                print(f"  [{i+1}/{len(to_fetch)}] b{race_id}: miss")
            continue

        prediction = parse_prediction_page(html, race_id)
        if prediction is None:
            errors += 1
            continue

        if save_prediction(conn, prediction):
            saved += 1
            venue = prediction.get("venue", "?")
            race_num = prediction.get("race_number", "?")
            date = prediction.get("date", "?")
            payout = prediction.get("payout", 0)
            print(f"  [{i+1}/{len(to_fetch)}] ✓ b{race_id}: {date} {venue}{race_num} ¥{payout:,}")

        if (i + 1) % 100 == 0:
            s = get_stats(conn)
            print(f"  --- Progress: {s['total']} total, {s['date_from']}→{s['date_to']} ---")

    print("-" * 60)
    print(f"Done: {saved} saved, {errors} errors")

    # 統計
    s = get_stats(conn)
    print(f"DB: {s['total']} predictions ({s['date_from']} → {s['date_to']})")
    if s['total_investment'] > 0:
        print(f"ROI: {s['total_payout']/s['total_investment']*100:.1f}%")

    # xlsx export
    export_xlsx(conn)
    conn.close()


if __name__ == "__main__":
    main()
