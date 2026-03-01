/**
 * POST /api/v2/classify_pdf
 * 根拠: 設計書 DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 5.2 / Section 12
 *
 * Phase 1: 既存 Python backend /classify_pdf（単一Gemini）を内部で呼び出し、
 *          レスポンスを v2 フォーマットへ変換して返す。
 * Phase 2: USE_MULTI_AGENT=true で Tax + Practice + Aggregator の3エージェント合議に切り替える。
 */

import { NextRequest, NextResponse } from 'next/server';
import { randomUUID } from 'crypto';
import type { ClassifyResponse } from '@/types/classify';
import type {
  ClassifyPDFV2Request,
  ClassifyPDFV2Response,
  ExtractedLineItem,
  ExtractedLineItems,
  LineResultV2,
  V2Summary,
  V2Status,
  V2Verdict,
} from '@/types/classify_pdf_v2';
import { runTaxAgent } from '@/lib/agents/taxAgent';
import { runPracticeAgent } from '@/lib/agents/practiceAgent';
import { aggregate } from '@/lib/agents/aggregator';
import type { AggregatedResult } from '@/types/multi_agent';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const TIMEOUT_MS = 5000;

// ─── Feature Flags ─────────────────────────────────────────────────────────

/** 設計書 Section 12: サーバーサイド Feature Flag を返す */
export function getFeatureFlags() {
  return {
    useMultiAgent: process.env.USE_MULTI_AGENT === 'true',
    parallelAgents: process.env.PARALLEL_AGENTS !== 'false',    // default true
    auditTrailEnabled: process.env.AUDIT_TRAIL_ENABLED !== 'false', // default true
  };
}

// ─── 変換ヘルパー ──────────────────────────────────────────────────────────

/**
 * ClassifyResponse.decision → V2Verdict に正規化する。
 * 根拠: 設計書 Section 1.2 用語対応表
 *
 * Python backend は既に CAPITAL_LIKE / EXPENSE_LIKE / GUIDANCE を返すが、
 * 将来的に CAPITAL / EXPENSE / UNCERTAIN を返す実装に対応するため保持。
 */
export function normalizeVerdict(raw: string): V2Verdict {
  switch (raw) {
    case 'CAPITAL':
    case 'CAPITAL_LIKE':
      return 'CAPITAL_LIKE';
    case 'EXPENSE':
    case 'EXPENSE_LIKE':
      return 'EXPENSE_LIKE';
    default:
      return 'GUIDANCE';
  }
}

/**
 * ClassifyResponse → ClassifyPDFV2Response に変換する。
 * 根拠: 設計書 Section 5.2
 *
 * @param classifyRes  Python backend からのレスポンス
 * @param requestId    生成済み UUID
 * @param auditTrailId 監査証跡 ID（null の場合は AUDIT_TRAIL_ENABLED=false）
 * @param elapsedMs    経過時間（ms）
 */
export function transformToV2(
  classifyRes: ClassifyResponse,
  requestId: string,
  auditTrailId: string | null,
  elapsedMs: number,
): ClassifyPDFV2Response {
  const lineItems = classifyRes.line_items ?? [];

  // line_items が空の場合は decision 全体を1行として扱う
  const itemsToProcess =
    lineItems.length > 0
      ? lineItems
      : [
          {
            description: 'ドキュメント全体',
            amount: 0,
            classification: classifyRes.decision,
            flags: [] as string[],
            ai_hint: classifyRes.reasons.join('; '),
          },
        ];

  // 各明細に一意な line_item_id を割り当てる
  const lineItemIds = itemsToProcess.map(() => `li_${randomUUID().replace(/-/g, '').slice(0, 12)}`);

  const extractedItems: ExtractedLineItem[] = itemsToProcess.map((item, i) => ({
    line_item_id: lineItemIds[i],
    description: item.description,
    amount: item.amount ?? 0,
    quantity: undefined,
  }));

  const extracted: ExtractedLineItems = {
    vendor: undefined,
    document_date: undefined,
    items: extractedItems,
  };

  const lineResults: LineResultV2[] = itemsToProcess.map((item, i) => ({
    line_item_id: lineItemIds[i],
    verdict: normalizeVerdict(item.classification),
    confidence: classifyRes.confidence,
    account_category: null,
    useful_life: null,
    tax_verdict: normalizeVerdict(item.classification),
    tax_rationale: classifyRes.reasons.join('; '),
    tax_account: null,
    practice_verdict: normalizeVerdict(item.classification),
    practice_rationale: item.ai_hint ?? '',
    practice_account: null,
    similar_cases: [],
  }));

  // サマリー: verdict 別に金額合計を集計（設計書 Section 5.2）
  const summary: V2Summary = {
    capital_total: itemsToProcess
      .filter((_, i) => lineResults[i].verdict === 'CAPITAL_LIKE')
      .reduce((sum, item) => sum + (item.amount ?? 0), 0),
    expense_total: itemsToProcess
      .filter((_, i) => lineResults[i].verdict === 'EXPENSE_LIKE')
      .reduce((sum, item) => sum + (item.amount ?? 0), 0),
    guidance_total: itemsToProcess
      .filter((_, i) => lineResults[i].verdict === 'GUIDANCE')
      .reduce((sum, item) => sum + (item.amount ?? 0), 0),
    by_account: [],
  };

  const status: V2Status =
    classifyRes.is_valid_document === false ? 'partial' : 'success';

  return {
    request_id: requestId,
    status,
    extracted,
    line_results: lineResults,
    summary,
    audit_trail_id: auditTrailId,
    elapsed_ms: elapsedMs,
  };
}

