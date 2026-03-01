'use client';

import { BookOpen } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { useTrainingDataStore } from '@/store/trainingDataStore';
import type { TrainingLabel } from '@/types/training_data';

// ─── ラベル → Badge variant マッピング ────────────────────────────────
const LABEL_VARIANT: Record<TrainingLabel, 'default' | 'success' | 'warning'> = {
  固定資産: 'default',
  費用: 'success',
  要確認: 'warning',
};

const MAX_RESULTS = 5;

// ─── 類似度スコア計算 ────────────────────────────────────────────────
// 高スコア = より関連性が高い
// 2: item が query の中に含まれる（例: "サーバーラック" ⊂ "サーバーラック購入費"）
// 1: query が item の中に含まれる（逆包含）
// 0.5×n: スペース/句読点で分割したトークンが item にマッチした数
function calcScore(item: string, query: string): number {
  const q = query.toLowerCase();
  const i = item.toLowerCase();

  if (q.includes(i)) return 2;
  if (i.includes(q)) return 1;

  const tokens = q.split(/[\s　、。・,，]+/).filter((t) => t.length >= 2);
  const matched = tokens.filter((t) => i.includes(t)).length;
  return matched > 0 ? matched * 0.5 : 0;
}

// ─── SimilarCasesPanel ───────────────────────────────────────────────
interface SimilarCasesPanelProps {
  /** 分類入力フォームの description 値 */
  query: string;
}

export function SimilarCasesPanel({ query }: SimilarCasesPanelProps) {
  const records = useTrainingDataStore((s) => s.records);

  // クエリが2文字未満なら非表示
  if (query.trim().length < 2) return null;

  // 教師データ未登録の場合はヒント表示
  if (records.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground flex items-center gap-2">
        <BookOpen className="size-3.5 shrink-0" />
        教師データが未登録です。下部の「CSVインポート」で登録すると類似事例が表示されます。
      </div>
    );
  }

  // スコアリング → フィルタ → ソート → 上位5件
  const matches = records
    .map((r) => ({ record: r, score: calcScore(r.item, query) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, MAX_RESULTS)
    .map((x) => x.record);

  // 一致なしなら非表示（ノイズにならないよう）
  if (matches.length === 0) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
        <BookOpen className="size-3.5" />
        教師データの類似事例（{matches.length} 件）
      </p>
      <div className="space-y-1">
        {matches.map((rec, i) => (
          <div
            key={i}
            className="flex items-center justify-between gap-2 rounded-md bg-muted/50 px-3 py-1.5 text-xs"
          >
            <span className="flex-1 truncate font-medium">{rec.item}</span>
            <span className="tabular-nums text-muted-foreground shrink-0">
              ¥{rec.amount.toLocaleString()}
            </span>
            <Badge variant={LABEL_VARIANT[rec.label]} className="text-xs shrink-0">
              {rec.label}
            </Badge>
            {rec.notes && (
              <span className="text-muted-foreground truncate max-w-[120px] shrink-0">
                {rec.notes}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
