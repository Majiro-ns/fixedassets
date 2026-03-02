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
import {
  getFeatureFlags,
  transformToV2,
  extractLineItemsFromClassify,
  transformAggregatedToV2,
} from './route.helpers';
import { trainingDataStore } from '@/lib/agents/trainingDataStore';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const TIMEOUT_MS = 5000;

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
        runPracticeAgent(extractedItems, trainingDataStore.getAll()),
      ]);
      taxResults = taxSettled.status === 'fulfilled' ? taxSettled.value : null;
      practiceResults = practiceSettled.status === 'fulfilled' ? practiceSettled.value : null;
      if (taxSettled.status === 'rejected' || practiceSettled.status === 'rejected') {
        agentStatus = 'partial';
      }
    } else {
      // Sequential（PARALLEL_AGENTS=false の場合）
      try { taxResults = await runTaxAgent(extractedItems); } catch { agentStatus = 'partial'; }
      try { practiceResults = await runPracticeAgent(extractedItems, trainingDataStore.getAll()); } catch { agentStatus = 'partial'; }
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
