'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

// ─── 税務ルールの境界定義 ─────────────────────────────────────────────
// 根拠: 法人税法施行令第133条・第133条の2 / 租税特別措置法第67条の5
interface TaxRule {
  label: string;
  rule: string;
  note?: string;
  match: (amount: number) => boolean;
}

const TAX_RULES: TaxRule[] = [
  {
    label: '10万円未満',
    rule: '全額損金算入可（消耗品費）',
    match: (a) => a < 100_000,
  },
  {
    label: '10万〜20万円',
    rule: '一括償却資産（3年均等割）または全額損金算入選択可',
    match: (a) => a >= 100_000 && a < 200_000,
  },
  {
    label: '20万〜30万円',
    rule: '固定資産計上必須・減価償却',
    note: '中小企業（青色申告）は30万円未満まで即時償却の特例あり（租税特別措置法第67条の5）',
    match: (a) => a >= 200_000 && a < 300_000,
  },
  {
    label: '30万円以上',
    rule: '固定資産計上・通常の減価償却必須',
    match: (a) => a >= 300_000,
  },
];

function getActiveIndex(amount: number): number {
  return TAX_RULES.findIndex((r) => r.match(amount));
}

// ─── TaxBoundaryCard コンポーネント ──────────────────────────────────
interface TaxBoundaryCardProps {
  /** ユーザー入力金額（円）。指定ない場合は全境界をガイドとして等価表示。 */
  amount?: number;
}

/**
 * 金額に応じた税務ルール境界を表示するコンポーネント。
 * - amount あり: 該当する境界をハイライト表示
 * - amount なし: 全境界を等価表示（入力前のガイド）
 * - 10万 / 20万 / 30万 の3境界を可視化
 */
export function TaxBoundaryCard({ amount }: TaxBoundaryCardProps) {
  const hasAmount = amount != null;
  const activeIndex = hasAmount ? getActiveIndex(amount) : -1;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold flex items-center gap-2">
          💡 金額ベース税務ルール
          {hasAmount && (
            <span className="text-xs font-normal text-muted-foreground">
              （入力金額: ¥{amount.toLocaleString('ja-JP')}）
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {TAX_RULES.map((rule, i) => {
          const isActive = hasAmount && i === activeIndex;
          return (
            <div
              key={rule.label}
              className={cn(
                'rounded-md border p-3 transition-colors',
                isActive
                  ? 'border-primary bg-primary/10 ring-1 ring-primary'
                  : 'border-border bg-muted/30 opacity-70'
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className={cn(
                    'text-sm font-medium',
                    isActive ? 'text-primary' : 'text-muted-foreground'
                  )}
                >
                  {rule.label}
                </span>
                {isActive && (
                  <Badge variant="default" className="shrink-0">
                    該当
                  </Badge>
                )}
              </div>
              <p
                className={cn(
                  'text-sm mt-1',
                  isActive ? 'text-foreground font-medium' : 'text-muted-foreground'
                )}
              >
                {rule.rule}
              </p>
              {rule.note && (
                <p className="text-xs text-muted-foreground mt-1">
                  ※ {rule.note}
                </p>
              )}
            </div>
          );
        })}
        <p className="text-xs text-muted-foreground border-t pt-2">
          ※ 最終的な税務処理は顧問税理士・公認会計士にご確認ください。
        </p>
      </CardContent>
    </Card>
  );
}
