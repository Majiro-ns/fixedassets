'use client';

import { Building2, CheckCircle2, HelpCircle, Download, CheckCheck } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { LineItemReviewCard } from '@/components/LineItemReviewCard';
import type { Decision } from '@/types/classify';
import type { LineItemWithAction, UserAction, CsvRow } from '@/types/pdf_review';

// ─── Props ────────────────────────────────────────────────────────────

interface PDFReviewSectionProps {
  items: LineItemWithAction[];
  onAction: (id: string, action: UserAction, finalVerdict: Decision) => void;
  onApproveAll: () => void;
}

// ─── 金額フォーマット ──────────────────────────────────────────────────

function fmt(amount: number | undefined): string {
  if (amount == null) return '—';
  return `¥${amount.toLocaleString('ja-JP')}`;
}

// ─── 集計計算 ──────────────────────────────────────────────────────────

function calcSummary(items: LineItemWithAction[]) {
  let capitalTotal = 0;
  let expenseTotal = 0;
  let pendingCount = 0;

  for (const item of items) {
    if (item.userAction === 'pending') {
      pendingCount++;
    } else {
      if (item.finalVerdict === 'CAPITAL_LIKE') {
        capitalTotal += item.amount ?? 0;
      } else if (item.finalVerdict === 'EXPENSE_LIKE') {
        expenseTotal += item.amount ?? 0;
      }
    }
  }

  return { capitalTotal, expenseTotal, pendingCount };
}

// ─── CSV エクスポート ──────────────────────────────────────────────────

const VERDICT_LABEL: Record<Decision, string> = {
  CAPITAL_LIKE: '固定資産',
  EXPENSE_LIKE: '費用',
  GUIDANCE: '要確認',
};

const ACTION_LABEL: Record<UserAction, string> = {
  approved: 'AI承認',
  changed_capital: '固定資産に変更',
  changed_expense: '費用に変更',
  manual_edit: '手入力補正',
  pending: '未確定',
};

function exportCsv(items: LineItemWithAction[]) {
  const rows: CsvRow[] = items.map((item) => ({
    品目名: item.description,
    金額: item.amount != null ? String(item.amount) : '',
    AI判定: VERDICT_LABEL[item.verdict],
    確定判定: VERDICT_LABEL[item.finalVerdict],
    操作: ACTION_LABEL[item.userAction],
  }));

  const header = Object.keys(rows[0] ?? {}).join(',');
  const body = rows
    .map((r) =>
      Object.values(r)
        .map((v) => `"${String(v).replace(/"/g, '""')}"`)
        .join(',')
    )
    .join('\n');
  const csv = `${header}\n${body}`;
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `fixed_asset_review_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── PDFReviewSection ─────────────────────────────────────────────────

export function PDFReviewSection({ items, onAction, onApproveAll }: PDFReviewSectionProps) {
  if (items.length === 0) return null;

  const { capitalTotal, expenseTotal, pendingCount } = calcSummary(items);
  const highConfidencePending = items.filter(
    (item) => item.userAction === 'pending' && item.confidence >= 0.8
  );

  return (
    <div className="space-y-6" data-testid="pdf-review-section">
      {/* 集計サマリー */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">判定サマリー</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4 text-center" data-testid="summary-grid">
            <div className="rounded-lg bg-blue-50 p-3 space-y-1">
              <Building2 className="size-5 mx-auto text-blue-600" />
              <p className="text-xs text-muted-foreground">固定資産合計</p>
              <p className="text-base font-bold text-blue-700" data-testid="capital-total">
                {fmt(capitalTotal)}
              </p>
            </div>
            <div className="rounded-lg bg-green-50 p-3 space-y-1">
              <CheckCircle2 className="size-5 mx-auto text-green-600" />
              <p className="text-xs text-muted-foreground">費用合計</p>
              <p className="text-base font-bold text-green-700" data-testid="expense-total">
                {fmt(expenseTotal)}
              </p>
            </div>
            <div className="rounded-lg bg-yellow-50 p-3 space-y-1">
              <HelpCircle className="size-5 mx-auto text-yellow-600" />
              <p className="text-xs text-muted-foreground">未確定件数</p>
              <p className="text-base font-bold text-yellow-700" data-testid="pending-count">
                {pendingCount}件
              </p>
            </div>
          </div>

          {/* アクションボタン */}
          <div className="flex flex-wrap gap-2 mt-4">
            <Button
              variant="default"
              size="sm"
              onClick={onApproveAll}
              disabled={highConfidencePending.length === 0}
              data-testid="btn-approve-all"
            >
              <CheckCheck className="size-4 mr-1.5" />
              全て承認（信頼度80%以上・{highConfidencePending.length}件）
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => exportCsv(items)}
              data-testid="btn-csv-export"
            >
              <Download className="size-4 mr-1.5" />
              CSVエクスポート
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 明細カード一覧 */}
      <div className="space-y-3">
        <p className="text-sm font-medium text-muted-foreground">
          明細一覧（{items.length}件）
        </p>
        {items.map((item) => (
          <LineItemReviewCard
            key={item.id}
            item={item}
            onAction={onAction}
          />
        ))}
      </div>
    </div>
  );
}
