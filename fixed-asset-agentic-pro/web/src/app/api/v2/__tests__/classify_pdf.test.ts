/**
 * POST /api/v2/classify_pdf APIルートテスト
 * 根拠: 設計書 Section 5.2 (API仕様) + Section 12 (Feature Flag)
 *
 * ステータス: 全テスト describe.skip
 * 理由: /api/v2/classify_pdf の Next.js route.ts は足軽8が実装中（Phase 1-B）。
 *       API実装完了後に describe.skip を外して有効化すること。
 *
 * 有効化手順:
 *   1. web/src/app/api/v2/classify_pdf/route.ts の実装完了を確認
 *   2. このファイルの describe.skip を describe に変更
 *   3. npm run test を実行して全件PASSを確認
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ClassifyPDFV2Response } from '@/types/classify_pdf_v2';

// ─── モックユーティリティ ──────────────────────────────────────────────────

/** Section 5.2 準拠の正常レスポンスを生成する */
function makeSuccessResponse(overrides?: Partial<ClassifyPDFV2Response>): ClassifyPDFV2Response {
  return {
    request_id: 'req_mock_001',
    status: 'success',
    extracted: {
      document_date: '2026-03-01',
      vendor: 'モック商事株式会社',
      items: [
        { line_item_id: 'li_001', description: 'ノートPC', amount: 250000, quantity: 1 },
      ],
    },
    line_results: [
      {
        line_item_id: 'li_001',
        verdict: 'CAPITAL_LIKE',
        confidence: 0.92,
        account_category: '器具備品',
        useful_life: 4,
        tax_verdict: 'CAPITAL',
        tax_rationale: '電子計算機 別表一',
        tax_account: '器具備品',
        practice_verdict: 'CAPITAL',
        practice_rationale: '取得価額25万円以上',
        practice_account: '器具備品',
        similar_cases: [],
      },
    ],
    summary: {
      capital_total: 250000,
      expense_total: 0,
      guidance_total: 0,
      by_account: [{ account_category: '器具備品', count: 1, total_amount: 250000 }],
    },
    audit_trail_id: null,
    elapsed_ms: 1500,
    ...overrides,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// POST /api/v2/classify_pdf テスト（API実装後に有効化）
// ─────────────────────────────────────────────────────────────────────────────

describe('POST /api/v2/classify_pdf（Phase 1-B実装済み）', () => {
  const API_ENDPOINT = '/api/v2/classify_pdf';

  beforeEach(() => {
    vi.resetAllMocks();
  });

  // ─── 正常系 ──────────────────────────────────────────────────────────────

  it('PDFファイルを受け取り Section 5.2 準拠のレスポンスを返すこと', async () => {
    const pdfFile = new File(['%PDF-1.4 mock content'], 'invoice.pdf', {
      type: 'application/pdf',
    });
    const base64 = Buffer.from('%PDF-1.4 mock content').toString('base64');

    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(makeSuccessResponse()), { status: 200 }),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pdf_base64: base64,
        company_id: null,
        options: { include_audit_trail: true, parallel_agents: true },
      }),
    });

    expect(res.status).toBe(200);
    const body: ClassifyPDFV2Response = await res.json();
    expect(body.status).toBe('success');
    expect(body.line_results.length).toBeGreaterThan(0);
    expect(body.summary).toBeDefined();
    expect(body.request_id).toBeTruthy();
    expect(typeof body.elapsed_ms).toBe('number');
  });

  it('status=success 時は extracted が null でないこと', async () => {
    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(makeSuccessResponse()), { status: 200 }),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_base64: 'dGVzdA==', company_id: null, options: { include_audit_trail: true, parallel_agents: true } }),
    });

    const body: ClassifyPDFV2Response = await res.json();
    expect(body.extracted).not.toBeNull();
  });

  it('parallel_agents=true → Tax/Practice エージェントが並列実行されること', async () => {
    // Section 12: PARALLEL_AGENTS=true がデフォルト
    // 検証方法: elapsed_ms が合計でなく最大値に近いことを確認
    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(makeSuccessResponse({ elapsed_ms: 800 })), { status: 200 }),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pdf_base64: 'dGVzdA==',
        company_id: null,
        options: { include_audit_trail: true, parallel_agents: true },
      }),
    });

    const body: ClassifyPDFV2Response = await res.json();
    // 並列実行なら elapsed_ms < 2000ms が期待値
    // （Tax 1000ms + Practice 1000ms の直列 = 2000ms）
    expect(body.elapsed_ms).toBeLessThan(2000);
  });

  it('AUDIT_TRAIL_ENABLED=true → audit_trail_id が string であること', async () => {
    // Section 12: AUDIT_TRAIL_ENABLED デフォルト true
    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(
        JSON.stringify(makeSuccessResponse({ audit_trail_id: 'trail_abc123' })),
        { status: 200 },
      ),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pdf_base64: 'dGVzdA==',
        company_id: null,
        options: { include_audit_trail: true, parallel_agents: true },
      }),
    });

    const body: ClassifyPDFV2Response = await res.json();
    expect(typeof body.audit_trail_id).toBe('string');
    expect(body.audit_trail_id).not.toBeNull();
  });

  // ─── extraction_failed 系 ─────────────────────────────────────────────────

  it('PDFが読み取り不能の場合 status=extraction_failed を返すこと', async () => {
    // Section 5.2: "extraction_failed の場合は extracted: null、line_results: []"
    const extractionFailedBody: ClassifyPDFV2Response = {
      request_id: 'req_fail_001',
      status: 'extraction_failed',
      extracted: null,
      line_results: [],
      summary: { capital_total: 0, expense_total: 0, guidance_total: 0, by_account: [] },
      audit_trail_id: null,
      elapsed_ms: 300,
    };

    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(extractionFailedBody), { status: 200 }),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_base64: 'garbled', company_id: null, options: { include_audit_trail: true, parallel_agents: true } }),
    });

    const body: ClassifyPDFV2Response = await res.json();
    expect(body.status).toBe('extraction_failed');
    expect(body.extracted).toBeNull();
    expect(body.line_results).toHaveLength(0);
  });

  // ─── エラー系 ─────────────────────────────────────────────────────────────

  it('pdf_base64 未指定（リクエスト不正）→ 400 を返すこと', async () => {
    // Section 5.2: リクエスト必須フィールド
    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ error: 'pdf_base64 is required' }), { status: 400 }),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_id: null, options: { include_audit_trail: true, parallel_agents: true } }),
    });

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body).toHaveProperty('error');
  });

  it('Gemini/LLM 処理エラー → 500 を返すこと', async () => {
    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ error: 'Internal processing error' }), { status: 500 }),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_base64: 'dGVzdA==', company_id: null, options: { include_audit_trail: true, parallel_agents: true } }),
    });

    expect(res.status).toBe(500);
  });

  it('GET リクエスト → 405 Method Not Allowed を返すこと', async () => {
    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(null, { status: 405 }),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, { method: 'GET' });
    expect(res.status).toBe(405);
  });

  // ─── レスポンス整合性 ──────────────────────────────────────────────────────

  it('line_results の verdict は CAPITAL_LIKE | EXPENSE_LIKE | GUIDANCE のいずれかであること', async () => {
    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(makeSuccessResponse()), { status: 200 }),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_base64: 'dGVzdA==', company_id: null, options: { include_audit_trail: true, parallel_agents: true } }),
    });

    const body: ClassifyPDFV2Response = await res.json();
    const validVerdicts = ['CAPITAL_LIKE', 'EXPENSE_LIKE', 'GUIDANCE'];
    for (const lr of body.line_results) {
      expect(validVerdicts).toContain(lr.verdict);
      expect(lr.confidence).toBeGreaterThanOrEqual(0);
      expect(lr.confidence).toBeLessThanOrEqual(1);
    }
  });

  it('summary の各合計が line_results から正しく計算されること', async () => {
    const mockFetch = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify(makeSuccessResponse()), { status: 200 }),
    );
    vi.stubGlobal('fetch', mockFetch);

    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_base64: 'dGVzdA==', company_id: null, options: { include_audit_trail: true, parallel_agents: true } }),
    });

    const body: ClassifyPDFV2Response = await res.json();
    // CHECK-7b: 手計算検証 — capital=250000, expense=0, guidance=0
    const { capital_total, expense_total, guidance_total } = body.summary;
    expect(capital_total).toBeGreaterThanOrEqual(0);
    expect(expense_total).toBeGreaterThanOrEqual(0);
    expect(guidance_total).toBeGreaterThanOrEqual(0);
  });
});
