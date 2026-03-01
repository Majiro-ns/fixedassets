'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { Decision, LineItem } from '@/types/classify';

// ─── 分類別の表示設定 ───────────────────────────────────────────────────
// タスク指定: CAPITAL=緑 / EXPENSE=青 / GUIDANCE=黄
const CLS_CONFIG: Record<
  Decision,
  { label: string; badgeVariant: 'success' | 'default' | 'warning'; borderColor: string; bgColor: string }
> = {
  CAPITAL_LIKE: {
    label: '資産計上',
    badgeVariant: 'success',
    borderColor: 'border-green-400',
    bgColor: 'bg-green-50',
  },
  EXPENSE_LIKE: {
    label: '経費処理',
    badgeVariant: 'default',
    borderColor: 'border-blue-400',
    bgColor: 'bg-blue-50',
  },
  GUIDANCE: {
    label: '要確認',
    badgeVariant: 'warning',
    borderColor: 'border-yellow-400',
    bgColor: 'bg-yellow-50',
  },
};

function formatAmount(amount: number | undefined): string {
  if (amount == null) return '';
  return `¥${amount.toLocaleString('ja-JP')}`;
}

// ─── LineItemsTable コンポーネント ────────────────────────────────────
interface LineItemsTableProps {
  items: LineItem[];
}

/**
 * ClassifyResponse.line_items を色分きして一覧表示するコンポーネント。
 * - CAPITAL_LIKE: 緑（資産計上）
 * - EXPENSE_LIKE: 青（経費処理）
 * - GUIDANCE:     黄（要確認）
 * items が空の場合は null を返す（空レンダリングなし）。
 */
export function LineItemsTable({ items }: LineItemsTableProps) {
  if (items.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">
          明細内訳（{items.length}件）
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((item, i) => {
          const cfg = CLS_CONFIG[item.classification] ?? CLS_CONFIG.GUIDANCE;
          return (
            <div
              key={i}
              className={`flex flex-col gap-1 rounded-md border-l-4 p-3 ${cfg.borderColor} ${cfg.bgColor}`}
            >
              {/* 品名 / 金額 / 分類バッジ */}
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium flex-1 break-words">
                  {item.description || '（品名なし）'}
                </span>
                <div className="flex items-center gap-2 shrink-0">
                  {item.amount != null && (
                    <span className="text-sm tabular-nums text-muted-foreground">
                      {formatAmount(item.amount)}
                    </span>
                  )}
                  <Badge variant={cfg.badgeVariant}>{cfg.label}</Badge>
                </div>
              </div>

              {/* 注意フラグ */}
              {item.flags && item.flags.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  注意: {item.flags.join(' / ')}
                </p>
              )}

              {/* AI参考判定 */}
              {item.ai_hint && (
                <p className="text-xs text-blue-700 rounded bg-blue-100 px-2 py-1">
                  🤖 AI参考: {item.ai_hint}
                </p>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
