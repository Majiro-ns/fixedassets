'use client';

import { Building2, CheckCircle2, HelpCircle, PenLine } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { Decision } from '@/types/classify';
import type { LineItemWithAction, UserAction } from '@/types/pdf_review';

// ─── 判定ラベル設定 ────────────────────────────────────────────────────

const VERDICT_CONFIG: Record<
  Decision,
  { label: string; badgeVariant: 'default' | 'success' | 'warning'; icon: React.ElementType; borderColor: string }
> = {
  CAPITAL_LIKE: {
    label: '固定資産',
    badgeVariant: 'default',
    icon: Building2,
    borderColor: 'border-l-blue-500',
  },
  EXPENSE_LIKE: {
    label: '費用',
    badgeVariant: 'success',
    icon: CheckCircle2,
    borderColor: 'border-l-green-500',
  },
  GUIDANCE: {
    label: '要確認',
    badgeVariant: 'warning',
    icon: HelpCircle,
    borderColor: 'border-l-yellow-500',
  },
};

// ─── 信頼度バー ────────────────────────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-400';
  return (
    <div className="space-y-0.5">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>信頼度</span>
        <span className="font-medium">{pct}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-secondary overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ─── Props ────────────────────────────────────────────────────────────

interface LineItemReviewCardProps {
  item: LineItemWithAction;
  onAction: (id: string, action: UserAction, finalVerdict: Decision) => void;
}

// ─── LineItemReviewCard ───────────────────────────────────────────────

export function LineItemReviewCard({ item, onAction }: LineItemReviewCardProps) {
  const verdictCfg = VERDICT_CONFIG[item.finalVerdict] ?? VERDICT_CONFIG.GUIDANCE;
  const VerdictIcon = verdictCfg.icon;
  const pct = Math.round(item.confidence * 100);

  const isConfirmed = item.userAction !== 'pending';

  return (
    <Card
      className={`border-l-4 ${verdictCfg.borderColor} ${isConfirmed ? 'opacity-80' : ''}`}
      data-testid="line-item-review-card"
    >
      <CardContent className="pt-4 space-y-3">
        {/* 品目名・金額・判定バッジ */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium break-words">{item.description || '（品名なし）'}</p>
            {item.amount != null && (
              <p className="text-xs text-muted-foreground mt-0.5">
                ¥{item.amount.toLocaleString('ja-JP')}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <VerdictIcon className="size-4 text-muted-foreground" />
            <Badge variant={verdictCfg.badgeVariant}>{verdictCfg.label}</Badge>
            {isConfirmed && (
              <Badge variant="outline" className="text-xs">確定済み</Badge>
            )}
          </div>
        </div>

        {/* 信頼度バー */}
        <ConfidenceBar value={item.confidence} />

        {/* 判定根拠 */}
        {item.rationale && (
          <p className="text-xs text-muted-foreground">{item.rationale}</p>
        )}

        {/* ボタン補正UI（確定前のみ表示） */}
        {!isConfirmed && (
          <div className="flex flex-wrap gap-2 pt-1" data-testid="action-buttons">
            {pct >= 80 ? (
              // >= 0.80: [✅ 承認] [費用に変更] [保留]
              <>
                <Button
                  size="sm"
                  variant="default"
                  onClick={() => onAction(item.id, 'approved', item.verdict)}
                  data-testid="btn-approve"
                >
                  ✅ 承認
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onAction(item.id, 'changed_expense', 'EXPENSE_LIKE')}
                  data-testid="btn-change-expense"
                >
                  費用に変更
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onAction(item.id, 'pending', item.verdict)}
                  data-testid="btn-hold"
                >
                  保留
                </Button>
              </>
            ) : pct >= 50 ? (
              // 0.50-0.79: [固定資産] [費用] [手入力]
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onAction(item.id, 'changed_capital', 'CAPITAL_LIKE')}
                  className="text-blue-700 border-blue-300 hover:bg-blue-50"
                  data-testid="btn-capital"
                >
                  <Building2 className="size-3.5 mr-1" />
                  固定資産
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onAction(item.id, 'changed_expense', 'EXPENSE_LIKE')}
                  className="text-green-700 border-green-300 hover:bg-green-50"
                  data-testid="btn-expense"
                >
                  <CheckCircle2 className="size-3.5 mr-1" />
                  費用
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onAction(item.id, 'manual_edit', item.verdict)}
                  data-testid="btn-manual"
                >
                  <PenLine className="size-3.5 mr-1" />
                  手入力
                </Button>
              </>
            ) : (
              // < 0.50: [固定資産] [費用] [✏️ 手入力で補正]
              <>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onAction(item.id, 'changed_capital', 'CAPITAL_LIKE')}
                  className="text-blue-700 border-blue-300 hover:bg-blue-50"
                  data-testid="btn-capital"
                >
                  <Building2 className="size-3.5 mr-1" />
                  固定資産
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onAction(item.id, 'changed_expense', 'EXPENSE_LIKE')}
                  className="text-green-700 border-green-300 hover:bg-green-50"
                  data-testid="btn-expense"
                >
                  <CheckCircle2 className="size-3.5 mr-1" />
                  費用
                </Button>
                <Button
                  size="sm"
                  variant="default"
                  onClick={() => onAction(item.id, 'manual_edit', item.verdict)}
                  data-testid="btn-manual-edit"
                >
                  <PenLine className="size-3.5 mr-1" />
                  ✏️ 手入力で補正
                </Button>
              </>
            )}
          </div>
        )}

        {/* 確定後の表示 */}
        {isConfirmed && item.userAction !== 'pending' && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground pt-1">
            <span>
              {item.userAction === 'approved' && '✅ AI判定を承認'}
              {item.userAction === 'changed_capital' && '🏢 固定資産に変更'}
              {item.userAction === 'changed_expense' && '✔ 費用に変更'}
              {item.userAction === 'manual_edit' && '✏️ 手入力補正'}
            </span>
            <button
              type="button"
              className="underline underline-offset-2 hover:text-foreground transition-colors"
              onClick={() => onAction(item.id, 'pending', item.verdict)}
            >
              取消
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
