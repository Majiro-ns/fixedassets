'use client';

import { useRef, useState } from 'react';
import { FileText, Loader2, AlertTriangle, CheckCircle2, Upload } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { useTrainingDataStore } from '@/store/trainingDataStore';
import type { TrainingRecord } from '@/types/training_data';

// ─── PdfTrainingImportCard ────────────────────────────────────────────

export function PdfTrainingImportCard() {
  // NEXT_PUBLIC_PDF_TRAINING_ENABLED=1 の場合のみ表示
  if (process.env.NEXT_PUBLIC_PDF_TRAINING_ENABLED !== '1') {
    return null;
  }

  return <PdfTrainingImportCardInner />;
}

// ─── Inner component（フック使用のため分離） ──────────────────────────

const PREVIEW_LIMIT = 10;

function PdfTrainingImportCardInner() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewRecords, setPreviewRecords] = useState<TrainingRecord[] | null>(null);
  const [importedCount, setImportedCount] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { addRecords } = useTrainingDataStore();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
    setError(null);
    setPreviewRecords(null);
    setImportedCount(null);
  };

  const handleExtract = async () => {
    if (!selectedFile) return;
    setIsLoading(true);
    setError(null);
    setPreviewRecords(null);
    setImportedCount(null);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const res = await fetch('/api/import_pdf_training', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`API error ${res.status}: ${text}`);
      }

      const data = (await res.json()) as { records: TrainingRecord[] };
      setPreviewRecords(data.records);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'PDF抽出中にエラーが発生しました');
    } finally {
      setIsLoading(false);
    }
  };

  const handleImport = () => {
    if (!previewRecords || previewRecords.length === 0) return;
    addRecords(previewRecords);
    setImportedCount(previewRecords.length);
    setPreviewRecords(null);
    setSelectedFile(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileText className="size-5 text-blue-600" />
          教師データ PDFインポート
        </CardTitle>
        <CardDescription>
          請求書・見積書などのPDFから明細を抽出して、教師データとして登録します。
          抽出後、内容を確認してからインポートしてください。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* ファイル選択エリア */}
        <div
          className="flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-muted-foreground/30 p-6 cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() => inputRef.current?.click()}
        >
          <Upload className="size-8 text-muted-foreground" />
          <div className="text-center">
            {selectedFile ? (
              <p className="text-sm font-medium text-foreground">{selectedFile.name}</p>
            ) : (
              <>
                <p className="text-sm font-medium">クリックしてPDFを選択</p>
                <p className="text-xs text-muted-foreground mt-0.5">PDF ファイルのみ対応</p>
              </>
            )}
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={handleFileChange}
          />
        </div>

        {/* エラー表示 */}
        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertTitle>エラー</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* 抽出ボタン */}
        <Button
          type="button"
          disabled={!selectedFile || isLoading}
          onClick={handleExtract}
          size="lg"
          className="w-full"
        >
          {isLoading ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              PDF抽出中...
            </>
          ) : (
            <>
              <FileText className="size-4" />
              PDFから明細を抽出
            </>
          )}
        </Button>

        {/* プレビュー */}
        {previewRecords && previewRecords.length > 0 && (
          <div className="space-y-3">
            <p className="text-sm font-medium">
              抽出結果（{previewRecords.length} 件中 最大 {PREVIEW_LIMIT} 件表示）
            </p>
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead className="bg-muted">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">品目</th>
                    <th className="px-3 py-2 text-right font-medium">金額（円）</th>
                    <th className="px-3 py-2 text-left font-medium">分類</th>
                    <th className="px-3 py-2 text-left font-medium">備考</th>
                  </tr>
                </thead>
                <tbody>
                  {previewRecords.slice(0, PREVIEW_LIMIT).map((rec, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-3 py-1.5">{rec.item}</td>
                      <td className="px-3 py-1.5 text-right">{rec.amount.toLocaleString()}</td>
                      <td className="px-3 py-1.5">
                        <Badge variant="warning" className="text-xs">
                          {rec.label}
                        </Badge>
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{rec.notes ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* インポートボタン */}
            <Button
              type="button"
              onClick={handleImport}
              size="lg"
              className="w-full"
            >
              <Upload className="size-4" />
              {previewRecords.length} 件を教師データとしてインポート
            </Button>
          </div>
        )}

        {/* インポート成功メッセージ */}
        {importedCount !== null && (
          <Alert>
            <CheckCircle2 className="size-4 text-green-600" />
            <AlertTitle>インポート完了</AlertTitle>
            <AlertDescription>{importedCount} 件を教師データとして登録しました。分類は「要確認」になっています。必要に応じて修正してください。</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}
