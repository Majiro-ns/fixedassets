// ─── 経理カレンダー イベント型定義 ───────────────────────────────────

export type CalendarEventType =
  | 'depreciation'   // 減価償却
  | 'tax_filing'     // 税申告
  | 'inventory'      // 棚卸し
  | 'closing'        // 決算
  | 'custom';        // カスタム

export type CalendarEventStatus = 'pending' | 'done' | 'overdue';

export interface CalendarEvent {
  id: string;
  title: string;
  date: string; // ISO date string YYYY-MM-DD
  type: CalendarEventType;
  status: CalendarEventStatus;
  description?: string;
  recurrence?: 'none' | 'monthly' | 'yearly';
}

export interface CalendarEventFormValues {
  title: string;
  date: string;
  type: CalendarEventType;
  description?: string;
  recurrence?: 'none' | 'monthly' | 'yearly';
}

// イベント種別の表示設定
export interface EventTypeConfig {
  label: string;
  color: string;         // Tailwind bg-xxx
  textColor: string;     // Tailwind text-xxx
  borderColor: string;   // Tailwind border-xxx
  dotColor: string;      // Tailwind bg-xxx for dot
}
