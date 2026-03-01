'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { MainLayout } from '@/components/layout/MainLayout';
import { StockCodeInput } from '@/components/forms/StockCodeInput';
import { FiscalYearSelect } from '@/components/forms/FiscalYearSelect';
import { LevelSelect } from '@/components/forms/LevelSelect';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useAnalysisStore } from '@/store/analysisStore';
import { startAnalysis } from '@/lib/api/client';
import { Loader2, Play, Building2, FileText } from 'lucide-react';
import type { CompanyInfo } from '@/types';

export default function CompanyPage() {
  const router = useRouter();
  const {
    selectedCompany,
    setSelectedCompany,
    fiscalYear,
    setFiscalYear,
    level,
    setLevel,
    setTaskId,
    addHistory,
  } = useAnalysisStore();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSelect = (company: CompanyInfo) => {
    setSelectedCompany(company);
    setError('');
  };

  const handleAnalyze = async () => {
    if (!selectedCompany) {
      setError('企業を選択してください');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const resp = await startAnalysis({
        sec_code: selectedCompany.sec_code,
        edinet_code: selectedCompany.edinet_code,
        company_name: selectedCompany.company_name,
        fiscal_year: fiscalYear,
        level: level,
        use_mock: true,
      });

      setTaskId(resp.task_id);
      addHistory({
        taskId: resp.task_id,
        companyName: selectedCompany.company_name,
        date: new Date().toLocaleDateString('ja-JP'),
        level,
      });

      router.push('/analysis');
    } catch (e) {
      setError(e instanceof Error ? e.message : '分析開始に失敗しました');
    } finally {
      setLoading(false);
    }
  };

  return (
    <MainLayout>
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold">企業検索 & 分析開始</h1>
          <p className="text-muted-foreground mt-1">
            証券コードまたは企業名で検索し、開示変更分析を開始します
          </p>
        </div>

        {/* Search */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="size-5" />
              企業検索
            </CardTitle>
            <CardDescription>証券コード(4桁)または企業名を入力してください</CardDescription>
          </CardHeader>
          <CardContent>
            <StockCodeInput onSelect={handleSelect} />
          </CardContent>
        </Card>

        {/* Selected Company Info */}
        {selectedCompany && (
          <Card className="border-primary/50">
            <CardHeader>
              <CardTitle className="text-lg">{selectedCompany.company_name}</CardTitle>
              <CardDescription className="flex gap-2 flex-wrap">
                {selectedCompany.sec_code && (
                  <Badge variant="secondary">{selectedCompany.sec_code}</Badge>
                )}
                <Badge variant="outline">{selectedCompany.edinet_code}</Badge>
                {selectedCompany.industry && (
                  <Badge variant="outline">{selectedCompany.industry}</Badge>
                )}
                {selectedCompany.listing && (
                  <Badge variant="outline">{selectedCompany.listing}</Badge>
                )}
              </CardDescription>
            </CardHeader>
          </Card>
        )}

        {/* Analysis Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="size-5" />
              分析設定
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <FiscalYearSelect value={fiscalYear} onChange={setFiscalYear} />
            <LevelSelect value={level} onChange={setLevel} />
          </CardContent>
        </Card>

        {/* Error */}
        {error && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Start Button */}
        <Button
          size="lg"
          className="w-full"
          onClick={handleAnalyze}
          disabled={loading || !selectedCompany}
        >
          {loading ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              分析起動中...
            </>
          ) : (
            <>
              <Play className="size-4" />
              分析開始
            </>
          )}
        </Button>
      </div>
    </MainLayout>
  );
}
