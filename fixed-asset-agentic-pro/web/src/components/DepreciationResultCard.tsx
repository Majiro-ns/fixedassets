'use client';

import { ArrowRight } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { DepreciationResponse, SpecialTreatment } from '@/types/depreciation';

// ─── ユーティリティ ────────────────────────────────────────────────────
function formatJPY(amount: number): string {
  return `¥${amount.toLocaleString('ja-JP')}`;
}

// ─── 特例区分バッジ設定 ────────────────────────────────────────────────
function getSpecialBadge(type: string): {
  variant: 'default' | 'success' | 'warning' | 'secondary' | 'outline';
  label: string;
} {
  if (type.includes('少額') && type.includes('中小')) {
    return { variant: 'warning', label: '中小企業特例' };
  }
  if (type.includes('一括')) {
    return { variant: 'secondary', label: '一括償却資産' };
  }
  if (type.includes('少額')) {
    return { variant: 'success', label: '少額資産' };
  }
  return { variant: 'outline', label: '通常償却' };
}

// ─── 特例区分パネル ────────────────────────────────────────────────────
function SpecialTreatmentPanel({ st }: { st: SpecialTreatment }) {
  const badge = getSpecialBadge(st.type);
  return (
    <div className="rounded-md border-l-4 border-yellow-400 bg-yellow-50 p-3 space-y-1.5">
      <div className="flex items-center gap-2">
        <Badge variant={badge.variant}>{badge.label}</Badge>
        <span className="text-sm font-semibold">{st.type}</span>
      </div>
      <p className="text-sm text-yellow-800">{st.treatment}</p>
      <p className="text-xs text-muted-foreground">根拠: {st.basis}</p>
      {st.annual_amount != null && (
        <p className="text-xs text-muted-foreground">
          年間均等額: {formatJPY(st.annual_amount)}
        </p>
      )}
      {st.note && (
        <p className="text-xs text-yellow-700">⚠ {st.note}</p>
      )}
    </div>
  );
}

// ─── 年次スケジュールテーブル ─────────────────────────────────────────
function ScheduleTable({ schedule, showAssetTax }: {
  schedule: DepreciationResponse['annual_schedule'];
  showAssetTax: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="py-2 pr-4 text-left font-medium">年度</th>
            <th className="py-2 pr-4 text-right font-medium">当期償却額</th>
            <th className="py-2 pr-4 text-right font-medium">期末帳簿価額</th>
            {showAssetTax && (
              <>
                <th className="py-2 pr-4 text-right font-medium">償却資産税評価額</th>
                <th className="py-2 text-right font-medium">償却資産税額</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {schedule.map((row) => (
            <tr key={row.year} className="border-b last:border-0 hover:bg-muted/30">
              <td className="py-2 pr-4 font-medium">{row.year}年目</td>
              <td className="py-2 pr-4 text-right tabular-nums">{formatJPY(row.depreciation)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{formatJPY(row.book_value_end)}</td>
              {showAssetTax && (
                <>
                  <td className="py-2 pr-4 text-right tabular-nums">
                    {row.asset_tax_value != null ? formatJPY(row.asset_tax_value) : '—'}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {row.asset_tax_amount != null ? formatJPY(row.asset_tax_amount) : '—'}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Props ─────────────────────────────────────────────────────────────
interface DepreciationResultCardProps {
  result: DepreciationResponse;
}

// ─── DepreciationResultCard ────────────────────────────────────────────
export function DepreciationResultCard({ result }: DepreciationResultCardProps) {
  const showAssetTax = result.annual_schedule.some(
    (r) => r.asset_tax_value != null || r.asset_tax_amount != null,
  );

  return (
    <Card className="border-l-4 border-blue-400">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <CardTitle className="text-base font-semibold">📊 償却スケジュール</CardTitle>
          <Badge variant="default">計算完了</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* 特例区分 */}
        {result.special_treatment && (
          <SpecialTreatmentPanel st={result.special_treatment} />
        )}

        {/* 総償却額サマリ */}
        <div className="grid grid-cols-2 gap-4 rounded-md bg-blue-50 p-3">
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">📋 総償却額</p>
            <p className="text-xl font-bold text-blue-700">
              {formatJPY(result.total_depreciation)}
            </p>
          </div>
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">⚖️ 根拠法令</p>
            <p className="text-sm font-medium text-blue-700 break-words">
              {result.tax_basis}
            </p>
          </div>
        </div>

        {/* 年次スケジュールテーブル */}
        {result.annual_schedule.length > 0 && (
          <div>
            <p className="text-sm font-medium mb-2">年次スケジュール</p>
            <ScheduleTable schedule={result.annual_schedule} showAssetTax={showAssetTax} />
          </div>
        )}

        {/* 根拠 */}
        <div>
          <div className="flex items-start gap-2 text-sm text-muted-foreground">
            <ArrowRight className="size-3.5 mt-0.5 shrink-0 text-primary" />
            <span>備忘価額: 耐用年数最終年度は帳簿価額−1円（法人税法施行令§49）</span>
          </div>
          {showAssetTax && (
            <div className="flex items-start gap-2 text-sm text-muted-foreground mt-1">
              <ArrowRight className="size-3.5 mt-0.5 shrink-0 text-primary" />
              <span>償却資産税: 標準税率1.4%・免税点150万円未満（地方税法§351）</span>
            </div>
          )}
        </div>

        {/* 免責 */}
        <p className="text-xs text-muted-foreground border-t pt-3">
          この計算は参考値です。実際の申告・税務処理は税理士にご確認ください。
        </p>
      </CardContent>
    </Card>
  );
}
