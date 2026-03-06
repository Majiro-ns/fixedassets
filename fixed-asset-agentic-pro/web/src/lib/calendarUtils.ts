import type { CalendarEvent, CalendarEventType, EventTypeConfig } from '@/types/calendar';

// ─── イベント種別の色設定 ───────────────────────────────────────────
export const EVENT_TYPE_CONFIG: Record<CalendarEventType, EventTypeConfig> = {
  depreciation: {
    label: '減価償却',
    color: 'bg-blue-100',
    textColor: 'text-blue-800',
    borderColor: 'border-blue-200',
    dotColor: 'bg-blue-500',
  },
  tax_filing: {
    label: '税申告',
    color: 'bg-red-100',
    textColor: 'text-red-800',
    borderColor: 'border-red-200',
    dotColor: 'bg-red-500',
  },
  inventory: {
    label: '棚卸し',
    color: 'bg-green-100',
    textColor: 'text-green-800',
    borderColor: 'border-green-200',
    dotColor: 'bg-green-500',
  },
  closing: {
    label: '決算',
    color: 'bg-purple-100',
    textColor: 'text-purple-800',
    borderColor: 'border-purple-200',
    dotColor: 'bg-purple-500',
  },
  custom: {
    label: 'カスタム',
    color: 'bg-gray-100',
    textColor: 'text-gray-800',
    borderColor: 'border-gray-200',
    dotColor: 'bg-gray-500',
  },
};

// ─── カレンダー日付計算ユーティリティ ─────────────────────────────

/**
 * 指定月のカレンダーグリッド用日付配列を返す（前後月の埋め込み含む）
 * 日曜始まり。返り値は常に length = 35 or 42
 */
export function buildCalendarDays(year: number, month: number): (Date | null)[] {
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const startDow = firstDay.getDay(); // 0=日, 1=月, ...
  const totalDays = lastDay.getDate();

  const days: (Date | null)[] = [];

  // 月初前の空白
  for (let i = 0; i < startDow; i++) {
    days.push(null);
  }

  // 当月の日付
  for (let d = 1; d <= totalDays; d++) {
    days.push(new Date(year, month, d));
  }

  // グリッドを7の倍数に揃える
  while (days.length % 7 !== 0) {
    days.push(null);
  }

  return days;
}

/**
 * ISO日付文字列（YYYY-MM-DD）を日本語の月日表示に変換
 */
export function formatDateJa(dateStr: string): string {
  const [year, month, day] = dateStr.split('-').map(Number);
  return `${year}年${month}月${day}日`;
}

/**
 * Date オブジェクトを YYYY-MM-DD 文字列に変換
 */
export function toISODate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * 指定日のイベントを抽出
 */
export function getEventsForDate(events: CalendarEvent[], date: Date): CalendarEvent[] {
  const dateStr = toISODate(date);
  return events.filter((e) => e.date === dateStr);
}

/**
 * 今後N日以内のイベントを返す（日付昇順）
 */
export function getUpcomingEvents(events: CalendarEvent[], daysAhead: number = 30): CalendarEvent[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const limit = new Date(today);
  limit.setDate(limit.getDate() + daysAhead);

  return events
    .filter((e) => {
      const d = new Date(e.date);
      return d >= today && d <= limit && e.status !== 'done';
    })
    .sort((a, b) => a.date.localeCompare(b.date));
}

/**
 * イベント種別の設定を取得
 */
export function getEventTypeConfig(type: CalendarEventType): EventTypeConfig {
  return EVENT_TYPE_CONFIG[type] ?? EVENT_TYPE_CONFIG.custom;
}

/**
 * 2つの年月が等しいか判定
 */
export function isSameMonth(date: Date, year: number, month: number): boolean {
  return date.getFullYear() === year && date.getMonth() === month;
}

/**
 * 今日かどうか判定
 */
export function isToday(date: Date): boolean {
  const today = new Date();
  return toISODate(date) === toISODate(today);
}

/**
 * 年月の日本語表示
 */
export function formatMonthJa(year: number, month: number): string {
  return `${year}年${month + 1}月`;
}
