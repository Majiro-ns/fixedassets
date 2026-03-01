'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { Decision } from '@/types/classify';

// ─── 判定別設定 ───────────────────────────────────────────────────

const CONFIG: Record<
  Decision,
  { header: string; borderClass: string; textClass: string; steps: string[] }
> = {
  CAPITAL_LIKE: {
    header: '📋 資産計上の次ステップ',
    borderClass: 'border-l-4 border-green-200',
    textClass: 'text-green-800',
    steps: [
      '固定資産台帳への登録',
      '耐用年数・償却方法の確定',
      '取得価額の確定と初年度減価償却計算',
    ],
  },
  EXPENSE_LIKE: {
    header: '📝 費用計上の次ステップ',
    borderClass: 'border-l-4 border-blue-200',
    textClass: 'text-blue-800',
    steps: [
      '仕訳処理（借方: 当該費用勘定）',
      '証憑書類の保管（5年間）',
      '部門別コスト管理への反映',
    ],
  },
  GUIDANCE: {
    header: '❓ 要確認の次ステップ',
    borderClass: 'border-l-4 border-yellow-200',
    textClass: 'text-yellow-800',
    steps: [
      '判定ウィザードで詳細情報を入力',
      '税理士・専門家への相談',
      '社内経理規程の確認',
    ],
  },
};

// ─── Props ────────────────────────────────────────────────────────

interface NextActionCardProps {
  decision: Decision;
}

// ─── NextActionCard ───────────────────────────────────────────────

export function NextActionCard({ decision }: NextActionCardProps) {
  const cfg = CONFIG[decision] ?? CONFIG.GUIDANCE;

  return (
    <Card className={cfg.borderClass}>
      <CardHeader className="pb-2">
        <CardTitle className={`text-sm font-semibold ${cfg.textClass}`}>
          🔜 次のアクション
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className={`text-sm font-medium mb-2 ${cfg.textClass}`}>{cfg.header}</p>
        <ol className="space-y-1 list-decimal list-inside">
          {cfg.steps.map((step, i) => (
            <li key={i} className={`text-sm ${cfg.textClass}`}>
              {step}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
