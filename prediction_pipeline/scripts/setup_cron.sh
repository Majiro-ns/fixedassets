#!/bin/bash
# setup_cron.sh — 競輪予測パイプライン crontab 設定スクリプト
# ================================================================
#
# 実行すると以下の crontab エントリを登録する:
#   07:00  Stage 1 — レース取得 + フィルター + リクエスト生成
#   09:00  Stage 2 — Haiku API で自動予測（ANTHROPIC_API_KEY 必須）
#   18:00  Stage 3 — 結果集約 + bet計算 + Discord通知
#   01日 03:00  月次再訓練（filters.yaml の最適化）
#
# 使い方:
#   bash scripts/setup_cron.sh          # crontab を登録
#   bash scripts/setup_cron.sh --check  # 現在の設定を確認
#   bash scripts/setup_cron.sh --remove # 登録した cron エントリを削除

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CRON_SCRIPT="$SCRIPT_DIR/cron_pipeline.sh"

# cron_pipeline.sh の実行権限確認
if [ ! -x "$CRON_SCRIPT" ]; then
    chmod +x "$CRON_SCRIPT"
    echo "✅ $CRON_SCRIPT に実行権限を付与しました。"
fi

# ─── チェックモード ─────────────────────────────────────────────
if [ "${1:-}" = "--check" ]; then
    echo "現在の crontab 設定 (keirin 関連):"
    echo "─────────────────────────────────────"
    crontab -l 2>/dev/null | grep -E "stage[123]_keirin|weekly_keirin|monthly_retrain|keirin|cron_pipeline" || echo "  (登録なし)"
    exit 0
fi

# ─── 削除モード ─────────────────────────────────────────────────
if [ "${1:-}" = "--remove" ]; then
    echo "keirin 関連の crontab エントリを削除します..."
    CURRENT_CRON=$(crontab -l 2>/dev/null || true)
    FILTERED=$(echo "$CURRENT_CRON" | grep -v "stage[123]_keirin\|weekly_keirin\|monthly_retrain\|cron_pipeline.sh" | grep -v "^# ─── keirin\|^# Stage [123]\|^# 週次フィードバック\|^# 月次再訓練")
    echo "$FILTERED" | crontab -
    echo "✅ 削除完了。残存エントリ:"
    crontab -l 2>/dev/null | head -20 || echo "  (空)"
    exit 0
fi

# ─── 登録モード ─────────────────────────────────────────────────
CURRENT_CRON=$(crontab -l 2>/dev/null || true)

# 既存エントリのチェック
if echo "$CURRENT_CRON" | grep -q "stage1_keirin"; then
    echo "✅ crontab は既に設定済みです。"
    echo ""
    echo "現在の設定:"
    crontab -l | grep -E "stage[123]_keirin|monthly_retrain|Stage|月次" | head -10
    echo ""
    echo "  設定を更新するには: bash scripts/setup_cron.sh --remove && bash scripts/setup_cron.sh"
    exit 0
fi

# ─── 旧エントリ（daily_keirin / health_check）を削除して競合を解消 ────────
# 旧パイプライン(6:00 daily_keirin, 21:00 health_check)が残存すると
# 新3段階パイプライン(7:00/9:00/18:00)と競合・混乱を招くため除去する。
if echo "$CURRENT_CRON" | grep -qE "cron_pipeline.sh (daily_keirin|health_check)"; then
    echo "⚠️  旧エントリ (daily_keirin / health_check) を検出。新パイプラインへ移行するため削除します..."
    CURRENT_CRON=$(echo "$CURRENT_CRON" | grep -v "cron_pipeline.sh daily_keirin\|cron_pipeline.sh health_check")
    echo "$CURRENT_CRON" | crontab -
    echo "✅ 旧エントリ削除完了。"
fi

NEW_ENTRIES="
# ─── keirin 予測パイプライン（cmd_102k: Stage 2は足軽手動トリガー方式）──────
# Stage 1: 朝7:00 レース取得 + フィルター + リクエスト生成
0 7 * * * $CRON_SCRIPT stage1_keirin
# Stage 2: 足軽手動実行（cronではなく家老弐が朝の巡回時に足軽へsend-keys）
#          scripts/stage2_process.py --list → --show {id} → --write {id} の手順
#          詳細: data/reports/daily_operation_guide.md
# Stage 3: 夕18:00 結果集約 + bet計算 + Discord日次サマリ通知
0 18 * * * $CRON_SCRIPT stage3_keirin
# 週次フィードバック: 毎週日曜 22:00（Tier別成績・逆指標・フィルター推奨 → Discord通知）
0 22 * * 0 $CRON_SCRIPT weekly_keirin
# 月次再訓練: 毎月1日 03:00（filters.yaml 自動最適化）
0 3 1 * * $CRON_SCRIPT monthly_retrain
"

# 既存エントリに追加
printf '%s%s\n' "$CURRENT_CRON" "$NEW_ENTRIES" | crontab -

echo "✅ crontab を登録しました。"
echo ""
echo "登録したエントリ:"
echo "─────────────────────────────────────"
crontab -l | grep -A1 -E "stage[123]_keirin|monthly_retrain|weekly_keirin"
echo ""
echo "確認コマンド: bash scripts/setup_cron.sh --check"
echo "削除コマンド: bash scripts/setup_cron.sh --remove"
