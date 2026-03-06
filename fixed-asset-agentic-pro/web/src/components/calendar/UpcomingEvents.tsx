import { CalendarDays } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { EventBadge } from './EventBadge';
import { formatDateJa, getUpcomingEvents } from '@/lib/calendarUtils';
import type { CalendarEvent } from '@/types/calendar';

interface UpcomingEventsProps {
  events: CalendarEvent[];
  daysAhead?: number;
  maxItems?: number;
}

const STATUS_LABEL: Record<CalendarEvent['status'], string> = {
  pending: '未処理',
  done: '完了',
  overdue: '期限超過',
};

const STATUS_COLOR: Record<CalendarEvent['status'], string> = {
  pending: 'text-muted-foreground',
  done: 'text-green-600',
  overdue: 'text-red-600',
};

export function UpcomingEvents({
  events,
  daysAhead = 30,
  maxItems = 5,
}: UpcomingEventsProps) {
  const upcoming = getUpcomingEvents(events, daysAhead).slice(0, maxItems);

  return (
    <Card data-testid="upcoming-events-widget">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarDays className="size-4 text-primary" />
          直近イベント（{daysAhead}日以内）
        </CardTitle>
      </CardHeader>
      <CardContent>
        {upcoming.length === 0 ? (
          <p className="text-sm text-muted-foreground py-2" data-testid="upcoming-events-empty">
            直近{daysAhead}日以内の予定はありません
          </p>
        ) : (
          <ul className="space-y-3" data-testid="upcoming-events-list">
            {upcoming.map((ev) => (
              <li
                key={ev.id}
                className="flex items-start gap-3"
                data-testid={`upcoming-event-${ev.id}`}
              >
                <EventBadge type={ev.type} showDotOnly className="mt-1.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{ev.title}</p>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                    <span>{formatDateJa(ev.date)}</span>
                    <span className={STATUS_COLOR[ev.status]}>
                      {STATUS_LABEL[ev.status]}
                    </span>
                  </div>
                </div>
                <EventBadge type={ev.type} className="shrink-0 hidden sm:inline-flex" />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
