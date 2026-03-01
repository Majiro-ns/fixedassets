'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { MainLayout } from '@/components/layout/MainLayout';
import { GapSummaryCard } from '@/components/analysis/GapSummaryCard';
import { GapTable } from '@/components/analysis/GapTable';
import { ProposalCard } from '@/components/analysis/ProposalCard';
import { ReportViewer } from '@/components/report/ReportViewer';
import { ExportButtons } from '@/components/report/ExportButtons';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useAnalysisStore } from '@/store/analysisStore';
import { getTaskStatus } from '@/lib/api/client';
import type { AnalysisResult } from '@/types';
import { ArrowLeft, Loader2 } from 'lucide-react';

export default function ReportPage() {
  const params = useParams();
  const router = useRouter();
  const taskId = typeof params.taskId === 'string' ? params.taskId : (params.taskId?.[0] ?? '');
  const storeResult = useAnalysisStore((s) => s.result);
  const [result, setResult] = useState<AnalysisResult | null>(storeResult);
  const [loading, setLoading] = useState(!storeResult);

  useEffect(() => {
    if (storeResult) {
      setResult(storeResult);
      setLoading(false);
      return;
    }

    // Fetch from API if not in store
    async function load() {
      try {
        const status = await getTaskStatus(taskId);
        if (status.result) {
          setResult(status.result);
        }
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [taskId, storeResult]);

  if (loading) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center py-12">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      </MainLayout>
    );
  }

  if (!result) {
    return (
      <MainLayout>
        <div className="text-center py-12 space-y-4">
          <p className="text-muted-foreground">レポートが見つかりません (Task: {taskId})</p>
          <Button variant="outline" onClick={() => router.push('/company')}>
            <ArrowLeft className="size-3" />
            企業検索に戻る
          </Button>
        </div>
      </MainLayout>
    );
  }

  const gapsWithGap = result.gaps.filter((g) => g.has_gap);

  return (
    <MainLayout>
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">{result.company_name}</h1>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant="secondary">{result.fiscal_year}年度</Badge>
              <Badge variant="outline">提案レベル: {result.level}</Badge>
              <Badge variant="outline">Task: {taskId}</Badge>
            </div>
          </div>
          <ExportButtons markdown={result.report_markdown} companyName={result.company_name} />
        </div>

        {/* Tabs */}
        <Tabs defaultValue="summary">
          <TabsList className="flex-wrap h-auto">
            <TabsTrigger value="summary">サマリ</TabsTrigger>
            <TabsTrigger value="gaps">ギャップ ({gapsWithGap.length})</TabsTrigger>
            <TabsTrigger value="proposals">提案 ({result.proposals.length})</TabsTrigger>
            <TabsTrigger value="report">全文</TabsTrigger>
          </TabsList>

          {/* Summary */}
          <TabsContent value="summary">
            <div className="space-y-4">
              <GapSummaryCard summary={result.summary} />
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <Card>
                  <CardContent className="pt-4 text-center">
                    <div className="text-2xl font-bold">{result.gaps.length}</div>
                    <div className="text-xs text-muted-foreground">分析項目</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-4 text-center">
                    <div className="text-2xl font-bold text-red-600">{gapsWithGap.length}</div>
                    <div className="text-xs text-muted-foreground">ギャップあり</div>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="pt-4 text-center">
                    <div className="text-2xl font-bold text-green-600">
                      {result.no_gap_items.length}
                    </div>
                    <div className="text-xs text-muted-foreground">充足済み</div>
                  </CardContent>
                </Card>
              </div>
            </div>
          </TabsContent>

          {/* Gap Table */}
          <TabsContent value="gaps">
            <Card>
              <CardHeader>
                <CardTitle>ギャップ一覧</CardTitle>
              </CardHeader>
              <CardContent>
                <GapTable gaps={result.gaps} />
              </CardContent>
            </Card>
          </TabsContent>

          {/* Proposals */}
          <TabsContent value="proposals">
            <ProposalCard proposals={result.proposals} />
          </TabsContent>

          {/* Full Report */}
          <TabsContent value="report">
            <Card>
              <CardContent className="pt-6">
                <ReportViewer markdown={result.report_markdown} />
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </MainLayout>
  );
}
