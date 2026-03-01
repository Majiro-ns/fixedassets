#!/bin/bash
# cron_watchdog.sh - cronジョブ実行確認・アラートスクリプト
#
# cron.log を解析し、各ジョブが予定時刻に実行されているかを確認する。
# 未実行のジョブがあれば cron_watchdog.log に記録し、Discord に通知する。
#
# 使い方:
#   bash scripts/cron_watchdog.sh          # 通常実行
#   bash scripts/cron_watchdog.sh --dry-run  # ログ書き込みなしで確認
#
# テスト用環境変数:
#   WATCHDOG_TEST_ROOT   : プロジェクトルートを上書き（モックディレクトリ用）
#   WATCHDOG_NOW_OVERRIDE: 現在時刻を上書き（"2026-03-01 12:00:00" 形式）
#
# 確認対象ジョブ:
#   stage1_keirin        07:00  最大遅延3h  daily
#   daily_refit_keirin   07:30  最大遅延4h  daily
#   stage3_keirin        18:00  最大遅延3h  daily
#
# (cmd_148k_sub4)

set -uo pipefail

# ── ディレクトリ設定 ───────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="${WATCHDOG_TEST_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
LOG_DIR="$PROJECT_ROOT/data/logs"
CRON_LOG="$LOG_DIR/cron.log"
WATCHDOG_LOG="$LOG_DIR/cron_watchdog.log"
DISCORD_SCRIPT="$PROJECT_ROOT/scripts/discord_notify.py"
PYTHON="${PYTHON_BIN:-/usr/bin/python3}"

# ── オプション解析 ─────────────────────────────────────────────────────────
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --test-root) ;; # 後方互換（値は環境変数で渡す）
    esac
done

mkdir -p "$LOG_DIR"

# ── 現在時刻（テスト用オーバーライド対応）─────────────────────────────────
if [ -n "${WATCHDOG_NOW_OVERRIDE:-}" ]; then
    NOW=$(date -d "$WATCHDOG_NOW_OVERRIDE" +%s 2>/dev/null || \
          date -j -f "%Y-%m-%d %H:%M:%S" "$WATCHDOG_NOW_OVERRIDE" +%s 2>/dev/null || \
          date +%s)
    TODAY=$(date -d "$WATCHDOG_NOW_OVERRIDE" +%Y%m%d 2>/dev/null || \
            date -j -f "%Y-%m-%d %H:%M:%S" "$WATCHDOG_NOW_OVERRIDE" +%Y%m%d 2>/dev/null || \
            date +%Y%m%d)
else
    NOW=$(date +%s)
    TODAY=$(date +%Y%m%d)
fi

TODAY_DASH="${TODAY:0:4}-${TODAY:4:2}-${TODAY:6:2}"

# ── ログ出力関数 ──────────────────────────────────────────────────────────
log() {
    local level="$1"
    local msg="$2"
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S') [$level] $msg"
    echo "$line"
    if [ "$DRY_RUN" -eq 0 ]; then
        echo "$line" >> "$WATCHDOG_LOG"
    fi
}

# ── 確認ジョブ定義: "コマンド名 予定時刻H:M 最大遅延H" ──────────────────
# フォーマット: command expected_hhmm(HHMM) max_delay_hours
JOBS=(
    "stage1_keirin       0700 3"
    "daily_refit_keirin  0730 4"
    "stage3_keirin       1800 3"
)

ALERT_COUNT=0
ALERT_MESSAGES=""

