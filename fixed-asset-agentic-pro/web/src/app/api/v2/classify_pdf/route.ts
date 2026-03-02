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
  V2Status,
} from '@/types/classify_pdf_v2';
import { runTaxAgent } from '@/lib/agents/taxAgent';
import { runPracticeAgent } from '@/lib/agents/practiceAgent';
import { aggregate } from '@/lib/agents/aggregator';
import { runSplitJudge } from '@/lib/agents/splitJudge';
import {
  getFeatureFlags,
  transformToV2,
  extractLineItemsFromClassify,
  transformAggregatedToV2,
} from './route.helpers';
import { trainingDataStore } from '@/lib/agents/trainingDataStore';
import { auditStore } from '@/lib/agents/auditStore';
import { policyStore } from '@/lib/policyStore';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const TIMEOUT_MS = 5000;

// ─── Audit Trail ヘルパー ───────────────────────────────────────────────────

/**
 * 判定完了後に監査証跡を記録する。
 * audit_trail_id が null（AUDIT_TRAIL_ENABLED=false）の場合は何もしない。
 */
function appendAudit(v2Response: ClassifyPDFV2Response, modelUsed: string): void {
  if (!v2Response.audit_trail_id) return;
  const first = v2Response.line_results[0];
  auditStore.append({
    audit_trail_id: v2Response.audit_trail_id,
    request_id: v2Response.request_id,
    timestamp: new Date().toISOString(),
    pdf_filename: 'document.pdf',
    line_items_count: v2Response.line_results.length,
    tax_verdict: first?.tax_verdict ?? 'UNKNOWN',
    practice_verdict: first?.practice_verdict ?? 'UNKNOWN',
    final_verdict: first?.verdict ?? 'UNKNOWN',
    confidence: first?.confidence ?? 0,
    account_category: first?.account_category ?? null,
    useful_life: first?.useful_life ?? null,
    elapsed_ms: v2Response.elapsed_ms,
    model_used: modelUsed,
  });
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

  const { pdf_base64, options, policy_id } = body;

  if (!pdf_base64) {
    return NextResponse.json({ error: 'pdf_base64 is required' }, { status: 400 });
  }

  // 1.5 ポリシー閾値の解決（F-10: クライアント別ポリシー管理）
  // policy_id が指定された場合、PolicyStore から閾値を取得する。
  // 指定なし or 存在しない ID の場合は undefined（taxAgent のデフォルト 10万円）。
  let policyThreshold: number | undefined;
  if (policy_id !== undefined && policy_id !== null) {
    const policy = policyStore.getById(policy_id);
    if (policy) {
      policyThreshold = policy.threshold_amount;
    }
  }

  // 2. Feature Flag & ID 生成
  const flags = getFeatureFlags();
  const modelUsed = flags.useMultiAgent
    ? (process.env.MULTI_AGENT_MODEL ?? 'claude-haiku-4-5')
    : 'gemini-vision';
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
  //    Phase 3 F-N09: [PDF抽出] → [分割判定] → [Tax/Practice] → [Aggregator]
  if (flags.useMultiAgent) {
    const extractedItems = extractLineItemsFromClassify(classifyRes);

    // Phase 3 F-N09: 分割判定（splitJudge）
    // LLM不要のルールベース実装（APIキー不要）
    const extractedWithMeta = {
      document_date: undefined as string | undefined,
      vendor: undefined as string | undefined,
      items: extractedItems,
    };
    const splitJudgeResult = runSplitJudge(extractedWithMeta);

    // 両エージェント無効 → Phase 1 フォールバック（キルスイッチ: cmd_138k_sub3）
    if (!flags.taxAgentEnabled && !flags.practiceAgentEnabled) {
      const elapsed = Date.now() - startTime;
      const killSwitchResponse = transformToV2(classifyRes, requestId, auditTrailId, elapsed);
      appendAudit(killSwitchResponse, modelUsed);
      return NextResponse.json(killSwitchResponse);
    }

    const parallelEnabled = options?.parallel_agents ?? flags.parallelAgents;

    let taxResults: Awaited<ReturnType<typeof runTaxAgent>> | null = null;
    let practiceResults: Awaited<ReturnType<typeof runPracticeAgent>> | null = null;
    let agentStatus: 'success' | 'partial' = 'success';

    if (parallelEnabled) {
      // Promise.allSettled: 片方失敗でも残りで判定継続（根拠: Section 6 エラーハンドリング）
      // キルスイッチが有効な場合は無効エージェントを null で解決する
      const taxPromise = flags.taxAgentEnabled
        ? runTaxAgent(extractedItems, undefined, policyThreshold)
        : Promise.resolve(null as Awaited<ReturnType<typeof runTaxAgent>> | null);
      const practicePromise = flags.practiceAgentEnabled
        ? runPracticeAgent(extractedItems, trainingDataStore.getAll())
        : Promise.resolve(null as Awaited<ReturnType<typeof runPracticeAgent>> | null);

      const [taxSettled, practiceSettled] = await Promise.allSettled([taxPromise, practicePromise]);
      taxResults = taxSettled.status === 'fulfilled' ? taxSettled.value : null;
      practiceResults = practiceSettled.status === 'fulfilled' ? practiceSettled.value : null;
      if (taxSettled.status === 'rejected' || practiceSettled.status === 'rejected') {
        agentStatus = 'partial';
      }
    } else {
      // Sequential（PARALLEL_AGENTS=false の場合）
      if (flags.taxAgentEnabled) {
        try { taxResults = await runTaxAgent(extractedItems, undefined, policyThreshold); } catch { agentStatus = 'partial'; }
      }
      if (flags.practiceAgentEnabled) {
        try { practiceResults = await runPracticeAgent(extractedItems, trainingDataStore.getAll()); } catch { agentStatus = 'partial'; }
      }
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
    // Phase 3 F-N09: 分割判定結果をレスポンスに追加
    v2Response.split_groups = splitJudgeResult.groups;
    appendAudit(v2Response, modelUsed);
    return NextResponse.json(v2Response);
  }

  // 6. Phase 1 フォールバック（USE_MULTI_AGENT=false）
  const elapsed = Date.now() - startTime;
  const v2Response = transformToV2(classifyRes, requestId, auditTrailId, elapsed);
  appendAudit(v2Response, modelUsed);
  return NextResponse.json(v2Response);
}
