import { describe, it, expect } from 'vitest';
import {
  buildCalendarDays,
  formatDateJa,
  toISODate,
  getEventsForDate,
  getUpcomingEvents,
  getEventTypeConfig,
  isToday,
  formatMonthJa,
  isSameMonth,
} from '@/lib/calendarUtils';
import type { CalendarEvent } from '@/types/calendar';

// ─── テストデータ ──────────────────────────────────────────────────
const TODAY = new Date();
const TODAY_STR = toISODate(TODAY);

function makeEvent(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: 'test-ev-1',
    title: 'テストイベント',
    date: TODAY_STR,
    type: 'custom',
    status: 'pending',
    ...overrides,
  };
}

// ─── buildCalendarDays ─────────────────────────────────────────────
describe('buildCalendarDays', () => {
  it('returns array with length multiple of 7', () => {
    const days = buildCalendarDays(2026, 0); // 2026年1月
    expect(days.length % 7).toBe(0);
  });

  it('returns at least 28 non-null dates for any month', () => {
    const days = buildCalendarDays(2026, 1); // 2026年2月
    const nonNull = days.filter((d) => d !== null);
    expect(nonNull.length).toBeGreaterThanOrEqual(28);
  });

  it('first non-null date is 1st of the month', () => {
    const days = buildCalendarDays(2026, 2); // 2026年3月
    const first = days.find((d) => d !== null);
    expect(first?.getDate()).toBe(1);
  });

  it('last non-null date is last day of month', () => {
    const days = buildCalendarDays(2026, 2); // 3月は31日
    const nonNull = days.filter((d) => d !== null) as Date[];
    expect(nonNull[nonNull.length - 1].getDate()).toBe(31);
  });

  it('null padding appears before day 1 (Sunday start)', () => {
    // 2026-03-01 は日曜日 → 先頭はnullなし
    const days = buildCalendarDays(2026, 2);
    expect(days[0]?.getDate()).toBe(1);
  });

  it('handles year boundary (December → January)', () => {
    const days = buildCalendarDays(2025, 11); // 2025年12月
    const nonNull = days.filter((d) => d !== null) as Date[];
    expect(nonNull[0].getDate()).toBe(1);
    expect(nonNull[nonNull.length - 1].getDate()).toBe(31);
  });
});

// ─── formatDateJa ─────────────────────────────────────────────────
describe('formatDateJa', () => {
  it('formats ISO date to Japanese format', () => {
    expect(formatDateJa('2026-03-08')).toBe('2026年3月8日');
  });

  it('handles single digit month and day', () => {
    expect(formatDateJa('2026-01-05')).toBe('2026年1月5日');
  });
});

// ─── toISODate ────────────────────────────────────────────────────
describe('toISODate', () => {
  it('formats Date to YYYY-MM-DD', () => {
    const d = new Date(2026, 2, 8); // 2026-03-08
    expect(toISODate(d)).toBe('2026-03-08');
  });

  it('zero-pads month and day', () => {
    const d = new Date(2026, 0, 5); // 2026-01-05
    expect(toISODate(d)).toBe('2026-01-05');
  });
});

// ─── getEventsForDate ──────────────────────────────────────────────
describe('getEventsForDate', () => {
  it('returns events matching the date', () => {
    const events = [
      makeEvent({ id: '1', date: '2026-03-08' }),
      makeEvent({ id: '2', date: '2026-03-09' }),
      makeEvent({ id: '3', date: '2026-03-08' }),
    ];
    const result = getEventsForDate(events, new Date(2026, 2, 8));
    expect(result).toHaveLength(2);
    expect(result.map((e) => e.id)).toEqual(['1', '3']);
  });

  it('returns empty array when no events match', () => {
    const events = [makeEvent({ date: '2026-03-10' })];
    const result = getEventsForDate(events, new Date(2026, 2, 8));
    expect(result).toHaveLength(0);
  });
});

