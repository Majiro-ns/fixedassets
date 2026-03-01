'use client';

import type { GapSummary } from '@/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';

interface Props {
  summary: GapSummary;
}

const CHANGE_TYPE_CONFIG: Record<
  string,
  { label: string; color: string; icon: React.ElementType }
> = {
  追加必須: {
    label: '追加必須',
    color: 'bg-red-100 text-red-800 border-red-200',
    icon: AlertTriangle,
  },
  修正推奨: {
    label: '修正推奨',
    color: 'bg-amber-100 text-amber-800 border-amber-200',
    icon: Info,
  },
  参考: { label: '参考', color: 'bg-blue-100 text-blue-800 border-blue-200', icon: CheckCircle2 },
};

export function GapSummaryCard({ summary }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>ギャップサマリ</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
          <div className="rounded-lg border p-3 text-center">
            <div className="text-2xl font-bold">{summary.total_gaps}</div>
            <div className="text-xs text-muted-foreground">総ギャップ数</div>
          </div>
          {Object.entries(summary.by_change_type).map(([type, count]) => {
            const config = CHANGE_TYPE_CONFIG[type] || CHANGE_TYPE_CONFIG['参考'];
            const Icon = config.icon;
            return (
              <div key={type} className={`rounded-lg border p-3 text-center ${config.color}`}>
                <div className="flex items-center justify-center gap-1">
                  <Icon className="size-4" />
                  <span className="text-2xl font-bold">{count}</span>
                </div>
                <div className="text-xs">{config.label}</div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
