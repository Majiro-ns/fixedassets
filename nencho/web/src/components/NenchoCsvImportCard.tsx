'use client';

import { useRef, useState } from 'react';
import { Upload, AlertTriangle, CheckCircle2, Trash2, Info } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { useNenchoTrainingStore } from '@/store/nenchoTrainingStore';
import type { NenchoCsvImportResult, NenchoCsvRecord } from '@/types/nencho_csv';

// ─── 定数 ────────────────────────────────────────────────────────────────────
const PREVIEW_LIMIT = 10;

// ─── CSV パース ───────────────────────────────────────────────────────────────
function parseNenchoCsv(text: string): NenchoCsvImportResult {
  // BOM 除去（Excel UTF-8 BOM 対応）
  const cleaned = text.startsWith('\uFEFF') ? text.slice(1) : text;
  const lines = cleaned.split(/\r?\n/).filter((l) => l.trim() !== '');

  if (lines.length < 2) {
    return { records: [], errorRows: [{ row: 0, reason: 'ヘッダー行またはデータ行がありません' }] };
  }

  const headers = lines[0].split(',').map((h) => h.trim());

  // 必須列インデックス
  const nameIdx   = headers.indexOf('従業員名');
  const salaryIdx = headers.indexOf('給与収入');
  const socialIdx = headers.indexOf('社会保険料');

  if (nameIdx === -1 || salaryIdx === -1 || socialIdx === -1) {
    return {
      records: [],
      errorRows: [{ row: 1, reason: '必須列（従業員名,給与収入,社会保険料）が見つかりません' }],
    };
  }

  // 任意列インデックス
  const depIdx      = headers.indexOf('扶養人数');
  const lifeNewIdx  = headers.indexOf('生命保険料_新');
  const lifeOldIdx  = headers.indexOf('生命保険料_旧');
  const spouseIdx   = headers.indexOf('配偶者あり');
  const notesIdx    = headers.indexOf('備考');

  const records: NenchoCsvRecord[] = [];
  const errorRows: Array<{ row: number; reason: string }> = [];

  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',').map((c) => c.trim());
    const rowNum = i + 1;

    const name      = cols[nameIdx] ?? '';
    const salaryRaw = cols[salaryIdx] ?? '';
    const socialRaw = cols[socialIdx] ?? '';

    // 従業員名バリデーション
    if (!name) {
      errorRows.push({ row: rowNum, reason: '従業員名が空です' });
      continue;
    }

    // 給与収入パース
    const salary = parseInt(salaryRaw.replace(/,/g, ''), 10);
    if (isNaN(salary) || salary < 0) {
      errorRows.push({ row: rowNum, reason: `給与収入が不正です: "${salaryRaw}"` });
      continue;
    }

    // 社会保険料パース
    const social = parseInt(socialRaw.replace(/,/g, ''), 10);
    if (isNaN(social) || social < 0) {
      errorRows.push({ row: rowNum, reason: `社会保険料が不正です: "${socialRaw}"` });
      continue;
    }

    // 任意列パース（エラーは警告扱いでスキップしない）
    const depRaw    = depIdx >= 0 ? (cols[depIdx] ?? '') : '';
    const lifeNewRaw = lifeNewIdx >= 0 ? (cols[lifeNewIdx] ?? '') : '';
    const lifeOldRaw = lifeOldIdx >= 0 ? (cols[lifeOldIdx] ?? '') : '';
    const spouseRaw = spouseIdx >= 0 ? (cols[spouseIdx] ?? '') : '';
    const notes     = notesIdx >= 0 ? (cols[notesIdx] ?? '') : '';

    const record: NenchoCsvRecord = {
      employee_name: name,
      salary_income: salary,
      social_insurance_paid: social,
    };

    const dep = depRaw ? parseInt(depRaw, 10) : NaN;
    if (!isNaN(dep) && dep >= 0) record.dependent_count = dep;

    const lifeNew = lifeNewRaw ? parseInt(lifeNewRaw.replace(/,/g, ''), 10) : NaN;
    if (!isNaN(lifeNew) && lifeNew >= 0) record.life_insurance_new = lifeNew;

    const lifeOld = lifeOldRaw ? parseInt(lifeOldRaw.replace(/,/g, ''), 10) : NaN;
    if (!isNaN(lifeOld) && lifeOld >= 0) record.life_insurance_old = lifeOld;

    if (spouseRaw.toLowerCase() === 'true') record.has_spouse = true;
    else if (spouseRaw.toLowerCase() === 'false') record.has_spouse = false;

    if (notes) record.notes = notes;

    records.push(record);
  }

  return { records, errorRows };
}

