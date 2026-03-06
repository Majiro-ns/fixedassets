'use client';

import { useState } from 'react';
import { Plus, X } from 'lucide-react';
import Link from 'next/link';
import { MainLayout } from '@/components/layout/MainLayout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { CalendarGrid } from '@/components/calendar/CalendarGrid';
import { EventBadge } from '@/components/calendar/EventBadge';
import { EventForm } from '@/components/calendar/EventForm';
import { formatDateJa, toISODate, getEventTypeConfig } from '@/lib/calendarUtils';
import type { CalendarEvent, CalendarEventFormValues } from '@/types/calendar';

// ─── モックデータ（API完成前の先行UI実装） ───────────────────────────
const MOCK_EVENTS: CalendarEvent[] = [
  {
    id: 'ev-001',
    title: '月次減価償却計上',
    date: (() => { const d = new Date(); d.setDate(d.getDate() + 3); return toISODate(d); })(),
    type: 'depreciation',
    status: 'pending',
    recurrence: 'monthly',
    description: '固定資産台帳との照合必須',
  },
  {
    id: 'ev-002',
    title: '償却資産税申告',
    date: (() => { const d = new Date(); d.setDate(d.getDate() + 7); return toISODate(d); })(),
    type: 'tax_filing',
    status: 'pending',
    recurrence: 'yearly',
  },
  {
    id: 'ev-003',
    title: '期末棚卸し',
    date: (() => { const d = new Date(); d.setDate(d.getDate() + 14); return toISODate(d); })(),
    type: 'inventory',
    status: 'pending',
    recurrence: 'yearly',
  },
  {
    id: 'ev-004',
    title: '第3四半期決算',
    date: (() => { const d = new Date(); d.setDate(d.getDate() + 21); return toISODate(d); })(),
    type: 'closing',
    status: 'pending',
    recurrence: 'yearly',
  },
];

let _idCounter = 100;

export default function CalendarPage() {
  const [events, setEvents] = useState<CalendarEvent[]>(MOCK_EVENTS);
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [selectedDayEvents, setSelectedDayEvents] = useState<CalendarEvent[]>([]);
  const [showAddForm, setShowAddForm] = useState(false);

  const handleDateClick = (date: Date, dayEvents: CalendarEvent[]) => {
    setSelectedDate(date);
    setSelectedDayEvents(dayEvents);
    setShowAddForm(false);
  };

  const handleAddEvent = (values: CalendarEventFormValues) => {
    const newEvent: CalendarEvent = {
      id: `ev-${++_idCounter}`,
      title: values.title,
      date: values.date,
      type: values.type,
      status: 'pending',
      description: values.description,
      recurrence: values.recurrence ?? 'none',
    };
    setEvents((prev) => [...prev, newEvent]);
    setShowAddForm(false);
  };

  const handleDeleteEvent = (id: string) => {
    setEvents((prev) => prev.filter((e) => e.id !== id));
    setSelectedDayEvents((prev) => prev.filter((e) => e.id !== id));
  };

  const handleToggleDone = (id: string) => {
    setEvents((prev) =>
      prev.map((e) => (e.id === id ? { ...e, status: e.status === 'done' ? 'pending' : 'done' } : e))
    );
    setSelectedDayEvents((prev) =>
      prev.map((e) => (e.id === id ? { ...e, status: e.status === 'done' ? 'pending' : 'done' } : e))
    );
  };

  return (
    <MainLayout>
      <div className="max-w-5xl mx-auto space-y-6">
        {/* ── ヘッダー ────────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">経理カレンダー</h1>
            <p className="text-sm text-muted-foreground mt-1">
              減価償却・税申告・決算などの経理イベントを管理します
            </p>
          </div>
          <div className="flex gap-2">
            <Link href="/calendar/events">
              <Button variant="outline" size="sm">
                イベント一覧
              </Button>
            </Link>
            <Button size="sm" onClick={() => setShowAddForm(true)} data-testid="btn-add-event">
              <Plus className="size-4" />
              イベント追加
            </Button>
          </div>
        </div>

        {/* ── イベント追加フォーム ─────────────────────────────────── */}
        {showAddForm && (
          <Card data-testid="add-event-card">
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-base">
                イベント追加
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowAddForm(false)}
                  aria-label="閉じる"
                >
                  <X className="size-4" />
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <EventForm
                onSubmit={handleAddEvent}
                onCancel={() => setShowAddForm(false)}
              />
            </CardContent>
          </Card>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* ── カレンダーグリッド ───────────────────────────────── */}
          <div className="lg:col-span-2">
            <CalendarGrid events={events} onDateClick={handleDateClick} />
          </div>

          {/* ── サイドパネル ─────────────────────────────────────── */}
          <div className="space-y-4">
            {/* 選択日のイベント */}
            {selectedDate && (
              <Card data-testid="day-events-panel">
                <CardHeader>
                  <CardTitle className="text-base">
                    {formatDateJa(
                      `${selectedDate.getFullYear()}-${String(selectedDate.getMonth() + 1).padStart(2, '0')}-${String(selectedDate.getDate()).padStart(2, '0')}`
                    )}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {selectedDayEvents.length === 0 ? (
                    <p className="text-sm text-muted-foreground">この日のイベントはありません</p>
                  ) : (
                    <ul className="space-y-2">
                      {selectedDayEvents.map((ev) => (
                        <li
                          key={ev.id}
                          className="flex items-start gap-2 group"
                          data-testid={`day-event-${ev.id}`}
                        >
                          <EventBadge type={ev.type} showDotOnly className="mt-1.5 shrink-0" />
                          <div className="flex-1 min-w-0">
                            <p
                              className={`text-sm font-medium ${
                                ev.status === 'done' ? 'line-through text-muted-foreground' : ''
                              }`}
                            >
                              {ev.title}
                            </p>
                            <EventBadge type={ev.type} className="mt-0.5" />
                          </div>
                          <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              className="text-xs text-muted-foreground hover:text-foreground"
                              onClick={() => handleToggleDone(ev.id)}
                              aria-label="完了切替"
                              data-testid={`btn-toggle-done-${ev.id}`}
                            >
                              {ev.status === 'done' ? '戻す' : '完了'}
                            </button>
                            <button
                              className="text-xs text-destructive hover:text-destructive/80"
                              onClick={() => handleDeleteEvent(ev.id)}
                              aria-label="削除"
                              data-testid={`btn-delete-event-${ev.id}`}
                            >
                              削除
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            )}

            {/* 凡例 */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">イベント種別</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {(
                    [
                      'depreciation',
                      'tax_filing',
                      'inventory',
                      'closing',
                      'custom',
                    ] as const
                  ).map((type) => (
                    <li key={type} className="flex items-center gap-2">
                      <EventBadge type={type} showDotOnly />
                      <span className="text-sm text-muted-foreground">
                        {getEventTypeConfig(type).label}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
