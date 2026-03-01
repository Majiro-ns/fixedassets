'use client';

import type { GapItem } from '@/types';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';

interface Props {
  gaps: GapItem[];
}

const CHANGE_TYPE_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  追加必須: 'destructive',
  修正推奨: 'default',
  参考: 'secondary',
};

const CONFIDENCE_COLOR: Record<string, string> = {
  high: 'text-green-600',
  medium: 'text-amber-600',
  low: 'text-red-600',
  error: 'text-gray-400',
};

export function GapTable({ gaps }: Props) {
  if (gaps.length === 0) {
    return <p className="text-sm text-muted-foreground">ギャップは検出されませんでした</p>;
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-24">ID</TableHead>
            <TableHead>開示項目</TableHead>
            <TableHead className="w-24">変更種別</TableHead>
            <TableHead className="w-20">ギャップ</TableHead>
            <TableHead className="w-20">確信度</TableHead>
            <TableHead>根拠</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {gaps.map((gap) => (
            <TableRow key={gap.gap_id}>
              <TableCell className="font-mono text-xs">{gap.gap_id}</TableCell>
              <TableCell>
                <div className="text-sm">{gap.disclosure_item}</div>
                <div className="text-xs text-muted-foreground mt-0.5">{gap.section_heading}</div>
              </TableCell>
              <TableCell>
                <Badge variant={CHANGE_TYPE_VARIANT[gap.change_type] ?? 'outline'}>
                  {gap.change_type}
                </Badge>
              </TableCell>
              <TableCell>
                {gap.has_gap ? (
                  <Badge variant="destructive">あり</Badge>
                ) : (
                  <Badge variant="secondary">なし</Badge>
                )}
              </TableCell>
              <TableCell>
                <span className={`text-xs font-medium ${CONFIDENCE_COLOR[gap.confidence] ?? ''}`}>
                  {gap.confidence}
                </span>
              </TableCell>
              <TableCell className="text-xs max-w-48 truncate">{gap.evidence_hint}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