// ─── メインコンポーネント ─────────────────────────────────────────────────────
export function NenchoCsvImportCard() {
  const [parseResult, setParseResult] = useState<NenchoCsvImportResult | null>(null);
  const [importedCount, setImportedCount] = useState<number | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { records: storedRecords, addRecords, clearRecords } = useNenchoTrainingStore();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setImportedCount(null);
    setParseResult(null);

    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      setParseResult(parseNenchoCsv(text));
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
          <Upload className="size-5" />
          源泉徴収票 CSV インポート
        </CardTitle>
        <CardDescription>
          源泉徴収票データを CSV ファイルから一括取込し、教師データとして登録します。
          必須列:{' '}
          <code className="text-xs bg-muted px-1 rounded">従業員名,給与収入,社会保険料</code>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">

        {/* セキュリティ注意 */}
        <Alert variant="default">
          <Info className="size-4" />
          <AlertTitle>個人情報の取り扱いについて</AlertTitle>
          <AlertDescription>
            取り込んだデータはブラウザの localStorage にのみ保存され、外部には送信されません。
            元の CSV ファイルは取込後に削除することを推奨します（要件定義 F-08 準拠）。
          </AlertDescription>
        </Alert>

        {/* 登録済み件数 + 全件削除 */}
        <div className="flex items-center gap-3">
          <Badge variant="secondary">登録済み: {storedRecords.length} 件</Badge>
          {storedRecords.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClear}
              className="text-destructive hover:text-destructive"
            >
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
              <p className="text-sm font-medium">{fileName}</p>
            ) : (
              <>
                <p className="text-sm font-medium">クリックして CSV を選択</p>
                <p className="text-xs text-muted-foreground mt-0.5">UTF-8 / BOM付き可（Excel出力対応）</p>
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

        {/* プレビュー */}
        {parseResult && parseResult.records.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-medium">
              プレビュー（{parseResult.records.length} 件中 最大 {PREVIEW_LIMIT} 件表示）
            </p>
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full text-xs">
                <thead className="bg-muted">
                  <tr>
                    <th className="px-3 py-2 text-left">従業員名</th>
                    <th className="px-3 py-2 text-right">給与収入</th>
                    <th className="px-3 py-2 text-right">社会保険料</th>
                    <th className="px-3 py-2 text-center">扶養人数</th>
                    <th className="px-3 py-2 text-center">配偶者</th>
                    <th className="px-3 py-2 text-left">備考</th>
                  </tr>
                </thead>
                <tbody>
                  {parseResult.records.slice(0, PREVIEW_LIMIT).map((rec, i) => (
                    <tr key={i} className="border-t">
                      <td className="px-3 py-1.5">{rec.employee_name}</td>
                      <td className="px-3 py-1.5 text-right">{rec.salary_income.toLocaleString()}</td>
                      <td className="px-3 py-1.5 text-right">{rec.social_insurance_paid.toLocaleString()}</td>
                      <td className="px-3 py-1.5 text-center">{rec.dependent_count ?? 0}</td>
                      <td className="px-3 py-1.5 text-center">{rec.has_spouse ? '○' : '—'}</td>
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
            <AlertTitle>エラー行 ({parseResult.errorRows.length} 件) — スキップされます</AlertTitle>
            <AlertDescription>
              <ul className="mt-1 space-y-0.5">
                {parseResult.errorRows.map((e, i) => (
                  <li key={i} className="text-xs">行 {e.row}: {e.reason}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {/* 成功メッセージ */}
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
          {parseResult && parseResult.records.length > 0
            ? `${parseResult.records.length} 件をインポート`
            : 'CSV を選択してください'}
        </Button>
      </CardContent>
    </Card>
  );
}
