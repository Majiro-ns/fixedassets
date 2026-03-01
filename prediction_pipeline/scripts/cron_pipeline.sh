#!/bin/bash
# prediction_pipeline 日次cron ラッパースクリプト
#
# cronから呼び出され、各ステージを実行する。
# ログは data/logs/cron.log に記録される。
# flockで排他制御し、同時実行を防ぐ。
#
# === 新パイプライン (2026-02-28 cmd_098 更新) ===
# cronに設定するエントリ例:
#   # 朝7:00 Stage 1: レース取得 + フィルター + リクエスト生成
#   0 7 * * * /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline/scripts/cron_pipeline.sh stage1_keirin
#   # 朝9:00 Stage 2: Haiku API で自動予測（ANTHROPIC_API_KEY 必須）
#   0 9 * * * /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline/scripts/cron_pipeline.sh stage2_haiku_keirin
#   # 夕18:00 Stage 3: 結果集約 + bet計算
#   0 18 * * * /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline/scripts/cron_pipeline.sh stage3_keirin
#   # 毎月1日 03:00 月次再訓練
#   0 3 1 * * /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline/scripts/cron_pipeline.sh monthly_retrain
#
# === 旧パイプライン（後方互換）===
#   # 毎朝6:00 競輪予測実行（一括・旧方式）
#   0 6 * * * .../cron_pipeline.sh daily_keirin
#
# 直接実行:
#   bash scripts/cron_pipeline.sh stage1_keirin
#   bash scripts/cron_pipeline.sh stage2_haiku_keirin
#   bash scripts/cron_pipeline.sh stage3_keirin
#   bash scripts/cron_pipeline.sh monthly_retrain

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# .env ファイルから環境変数をロード（cronはホーム環境変数を読まないため）
ENV_FILE="$PROJECT_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*=.+ ]]; then
            export "$line"
        fi
    done < "$ENV_FILE"
fi

# Python実行パス
PYTHON="/usr/bin/python3"

# ログディレクトリ
LOG_DIR="$PROJECT_ROOT/data/logs"
mkdir -p "$LOG_DIR"

# コマンド引数（デフォルト: daily_keirin）
COMMAND="${1:-daily_keirin}"
TODAY=$(date +%Y%m%d)
LOG_FILE="$LOG_DIR/cron.log"

# ロックファイル（排他制御）
LOCK_FILE="$LOG_DIR/.cron_pipeline.lock"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [SKIP] cron_pipeline.sh: already running ($COMMAND)" >> "$LOG_FILE"
    exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') [START] command=$COMMAND date=$TODAY" >> "$LOG_FILE"

EXIT_CODE=0

case "$COMMAND" in

    # ─── 新パイプライン（3段階）─────────────────────────────────────────
    stage1_keirin)
        # 朝7:00 Stage 1: Kドリームスからレース取得 + フィルター + リクエストYAML生成
        cd "$PROJECT_ROOT" || exit 1
        "$PYTHON" scripts/ashigaru_predict.py --date "$TODAY" --sport keirin --stage 1 >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?
        ;;

    stage2_haiku_keirin)
        # 朝9:00 Stage 2: Haiku API で自動予測テキスト生成
        # ANTHROPIC_API_KEY がない場合は足軽が手動実行
        cd "$PROJECT_ROOT" || exit 1
        "$PYTHON" scripts/stage2_haiku.py >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?
        ;;

    stage3_keirin)
        # 夕18:00 Stage 3: 予測結果を集約 + bet計算 + 出力JSON生成
        cd "$PROJECT_ROOT" || exit 1
        "$PYTHON" scripts/ashigaru_predict.py --date "$TODAY" --sport keirin --stage 3 >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?
        # Stage 3 成功時: 実結果収集 + ROIトラッカー自動更新 + Discord 日次サマリ通知
        if [ "$EXIT_CODE" -eq 0 ]; then
            # 実レース結果収集（kdreams.jp から取得・予測と突合・ROI記録）
            # collect_results.py は内部で roi_tracker.record_result() を呼び出す
            "$PYTHON" scripts/collect_results.py --date "$TODAY" >> "$LOG_FILE" 2>&1 || true
            # ROIトラッカーを月次集計（bet件数・投資額を更新）
            MONTH=$(echo "$TODAY" | cut -c1-6)
            "$PYTHON" scripts/roi_tracker.py --scan-month "$MONTH" --sport keirin >> "$LOG_FILE" 2>&1 || true
            SUMMARY_FILE="$PROJECT_ROOT/output/$TODAY/summary.md"
            if [ -f "$SUMMARY_FILE" ]; then
                SUMMARY=$(cat "$SUMMARY_FILE")
                "$PYTHON" scripts/discord_notify.py \
                    --type success \
                    --message "📊 本日の競輪予測サマリー (${TODAY})
