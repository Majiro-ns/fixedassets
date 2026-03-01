'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { Decision, HistoryEntry } from '@/types/classify';

// ─── 判定別バッジ設定（LineItemsTable.tsx と同じ方式） ─────────────────
const BADGE_CONFIG: Record<
  Decision,
  { label: string; variant: 'success' | 'default' | 'warning' }
> = {
  CAPITAL_LIKE: { label: '固定資産', variant: 'success' },
  EXPENSE_LIKE: { label: '費用',     variant: 'default' },
  GUIDANCE:     { label: '要確認',   variant: 'warning' },
};

function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, max) + '…';
}

// ─── CSV生成 ──────────────────────────────────────────────────────────
const generateCsv = (history: HistoryEntry[]): string => {
  const BOM = '\uFEFF'; // Excel UTF-8 BOM
  const header = '判定日時,摘要,判定結果,信頼度,金額\n';
  const rows = history.map((entry) => {
    const date = new Date(entry.timestamp).toLocaleString('ja-JP');
    const desc = entry.request.description.replace(/,/g, '，');
    const decision = entry.response.decision;
    const confidence = Math.round(entry.response.confidence * 100);
    const amount = entry.request.amount ?? '';
    return `${date},${desc},${decision},${confidence}%,${amount}`;
  }).join('\n');
  return BOM + header + rows;
};

// ─── HistoryPanel コンポーネント ──────────────────────────────────────
interface HistoryPanelProps {
  history: HistoryEntry[];
}

/**
 * 判定履歴を新しい順で一覧表示するコンポーネント。
 * - history が空の場合は null を返す（非表示）
 * - 1行: 時刻 + 摘要（25文字+…）+ 判定バッジ
 * - バッジカラー: CAPITAL_LIKE=success / EXPENSE_LIKE=default / GUIDANCE=warning
 * - ヘッダー右側に CSV ダウンロードボタン
 */
export function HistoryPanel({ history }: HistoryPanelProps) {
  if (history.length === 0) return null;

  const handleCsvDownload = () => {
    const csv = generateCsv(history);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `fixed-asset-history-${new Date().toISOString().slice(0, 10)}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">
            📋 判定履歴（{history.length}件）
          </CardTitle>
          <Button variant="outline" size="sm" onClick={handleCsvDownload}>
            📥 CSV
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {history.map((entry, i) => {
          const cfg = BADGE_CONFIG[entry.response.decision] ?? BADGE_CONFIG.GUIDANCE;
          const time = new Date(entry.timestamp).toLocaleString('ja-JP');
          const desc = truncate(entry.request.description, 25);
          return (
            <div
              key={i}
              className="flex items-center gap-3 rounded-md border p-3"
            >
              <span className="text-xs text-muted-foreground shrink-0 tabular-nums">
                {time}
              </span>
              <span className="text-sm flex-1 truncate text-foreground">
                {desc}
              </span>
              <Badge variant={cfg.variant} className="shrink-0">
                {cfg.label}
              </Badge>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
