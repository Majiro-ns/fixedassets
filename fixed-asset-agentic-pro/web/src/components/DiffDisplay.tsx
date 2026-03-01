'use client';

import { ArrowDown, FileText } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { ClassifyResponse, Decision } from '@/types/classify';

// ─── 判定ラベル定義 ───────────────────────────────────────────────────
const DECISION_LABELS: Record<Decision, { label: string; badgeVariant: 'default' | 'success' | 'warning' }> = {
  CAPITAL_LIKE: { label: '✅ 固定資産（資産計上）', badgeVariant: 'default' },
  EXPENSE_LIKE: { label: '💰 費用（損金算入）', badgeVariant: 'success' },
  GUIDANCE: { label: '⚠️ 確認が必要です', badgeVariant: 'warning' },
};

// ─── 判断理由の差分表示 ───────────────────────────────────────────────
function ReasonsDiff({ prevReasons, nextReasons }: { prevReasons: string[]; nextReasons: string[] }) {
  if (nextReasons.length === 0) return null;
  const prevSet = new Set(prevReasons);
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold text-purple-700">判断理由の変化</p>
      {nextReasons.map((r, i) => {
        const isNew = !prevSet.has(r);
        return (
          <p
            key={i}
            className={`text-xs ${isNew ? 'text-green-700' : 'text-muted-foreground'}`}
          >
            {isNew ? '＋ ' : '　 '}
            {r}
          </p>
        );
      })}
    </div>
  );
}

// ─── Props ────────────────────────────────────────────────────────────
interface DiffDisplayProps {
  prevResult: ClassifyResponse;
  nextResult: ClassifyResponse;
}

// ─── DiffDisplay メイン ───────────────────────────────────────────────
export function DiffDisplay({ prevResult, nextResult }: DiffDisplayProps) {
  if (prevResult.decision === nextResult.decision) return null;

  const prev = DECISION_LABELS[prevResult.decision] ?? DECISION_LABELS.GUIDANCE;
  const next = DECISION_LABELS[nextResult.decision] ?? DECISION_LABELS.GUIDANCE;
  const prevPct = Math.round(prevResult.confidence * 100);
  const nextPct = Math.round(nextResult.confidence * 100);

  return (
    <Card className="border-purple-400 bg-purple-50 dark:bg-purple-950/20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-purple-800 dark:text-purple-300">
          🔄 判定が変わりました
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Before / After */}
        <div className="space-y-2">
          {/* Before */}
          <div className="flex items-center gap-3 rounded-lg bg-white/70 border border-purple-200 px-4 py-3">
            <span className="text-xs text-muted-foreground shrink-0">変更前</span>
            <Badge variant={prev.badgeVariant} className="shrink-0">{prev.label}</Badge>
            <span className="ml-auto text-xs text-muted-foreground">{prevPct}%</span>
          </div>

          {/* Arrow */}
          <div className="flex justify-center text-purple-400">
            <ArrowDown className="size-5" />
          </div>

          {/* After */}
          <div className="flex items-center gap-3 rounded-lg bg-purple-100 border-2 border-purple-400 px-4 py-3">
            <span className="text-xs text-muted-foreground shrink-0">変更後</span>
            <Badge variant={next.badgeVariant} className="shrink-0">{next.label}</Badge>
            <span className="ml-auto text-xs font-semibold text-purple-700">{nextPct}%</span>
          </div>
        </div>

        {/* 理由差分 */}
        {(prevResult.reasons.length > 0 || nextResult.reasons.length > 0) && (
          <div className="rounded-lg border border-purple-200 bg-white/60 p-3">
            <ReasonsDiff prevReasons={prevResult.reasons} nextReasons={nextResult.reasons} />
          </div>
        )}

        {/* 監査用メモ */}
        <div className="flex items-start gap-2 rounded-lg bg-purple-100 px-3 py-2 text-xs text-purple-700">
          <FileText className="size-3.5 mt-0.5 shrink-0" />
          <span>この差分は監査時の説明資料として利用できます</span>
        </div>
      </CardContent>
    </Card>
  );
}