${SUMMARY}" \
                    --script "stage3_keirin" \
                    >> "$LOG_FILE" 2>&1 || true
            fi
        fi
        ;;

    weekly_keirin)
        # 毎週日曜 22:00 週次フィードバックレポート生成 + Discord通知
        # cmd_103k: 新規実装なし。weekly_feedback.py（既存）をcron化するだけ
        cd "$PROJECT_ROOT" || exit 1
        END_DATE=$(date +%Y%m%d)
        START_DATE=$(date -d "$END_DATE -6 days" +%Y%m%d 2>/dev/null || date -v-6d +%Y%m%d)
        "$PYTHON" scripts/weekly_feedback.py \
            --start "$START_DATE" \
            --end "$END_DATE" \
            --sport keirin >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?
        # レポートをDiscordに週次通知
        if [ "$EXIT_CODE" -eq 0 ]; then
            REPORT_FILE="$PROJECT_ROOT/data/reports/weekly_report_${END_DATE}.md"
            if [ -f "$REPORT_FILE" ]; then
                REPORT=$(head -40 "$REPORT_FILE")
                "$PYTHON" scripts/discord_notify.py \
                    --type success \
                    --message "📈 週次フィードバックレポート (${START_DATE}〜${END_DATE})

${REPORT}" \
                    --script "weekly_keirin" \
                    >> "$LOG_FILE" 2>&1 || true
            fi
        fi
        ;;

    daily_refit_keirin)
        # 毎日 07:30 日次 hit_model refit（案C / cmd_126k）
        # Stage1（07:00）完了後・Stage2（手動）前に実行
        # 月次(毎月1日)・週次(日曜)と同日の場合は daily_refit.py 内でSKIP
        MRT_ROOT="/mnt/c/Users/owner/Documents/Obsidian Vault/10_Projects/keirin_prediction"
        cd "$MRT_ROOT" || exit 1
        # features.csv を最新 DB から再生成（Stage1 完了後なので当日分が含まれる）
        echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] features.csv 更新中..." >> "$LOG_FILE"
        if ! "$PYTHON" src/ml/build_features.py >> "$LOG_FILE" 2>&1; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] build_features.py 失敗。daily_refit をスキップ" >> "$LOG_FILE"
            EXIT_CODE=1
        else
            "$PYTHON" src/pipeline/daily_refit.py >> "$LOG_FILE" 2>&1
            EXIT_CODE=$?
        fi
        ;;

    weekly_retrain_keirin)
        # 毎週日曜 0:00 hit_model 週次ミニ再訓練（E5 / cmd_119k）
        # 月次と同週の場合は weekly_retrain.py 内でスキップ
        MRT_ROOT="/mnt/c/Users/owner/Documents/Obsidian Vault/10_Projects/keirin_prediction"
        cd "$MRT_ROOT" || exit 1
        # features.csv を最新 DB から再生成（cmd_125k: バックフィル後の鮮度保証）
        echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] features.csv 更新中..." >> "$LOG_FILE"
        if ! "$PYTHON" src/ml/build_features.py >> "$LOG_FILE" 2>&1; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] build_features.py 失敗。weekly_retrain をスキップ" >> "$LOG_FILE"
            EXIT_CODE=1
        else
            "$PYTHON" src/pipeline/weekly_retrain.py >> "$LOG_FILE" 2>&1
            EXIT_CODE=$?
        fi
        ;;

    monthly_retrain)
        # 毎月1日 03:00 月次フィルター最適化（再訓練相当）
        cd "$PROJECT_ROOT" || exit 1
        LAST_MONTH=$(date -d "$(date +%Y-%m-01) -1 day" +%Y-%m 2>/dev/null || date -v-1m +%Y-%m)
        "$PYTHON" scripts/monthly_optimize.py \
            --sport keirin \
            --month "$LAST_MONTH" \
            --apply >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?
        ;;

    # ─── 旧パイプライン（後方互換）─────────────────────────────────────
    daily_keirin)
        # 旧方式: 一括実行（非推奨。新パイプラインは stage1/2/3 を使用）
        cd "$PROJECT_ROOT" || exit 1
        "$PYTHON" scripts/daily_run.py --sport keirin >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?
        ;;

    daily_kyotei)
        # 競艇予測パイプライン実行（旧方式）
        cd "$PROJECT_ROOT" || exit 1
        "$PYTHON" scripts/daily_run.py --sport kyotei >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?
        ;;

    health_check)
        # ヘルスチェック（output鮮度確認）
        cd "$PROJECT_ROOT" || exit 1
        "$PYTHON" scripts/health_check.py --sport keirin >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?
        ;;

    *)
        echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] 不明なコマンド: $COMMAND" >> "$LOG_FILE"
        EXIT_CODE=1
        ;;
esac

echo "$(date '+%Y-%m-%d %H:%M:%S') [END] command=$COMMAND exit=$EXIT_CODE" >> "$LOG_FILE"

# エラー時はDiscord通知
NOTIFY_SCRIPT="$PROJECT_ROOT/scripts/discord_notify.py"
if [ "$EXIT_CODE" -ne 0 ] && [ -f "$NOTIFY_SCRIPT" ]; then
    LAST_SUCCESS=$(stat -c '%y' "$PROJECT_ROOT/data/logs/pipeline.log" 2>/dev/null | cut -c1-19 || echo "不明")
    "$PYTHON" "$NOTIFY_SCRIPT" \
        --type error \
        --message "cron_pipeline.sh $COMMAND が失敗しました (exit=$EXIT_CODE)" \
        --script "$COMMAND" \
        --last-success "$LAST_SUCCESS" \
        >> "$LOG_FILE" 2>&1 || true
fi

exit $EXIT_CODE
