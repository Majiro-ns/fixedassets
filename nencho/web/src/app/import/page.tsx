'use client';

import { useRouter } from 'next/navigation';
import { NenchoCsvImportCard } from '@/components/NenchoCsvImportCard';

export default function ImportPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold">nencho</span>
            <span className="text-xs bg-secondary text-secondary-foreground px-2 py-0.5 rounded-full">
              CSVインポート
            </span>
          </div>
          <button
            onClick={() => router.push('/')}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            ← ホームへ戻る
          </button>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10 space-y-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">源泉徴収票 CSV インポート</h1>
          <p className="text-muted-foreground text-sm">
            従業員の給与・控除データを CSV から一括取込し、AIアシスト用の教師データとして登録します。
          </p>
        </div>

        <NenchoCsvImportCard />

        {/* CSVフォーマット説明 */}
        <div className="border border-border rounded-lg p-5 bg-card space-y-3">
          <h2 className="font-semibold text-sm">CSV フォーマット</h2>
          <div className="space-y-1.5 text-sm text-muted-foreground">
            <p>
              <span className="font-medium text-foreground">必須列:</span>{' '}
              従業員名、給与収入（円）、社会保険料（円）
            </p>
            <p>
              <span className="font-medium text-foreground">任意列:</span>{' '}
              扶養人数、生命保険料_新（円）、生命保険料_旧（円）、配偶者あり（true/false）、備考
            </p>
          </div>
          <div className="rounded-md bg-muted px-4 py-3 font-mono text-xs leading-relaxed whitespace-pre">
{`従業員名,給与収入,社会保険料,扶養人数,生命保険料_新,生命保険料_旧,配偶者あり,備考
山田太郎,5000000,620000,2,80000,0,true,
鈴木花子,3800000,480000,0,50000,0,false,パート`}
          </div>
          <ul className="text-xs text-muted-foreground space-y-0.5 list-disc list-inside">
            <li>文字コード: UTF-8（BOM 付き可。Excel の「CSV UTF-8」形式に対応）</li>
            <li>カンマを含む値はダブルクォートで囲むパターン（RFC 4180）には未対応</li>
            <li>金額列はカンマ区切り（例: 5,000,000）でも正しく読み込めます</li>
          </ul>
        </div>
      </main>
    </div>
  );
}
