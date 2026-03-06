'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { EVENT_TYPE_CONFIG } from '@/lib/calendarUtils';
import type { CalendarEvent, CalendarEventFormValues, CalendarEventType } from '@/types/calendar';

const schema = z.object({
  title: z.string().min(1, 'タイトルを入力してください').max(100, '100文字以内で入力してください'),
  date: z.string().min(1, '日付を選択してください'),
  type: z.enum(['depreciation', 'tax_filing', 'inventory', 'closing', 'custom'] as const),
  description: z.string().max(500, '500文字以内で入力してください').optional(),
  recurrence: z.enum(['none', 'monthly', 'yearly'] as const).optional(),
});

interface EventFormProps {
  defaultValues?: Partial<CalendarEventFormValues>;
  onSubmit: (values: CalendarEventFormValues) => void;
  onCancel?: () => void;
  isEdit?: boolean;
}

const EVENT_TYPES: CalendarEventType[] = [
  'depreciation',
  'tax_filing',
  'inventory',
  'closing',
  'custom',
];

export function EventForm({ defaultValues, onSubmit, onCancel, isEdit = false }: EventFormProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CalendarEventFormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      type: 'custom',
      recurrence: 'none',
      ...defaultValues,
    },
  });

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" data-testid="event-form">
      {/* タイトル */}
      <div className="space-y-1">
        <Label htmlFor="event-title">
          タイトル <span className="text-destructive">*</span>
        </Label>
        <Input
          id="event-title"
          placeholder="例: 3月決算締め"
          {...register('title')}
          aria-invalid={!!errors.title}
          data-testid="input-event-title"
        />
        {errors.title && <p className="text-xs text-destructive">{errors.title.message}</p>}
      </div>

      {/* 日付 */}
      <div className="space-y-1">
        <Label htmlFor="event-date">
          日付 <span className="text-destructive">*</span>
        </Label>
        <Input
          id="event-date"
          type="date"
          {...register('date')}
          aria-invalid={!!errors.date}
          data-testid="input-event-date"
        />
        {errors.date && <p className="text-xs text-destructive">{errors.date.message}</p>}
      </div>

      {/* イベント種別 */}
      <div className="space-y-1">
        <Label htmlFor="event-type">種別</Label>
        <select
          id="event-type"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring"
          {...register('type')}
          data-testid="select-event-type"
        >
          {EVENT_TYPES.map((t) => (
            <option key={t} value={t}>
              {EVENT_TYPE_CONFIG[t].label}
            </option>
          ))}
        </select>
      </div>

      {/* 繰り返し */}
      <div className="space-y-1">
        <Label htmlFor="event-recurrence">繰り返し</Label>
        <select
          id="event-recurrence"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring"
          {...register('recurrence')}
          data-testid="select-event-recurrence"
        >
          <option value="none">なし</option>
          <option value="monthly">毎月</option>
          <option value="yearly">毎年</option>
        </select>
      </div>

      {/* 説明 */}
      <div className="space-y-1">
        <Label htmlFor="event-description">説明（任意）</Label>
        <Textarea
          id="event-description"
          placeholder="例: 固定資産台帳との照合が必要"
          rows={3}
          {...register('description')}
          data-testid="input-event-description"
        />
        {errors.description && (
          <p className="text-xs text-destructive">{errors.description.message}</p>
        )}
      </div>

      {/* ボタン */}
      <div className="flex gap-2 justify-end">
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel} data-testid="btn-cancel-event">
            キャンセル
          </Button>
        )}
        <Button type="submit" data-testid="btn-submit-event">
          {isEdit ? '更新する' : 'イベント追加'}
        </Button>
      </div>
    </form>
  );
}
