'use client';

import { AlertTriangle, Wrench, Package } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

// ─── プログレスインジケーター ──────────────────────────────────────────
function StepProgress({ current }: { current: 1 | 2 }) {
  const steps = ['質問1', '質問2', '判定'];
  return (
    <div className="flex items-center gap-1.5 text-xs mb-1">
      {steps.map((label, i) => {
        const stepNum = i + 1;
        const done = stepNum < current;
        const active = stepNum === current;
        return (
          <div key={label} className="flex items-center gap-1.5">
            <span
              className={cn(
                'inline-flex size-5 items-center justify-center rounded-full text-[10px] font-bold',
                done && 'bg-green-500 text-white',
                active && 'bg-yellow-500 text-white ring-2 ring-yellow-300',
                !done && !active && 'bg-muted text-muted-foreground',
              )}
            >
              {stepNum}
            </span>
            <span
              className={cn(
                done && 'text-green-600',
                active && 'font-semibold text-yellow-700',
                !done && !active && 'text-muted-foreground',
              )}
            >
              {label}
            </span>
            {i < steps.length - 1 && (
              <span className={cn('mx-0.5 h-px w-4 shrink-0', done ? 'bg-green-400' : 'bg-muted')} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Props ────────────────────────────────────────────────────────────
interface WizardStep1Props {
  missingFields: string[];
  whyMissing: string[];
  onChoose: (choice: 'repair' | 'upgrade') => void;
}

// ─── 大型選択ボタン ───────────────────────────────────────────────────
function ChoiceButton({
  icon: Icon,
  title,
  description,
  hint,
  colorClass,
  hoverClass,
  onClick,
}: {
  icon: React.ElementType;
  title: string;
  description: string;
  hint: string;
  colorClass: string;
  hoverClass: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex flex-col items-center gap-2 rounded-xl border-2 p-5 text-center transition-all',
        'hover:-translate-y-0.5 hover:shadow-md active:translate-y-0',
        colorClass,
        hoverClass,
      )}
    >
      <Icon className="size-8" />
      <span className="text-base font-bold">{title}</span>
      <span className="text-xs leading-relaxed">{description}</span>
      <span className="mt-1 rounded-full bg-white/60 px-3 py-0.5 text-xs font-semibold">{hint}</span>
    </button>
  );
}

// ─── WizardStep1 メイン ───────────────────────────────────────────────
export function WizardStep1({ missingFields, whyMissing, onChoose }: WizardStep1Props) {
  return (
    <Card className="border-yellow-300 bg-yellow-50 dark:bg-yellow-950/20">
      <CardHeader>
        <StepProgress current={1} />
        <CardTitle className="flex items-center gap-2 text-yellow-800 dark:text-yellow-300">
          <AlertTriangle className="size-5" />
          AIが判断を保留しました
        </CardTitle>
        <CardDescription className="text-yellow-700 dark:text-yellow-400">
          この取引はAIが自動判定できません。下のボタンで教えてください。
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* 2択ボタン（最上部） */}
        <div className="grid grid-cols-2 gap-3">
          <ChoiceButton
            icon={Wrench}
            title="修繕・維持"
            description="壊れたものを直す"
            hint="→ 経費になります"
            colorClass="border-red-300 bg-red-50 text-red-800 dark:bg-red-950/30 dark:text-red-300"
            hoverClass="hover:border-red-400 hover:bg-red-100"
            onClick={() => onChoose('repair')}
          />
          <ChoiceButton
            icon={Package}
            title="新規購入・増強"
            description="新しく買う・増やす"
            hint="→ 資産になります"
            colorClass="border-blue-300 bg-blue-50 text-blue-800 dark:bg-blue-950/30 dark:text-blue-300"
            hoverClass="hover:border-blue-400 hover:bg-blue-100"
            onClick={() => onChoose('upgrade')}
          />
        </div>

        {/* 判断ヒント */}
        <div className="rounded-lg bg-green-50 border border-green-200 p-3 text-sm text-green-800">
          <p className="font-medium mb-1">💡 判断のヒント</p>
          <ul className="space-y-0.5 text-xs">
            <li>・元々ある設備の修理・メンテナンス → 修繕</li>
            <li>・初めて導入する、性能を上げる → 新規購入</li>
          </ul>
        </div>

        {/* AIが迷った理由 */}
        {missingFields.length > 0 && (
          <div className="rounded-lg border border-yellow-200 bg-yellow-100/60 p-3 text-sm">
            <p className="font-medium text-yellow-800 mb-1">🔍 AIが迷った理由</p>
            <ul className="space-y-1">
              {missingFields.map((f, i) => (
                <li key={i} className="text-xs text-yellow-700">
                  ・{f}
                  {whyMissing[i] && (
                    <span className="ml-1 text-yellow-600">→ {whyMissing[i]}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="text-center text-xs text-muted-foreground">
          わからない場合は税理士にご相談ください
        </p>
      </CardContent>
    </Card>
  );
}
