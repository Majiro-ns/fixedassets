'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  Building2,
  Sparkles,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  Loader2,
  Upload,
  FileText,
  PenLine,
} from 'lucide-react';

import { MainLayout } from '@/components/layout/MainLayout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { classifyAsset } from '@/lib/api';
import { convertV2ToLineItems } from '@/lib/classify_pdf_v2';
import type { ClassifyRequest, ClassifyResponse, Decision, HistoryEntry } from '@/types/classify';
import type { ClassifyPDFV2Response, V2Summary } from '@/types/classify_pdf_v2';
import type { LineItemWithAction, UserAction } from '@/types/pdf_review';
import { GuidanceWizard } from '@/components/GuidanceWizard';
import { HistoryPanel } from '@/components/HistoryPanel';
import { LineItemsTable } from '@/components/LineItemsTable';
import { PDFUploadCard } from '@/components/PDFUploadCard';
import { PDFReviewSection } from '@/components/PDFReviewSection';
import { TaxBoundaryCard } from '@/components/TaxBoundaryCard';
import { SummaryCard } from '@/components/SummaryCard';
import { NextActionCard } from '@/components/NextActionCard';
import { LeaseInputForm } from '@/components/LeaseInputForm';
import { LeaseResultCard } from '@/components/LeaseResultCard';
import { classifyLease, calculateDepreciation } from '@/lib/api';
import type { LeaseClassifyRequest, LeaseClassifyResponse } from '@/types/classify_lease';
import { DepreciationInputForm } from '@/components/DepreciationInputForm';
import { DepreciationResultCard } from '@/components/DepreciationResultCard';
import type { DepreciationRequest, DepreciationResponse } from '@/types/depreciation';
import { TrainingDataImportCard } from '@/components/TrainingDataImportCard';
import { TrainingDataManagerCard } from '@/components/TrainingDataManagerCard';
import { PdfTrainingImportCard } from '@/components/PdfTrainingImportCard';
import { SimilarCasesPanel } from '@/components/SimilarCasesPanel';
import { useTrainingDataStore } from '@/store/trainingDataStore';

// ─── バリデーションスキーマ ───────────────────────────────────────────
const schema = z.object({
  description: z
    .string()
    .min(5, '5文字以上の説明を入力してください')
    .max(1000, '1000文字以内で入力してください'),
  amount: z
    .string()
    .optional()
    .refine((v) => !v || /^\d+$/.test(v), '半角数字で入力してください'),
  account: z.string().max(50, '50文字以内で入力してください').optional(),
});

type FormValues = z.infer<typeof schema>;

// ─── デモデータ ───────────────────────────────────────────────────────
const DEMO_DATA = [
  { label: 'サーバーラック 200万', description: 'データセンター用サーバーラック購入費', amount: 2000000, account: '工具器具備品' },
  { label: 'エアコン修繕 15万', description: '事務所エアコン修繕費（定期メンテナンス）', amount: 150000, account: '修繕費' },
  { label: 'ライセンス 25万', description: '会計ソフトウェアライセンス年間費用', amount: 250000, account: 'ソフトウエア' },
] as const;

// ─── 判定結果の表示設定 ───────────────────────────────────────────────
const DECISION_CONFIG: Record<
  Decision,
  { label: string; color: string; badgeVariant: 'default' | 'success' | 'warning' | 'destructive' | 'secondary' | 'outline'; icon: React.ElementType }
> = {
  CAPITAL_LIKE: {
    label: '固定資産（資産計上）',
    color: 'text-blue-700',
    badgeVariant: 'default',
    icon: Building2,
  },
  EXPENSE_LIKE: {
    label: '費用（損金算入）',
    color: 'text-green-700',
    badgeVariant: 'success',
    icon: CheckCircle2,
  },
  GUIDANCE: {
    label: '要確認（グレーゾーン）',
    color: 'text-yellow-700',
    badgeVariant: 'warning',
    icon: HelpCircle,
  },
};

// ─── 信頼度バー ───────────────────────────────────────────────────────
function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 80 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-400';
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>信頼度</span>
        <span className="font-medium">{pct}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-secondary overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ─── 結果カードコンポーネント ─────────────────────────────────────────
