'use client';

import { useEffect } from 'react';
import { MainLayout } from '@/components/layout/MainLayout';
import { Button } from '@/components/ui/button';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <MainLayout>
      <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
        <h2 className="text-xl font-semibold">EDINET接続エラー</h2>
        <p className="text-muted-foreground max-w-md">
          {error.message || 'EDINET文書の読み込み中に問題が発生しました。'}
        </p>
        <Button onClick={reset}>再試行</Button>
      </div>
    </MainLayout>
  );
}