# ── 単一ジョブのチェック関数 ───────────────────────────────────────────────
check_job() {
    local cmd="$1"
    local expected_hhmm="$2"
    local max_delay_hours="$3"

    local exp_h="${expected_hhmm:0:2}"
    local exp_m="${expected_hhmm:2:2}"

    # 今日の予定時刻（unixtime）
    local expected_ts
    expected_ts=$(date -d "${TODAY_DASH} ${exp_h}:${exp_m}:00" +%s 2>/dev/null || \
                  date -j -f "%Y-%m-%d %H:%M:%S" "${TODAY_DASH} ${exp_h}:${exp_m}:00" +%s 2>/dev/null || \
                  echo 0)

    # 予定時刻 + 最大遅延の締め切り
    local deadline=$(( expected_ts + max_delay_hours * 3600 ))

    # 締め切りがまだ来ていない場合はスキップ（チェック不要）
    if [ "$NOW" -lt "$deadline" ]; then
        log "SKIP" "$cmd: 締め切り未到達 (check at $(date -d @"$deadline" '+%H:%M' 2>/dev/null || echo "${exp_h}:${exp_m}+${max_delay_hours}h"))"
        return 0
    fi

    # cron.log が存在しない場合
    if [ ! -f "$CRON_LOG" ]; then
        log "ALERT" "$cmd: cron.log が存在しません ($CRON_LOG)"
        ALERT_COUNT=$(( ALERT_COUNT + 1 ))
        ALERT_MESSAGES="${ALERT_MESSAGES}\n  - ${cmd}: cron.log なし"
        return 1
    fi

    # cron.log から今日の [END] エントリを検索
    local last_end_line
    last_end_line=$(grep "\[END\] command=${cmd}" "$CRON_LOG" 2>/dev/null | \
                    grep "^${TODAY_DASH}" | tail -1)

    if [ -z "$last_end_line" ]; then
        # 今日の実行記録なし → 直近の実行日時を取得してアラート
        local prev_end
        prev_end=$(grep "\[END\] command=${cmd}" "$CRON_LOG" 2>/dev/null | tail -1)
        local prev_ts=""
        if [ -n "$prev_end" ]; then
            prev_ts=$(echo "$prev_end" | grep -oP '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}' || \
                      echo "$prev_end" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}' || \
                      echo "不明")
        else
            prev_ts="記録なし"
        fi
        log "ALERT" "$cmd: 今日($TODAY_DASH)の実行記録なし (直近: $prev_ts)"
        ALERT_COUNT=$(( ALERT_COUNT + 1 ))
        ALERT_MESSAGES="${ALERT_MESSAGES}\n  - ${cmd}: 今日未実行 (直近: ${prev_ts})"
        return 1
    fi

    # 終了コードを確認
    local exit_code
    exit_code=$(echo "$last_end_line" | grep -oP 'exit=\K\d+' || \
                echo "$last_end_line" | grep -oE 'exit=[0-9]+' | cut -d= -f2 || \
                echo "?")

    if [ "$exit_code" != "0" ] && [ "$exit_code" != "?" ]; then
        log "WARN" "$cmd: exit=${exit_code} (エラー終了)"
        ALERT_COUNT=$(( ALERT_COUNT + 1 ))
        ALERT_MESSAGES="${ALERT_MESSAGES}\n  - ${cmd}: エラー終了 (exit=${exit_code})"
    else
        log "OK" "$cmd: 正常実行確認 (exit=${exit_code})"
    fi
    return 0
}

# ── メイン処理 ────────────────────────────────────────────────────────────
log "START" "cron_watchdog 開始 (today=${TODAY_DASH} dry_run=${DRY_RUN})"

for job_spec in "${JOBS[@]}"; do
    # 余分な空白を除去して分割
    read -r cmd expected_hhmm max_delay <<< "$job_spec"
    check_job "$cmd" "$expected_hhmm" "$max_delay"
done

# ── Discord アラート ───────────────────────────────────────────────────────
if [ "$ALERT_COUNT" -gt 0 ]; then
    log "SUMMARY" "アラート: ${ALERT_COUNT}件のジョブに問題あり"
    if [ "$DRY_RUN" -eq 0 ] && [ -f "$DISCORD_SCRIPT" ]; then
        "$PYTHON" "$DISCORD_SCRIPT" \
            --type error \
            --message "⚠️ cron_watchdog アラート (${TODAY_DASH}):
${ALERT_MESSAGES}" \
            --script "cron_watchdog" \
            >> "$WATCHDOG_LOG" 2>&1 || true
    fi
else
    log "SUMMARY" "全ジョブ正常"
fi

log "END" "cron_watchdog 完了 (alerts=${ALERT_COUNT})"
exit $ALERT_COUNT
