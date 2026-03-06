'use client';

import { useState, useMemo } from 'react';
import { ChevronUp, ChevronDown, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import { MainLayout } from '@/components/layout/MainLayout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { EventBadge } from '@/components/calendar/EventBadge';
import { formatDateJa, toISODate } from '@/lib/calendarUtils';
import type { CalendarEvent, CalendarEventType, CalendarEventStatus } from '@/types/calendar';

// ─── モックデータ ──────────────────────────────────────────────────
const MOCK_EVENTS: CalendarEvent[] = [
  { id: 'ev-001', title: '月次減価償却計上', date: (() => { const d = new Date(); d.setDate(d.getDate() + 3); return toISODate(d); })(), type: 'depreciation', status: 'pending', recurrence: 'monthly' },
  { id: 'ev-002', title: '償却資産税申告', date: (() => { const d = new Date(); d.setDate(d.getDate() + 7); return toISODate(d); })(), type: 'tax_filing', status: 'pending', recurrence: 'yearly' },
  { id: 'ev-003', title: '期末棚卸し', date: (() => { const d = new Date(); d.setDate(d.getDate() + 14); return toISODate(d); })(), type: 'inventory', status: 'pending', recurrence: 'yearly' },
  { id: 'ev-004', title: '第3四半期決算', date: (() => { const d = new Date(); d.setDate(d.getDate() + 21); return toISODate(d); })(), type: 'closing', status: 'pending', recurrence: 'yearly' },
  { id: 'ev-005', title: '1月固定資産棚卸', date: (() => { const d = new Date(); d.setDate(d.getDate() - 10); return toISODate(d); })(), type: 'inventory', status: 'done', recurrence: 'yearly' },
  { id: 'ev-006', title: '保険料更新リマインド', date: (() => { const d = new Date(); d.setDate(d.getDate() - 5); return toISODate(d); })(), type: 'custom', status: 'overdue', recurrence: 'yearly' },
];

type SortKey = 'date' | 'title' | 'type' | 'status';
type SortDir = 'asc' | 'desc';

const EVENT_TYPE_OPTIONS: { value: CalendarEventType | 'all'; label: string }[] = [
  { value: 'all', label: '全種別' },
  { value: 'depreciation', label: '減価償却' },
  { value: 'tax_filing', label: '税申告' },
  { value: 'inventory', label: '棚卸し' },
  { value: 'closing', label: '決算' },
  { value: 'custom', label: 'カスタム' },
];

const STATUS_OPTIONS: { value: CalendarEventStatus | 'all'; label: string }[] = [
  { value: 'all', label: '全ステータス' },
  { value: 'pending', label: '未処理' },
  { value: 'done', label: '完了' },
  { value: 'overdue', label: '期限超過' },
];

const STATUS_LABEL: Record<CalendarEventStatus, string> = {
  pending: '未処理',
  done: '完了',
  overdue: '期限超過',
};

const STATUS_COLOR: Record<CalendarEventStatus, string> = {
  pending: 'text-muted-foreground',
  done: 'text-green-600',
  overdue: 'text-red-600 font-medium',
};

export default function CalendarEventsPage() {
  const [filterType, setFilterType] = useState<CalendarEventType | 'all'>('all');
  const [filterStatus, setFilterStatus] = useState<CalendarEventStatus | 'all'>('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const filtered = useMemo(() => {
    let result = [...MOCK_EVENTS];

    if (filterType !== 'all') result = result.filter((e) => e.type === filterType);
    if (filterStatus !== 'all') result = result.filter((e) => e.status === filterStatus);
    if (dateFrom) result = result.filter((e) => e.date >= dateFrom);
    if (dateTo) result = result.filter((e) => e.date <= dateTo);

    result.sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'date') cmp = a.date.localeCompare(b.date);
      else if (sortKey === 'title') cmp = a.title.localeCompare(b.title, 'ja');
      else if (sortKey === 'type') cmp = a.type.localeCompare(b.type);
      else if (sortKey === 'status') cmp = a.status.localeCompare(b.status);
      return sortDir === 'asc' ? cmp : -cmp;
    });

    return result;
  }, [filterType, filterStatus, dateFrom, dateTo, sortKey, sortDir]);

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) return null;
    return sortDir === 'asc' ? (
      <ChevronUp className="size-3 inline ml-0.5" />
    ) : (
      <ChevronDown className="size-3 inline ml-0.5" />
    );
  };

  return (
    <MainLayout>
      <div className="max-w-5xl mx-auto space-y-6">
        {/* ── ヘッダー ────────────────────────────────────────────── */}
        <div className="flex items-center gap-3">
          <Link href="/calendar">
            <Button variant="outline" size="sm" aria-label="カレンダーに戻る">
              <ArrowLeft className="size-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-2xl font-bold">イベント一覧</h1>
            <p className="text-sm text-muted-foreground mt-0.5">全{MOCK_EVENTS.length}件のイベント</p>
          </div>
        </div>

        {/* ── フィルター ───────────────────────────────────────────── */}
        <Card>
          <CardContent className="pt-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {/* 種別フィルター */}
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">種別</label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value as CalendarEventType | 'all')}
                  data-testid="filter-type"
                >
                  {EVENT_TYPE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>

              {/* ステータスフィルター */}
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">ステータス</label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value as CalendarEventStatus | 'all')}
                  data-testid="filter-status"
                >
                  {STATUS_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>

              {/* 日付from */}
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">開始日</label>
                <Input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  data-testid="filter-date-from"
                />
              </div>

              {/* 日付to */}
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">終了日</label>
                <Input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  data-testid="filter-date-to"
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* ── テーブル ─────────────────────────────────────────────── */}
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="events-table">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th
                      className="text-left px-4 py-3 font-medium cursor-pointer hover:text-foreground"
                      onClick={() => handleSort('date')}
                      data-testid="col-date"
                    >
                      日付 <SortIcon col="date" />
                    </th>
                    <th
                      className="text-left px-4 py-3 font-medium cursor-pointer hover:text-foreground"
                      onClick={() => handleSort('title')}
                      data-testid="col-title"
                    >
                      タイトル <SortIcon col="title" />
                    </th>
                    <th
                      className="text-left px-4 py-3 font-medium cursor-pointer hover:text-foreground"
                      onClick={() => handleSort('type')}
                      data-testid="col-type"
                    >
                      種別 <SortIcon col="type" />
                    </th>
                    <th
                      className="text-left px-4 py-3 font-medium cursor-pointer hover:text-foreground"
                      onClick={() => handleSort('status')}
                      data-testid="col-status"
                    >
                      ステータス <SortIcon col="status" />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                        条件に一致するイベントがありません
                      </td>
                    </tr>
                  ) : (
                    filtered.map((ev) => (
                      <tr
                        key={ev.id}
                        className="border-b hover:bg-muted/30 transition-colors"
                        data-testid={`event-row-${ev.id}`}
                      >
                        <td className="px-4 py-3 whitespace-nowrap text-muted-foreground">
                          {formatDateJa(ev.date)}
                        </td>
                        <td className="px-4 py-3">
                          <span className={ev.status === 'done' ? 'line-through text-muted-foreground' : ''}>
                            {ev.title}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <EventBadge type={ev.type} />
                        </td>
                        <td className={`px-4 py-3 ${STATUS_COLOR[ev.status]}`}>
                          {STATUS_LABEL[ev.status]}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <div className="px-4 py-3 border-t text-xs text-muted-foreground">
              {filtered.length}件表示 / 全{MOCK_EVENTS.length}件
            </div>
          </CardContent>
        </Card>
      </div>
    </MainLayout>
  );
}