function ResultCard({ result }: { result: ClassifyResponse }) {
  const cfg = DECISION_CONFIG[result.decision] ?? DECISION_CONFIG.GUIDANCE;
  const DecisionIcon = cfg.icon;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-5 text-primary" />
          AI判定結果
        </CardTitle>
        <CardDescription>AIによる参考情報です。最終判断は専門家にご確認ください</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* 判定メイン */}
        <div className="flex items-center gap-3 p-4 rounded-lg bg-muted/50">
          <DecisionIcon className={`size-7 ${cfg.color}`} />
          <div>
            <p className="text-xs text-muted-foreground mb-0.5">判定</p>
            <p className={`text-lg font-bold ${cfg.color}`}>{cfg.label}</p>
          </div>
          <Badge variant={cfg.badgeVariant} className="ml-auto">
            {result.decision}
          </Badge>
        </div>

        {/* 信頼度 */}
        <ConfidenceBar value={result.confidence} />

        {/* 根拠 */}
        {result.reasons.length > 0 && (
          <div>
            <p className="text-sm font-medium mb-2">判定根拠</p>
            <ul className="space-y-1.5">
              {result.reasons.map((r, i) => (
                <li key={i} className="text-sm text-muted-foreground flex items-start gap-2">
                  <ArrowRight className="size-3.5 mt-0.5 shrink-0 text-primary" />
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* 不足情報 */}
        {result.missing_fields.length > 0 && (
          <Alert variant="warning">
            <AlertTriangle className="size-4" />
            <AlertTitle>追加情報が必要です</AlertTitle>
            <AlertDescription>
              <ul className="mt-1 space-y-0.5">
                {result.missing_fields.map((f, i) => (
                  <li key={i} className="text-xs">・{f}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {/* 確認事項 */}
        {result.questions.length > 0 && (
          <div>
            <p className="text-sm font-medium mb-2">確認事項</p>
            <ul className="space-y-1">
              {result.questions.map((q, i) => (
                <li key={i} className="text-sm text-muted-foreground flex items-start gap-2">
                  <HelpCircle className="size-3.5 mt-0.5 shrink-0 text-yellow-500" />
                  {q}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* 免責 */}
        <p className="text-xs text-muted-foreground border-t pt-4">{result.disclaimer}</p>
      </CardContent>
    </Card>
  );
}

// ─── LineItemWithAction への変換ユーティリティ ─────────────────────────
let _idCounter = 0;
function toLineItemWithAction(result: ClassifyResponse): LineItemWithAction[] {
  if (result.line_items.length > 0) {
    return result.line_items.map((item) => ({
      id: `li-${++_idCounter}`,
      description: item.description,
      amount: item.amount,
      verdict: item.classification,
      confidence: result.confidence,
      rationale: result.reasons[0],
      userAction: 'pending',
      finalVerdict: item.classification,
    }));
  }
  // line_items が空の場合は単件として扱う
  return [
    {
      id: `li-${++_idCounter}`,
      description: 'PDF判定結果',
      amount: undefined,
      verdict: result.decision,
      confidence: result.confidence,
      rationale: result.reasons[0],
      userAction: 'pending',
      finalVerdict: result.decision,
    },
  ];
}

// ─── タブ型 ───────────────────────────────────────────────────────────
type ActiveTab = 'pdf' | 'manual';

// ─── メインページ ─────────────────────────────────────────────────────
export default function HomePage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('pdf');

  // PDF判定用状態
  const [pdfLineItems, setPdfLineItems] = useState<LineItemWithAction[]>([]);
  const [pdfV2Summary, setPdfV2Summary] = useState<V2Summary | null>(null);

  // 手入力判定用状態
  const [result, setResult] = useState<ClassifyResponse | null>(null);
  const [originalRequest, setOriginalRequest] = useState<ClassifyRequest | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>([]);

  // リース・減価償却用
  const [leaseResult, setLeaseResult] = useState<LeaseClassifyResponse | null>(null);
  const [isLeaseLoading, setIsLeaseLoading] = useState(false);
  const [leaseError, setLeaseError] = useState<string | null>(null);
  const [depreciationResult, setDepreciationResult] = useState<DepreciationResponse | null>(null);
  const [isDepreciationLoading, setIsDepreciationLoading] = useState(false);
  const [depreciationError, setDepreciationError] = useState<string | null>(null);

  const trainingRecords = useTrainingDataStore((s) => s.records);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const watchAmount = watch('amount');
  const watchDescription = watch('description');

  // ─── PDF 判定結果ハンドラ ───────────────────────────────────────────
  const handlePdfResult = (res: ClassifyResponse | ClassifyPDFV2Response) => {
    if ('request_id' in res) {
      // v2 レスポンス
      const v2Res = res as ClassifyPDFV2Response;
      setPdfLineItems(convertV2ToLineItems(v2Res));
      setPdfV2Summary(v2Res.summary);
    } else {
      // v1 レスポンス
      setPdfLineItems(toLineItemWithAction(res as ClassifyResponse));
      setPdfV2Summary(null);
    }
  };

  // ─── PDF 明細アクション ────────────────────────────────────────────
  const handleLineItemAction = (id: string, action: UserAction, finalVerdict: Decision) => {
    setPdfLineItems((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, userAction: action, finalVerdict } : item
      )
    );
  };

  // ─── 全承認 ───────────────────────────────────────────────────────
  const handleApproveAll = () => {
    setPdfLineItems((prev) =>
      prev.map((item) =>
        item.userAction === 'pending' && item.confidence >= 0.8
          ? { ...item, userAction: 'approved', finalVerdict: item.verdict }
          : item
      )
    );
  };

  // ─── 手入力判定 ────────────────────────────────────────────────────
  const onSubmit = async (values: FormValues) => {
    setIsLoading(true);
    setApiError(null);
    setResult(null);
    setOriginalRequest(null);
    const req: ClassifyRequest = {
      description: values.description,
      amount: values.amount ? Number(values.amount) : undefined,
      account: values.account || undefined,
    };
    try {
      const res = await classifyAsset(req, trainingRecords);
      setOriginalRequest(req);
      setResult(res);
      setHistory((prev) => [{ request: req, response: res, timestamp: new Date().toISOString() }, ...prev]);
    } catch (err) {
      setApiError(err instanceof Error ? err.message : '判定中にエラーが発生しました');
    } finally {
      setIsLoading(false);
    }
  };

  const handleLeaseSubmit = async (req: LeaseClassifyRequest) => {
    setIsLeaseLoading(true);
    setLeaseError(null);
    setLeaseResult(null);
    try {
      const res = await classifyLease(req);
      setLeaseResult(res);
    } catch (e) {
      setLeaseError(e instanceof Error ? e.message : 'エラーが発生しました');
    } finally {
      setIsLeaseLoading(false);
    }
  };

  const handleDepreciationSubmit = async (req: DepreciationRequest) => {
    setIsDepreciationLoading(true);
    setDepreciationError(null);
    setDepreciationResult(null);
    try {
      const res = await calculateDepreciation(req);
      setDepreciationResult(res);
    } catch (e) {
      setDepreciationError(e instanceof Error ? e.message : 'エラーが発生しました');
    } finally {
      setIsDepreciationLoading(false);
    }
  };

  return (
    <MainLayout>
      <div className="max-w-3xl mx-auto space-y-8">

        {/* ── ヒーローセクション ──────────────────────────────────── */}
        <div className="text-center space-y-4 py-6">
          <div className="flex items-center justify-center gap-2">
            <Building2 className="size-8 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">固定資産AI仕分けアドバイザー</h1>
          </div>
          <p className="text-muted-foreground max-w-xl mx-auto">
            請求書・領収書のPDFをアップロードするだけで、AIが<strong>固定資産</strong>か<strong>費用</strong>かを
            自動判定します。
          </p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Badge variant="secondary">PDF-First</Badge>
            <Badge variant="outline">固定資産 / 費用 判定</Badge>
            <Badge variant="outline">信頼度・根拠 可視化</Badge>
          </div>
          <div className="grid grid-cols-3 gap-4 mt-4 text-center">
            {[
              { icon: Building2, label: '固定資産', desc: '資本的支出・減価償却対象' },
              { icon: CheckCircle2, label: '費用計上', desc: '修繕費・消耗品費など' },
              { icon: HelpCircle, label: 'グレーゾーン', desc: '要専門家確認の案件' },
            ].map(({ icon: Icon, label, desc }) => (
              <div key={label} className="rounded-lg border p-3 space-y-1">
                <Icon className="size-5 mx-auto text-muted-foreground" />
                <p className="text-sm font-medium">{label}</p>
                <p className="text-xs text-muted-foreground">{desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* ── タブ切り替え ──────────────────────────────────────── */}
        <div className="flex rounded-lg border overflow-hidden" role="tablist">
          <button
            role="tab"
            aria-selected={activeTab === 'pdf'}
            onClick={() => setActiveTab('pdf')}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors
              ${activeTab === 'pdf'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted/50 text-muted-foreground hover:bg-muted'
              }`}
            data-testid="tab-pdf"
          >
            <FileText className="size-4" />
            📄 PDFアップロード
          </button>
          <button
            role="tab"
            aria-selected={activeTab === 'manual'}
            onClick={() => setActiveTab('manual')}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors
              ${activeTab === 'manual'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted/50 text-muted-foreground hover:bg-muted'
              }`}
            data-testid="tab-manual"
          >
            <PenLine className="size-4" />
            ✏️ 手入力
          </button>
        </div>

        {/* ── PDF タブ ─────────────────────────────────────────── */}
        {activeTab === 'pdf' && (
          <div className="space-y-6" role="tabpanel" aria-label="PDFアップロード">
            <PDFUploadCard
              onResult={handlePdfResult}
              onManualInput={() => setActiveTab('manual')}
            />
            {/* v2 合議サマリー */}
            {pdfV2Summary && (
              <Card data-testid="v2-summary">
                <CardContent className="pt-4">
                  <div className="grid grid-cols-3 gap-4 text-center">
                    <div>
                      <p className="text-xs text-muted-foreground">固定資産合計</p>
                      <p className="font-bold text-blue-700">{pdfV2Summary.capital_total.toLocaleString()}円</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">費用合計</p>
                      <p className="font-bold text-green-700">{pdfV2Summary.expense_total.toLocaleString()}円</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">要確認合計</p>
                      <p className="font-bold text-yellow-700">{pdfV2Summary.guidance_total.toLocaleString()}円</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
            {pdfLineItems.length > 0 && (
              <PDFReviewSection
                items={pdfLineItems}
                onAction={handleLineItemAction}
                onApproveAll={handleApproveAll}
              />
            )}
          </div>
        )}

        {/* ── 手入力タブ ───────────────────────────────────────── */}
        {activeTab === 'manual' && (
          <div className="space-y-6" role="tabpanel" aria-label="手入力">

            {/* 入力フォーム */}
            <Card>
              <CardHeader>
                <CardTitle>資産情報の入力</CardTitle>
                <CardDescription>
                  購入した物品や工事の内容を入力してください。金額・勘定科目は任意です。
                </CardDescription>
              </CardHeader>
              <CardContent>
                {/* デモデータボタン */}
                <div className="flex flex-wrap items-center gap-2 mb-4">
                  <span className="text-xs text-muted-foreground">💡 デモデータで試す:</span>
                  {DEMO_DATA.map((d) => (
                    <Button
                      key={d.label}
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setValue('description', d.description);
                        setValue('amount', String(d.amount));
                        setValue('account', d.account);
                      }}
                    >
                      {d.label}
                    </Button>
                  ))}
                </div>
                <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
                  {/* 説明（必須） */}
                  <div className="space-y-2">
                    <Label htmlFor="description">
                      説明・仕訳内容 <span className="text-destructive">*</span>
                    </Label>
                    <Textarea
                      id="description"
                      placeholder={
                        '例: サーバーラック購入費用 150万円。耐用年数5年予定。\n例: 事務所の壁紙張り替え工事 50万円。原状回復目的。'
                      }
                      rows={5}
                      {...register('description')}
                      aria-invalid={!!errors.description}
                    />
                    {errors.description && (
                      <p className="text-xs text-destructive">{errors.description.message}</p>
                    )}
                  </div>

                  {/* 類似事例パネル */}
                  <SimilarCasesPanel query={watchDescription ?? ''} />

                  {/* 金額・勘定科目 */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="amount">金額（円・任意）</Label>
                      <Input
                        id="amount"
                        type="text"
                        inputMode="numeric"
                        placeholder="1500000"
                        {...register('amount')}
                        aria-invalid={!!errors.amount}
                      />
                      {errors.amount && (
                        <p className="text-xs text-destructive">{errors.amount.message}</p>
                      )}
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="account">勘定科目（任意）</Label>
                      <Input
                        id="account"
                        type="text"
                        placeholder="例: 備品、建物附属設備"
                        {...register('account')}
                        aria-invalid={!!errors.account}
                      />
                      {errors.account && (
                        <p className="text-xs text-destructive">{errors.account.message}</p>
                      )}
                    </div>
                  </div>

                  {/* エラー */}
                  {apiError && (
                    <Alert variant="destructive">
                      <AlertTriangle className="size-4" />
                      <AlertTitle>エラー</AlertTitle>
                      <AlertDescription>{apiError}</AlertDescription>
                    </Alert>
                  )}

                  <Button type="submit" disabled={isLoading} size="lg" className="w-full">
                    {isLoading ? (
                      <>
                        <Loader2 className="size-4 animate-spin" />
                        判定中...
                      </>
                    ) : (
                      <>
                        <Sparkles className="size-4" />
                        AIで判定する
                      </>
                    )}
                  </Button>
                </form>
              </CardContent>
            </Card>

            {/* 金額ベース税務ルール */}
            <TaxBoundaryCard amount={watchAmount ? Number(watchAmount) : undefined} />

            {/* 結果カード */}
            {result && <ResultCard result={result} />}

            {/* 明細内訳 */}
            {result && <LineItemsTable items={result.line_items} />}

            {/* 集計サマリ */}
            {result?.line_items && result.line_items.length > 0 && (
              <SummaryCard items={result.line_items} />
            )}

            {/* 次のアクション */}
            {result && <NextActionCard decision={result.decision} />}

            {/* GUIDANCE 2段階ウィザード */}
            {result?.decision === 'GUIDANCE' && originalRequest && (
              <GuidanceWizard
                stage0Result={result}
                originalRequest={originalRequest}
                onResolved={(resolved) => setResult(resolved)}
              />
            )}
          </div>
        )}

        {/* ── 判定履歴（共通） ──────────────────────────────────── */}
        {history.length > 0 && <HistoryPanel history={history} />}

        {/* ── IFRS 16 リース会計判定 ───────────────────────────── */}
        <div className="border-t pt-8 mt-4">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Building2 className="size-5 text-blue-600" />
            IFRS 16 リース会計判定
          </h2>
          <LeaseInputForm onSubmit={handleLeaseSubmit} isLoading={isLeaseLoading} />
          {leaseError && (
            <Alert variant="destructive" className="mt-4">
              <AlertTriangle className="size-4" />
              <AlertTitle>エラー</AlertTitle>
              <AlertDescription>{leaseError}</AlertDescription>
            </Alert>
          )}
          {leaseResult && <LeaseResultCard result={leaseResult} />}
        </div>

        {/* ── 減価償却計算 ─────────────────────────────────────── */}
        <div className="border-t pt-8 mt-4">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Building2 className="size-5 text-green-600" />
            減価償却計算（定率法・定額法）
          </h2>
          <DepreciationInputForm onSubmit={handleDepreciationSubmit} isLoading={isDepreciationLoading} />
          {depreciationError && (
            <Alert variant="destructive" className="mt-4">
              <AlertTriangle className="size-4" />
              <AlertTitle>エラー</AlertTitle>
              <AlertDescription>{depreciationError}</AlertDescription>
            </Alert>
          )}
          {depreciationResult && <DepreciationResultCard result={depreciationResult} />}
        </div>

        {/* ── 教師データ CSV インポート + 管理 ─────────────────── */}
        <div className="border-t pt-8 mt-4">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Upload className="size-5 text-purple-600" />
            教師データ登録（CSV インポート）
          </h2>
          <div className="space-y-4">
            <TrainingDataImportCard />
            <PdfTrainingImportCard />
            <TrainingDataManagerCard />
          </div>
        </div>

      </div>
    </MainLayout>
  );
}