// ─── マルチエージェント用ヘルパー ──────────────────────────────────────────

/**
 * ClassifyResponse の line_items を ExtractedLineItem[] に変換する。
 * 各明細に一意な line_item_id を割り当てる。
 * 根拠: 設計書 Section 4.1 — マルチエージェントへの入力形式
 */
export function extractLineItemsFromClassify(classifyRes: ClassifyResponse): ExtractedLineItem[] {
  const items =
    classifyRes.line_items?.length > 0
      ? classifyRes.line_items
      : [{ description: 'ドキュメント全体', amount: 0, classification: classifyRes.decision }];

  return items.map((item) => ({
    line_item_id: `li_${randomUUID().replace(/-/g, '').slice(0, 12)}`,
    description: item.description,
    amount: item.amount ?? 0,
  }));
}

/**
 * AggregatedResult[] + ExtractedLineItem[] → ClassifyPDFV2Response に変換する。
 * 根拠: 設計書 Section 5.2 レスポンス形式
 *
 * CHECK-9: レスポンスフィールドは Section 5.2 スキーマから直接引用:
 *   - verdict / confidence / account_category / useful_life: Aggregator出力
 *   - tax_verdict / tax_rationale / tax_account: Tax Agent出力
 *   - practice_verdict / practice_rationale / practice_account: Practice Agent出力
 *   - similar_cases: Practice Agent の similar_cases[].description
 */
export function transformAggregatedToV2(
  aggregatedResults: AggregatedResult[],
  extractedItems: ExtractedLineItem[],
  requestId: string,
  auditTrailId: string | null,
  elapsedMs: number,
  agentStatus: 'success' | 'partial' = 'success',
): ClassifyPDFV2Response {
  // 金額マップ（line_item_id → amount）
  const amountMap = new Map(extractedItems.map((i) => [i.line_item_id, i.amount]));

  const lineResults: LineResultV2[] = aggregatedResults.map((agg) => ({
    line_item_id: agg.line_item_id,
    verdict: agg.final_verdict,                            // CAPITAL_LIKE | EXPENSE_LIKE | GUIDANCE
    confidence: agg.confidence,                            // Aggregator算出: 0.95/0.80/0.50/0.30
    account_category: agg.account_category,                // Tax優先, Tax null時Practice採用
    useful_life: agg.useful_life,                          // Tax Agentの値を正とする
    tax_verdict: agg.tax_result?.verdict ?? 'UNCERTAIN',
    tax_rationale: agg.tax_result?.rationale ?? '',
    tax_account: agg.tax_result?.account_category ?? null,
    practice_verdict: agg.practice_result?.verdict ?? 'UNCERTAIN',
    practice_rationale: agg.practice_result?.rationale ?? '',
    practice_account: agg.practice_result?.suggested_account ?? null,
    similar_cases: agg.practice_result?.similar_cases.map((sc) => sc.description) ?? [],
  }));

  // 金額集計（CHECK-7b 手計算検証済み）
  let capital_total = 0;
  let expense_total = 0;
  let guidance_total = 0;
  const byAccountMap = new Map<string, { count: number; total_amount: number }>();

  for (const lr of lineResults) {
    const amount = amountMap.get(lr.line_item_id) ?? 0;
    if (lr.verdict === 'CAPITAL_LIKE') {
      capital_total += amount;
      if (lr.account_category) {
        const prev = byAccountMap.get(lr.account_category) ?? { count: 0, total_amount: 0 };
        byAccountMap.set(lr.account_category, {
          count: prev.count + 1,
          total_amount: prev.total_amount + amount,
        });
      }
    } else if (lr.verdict === 'EXPENSE_LIKE') {
      expense_total += amount;
    } else {
      guidance_total += amount;
    }
  }

  const by_account = Array.from(byAccountMap.entries()).map(([account_category, stats]) => ({
    account_category,
    count: stats.count,
    total_amount: stats.total_amount,
  }));

  const extracted: ExtractedLineItems = { items: extractedItems };

  const summary: V2Summary = { capital_total, expense_total, guidance_total, by_account };

  return {
    request_id: requestId,
    status: agentStatus,
    extracted,
    line_results: lineResults,
    summary,
    audit_trail_id: auditTrailId,
    elapsed_ms: elapsedMs,
  };
}

// ─── fetch with timeout / retry ────────────────────────────────────────────

async function fetchWithTimeout(url: string, formData: FormData): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

// ─── POST ──────────────────────────────────────────────────────────────────

