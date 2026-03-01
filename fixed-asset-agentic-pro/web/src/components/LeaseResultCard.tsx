'use client';

import { ArrowRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { LeaseClassifyResponse, LeaseType } from '@/types/classify_lease';

// ─── 表示設定型 ─────────────────────────────────────────────────────────
interface DisplayConfig {
  badgeLabel: string;
  badgeVariant: 'default' | 'destructive' | 'success' | 'warning' | 'secondary' | 'outline';
  borderClass: string;
  bgClass: string;
  heading: string;
}

// ─── LeaseType 基本設定 ────────────────────────────────────────────────
const LEASE_TYPE_CONFIG: Record<LeaseType, DisplayConfig> = {
  NOT_A_LEASE: {
    badgeLabel: 'リースなし',
    badgeVariant: 'destructive',
    borderClass: 'border-l-4 border-red-400',
    bgClass: 'bg-red-50',
    heading: '🚫 リース識別なし（サービス契約）',
  },
  EXEMPT_SHORT_TERM: {
    badgeLabel: '短期免除',
    badgeVariant: 'success',
    borderClass: 'border-l-4 border-green-400',
    bgClass: 'bg-green-50',
    heading: '✅ 短期リース免除（IFRS 16 §B34）',
  },
  EXEMPT_LOW_VALUE: {
    badgeLabel: '少額免除',
    badgeVariant: 'success',
    borderClass: 'border-l-4 border-green-400',
    bgClass: 'bg-green-50',
    heading: '✅ 少額資産リース免除（IFRS 16 BC100）',
  },
  QUALIFYING_LEASE: {
    badgeLabel: 'ROU資産計上',
    badgeVariant: 'default',
    borderClass: 'border-l-4 border-blue-400',
    bgClass: 'bg-blue-50',
    heading: '🏢 認識対象リース（ROU資産・リース負債）',
  },
};

// QUALIFYING_LEASE + GUIDANCE 用上書き設定（IBR未入力で計算不可の場合）
const GUIDANCE_OVERRIDE: Partial<DisplayConfig> = {
  badgeLabel: 'IBR入力要',
  badgeVariant: 'warning',
  borderClass: 'border-l-4 border-yellow-400',
  bgClass: 'bg-yellow-50',
  heading: '❓ 追加情報が必要（IBR未入力）',
};

// ─── ユーティリティ ────────────────────────────────────────────────────
function formatJPY(amount: number): string {
  return `¥${amount.toLocaleString('ja-JP')}`;
}

// ─── 信頼度バー ─────────────────────────────────────────────────────────
function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-400';
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>信頼度</span>
        <span className="font-medium">{pct}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-secondary overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ─── Props ─────────────────────────────────────────────────────────────
interface LeaseResultCardProps {
  result: LeaseClassifyResponse;
}

// ─── LeaseResultCard ───────────────────────────────────────────────────
export function LeaseResultCard({ result }: LeaseResultCardProps) {
  const baseConfig =
    LEASE_TYPE_CONFIG[result.lease_type] ?? LEASE_TYPE_CONFIG.NOT_A_LEASE;

  // QUALIFYING_LEASE + GUIDANCE → IBR未入力で計算できない状態
  const cfg =
    result.lease_type === 'QUALIFYING_LEASE' && result.decision === 'GUIDANCE'
      ? { ...baseConfig, ...GUIDANCE_OVERRIDE }
      : baseConfig;

  const isQualifyingCapital =
    result.lease_type === 'QUALIFYING_LEASE' && result.decision === 'CAPITAL_LIKE';

  return (
    <Card className={cfg.borderClass}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <CardTitle className="text-base font-semibold">{cfg.heading}</CardTitle>
          <Badge variant={cfg.badgeVariant}>{cfg.badgeLabel}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* ROU資産・リース負債（QUALIFYING_LEASE + CAPITAL_LIKE のみ表示）*/}
        {isQualifyingCapital && (result.lease_liability != null || result.rou_asset != null) && (
          <div className={`grid grid-cols-2 gap-4 rounded-md p-3 ${cfg.bgClass}`}>
            {result.lease_liability != null && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">📋 初期リース負債</p>
                <p className="text-xl font-bold text-blue-700">
                  {formatJPY(result.lease_liability)}
                </p>
              </div>
            )}
            {result.rou_asset != null && (
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground">🏢 ROU資産（初期）</p>
                <p className="text-xl font-bold text-blue-700">
                  {formatJPY(result.rou_asset)}
                </p>
              </div>
            )}
          </div>
        )}

        {/* 免除種別の追加情報 */}
        {result.lease_type === 'EXEMPT_SHORT_TERM' && (
          <div className={`rounded-md p-3 text-sm ${cfg.bgClass}`}>
            <p className="text-green-800">
              リース期間が12ヶ月以内のため短期リース免除が適用されます。
              リース料をリース期間にわたって定額で費用計上してください（IFRS 16 §B34）。
            </p>
          </div>
        )}
        {result.lease_type === 'EXEMPT_LOW_VALUE' && (
          <div className={`rounded-md p-3 text-sm ${cfg.bgClass}`}>
            <p className="text-green-800">
              原資産の新品時価値がUSD 5,000以下のため少額資産リース免除が適用されます。
              個別資産ベースで判定しており、リース料を費用計上してください（IFRS 16 BC100）。
            </p>
          </div>
        )}

        {/* missing_fields（GUIDANCE / IBR未入力時） */}
        {result.missing_fields.length > 0 && (
          <div className="rounded-md bg-yellow-50 border border-yellow-200 p-3">
            <p className="text-sm font-medium text-yellow-800 mb-1.5">
              計算に必要な追加情報:
            </p>
            <ul className="space-y-0.5">
              {result.missing_fields.map((f, i) => (
                <li key={i} className="text-xs text-yellow-700">・{f}</li>
              ))}
            </ul>
          </div>
        )}

        {/* 判定根拠 */}
        {result.reasons.length > 0 && (
          <div>
            <p className="text-sm font-medium mb-2">判定根拠</p>
            <ul className="space-y-1.5">
              {result.reasons.map((r, i) => (
                <li
                  key={i}
                  className="text-sm text-muted-foreground flex items-start gap-2"
                >
                  <ArrowRight className="size-3.5 mt-0.5 shrink-0 text-primary" />
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* 信頼度 */}
        <ConfidenceBar value={result.confidence} />

        {/* 免責 */}
        <p className="text-xs text-muted-foreground border-t pt-3">{result.disclaimer}</p>
      </CardContent>
    </Card>
  );
}
