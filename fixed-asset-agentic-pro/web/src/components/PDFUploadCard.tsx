'use client';

import { useRef, useState, useCallback } from 'react';
import { FileText, Loader2, AlertTriangle, Upload, X, PenLine } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { classifyFromPDF } from '@/lib/api';
import type { ClassifyResponse } from '@/types/classify';

const MAX_FILES = 10;

// ─── Props ────────────────────────────────────────────────────────────

interface PDFUploadCardProps {
  onResult: (result: ClassifyResponse) => void;
  onManualInput?: () => void;
}

// ─── ファイル処理結果 ──────────────────────────────────────────────────

interface FileProcessResult {
  file: File;
  status: 'pending' | 'processing' | 'done' | 'error';
  error?: string;
}

// ─── PDFUploadCard ────────────────────────────────────────────────────

export function PDFUploadCard({ onResult, onManualInput }: PDFUploadCardProps) {
  const [files, setFiles] = useState<FileProcessResult[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processedCount, setProcessedCount] = useState(0);
  const [extractionFailed, setExtractionFailed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // ─── ファイル追加 ──────────────────────────────────────────────────

  const addFiles = useCallback((incoming: File[]) => {
    const pdfs = incoming.filter((f) => f.type === 'application/pdf' || f.name.endsWith('.pdf'));
    setFiles((prev) => {
      const combined = [...prev, ...pdfs.map((f): FileProcessResult => ({ file: f, status: 'pending' }))];
      return combined.slice(0, MAX_FILES);
    });
    setExtractionFailed(false);
  }, []);

  // ─── ドラッグ＆ドロップ ────────────────────────────────────────────

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    addFiles(Array.from(e.dataTransfer.files));
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(e.target.files ?? []));
    e.target.value = '';
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // ─── 判定実行 ──────────────────────────────────────────────────────

  const handleSubmit = async () => {
    if (files.length === 0 || isProcessing) return;
    setIsProcessing(true);
    setProcessedCount(0);
    setExtractionFailed(false);

    let lastResult: ClassifyResponse | null = null;
    let anyFailed = false;

    for (let i = 0; i < files.length; i++) {
      setFiles((prev) =>
        prev.map((f, idx) => (idx === i ? { ...f, status: 'processing' } : f))
      );
      try {
        const result = await classifyFromPDF(files[i].file, true);
        lastResult = result;
        setFiles((prev) =>
          prev.map((f, idx) => (idx === i ? { ...f, status: 'done' } : f))
        );
      } catch (err) {
        anyFailed = true;
        const msg = err instanceof Error ? err.message : 'PDF判定中にエラーが発生しました';
        setFiles((prev) =>
          prev.map((f, idx) => (idx === i ? { ...f, status: 'error', error: msg } : f))
        );
      }
      setProcessedCount(i + 1);
    }

    setIsProcessing(false);
    if (anyFailed && !lastResult) {
      setExtractionFailed(true);
    } else if (lastResult) {
      onResult(lastResult);
    }
  };

  const totalFiles = files.length;
  const doneCount = files.filter((f) => f.status === 'done').length;

  return (
    <Card className="border-2 border-primary/20">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-xl">
          <FileText className="size-6 text-primary" />
          PDFをアップロードして判定
        </CardTitle>
        <CardDescription>
          請求書・領収書などのPDFをアップロードするだけで、AIが固定資産・費用を自動判定します
          （最大{MAX_FILES}ファイル/回）
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* ドロップゾーン */}
        <div
          data-testid="drop-zone"
          className={`flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-10 cursor-pointer transition-colors
            ${isDragOver ? 'border-primary bg-primary/5' : 'border-muted-foreground/30 hover:border-primary/50'}
            ${files.length >= MAX_FILES ? 'opacity-50 pointer-events-none' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <Upload className={`size-10 ${isDragOver ? 'text-primary' : 'text-muted-foreground'}`} />
          <div className="text-center">
            <p className="text-base font-semibold">
              {isDragOver ? 'ここにドロップ' : 'ドラッグ＆ドロップ、またはクリックして選択'}
            </p>
            <p className="text-sm text-muted-foreground mt-1">
              PDFファイルのみ対応 · 最大{MAX_FILES}ファイル
            </p>
          </div>
          {files.length > 0 && files.length < MAX_FILES && (
            <Badge variant="secondary">{files.length}件選択中</Badge>
          )}
          {files.length >= MAX_FILES && (
            <Badge variant="warning">上限({MAX_FILES}件)に達しました</Badge>
          )}
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            multiple
            className="hidden"
            onChange={handleFileChange}
            data-testid="file-input"
          />
        </div>

        {/* ファイルリスト */}
        {files.length > 0 && (
          <div className="space-y-1.5">
            {files.map((item, i) => (
              <div
                key={i}
                className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
              >
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <span className="flex-1 truncate">{item.file.name}</span>
                {item.status === 'processing' && (
                  <Loader2 className="size-4 animate-spin text-primary" />
                )}
                {item.status === 'done' && (
                  <Badge variant="success" className="text-xs">完了</Badge>
                )}
                {item.status === 'error' && (
                  <Badge variant="destructive" className="text-xs">エラー</Badge>
                )}
                {item.status === 'pending' && !isProcessing && (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); removeFile(i); }}
                    className="text-muted-foreground hover:text-destructive transition-colors"
                    aria-label="削除"
                  >
                    <X className="size-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 進行状態 */}
        {isProcessing && (
          <p className="text-sm text-primary text-center font-medium">
            {processedCount} / {totalFiles} 処理中...
          </p>
        )}

        {/* 抽出失敗時の誘導 */}
        {extractionFailed && (
          <Alert variant="warning">
            <AlertTriangle className="size-4" />
            <AlertTitle>PDFの読み取りに失敗しました</AlertTitle>
            <AlertDescription className="space-y-2">
              <p>PDFの内容を正常に読み取れませんでした。手入力モードで続行できます。</p>
              {onManualInput && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onManualInput}
                  className="flex items-center gap-1.5"
                >
                  <PenLine className="size-4" />
                  手入力モードへ
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}

        {/* エラー詳細 */}
        {files.some((f) => f.status === 'error' && f.error) && (
          <div className="space-y-1">
            {files
              .filter((f) => f.status === 'error' && f.error)
              .map((f, i) => (
                <p key={i} className="text-xs text-destructive">
                  {f.file.name}: {f.error}
                </p>
              ))}
          </div>
        )}

        {/* アクションボタン */}
        <div className="flex flex-col gap-2">
          <Button
            type="button"
            disabled={files.length === 0 || isProcessing}
            onClick={handleSubmit}
            size="lg"
            className="w-full"
          >
            {isProcessing ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                {processedCount} / {totalFiles} 判定中...
              </>
            ) : (
              <>
                <FileText className="size-4" />
                {files.length > 0 ? `${files.length}件を判定する` : 'PDFを選択してください'}
              </>
            )}
          </Button>

          {onManualInput && (
            <button
              type="button"
              className="text-sm text-muted-foreground hover:text-foreground text-center underline underline-offset-2 transition-colors"
              onClick={onManualInput}
            >
              PDFがない場合は手入力モードへ
            </button>
          )}
        </div>

        {/* 完了サマリ */}
        {!isProcessing && doneCount > 0 && doneCount === totalFiles && (
          <p className="text-sm text-green-600 text-center font-medium">
            ✅ {doneCount}件の判定が完了しました
          </p>
        )}
      </CardContent>
    </Card>
  );
}
