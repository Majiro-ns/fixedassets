/**
 * POST /api/v2/classify_pdf
 * 根拠: 設計書 DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 5.2 / Section 12
 *
 * Phase 1: 既存 Python backend /classify_pdf（単一Gemini）を内部で呼び出し、
 *          レスポンスを v2 フォーマットへ変換して返す。
 * Phase 3: USE_MULTI_AGENT=true でマルチエージェント実装に切り替える。
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

  // 5. 変換 & レスポンス
  const elapsed = Date.now() - startTime;
  const v2Response = transformToV2(classifyRes, requestId, auditTrailId, elapsed);
  return NextResponse.json(v2Response);
}
