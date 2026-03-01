'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Calculator, Loader2 } from 'lucide-react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { LeaseClassifyRequest } from '@/types/classify_lease';

// ─── バリデーションスキーマ ──────────────────────────────────────────────
const schema = z.object({
  // 必須
  description: z
    .string()
    .min(5, '5文字以上の説明を入力してください')
    .max(1000, '1000文字以内で入力してください'),
  contract_term_months: z.coerce
    .number({ invalid_type_error: '数値を入力してください' })
    .int('整数で入力してください')
    .min(1, '1ヶ月以上')
    .max(600, '600ヶ月以内'),
  monthly_payment: z.coerce
    .number({ invalid_type_error: '数値を入力してください' })
    .min(1, '1円以上'),

  // 任意（空文字許容 → submit時にパース）
  asset_new_value_usd: z.string().optional(),
  annual_ibr: z
    .string()
    .optional()
    .refine(
      (v) => !v || (Number(v) >= 0 && Number(v) <= 1),
      '0〜1の範囲で入力してください（例: 0.03 = 3%）',
    ),
  initial_direct_costs: z.string().optional(),

  // チェックボックス
  is_substitution_right_substantive: z.boolean().optional(),
  has_purchase_option_certain: z.boolean().optional(),
});

type FormValues = z.infer<typeof schema>;

// ─── デモデータ ─────────────────────────────────────────────────────────
const DEMO_DEFAULTS: FormValues = {
  description: 'データセンター専用サーバーラックコロケーション契約（指定ラック固定・外装ロゴ入り）',
  contract_term_months: 36,
  monthly_payment: 100000,
  annual_ibr: '0.03',
  asset_new_value_usd: '8000',
  initial_direct_costs: '50000',
  is_substitution_right_substantive: false,
  has_purchase_option_certain: false,
};

// ─── Props ─────────────────────────────────────────────────────────────
interface LeaseInputFormProps {
  onSubmit: (req: LeaseClassifyRequest) => void;
  isLoading?: boolean;
}

// ─── LeaseInputForm ────────────────────────────────────────────────────
export function LeaseInputForm({ onSubmit, isLoading = false }: LeaseInputFormProps) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      is_substitution_right_substantive: false,
      has_purchase_option_certain: false,
    },
  });

  const handleFormSubmit = (values: FormValues) => {
    const req: LeaseClassifyRequest = {
      description: values.description,
      contract_term_months: values.contract_term_months,
      monthly_payment: values.monthly_payment,
      is_substitution_right_substantive: values.is_substitution_right_substantive,
      has_purchase_option_certain: values.has_purchase_option_certain,
      ...(values.asset_new_value_usd
        ? { asset_new_value_usd: Number(values.asset_new_value_usd) }
        : {}),
      ...(values.annual_ibr ? { annual_ibr: Number(values.annual_ibr) } : {}),
      ...(values.initial_direct_costs
        ? { initial_direct_costs: Number(values.initial_direct_costs) }
        : {}),
    };
    onSubmit(req);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Calculator className="size-5 text-primary" />
          IFRS 16 リース判定
        </CardTitle>
        <CardDescription>
          契約内容を入力してリース識別・免除判定・ROU資産計算を行います
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
            コロケーション契約 月¥100K/36ヶ月/IBR 3%
          </Button>
        </div>

        <form onSubmit={handleSubmit(handleFormSubmit)} className="space-y-5">

          {/* 契約概要（必須） */}
          <div className="space-y-2">
            <Label htmlFor="description">
              契約概要・説明 <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="description"
              rows={3}
              placeholder="例: データセンター専用ラック（指定ラック固定）のコロケーション契約&#10;例: 複合機リース契約（供給者が代替可能）"
              {...register('description')}
              aria-invalid={!!errors.description}
            />
            {errors.description && (
              <p className="text-xs text-destructive">{errors.description.message}</p>
            )}
          </div>

          {/* リース期間・月額（必須） */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="contract_term_months">
                リース期間（ヶ月）<span className="text-destructive">*</span>
              </Label>
              <Input
                id="contract_term_months"
                type="number"
                min={1}
                max={600}
                placeholder="36"
                {...register('contract_term_months')}
                aria-invalid={!!errors.contract_term_months}
              />
              {errors.contract_term_months && (
                <p className="text-xs text-destructive">{errors.contract_term_months.message}</p>
              )}
              <p className="text-xs text-muted-foreground">更新OP行使確実分を含む実質期間</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="monthly_payment">
                月額リース料（円）<span className="text-destructive">*</span>
              </Label>
              <Input
                id="monthly_payment"
                type="number"
                min={1}
                placeholder="100000"
                {...register('monthly_payment')}
                aria-invalid={!!errors.monthly_payment}
              />
              {errors.monthly_payment && (
                <p className="text-xs text-destructive">{errors.monthly_payment.message}</p>
              )}
            </div>
          </div>

          {/* 任意: 免除・測定パラメータ */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="asset_new_value_usd">
                原資産 新品時価値（USD・任意）
              </Label>
              <Input
                id="asset_new_value_usd"
                type="number"
                min={0}
                placeholder="8000"
                {...register('asset_new_value_usd')}
              />
              <p className="text-xs text-muted-foreground">
                USD 5,000 以下 → 少額免除（BC100）
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="annual_ibr">追加借入利子率 IBR（任意）</Label>
              <Input
                id="annual_ibr"
                type="number"
                step="0.001"
                min={0}
                max={1}
                placeholder="0.03"
                {...register('annual_ibr')}
                aria-invalid={!!errors.annual_ibr}
              />
              {errors.annual_ibr && (
                <p className="text-xs text-destructive">{errors.annual_ibr.message}</p>
              )}
              <p className="text-xs text-muted-foreground">
                例: 0.03 = 3%。入力でROU資産計算（§26-28）
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="initial_direct_costs">当初直接費用（円・任意）</Label>
            <Input
              id="initial_direct_costs"
              type="number"
              min={0}
              placeholder="50000"
              {...register('initial_direct_costs')}
            />
            <p className="text-xs text-muted-foreground">
              法律費用・仲介手数料等（§24 ROU資産に加算）
            </p>
          </div>

          {/* リース識別の追加判定チェックボックス */}
          <div className="space-y-3 rounded-md border p-4">
            <p className="text-sm font-medium">リース識別の追加判定</p>
            <label className="flex items-start gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                {...register('is_substitution_right_substantive')}
                className="mt-0.5 size-4 accent-primary"
              />
              <span className="text-sm">
                供給者に実質的な代替権がある
                <span className="text-xs text-muted-foreground ml-1">
                  （§B14 → リースなしの可能性）
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                {...register('has_purchase_option_certain')}
                className="mt-0.5 size-4 accent-primary"
              />
              <span className="text-sm">
                購入オプションの行使が合理的に確実
                <span className="text-xs text-muted-foreground ml-1">
                  （§B34 → 短期免除不可）
                </span>
              </span>
            </label>
          </div>

          <Button type="submit" disabled={isLoading} size="lg" className="w-full">
            {isLoading ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                判定中...
              </>
            ) : (
              <>
                <Calculator className="size-4" />
                リース判定を実行
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
