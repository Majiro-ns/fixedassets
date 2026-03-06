'use client';

import { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { EventBadge } from './EventBadge';
import {
  buildCalendarDays,
  formatMonthJa,
  getEventsForDate,
  isToday,
} from '@/lib/calendarUtils';
import { cn } from '@/lib/utils';
import type { CalendarEvent } from '@/types/calendar';

interface CalendarGridProps {
  events: CalendarEvent[];
  onDateClick?: (date: Date, events: CalendarEvent[]) => void;
}

const DOW_LABELS = ['日', '月', '火', '水', '木', '金', '土'];

export function CalendarGrid({ events, onDateClick }: CalendarGridProps) {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());

  const days = buildCalendarDays(year, month);

  const prevMonth = () => {
    if (month === 0) {
      setYear((y) => y - 1);
      setMonth(11);
    } else {
      setMonth((m) => m - 1);
    }
  };

  const nextMonth = () => {
    if (month === 11) {
      setYear((y) => y + 1);
      setMonth(0);
    } else {
      setMonth((m) => m + 1);
    }
  };

  return (
    <div className="rounded-xl border bg-card shadow-sm" data-testid="calendar-grid">
      {/* ヘッダー */}
      <div className="flex items-center justify-between px-6 py-4 border-b">
        <Button
          variant="outline"
          size="sm"
          onClick={prevMonth}
          aria-label="前の月"
          data-testid="btn-prev-month"
        >
          <ChevronLeft className="size-4" />
        </Button>
        <h2 className="text-lg font-semibold" data-testid="calendar-month-label">
          {formatMonthJa(year, month)}
        </h2>
        <Button
          variant="outline"
          size="sm"
          onClick={nextMonth}
          aria-label="次の月"
          data-testid="btn-next-month"
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>

      {/* 曜日ヘッダー */}
      <div className="grid grid-cols-7 border-b">
        {DOW_LABELS.map((dow, i) => (
          <div
            key={dow}
            className={cn(
              'py-2 text-center text-xs font-medium text-muted-foreground',
              i === 0 && 'text-red-500',
              i === 6 && 'text-blue-500'
            )}
          >
            {dow}
          </div>
        ))}
      </div>

      {/* 日付グリッド */}
      <div className="grid grid-cols-7">
        {days.map((date, idx) => {
          if (!date) {
            return <div key={`empty-${idx}`} className="h-24 border-b border-r last:border-r-0" />;
          }

          const dayEvents = getEventsForDate(events, date);
          const today_ = isToday(date);
          const dow = date.getDay();

          return (
            <div
              key={date.toISOString()}
              className={cn(
                'h-24 border-b border-r last:border-r-0 p-1 cursor-pointer transition-colors hover:bg-muted/50',
                today_ && 'bg-primary/5'
              )}
              onClick={() => onDateClick?.(date, dayEvents)}
              role="button"
              tabIndex={0}
              aria-label={`${date.getMonth() + 1}月${date.getDate()}日`}
              onKeyDown={(e) => e.key === 'Enter' && onDateClick?.(date, dayEvents)}
              data-testid={`calendar-day-${date.getDate()}`}
            >
              {/* 日付番号 */}
              <div className="flex justify-end mb-1">
                <span
                  className={cn(
                    'inline-flex size-7 items-center justify-center rounded-full text-sm font-medium',
                    today_ && 'bg-primary text-primary-foreground',
                    !today_ && dow === 0 && 'text-red-500',
                    !today_ && dow === 6 && 'text-blue-500'
                  )}
                >
                  {date.getDate()}
                </span>
              </div>

              {/* イベントドット（最大3個表示） */}
              <div className="flex flex-wrap gap-0.5 px-0.5">
                {dayEvents.slice(0, 3).map((ev) => (
                  <EventBadge key={ev.id} type={ev.type} showDotOnly />
                ))}
                {dayEvents.length > 3 && (
                  <span className="text-xs text-muted-foreground">+{dayEvents.length - 3}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
