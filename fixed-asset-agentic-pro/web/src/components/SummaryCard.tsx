'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { LineItem } from '@/types/classify';

// ─── SummaryCard コンポーネント ───────────────────────────────────────
interface SummaryCardProps {
  items: LineItem[];
}

/**
 * line_items から判定集計サマリを表示するカード。
 * - items が空の場合は null を返す（非表示）
 * - CAPITAL_LIKE: 資産計上合計（金額合計・緑）
 * - EXPENSE_LIKE: 費用計上合計（金額合計・青）
 * - GUIDANCE:     要確認件数（件数・黄）
 */
export function SummaryCard({ items }: SummaryCardProps) {
  if (items.length === 0) return null;

  const capitalTotal = items
    .filter((i) => i.classification === 'CAPITAL_LIKE')
    .reduce((sum, i) => sum + (i.amount ?? 0), 0);

  const expenseTotal = items
    .filter((i) => i.classification === 'EXPENSE_LIKE')
    .reduce((sum, i) => sum + (i.amount ?? 0), 0);

  const guidanceCount = items.filter((i) => i.classification === 'GUIDANCE').length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">📊 集計サマリ</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-4 text-center">
          {/* 資産計上合計 */}
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">💰 資産計上合計</p>
            <p className="text-lg font-bold text-green-600">
              {capitalTotal.toLocaleString('ja-JP')} 円
            </p>
          </div>

          {/* 費用計上合計 */}
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">📄 費用計上合計</p>
            <p className="text-lg font-bold text-blue-600">
              {expenseTotal.toLocaleString('ja-JP')} 円
            </p>
          </div>

          {/* 要確認件数 */}
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">❓ 要確認件数</p>
            <p className="text-lg font-bold text-yellow-600">{guidanceCount} 件</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
