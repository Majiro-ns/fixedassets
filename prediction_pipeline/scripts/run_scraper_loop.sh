#!/bin/bash
# Mr.T予想データ収集 — 連続実行ラッパー
# 5000リクエストごとに一時停止し、自動で--resumeで再開する
# 使い方: bash scripts/run_scraper_loop.sh
# 停止: Ctrl+C または touch /tmp/mrt_scraper_stop

cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline

MAX_SESSIONS=15  # 最大15セッション（= 75,000リクエスト）
REQUESTS_PER_SESSION=5000
RATE_LIMIT=3.0
LOG_FILE=/tmp/mrt_collect_log.txt
STOP_FILE=/tmp/mrt_scraper_stop

rm -f "$STOP_FILE"

echo "=== Mr.T Scraper Loop Started: $(date) ===" >> "$LOG_FILE"
echo "Max sessions: $MAX_SESSIONS, Requests/session: $REQUESTS_PER_SESSION" >> "$LOG_FILE"

# Phase 0: 早期範囲（12/20〜12/27）のスキャン
echo "" >> "$LOG_FILE"
echo "=== Phase 0: Early range (b1465000→b1479461) ===" >> "$LOG_FILE"
PYTHONUNBUFFERED=1 python3 scripts/scrape_mrt_netkeiba.py \
    --start-id 1465000 \
    --end-id 1479461 \
    --rate-limit "$RATE_LIMIT" \
    --max-requests 15000 \
    >> "$LOG_FILE" 2>&1
echo "=== Phase 0 completed: $(date) ===" >> "$LOG_FILE"
python3 scripts/scrape_mrt_netkeiba.py --stats >> "$LOG_FILE" 2>&1
sleep 10

# Phase 1: メイン範囲（--resume で続行）
for i in $(seq 1 $MAX_SESSIONS); do
    if [ -f "$STOP_FILE" ]; then
        echo "=== Stop file detected. Exiting at session $i ===" >> "$LOG_FILE"
        break
    fi

    echo "" >> "$LOG_FILE"
    echo "=== Session $i/$MAX_SESSIONS started: $(date) ===" >> "$LOG_FILE"

    PYTHONUNBUFFERED=1 python3 scripts/scrape_mrt_netkeiba.py \
        --resume \
        --end-id 1555000 \
        --rate-limit "$RATE_LIMIT" \
        --max-requests "$REQUESTS_PER_SESSION" \
        >> "$LOG_FILE" 2>&1

    echo "=== Session $i completed: $(date) ===" >> "$LOG_FILE"

    # 統計表示
    python3 scripts/scrape_mrt_netkeiba.py --stats >> "$LOG_FILE" 2>&1

    # 次セッション前に10秒休憩
    sleep 10
done

echo "" >> "$LOG_FILE"
echo "=== All sessions completed: $(date) ===" >> "$LOG_FILE"
python3 scripts/scrape_mrt_netkeiba.py --stats >> "$LOG_FILE" 2>&1

# 最終xlsxエクスポート
python3 scripts/scrape_mrt_netkeiba.py --export-only >> "$LOG_FILE" 2>&1

# 見解全文補完
echo "" >> "$LOG_FILE"
echo "=== Enriching existing xlsx with full comments ===" >> "$LOG_FILE"
python3 scripts/enrich_comments.py >> "$LOG_FILE" 2>&1

echo "=== DONE ===" >> "$LOG_FILE"
