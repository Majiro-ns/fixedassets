#!/usr/bin/env bash
# backup_output.sh — output/ スナップショットを data/backup/ に日次コピー（7日ローテーション）
#
# 使い方:
#   bash scripts/backup_output.sh
#   （cronから呼ぶ場合）0 23 * * * /path/to/backup_output.sh >> /path/to/logs/backup.log 2>&1
#
# 目的 (P14 / BUG-2対策):
#   output/20260228 消失事例の再発防止。
#   git追跡と組み合わせ、物理削除後もdata/backup/に7日分が残る。
#
# ローテーション:
#   data/backup/output_YYYYMMDD/ を作成し、7日超のディレクトリを自動削除。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$ROOT/output"
BACKUP_BASE="$ROOT/data/backup"
DATE_STR="$(date +%Y%m%d)"
BACKUP_DIR="$BACKUP_BASE/output_$DATE_STR"
KEEP_DAYS=7

# output/ が存在しない場合はスキップ
if [ ! -d "$OUTPUT_DIR" ]; then
    echo "[backup_output] output/ が存在しません。スキップ。"
    exit 0
fi

# バックアップ先作成
mkdir -p "$BACKUP_DIR"

# output/ を丸ごとコピー（既存バックアップは上書き）
cp -r "$OUTPUT_DIR/." "$BACKUP_DIR/"
echo "[backup_output] $OUTPUT_DIR → $BACKUP_DIR にコピー完了"

# ファイル数カウント
FILE_COUNT=$(find "$BACKUP_DIR" -type f | wc -l)
echo "[backup_output] バックアップファイル数: $FILE_COUNT"

# 7日超の古いバックアップを削除（ローテーション）
DELETED=0
for dir in "$BACKUP_BASE"/output_*/; do
    [ -d "$dir" ] || continue
    dir_date="${dir##*output_}"
    dir_date="${dir_date%/}"
    # 8桁の日付形式チェック
    if [[ ! "$dir_date" =~ ^[0-9]{8}$ ]]; then
        continue
    fi
    # 経過日数計算（bashのdate -d は GNU date が必要）
    if command -v python3 &>/dev/null; then
        days_old=$(python3 -c "
from datetime import datetime, date
d = datetime.strptime('$dir_date', '%Y%m%d').date()
print((date.today() - d).days)
" 2>/dev/null || echo 0)
    else
        days_old=0
    fi
    if [ "$days_old" -gt "$KEEP_DAYS" ]; then
        rm -rf "$dir"
        echo "[backup_output] 古いバックアップ削除: $dir（${days_old}日前）"
        DELETED=$((DELETED + 1))
    fi
done

echo "[backup_output] 完了。削除バックアップ: ${DELETED}件"
