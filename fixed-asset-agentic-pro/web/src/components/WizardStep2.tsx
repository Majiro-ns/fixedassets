'use client';

import { ArrowLeft, RotateCcw, Sparkles, Replace, PlusCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

// ─── プログレスインジケーター（Step 2用） ─────────────────────────────
function StepProgress({ choice }: { choice: 'repair' | 'upgrade' }) {
  const label = choice === 'repair' ? '🔧 修繕・維持' : '📦 新規購入・増強';
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs">
        {['質問1', '質問2', '判定'].map((step, i) => {
          const done = i < 1;
          const active = i === 1;
          return (
            <div key={step} className="flex items-center gap-1.5">
              <span
                className={cn(
                  'inline-flex size-5 items-center justify-center rounded-full text-[10px] font-bold',
                  done && 'bg-green-500 text-white',
                  active && 'bg-yellow-500 text-white ring-2 ring-yellow-300',
                  !done && !active && 'bg-muted text-muted-foreground',
                )}
              >
                {i + 1}
              </span>
              <span
                className={cn(
                  done && 'text-green-600',
                  active && 'font-semibold text-yellow-700',
                  !done && !active && 'text-muted-foreground',
                )}
              >
                {step}
              </span>
              {i < 2 && <span className={cn('mx-0.5 h-px w-4 shrink-0', done ? 'bg-green-400' : 'bg-muted')} />}
            </div>
          );
        })}
      </div>
      {/* Step 1 選択済み表示 */}
      <div className="flex items-center gap-2 rounded-md bg-green-50 border border-green-200 px-3 py-1.5 text-xs text-green-700">
        <span className="text-green-500">✅</span>
        <span>「{label}」を選択済み</span>
      </div>
    </div>
  );
}

// ─── 大型選択ボタン ───────────────────────────────────────────────────
function DetailButton({
  icon: Icon,
  title,
  subtitle,
  colorClass,
  hoverClass,
  onClick,
}: {
  icon: React.ElementType;
  title: string;
  subtitle: string;
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
      <Icon className="size-7" />
      <span className="text-sm font-bold">{title}</span>
      <span className="text-xs text-current/70">{subtitle}</span>
    </button>
  );
}

// ─── Props ────────────────────────────────────────────────────────────
interface WizardStep2Props {
  choice: 'repair' | 'upgrade';
  onChoose: (answers: Record<string, string>) => void;
  onBack: () => void;
}

// ─── WizardStep2 メイン ───────────────────────────────────────────────
export function WizardStep2({ choice, onChoose, onBack }: WizardStep2Props) {
  const isRepair = choice === 'repair';

  return (
    <Card className="border-yellow-300 bg-yellow-50 dark:bg-yellow-950/20">
      <CardHeader>
        <StepProgress choice={choice} />
        <CardTitle className="flex items-center gap-2 text-yellow-800 dark:text-yellow-300 mt-1">
          📋 あと1つだけ教えてください
        </CardTitle>
        <CardDescription className="text-yellow-700 dark:text-yellow-400">
          より正確に判定するための質問です。
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* 詳細質問 */}
        <div className="rounded-lg border-2 border-yellow-200 bg-white/70 p-4">
          <p className="text-sm font-semibold text-yellow-800 mb-3">
            {isRepair ? '🔧 修繕の頻度を教えてください' : '📦 既存設備の入替ですか？'}
          </p>
          <div className="grid grid-cols-2 gap-3">
            {isRepair ? (
              <>
                <DetailButton
                  icon={RotateCcw}
                  title="定期的（3年以内）"
                  subtitle="以前にも修理したことがある"
                  colorClass="border-red-300 bg-red-50 text-red-800"
                  hoverClass="hover:border-red-400 hover:bg-red-100"
                  onClick={() =>
                    onChoose({ purchase_type: 'repair', repair_frequency: 'periodic' })
                  }
                />
                <DetailButton
                  icon={Sparkles}
                  title="今回が初めて"
                  subtitle="初めての修理です"
                  colorClass="border-blue-300 bg-blue-50 text-blue-800"
                  hoverClass="hover:border-blue-400 hover:bg-blue-100"
                  onClick={() =>
                    onChoose({ purchase_type: 'repair', repair_frequency: 'first_time' })
                  }
                />
              </>
            ) : (
              <>
                <DetailButton
                  icon={Replace}
                  title="はい（入替）"
                  subtitle="古い設備を新しくする"
                  colorClass="border-red-300 bg-red-50 text-red-800"
                  hoverClass="hover:border-red-400 hover:bg-red-100"
                  onClick={() =>
                    onChoose({ purchase_type: 'upgrade', upgrade_type: 'replacement' })
                  }
                />
                <DetailButton
                  icon={PlusCircle}
                  title="いいえ（純粋な新規）"
                  subtitle="新しく追加する"
                  colorClass="border-blue-300 bg-blue-50 text-blue-800"
                  hoverClass="hover:border-blue-400 hover:bg-blue-100"
                  onClick={() =>
                    onChoose({ purchase_type: 'upgrade', upgrade_type: 'new' })
                  }
                />
              </>
            )}
          </div>
        </div>

        {/* ヒント */}
        <div className="rounded-lg bg-green-50 border border-green-200 p-3 text-xs text-green-800">
          <p className="font-medium mb-1">💡 ヒント</p>
          {isRepair ? (
            <ul className="space-y-0.5">
              <li>・定期的な修繕 → 通常は経費として処理</li>
              <li>・初めての大規模修繕 → 資本的支出の可能性も</li>
            </ul>
          ) : (
            <ul className="space-y-0.5">
              <li>・既存設備の入替 → 除却損の検討も必要</li>
              <li>・純粋な新規導入 → 資産計上が基本</li>
            </ul>
          )}
        </div>

        {/* 戻るボタン */}
        <Button variant="ghost" size="sm" onClick={onBack} className="text-muted-foreground">
          <ArrowLeft className="size-3.5" />
          選び直す
        </Button>

        <p className="text-center text-xs text-muted-foreground">
          わからない場合は税理士にご相談ください
        </p>
      </CardContent>
    </Card>
  );
}