// ─── getUpcomingEvents ────────────────────────────────────────────
describe('getUpcomingEvents', () => {
  it('returns only future non-done events within range', () => {
    const future = new Date();
    future.setDate(future.getDate() + 5);
    const past = new Date();
    past.setDate(past.getDate() - 5);
    const far = new Date();
    far.setDate(far.getDate() + 60);

    const events = [
      makeEvent({ id: 'future', date: toISODate(future), status: 'pending' }),
      makeEvent({ id: 'past', date: toISODate(past), status: 'pending' }),
      makeEvent({ id: 'far', date: toISODate(far), status: 'pending' }),
      makeEvent({ id: 'done', date: toISODate(future), status: 'done' }),
    ];

    const result = getUpcomingEvents(events, 30);
    expect(result.map((e) => e.id)).toContain('future');
    expect(result.map((e) => e.id)).not.toContain('past');
    expect(result.map((e) => e.id)).not.toContain('far');
    expect(result.map((e) => e.id)).not.toContain('done');
  });

  it('returns events sorted by date ascending', () => {
    const d1 = new Date(); d1.setDate(d1.getDate() + 10);
    const d2 = new Date(); d2.setDate(d2.getDate() + 3);
    const d3 = new Date(); d3.setDate(d3.getDate() + 7);

    const events = [
      makeEvent({ id: 'a', date: toISODate(d1) }),
      makeEvent({ id: 'b', date: toISODate(d2) }),
      makeEvent({ id: 'c', date: toISODate(d3) }),
    ];

    const result = getUpcomingEvents(events, 30);
    expect(result[0].id).toBe('b');
    expect(result[1].id).toBe('c');
    expect(result[2].id).toBe('a');
  });
});

// ─── getEventTypeConfig ───────────────────────────────────────────
describe('getEventTypeConfig', () => {
  it('returns blue config for depreciation', () => {
    const cfg = getEventTypeConfig('depreciation');
    expect(cfg.dotColor).toContain('blue');
    expect(cfg.label).toBe('減価償却');
  });

  it('returns red config for tax_filing', () => {
    const cfg = getEventTypeConfig('tax_filing');
    expect(cfg.dotColor).toContain('red');
    expect(cfg.label).toBe('税申告');
  });

  it('returns green config for inventory', () => {
    const cfg = getEventTypeConfig('inventory');
    expect(cfg.dotColor).toContain('green');
    expect(cfg.label).toBe('棚卸し');
  });

  it('returns purple config for closing', () => {
    const cfg = getEventTypeConfig('closing');
    expect(cfg.dotColor).toContain('purple');
    expect(cfg.label).toBe('決算');
  });

  it('returns gray config for custom', () => {
    const cfg = getEventTypeConfig('custom');
    expect(cfg.dotColor).toContain('gray');
    expect(cfg.label).toBe('カスタム');
  });
});

// ─── isToday ──────────────────────────────────────────────────────
describe('isToday', () => {
  it('returns true for today', () => {
    expect(isToday(new Date())).toBe(true);
  });

  it('returns false for yesterday', () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    expect(isToday(yesterday)).toBe(false);
  });
});

// ─── formatMonthJa ────────────────────────────────────────────────
describe('formatMonthJa', () => {
  it('formats year/month to Japanese', () => {
    expect(formatMonthJa(2026, 2)).toBe('2026年3月');
  });

  it('formats January correctly', () => {
    expect(formatMonthJa(2026, 0)).toBe('2026年1月');
  });
});

// ─── isSameMonth ──────────────────────────────────────────────────
describe('isSameMonth', () => {
  it('returns true when date matches year and month', () => {
    expect(isSameMonth(new Date(2026, 2, 15), 2026, 2)).toBe(true);
  });

  it('returns false when month differs', () => {
    expect(isSameMonth(new Date(2026, 3, 15), 2026, 2)).toBe(false);
  });
});
