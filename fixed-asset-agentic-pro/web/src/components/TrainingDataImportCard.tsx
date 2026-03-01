'use client';

import { useRef, useState } from 'react';
import { Upload, AlertTriangle, CheckCircle2, Trash2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { useTrainingDataStore } from '@/store/trainingDataStore';
import type { CsvImportResult, TrainingLabel, TrainingRecord } from '@/types/training_data';

// ─── 定数 ─────────────────────────────────────────────────────────────
const VALID_LABELS: TrainingLabel[] = ['固定資産', '費用', '要確認'];
const PREVIEW_LIMIT = 10;

// ─── CSV パース ────────────────────────────────────────────────────────
function parseCsv(text: string): CsvImportResult {
  // BOM 除去
  const cleaned = text.startsWith('\uFEFF') ? text.slice(1) : text;
  const lines = cleaned.split(/\r?\n/).filter((l) => l.trim() !== '');

  if (lines.length < 2) {
    return { records: [], errorRows: [{ row: 0, reason: 'ヘッダー行またはデータ行がありません' }] };
  }

  // ヘッダー検証
  const headers = lines[0].split(',').map((h) => h.trim());
  const itemIdx = headers.indexOf('品目');
  const amountIdx = headers.indexOf('金額');
  const labelIdx = headers.indexOf('分類');
  const notesIdx = headers.indexOf('備考');

  if (itemIdx === -1 || amountIdx === -1 || labelIdx === -1) {
    return {
      records: [],
      errorRows: [{ row: 1, reason: '必須列（品目,金額,分類）が見つかりません' }],
    };
  }

  const records: TrainingRecord[] = [];
  const errorRows: Array<{ row: number; reason: string }> = [];

  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',').map((c) => c.trim());
    const rowNum = i + 1;

    const item = cols[itemIdx] ?? '';
    const amountRaw = cols[amountIdx] ?? '';
    const labelRaw = cols[labelIdx] ?? '';
    const notes = notesIdx >= 0 ? (cols[notesIdx] ?? '') : '';

    if (!item) {
      errorRows.push({ row: rowNum, reason: '品目が空です' });
      continue;
    }

    const amountNum = parseInt(amountRaw.replace(/,/g, ''), 10);
    if (isNaN(amountNum)) {
      errorRows.push({ row: rowNum, reason: `金額が数値ではありません: "${amountRaw}"` });
      continue;
    }

    if (!(VALID_LABELS as string[]).includes(labelRaw)) {
      errorRows.push({ row: rowNum, reason: `分類値が不正です: "${labelRaw}"（固定資産/費用/要確認）` });
      continue;
    }

    records.push({
      item,
      amount: amountNum,
      label: labelRaw as TrainingLabel,
      ...(notes ? { notes } : {}),
    });
  }

  return { records, errorRows };
}

// ─── TrainingDataImportCard ───────────────────────────────────────────
export function TrainingDataImportCard() {
  const [parseResult, setParseResult] = useState<CsvImportResult | null>(null);
  const [importedCount, setImportedCount] = useState<number | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { records: storedRecords, addRecords, clearRecords } = useTrainingDataStore();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setImportedCount(null);
    setParseResult(null);

    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      const result = parseCsv(text);
      setParseResult(result);
    };
    reader.readAsText(file, 'UTF-8');
  };

  const handleImport = () => {
    if (!parseResult || parseResult.records.length === 0) return;
    addRecords(parseResult.records);
    setImportedCount(parseResult.records.length);
    setParseResult(null);
    setFileName(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const handleClear = () => {
    clearRecords();
    setImportedCount(null);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Upload className="size-5 text-purple-600" />
          教師データ CSVインポート
        </CardTitle>
        <CardDescription>
          固定資産台帳の CSV をインポートして、AI の Few-shot 学習用教師データとして登録します。
          必須列: <code className="text-xs bg-muted px-1 rounded">品目,金額,分類</code>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* 登録済み件数 */}
        <div className="flex items-center gap-3">
          <Badge variant="secondary">登録済み: {storedRecords.length} 件</Badge>
          {storedRecords.length > 0 && (
            <Button variant="ghost" size="sm" onClick={handleClear} className="text-destructive hover:text-destructive">
              <Trash2 className="size-3.5 mr-1" />
              全件削除
            </Button>
          )}
        </div>

        {/* ファイル選択エリア */}
        <div
          className="flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-muted-foreground/30 p-6 cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() => inputRef.current?.click()}
        >
          <Upload className="size-8 text-muted-foreground" />
          <div className="text-center">
            {fileName ? (
              <p className="text-sm font-medium text-foreground">{fileName}</p>
            ) : (
              <>
                <p className="text-sm font-medium">クリックして CSV を選択</p>
                <p className="text-xs text-muted-foreground mt-0.5">CSV ファイルのみ対応（UTF-8 / BOM付き可）</p>
              </>
            )}
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={handleFileChange}
          />
        </div>

        {/* パース結果プレビュー */}
        {parseResult && parseResult.records.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-medium">
              プレビュー（{parseResult.records.length} 件中 最大 {PREVIEW_LIMIT} 件表示）
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
                  {parseResult.records.slice(0, PREVIEW_LIMIT).map((rec, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-3 py-1.5">{rec.item}</td>
                      <td className="px-3 py-1.5 text-right">{rec.amount.toLocaleString()}</td>
                      <td className="px-3 py-1.5">
                        <Badge
                          variant={
                            rec.label === '固定資産'
                              ? 'default'
                              : rec.label === '費用'
                              ? 'success'
                              : 'warning'
                          }
                          className="text-xs"
                        >
                          {rec.label}
                        </Badge>
                      </td>
                      <td className="px-3 py-1.5 text-muted-foreground">{rec.notes ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* エラー行一覧 */}
        {parseResult && parseResult.errorRows.length > 0 && (
          <Alert variant="warning">
            <AlertTriangle className="size-4" />
            <AlertTitle>エラー行 ({parseResult.errorRows.length} 件)</AlertTitle>
            <AlertDescription>
              <ul className="mt-1 space-y-0.5">
                {parseResult.errorRows.map((e, i) => (
                  <li key={i} className="text-xs">
                    行 {e.row}: {e.reason}
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {/* インポート成功メッセージ */}
        {importedCount !== null && (
          <Alert>
            <CheckCircle2 className="size-4 text-green-600" />
            <AlertTitle>インポート完了</AlertTitle>
            <AlertDescription>{importedCount} 件を教師データとして登録しました。</AlertDescription>
          </Alert>
        )}

        {/* インポートボタン */}
        <Button
          type="button"
          disabled={!parseResult || parseResult.records.length === 0}
          onClick={handleImport}
          size="lg"
          className="w-full"
        >
          <Upload className="size-4" />
          {parseResult
            ? `${parseResult.records.length} 件をインポート`
            : 'CSV を選択してください'}
        </Button>
      </CardContent>
    </Card>
  );
}
