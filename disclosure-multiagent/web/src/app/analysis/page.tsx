'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { MainLayout } from '@/components/layout/MainLayout';
import { PipelineProgress } from '@/components/analysis/PipelineProgress';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Button } from '@/components/ui/button';
import { useAnalysisStore } from '@/store/analysisStore';
import { streamTaskStatus } from '@/lib/api/client';
import { ArrowRight, RotateCcw } from 'lucide-react';

export default function AnalysisPage() {
  const router = useRouter();
  const { taskId, pipelineStatus, setPipelineStatus, setResult } = useAnalysisStore();
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!taskId) return;

    cleanupRef.current = streamTaskStatus(
      taskId,
      (status) => {
        setPipelineStatus(status);
      },
      (status) => {
        setPipelineStatus(status);
        if (status.result) {
          setResult(status.result);
        }
      }
    );

    return () => {
      cleanupRef.current?.();
    };
  }, [taskId, setPipelineStatus, setResult]);

  if (!taskId) {
    return (
      <MainLayout>
        <div className="max-w-3xl mx-auto text-center py-12 space-y-4">
          <p className="text-muted-foreground">分析タスクが見つかりません</p>
          <Button onClick={() => router.push('/company')}>企業検索に戻る</Button>
        </div>
      </MainLayout>
    );
  }

  const steps = pipelineStatus?.steps ?? [];
  const doneCount = steps.filter((s) => s.status === 'done').length;
  const progress = steps.length > 0 ? (doneCount / steps.length) * 100 : 0;
  const isDone = pipelineStatus?.status === 'done';
  const isError = pipelineStatus?.status === 'error';

  return (
    <MainLayout>
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold">分析実行中</h1>
          <p className="text-muted-foreground mt-1">Task ID: {taskId}</p>
        </div>

        {/* Progress Bar */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>進捗</span>
              <span className="text-sm font-normal text-muted-foreground">
                {doneCount}/{steps.length} ステップ完了
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Progress value={progress} className="mb-4" />
            <PipelineProgress steps={steps} currentStep={pipelineStatus?.current_step ?? 0} />
          </CardContent>
        </Card>

        {/* Error */}
        {isError && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 space-y-2">
            <p className="font-medium text-destructive">エラーが発生しました</p>
            <p className="text-sm text-destructive/80">{pipelineStatus?.error}</p>
            <Button variant="outline" size="sm" onClick={() => router.push('/company')}>
              <RotateCcw className="size-3" />
              やり直す
            </Button>
          </div>
        )}

        {/* Done */}
        {isDone && (
          <Card className="border-green-500/50 bg-green-50">
            <CardContent className="pt-6">
              <div className="text-center space-y-3">
                <p className="text-lg font-semibold text-green-700">分析完了</p>
                <Button size="lg" onClick={() => router.push(`/report/${taskId}`)}>
                  レポートを表示 <ArrowRight className="size-4" />
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </MainLayout>
  );
}
