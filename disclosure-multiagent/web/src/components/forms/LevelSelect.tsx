'use client';

import { cn } from '@/lib/utils';

interface Props {
  value: '松' | '竹' | '梅';
  onChange: (level: '松' | '竹' | '梅') => void;
}

const LEVELS = [
  {
    value: '松' as const,
    label: '松 (詳細)',
    desc: '200-480文字の充実した記載文案',
    color: 'border-green-500 bg-green-50 text-green-700',
  },
  {
    value: '竹' as const,
    label: '竹 (標準)',
    desc: '100-260文字のバランスのとれた文案',
    color: 'border-blue-500 bg-blue-50 text-blue-700',
  },
  {
    value: '梅' as const,
    label: '梅 (簡潔)',
    desc: '50-120文字の最低限の記載文案',
    color: 'border-amber-500 bg-amber-50 text-amber-700',
  },
];

export function LevelSelect({ value, onChange }: Props) {
  return (
    <div className="space-y-2">
      <label className="text-sm font-medium">提案レベル</label>
      <div className="grid grid-cols-3 gap-2">
        {LEVELS.map((l) => (
          <button
            key={l.value}
            onClick={() => onChange(l.value)}
            className={cn(
              'rounded-lg border-2 p-3 text-left transition-all',
              value === l.value ? l.color : 'border-border hover:border-muted-foreground/50'
            )}
          >
            <div className="font-semibold text-sm">{l.label}</div>
            <div className="text-xs mt-1 opacity-75">{l.desc}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