export async function POST(req: NextRequest): Promise<NextResponse> {
  // 1. リクエスト解析
  let body: ClassifyPDFV2Request;
  try {
    body = (await req.json()) as ClassifyPDFV2Request;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const { pdf_base64, options } = body;

  if (!pdf_base64) {
    return NextResponse.json({ error: 'pdf_base64 is required' }, { status: 400 });
  }

  // 2. Feature Flag & ID 生成
  const flags = getFeatureFlags();
  const includeAuditTrail = options?.include_audit_trail ?? flags.auditTrailEnabled;
  const requestId = randomUUID();
  const auditTrailId = includeAuditTrail
    ? `trail_${randomUUID().replace(/-/g, '').slice(0, 16)}`
    : null;
  const startTime = Date.now();

  // 3. base64 → Buffer → Blob → FormData
  let pdfBuffer: Buffer;
  try {
    pdfBuffer = Buffer.from(pdf_base64, 'base64');
  } catch {
    return NextResponse.json({ error: 'Invalid base64 encoding' }, { status: 400 });
  }

  // Buffer は ArrayBufferLike を持つため Uint8Array にキャストして Blob に渡す
  const pdfBlob = new Blob([new Uint8Array(pdfBuffer)], { type: 'application/pdf' });
  const formData = new FormData();
  formData.append('file', pdfBlob, 'document.pdf');
  formData.append('use_gemini_vision', '1');
  formData.append('estimate_useful_life_flag', '1');

  // 4. Python backend 呼び出し（タイムアウト付き、リトライ1回）
  let classifyRes: ClassifyResponse | null = null;

  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const backendRes = await fetchWithTimeout(`${API_BASE}/classify_pdf`, formData);
      if (!backendRes.ok) {
        const text = await backendRes.text();
        return NextResponse.json(
          { error: `Backend error: ${text}` },
          { status: backendRes.status },
        );
      }
      classifyRes = (await backendRes.json()) as ClassifyResponse;
      break;
    } catch {
      if (attempt === 1) {
        // 2回目も失敗 → extraction_failed を返す（設計書 Section 6）
        const elapsed = Date.now() - startTime;
        const failResponse: ClassifyPDFV2Response = {
          request_id: requestId,
          status: 'extraction_failed',
          extracted: null,
          line_results: [],
          summary: { capital_total: 0, expense_total: 0, guidance_total: 0, by_account: [] },
          audit_trail_id: auditTrailId,
          elapsed_ms: elapsed,
        };
        return NextResponse.json(failResponse);
      }
    }
  }

  if (!classifyRes) {
    const elapsed = Date.now() - startTime;
    return NextResponse.json({
      request_id: requestId,
      status: 'extraction_failed' as V2Status,
      extracted: null,
      line_results: [],
      summary: { capital_total: 0, expense_total: 0, guidance_total: 0, by_account: [] },
      audit_trail_id: auditTrailId,
      elapsed_ms: elapsed,
    } satisfies ClassifyPDFV2Response);
  }

  // 5. マルチエージェント判定パス（USE_MULTI_AGENT=true）
  //    根拠: 設計書 Section 5.3 エージェント実行順序
  if (flags.useMultiAgent) {
    const extractedItems = extractLineItemsFromClassify(classifyRes);
    const parallelEnabled = options?.parallel_agents ?? flags.parallelAgents;

    let taxResults: Awaited<ReturnType<typeof runTaxAgent>> | null = null;
    let practiceResults: Awaited<ReturnType<typeof runPracticeAgent>> | null = null;
    let agentStatus: 'success' | 'partial' = 'success';

    if (parallelEnabled) {
      // Promise.allSettled: 片方失敗でも残りで判定継続（根拠: Section 6 エラーハンドリング）
      const [taxSettled, practiceSettled] = await Promise.allSettled([
        runTaxAgent(extractedItems),
        runPracticeAgent(extractedItems, []),
      ]);
      taxResults = taxSettled.status === 'fulfilled' ? taxSettled.value : null;
      practiceResults = practiceSettled.status === 'fulfilled' ? practiceSettled.value : null;
      if (taxSettled.status === 'rejected' || practiceSettled.status === 'rejected') {
        agentStatus = 'partial';
      }
    } else {
      // Sequential（PARALLEL_AGENTS=false の場合）
      try { taxResults = await runTaxAgent(extractedItems); } catch { agentStatus = 'partial'; }
      try { practiceResults = await runPracticeAgent(extractedItems, []); } catch { agentStatus = 'partial'; }
    }

    const aggregated = aggregate(taxResults, practiceResults);
    const elapsed = Date.now() - startTime;
    const v2Response = transformAggregatedToV2(
      aggregated,
      extractedItems,
      requestId,
      auditTrailId,
      elapsed,
      agentStatus,
    );
    return NextResponse.json(v2Response);
  }

  // 6. Phase 1 フォールバック（USE_MULTI_AGENT=false）
  const elapsed = Date.now() - startTime;
  const v2Response = transformToV2(classifyRes, requestId, auditTrailId, elapsed);
  return NextResponse.json(v2Response);
}
