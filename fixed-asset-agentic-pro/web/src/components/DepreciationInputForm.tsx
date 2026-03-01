'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Calculator, Loader2 } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { DepreciationRequest } from '@/types/depreciation';

// ─── バリデーションスキーマ ──────────────────────────────────────────────
const schema = z.object({
  acquisition_cost: z.coerce
    .number({ invalid_type_error: '数値を入力してください' })
    .int('整数で入力してください')
    .min(1, '1円以上'),
  acquisition_date: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, 'YYYY-MM-DD 形式で入力してください'),
  useful_life: z.coerce
    .number({ invalid_type_error: '数値を入力してください' })
    .int('整数で入力してください')
    .min(2, '2年以上')
    .max(50, '50年以内'),
  method: z.enum(['declining_balance', 'straight_line']),
  is_sme_blue: z.boolean().optional(),
  calculate_asset_tax: z.boolean().optional(),
});

type FormValues = z.infer<typeof schema>;

// ─── デモデータ ─────────────────────────────────────────────────────────
const DEMO_DEFAULTS: FormValues = {
  acquisition_cost: 1000000,
  acquisition_date: '2024-04-01',
  useful_life: 5,
  method: 'declining_balance',
  is_sme_blue: false,
  calculate_asset_tax: true,
};

// ─── Props ─────────────────────────────────────────────────────────────
interface DepreciationInputFormProps {
  onSubmit: (req: DepreciationRequest) => void;
  isLoading?: boolean;
}

// ─── DepreciationInputForm ──────────────────────────────────────────────
export function DepreciationInputForm({ onSubmit, isLoading = false }: DepreciationInputFormProps) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      method: 'declining_balance',
      is_sme_blue: false,
      calculate_asset_tax: false,
    },
  });

  const handleFormSubmit = (values: FormValues) => {
    const req: DepreciationRequest = {
      acquisition_cost: values.acquisition_cost,
      acquisition_date: values.acquisition_date,
      useful_life: values.useful_life,
      method: values.method,
      is_sme_blue: values.is_sme_blue,
      calculate_asset_tax: values.calculate_asset_tax,
    };
    onSubmit(req);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Calculator className="size-5 text-primary" />
          減価償却計算
        </CardTitle>
        <CardDescription>
          取得価額・耐用年数・償却方法を入力して年次償却スケジュールを計算します
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* デモデータボタン */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <span className="text-xs text-muted-foreground">💡 デモデータで試す:</span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => reset(DEMO_DEFAULTS)}
          >
            100万円・耐用5年・定率法
          </Button>
        </div>

        <form onSubmit={handleSubmit(handleFormSubmit)} className="space-y-5">

          {/* 取得価額（必須） */}
          <div className="space-y-2">
            <Label htmlFor="acquisition_cost">
              取得価額（円）<span className="text-destructive">*</span>
            </Label>
            <Input
              id="acquisition_cost"
              type="number"
              min={1}
              placeholder="1000000"
              {...register('acquisition_cost')}
              aria-invalid={!!errors.acquisition_cost}
              aria-describedby={errors.acquisition_cost ? 'acquisition_cost_error' : undefined}
            />
            {errors.acquisition_cost && (
              <p id="acquisition_cost_error" className="text-xs text-destructive">{errors.acquisition_cost.message}</p>
            )}
            <p className="text-xs text-muted-foreground">
              10万未満: 即時損金 / 10〜20万: 一括3年 / 中小青色30万未満: 特例全額
            </p>
          </div>

          {/* 取得日・耐用年数 */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="acquisition_date">
                取得日 <span className="text-destructive">*</span>
              </Label>
              <Input
                id="acquisition_date"
                type="date"
                {...register('acquisition_date')}
                aria-invalid={!!errors.acquisition_date}
                aria-describedby={errors.acquisition_date ? 'acquisition_date_error' : undefined}
              />
              {errors.acquisition_date && (
                <p id="acquisition_date_error" className="text-xs text-destructive">{errors.acquisition_date.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="useful_life">
                耐用年数（年）<span className="text-destructive">*</span>
              </Label>
              <Input
                id="useful_life"
                type="number"
                min={2}
                max={50}
                placeholder="5"
                {...register('useful_life')}
                aria-invalid={!!errors.useful_life}
                aria-describedby={errors.useful_life ? 'useful_life_error' : undefined}
              />
              {errors.useful_life && (
                <p id="useful_life_error" className="text-xs text-destructive">{errors.useful_life.message}</p>
              )}
              <p className="text-xs text-muted-foreground">耐用年数省令 別表参照</p>
            </div>
          </div>

          {/* 償却方法 */}
          <div className="space-y-2">
            <Label>
              償却方法 <span className="text-destructive">*</span>
            </Label>
            <div className="grid grid-cols-2 gap-3">
              <label className="flex items-center gap-2 rounded-md border p-3 cursor-pointer hover:bg-muted/50">
                <input
                  type="radio"
                  value="declining_balance"
                  {...register('method')}
                  className="accent-primary"
                />
                <div>
                  <p className="text-sm font-medium">定率法</p>
                  <p className="text-xs text-muted-foreground">200%定率法（施行令§48の2）</p>
                </div>
              </label>
              <label className="flex items-center gap-2 rounded-md border p-3 cursor-pointer hover:bg-muted/50">
                <input
                  type="radio"
                  value="straight_line"
                  {...register('method')}
                  className="accent-primary"
                />
                <div>
                  <p className="text-sm font-medium">定額法</p>
                  <p className="text-xs text-muted-foreground">残存価額0円（施行令§48）</p>
                </div>
              </label>
            </div>
            {errors.method && (
              <p className="text-xs text-destructive">{errors.method.message}</p>
            )}
          </div>

          {/* 追加オプション */}
          <div className="space-y-3 rounded-md border p-4">
            <p className="text-sm font-medium">追加オプション</p>
            <label className="flex items-start gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                {...register('is_sme_blue')}
                className="mt-0.5 size-4 accent-primary"
              />
              <span className="text-sm">
                中小企業の青色申告法人
                <span className="text-xs text-muted-foreground ml-1">
                  （30万未満の少額減価償却資産特例・租特法§67の5）
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                {...register('calculate_asset_tax')}
                className="mt-0.5 size-4 accent-primary"
              />
              <span className="text-sm">
                償却資産税も計算する
                <span className="text-xs text-muted-foreground ml-1">
                  （地方税法§349の2・税率1.4%）
                </span>
              </span>
            </label>
          </div>

          <Button type="submit" disabled={isLoading} size="lg" className="w-full">
            {isLoading ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                計算中...
              </>
            ) : (
              <>
                <Calculator className="size-4" />
                償却スケジュールを計算
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
