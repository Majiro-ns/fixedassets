import { cn } from '@/lib/utils';
import { getEventTypeConfig } from '@/lib/calendarUtils';
import type { CalendarEventType } from '@/types/calendar';

interface EventBadgeProps {
  type: CalendarEventType;
  className?: string;
  showDotOnly?: boolean;
}

export function EventBadge({ type, className, showDotOnly = false }: EventBadgeProps) {
  const cfg = getEventTypeConfig(type);

  if (showDotOnly) {
    return (
      <span
        className={cn('inline-block size-2 rounded-full', cfg.dotColor, className)}
        aria-label={cfg.label}
        data-testid={`event-dot-${type}`}
      />
    );
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
        cfg.color,
        cfg.textColor,
        cfg.borderColor,
        className
      )}
      data-testid={`event-badge-${type}`}
    >
      <span className={cn('size-1.5 rounded-full', cfg.dotColor)} />
      {cfg.label}
    </span>
  );
}
