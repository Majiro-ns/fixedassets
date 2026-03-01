'use client';

import { useState } from 'react';
import { MainLayout } from '@/components/layout/MainLayout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { getEdinetDocuments, startAnalysis } from '@/lib/api/client';
import { useAnalysisStore } from '@/store/analysisStore';
import { useRouter } from 'next/navigation';
import type { EdinetDocument } from '@/types';
import { Database, Search, Loader2, Play, Calendar } from 'lucide-react';

export default function EdinetPage() {
  const router = useRouter();
  const { setTaskId, addHistory } = useAnalysisStore();
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [documents, setDocuments] = useState<EdinetDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchDone, setSearchDone] = useState(false);
  const [analyzing, setAnalyzing] = useState<string | null>(null);

  const handleSearch = async () => {
    setLoading(true);
    try {
      const resp = await getEdinetDocuments(date);
      setDocuments(resp.documents);
      setSearchDone(true);
    } catch {
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyze = async (doc: EdinetDocument) => {
    setAnalyzing(doc.doc_id);
    try {
      const resp = await startAnalysis({
        edinet_code: doc.edinet_code,
        company_name: doc.filer_name,
        pdf_doc_id: doc.doc_id,
        use_mock: true,
      });
      setTaskId(resp.task_id);
      addHistory({
        taskId: resp.task_id,
        companyName: doc.filer_name,
        date: new Date().toLocaleDateString('ja-JP'),
        level: '竹',
      });
      router.push('/analysis');
    } catch {
      // ignore
    } finally {
      setAnalyzing(null);
    }
  };

  return (
    <MainLayout>
      <div className="max-w-5xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Database className="size-6" />
            EDINET 文書ブラウザ
          </h1>
          <p className="text-muted-foreground mt-1">
            金融庁EDINETから有価証券報告書を日付で検索し、直接分析を開始できます
          </p>
        </div>

        {/* Search */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Calendar className="size-5" />
              日付で検索
            </CardTitle>
            <CardDescription>書類提出日を指定して有価証券報告書を検索</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col sm:flex-row gap-3">
              <Input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="w-full sm:w-48"
              />
              <Button onClick={handleSearch} disabled={loading}>
                {loading ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Search className="size-4" />
                )}
                検索
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Results */}
        {searchDone && (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>検索結果</span>
                <Badge variant="secondary">{documents.length}件</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {documents.length === 0 ? (
                <p className="text-sm text-muted-foreground">該当する書類が見つかりませんでした</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>書類ID</TableHead>
                        <TableHead>提出者</TableHead>
                        <TableHead>EDINETコード</TableHead>
                        <TableHead>決算期末</TableHead>
                        <TableHead>提出日時</TableHead>
                        <TableHead className="w-24">操作</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {documents.map((doc) => (
                        <TableRow key={doc.doc_id}>
                          <TableCell className="font-mono text-xs">{doc.doc_id}</TableCell>
                          <TableCell className="font-medium">{doc.filer_name}</TableCell>
                          <TableCell>
                            <Badge variant="outline">{doc.edinet_code}</Badge>
                          </TableCell>
                          <TableCell className="text-sm">{doc.period_end}</TableCell>
                          <TableCell className="text-sm">{doc.submit_date_time}</TableCell>
                          <TableCell>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleAnalyze(doc)}
                              disabled={analyzing === doc.doc_id}
                            >
                              {analyzing === doc.doc_id ? (
                                <Loader2 className="size-3 animate-spin" />
                              ) : (
                                <Play className="size-3" />
                              )}
                              分析
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </MainLayout>
  );
}
