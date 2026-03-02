/**
 * POST /api/v2/report_pdf テスト
 *
 * F-12: 証跡レポート PDF 生成プロキシ
 * フロントエンドからの POST を Python バックエンド /report/pdf へ転送し、
 * application/pdf レスポンスをそのままクライアントに返す。
 *
 * CHECK-9: テスト期待値根拠
 *   - route.ts L29-32: req.json() 例外 → 400 { error: 'Invalid JSON' }
 *   - route.ts L41: fetch(`${API_BASE}/report/pdf`, { method: 'POST', ... })
 *   - route.ts L47-51: fetch 例外 → catch(err) → 503 { error: err.message or 'Backend unreachable' }
 *   - route.ts L55-58: !backendRes.ok → { error: `Backend error: ${text}` }, status = backendRes.status
 *   - route.ts L61: pdfBytes = await backendRes.arrayBuffer() → バイナリそのまま保持
 *   - route.ts L65-70: new NextResponse(pdfBytes, { 'Content-Type': 'application/pdf', 'Content-Disposition': ... })
 *
 * CHECK-7b: PDF バイナリ転送の手計算検証
 *   MOCK_PDF_BYTES = [0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34] = "%PDF-1.4" (8バイト)
 *   route.ts L61: pdfBytes = await backendRes.arrayBuffer() → ArrayBuffer をそのまま保持
 *   route.ts L65: new NextResponse(pdfBytes, ...) → 同一バッファを渡す
 *   → レスポンスから arrayBuffer() で取得した先頭4バイトが 0x25,0x50,0x44,0x46 (%PDF) と一致 ✓
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NextRequest } from 'next/server';
import { POST } from '@/app/api/v2/report_pdf/route';

// ─── テスト用フィクスチャ ─────────────────────────────────────────────────────

/**
 * モック PDF バイナリ: "%PDF-1.4" 先頭8バイト
 * CHECK-7b: 0x25=%  0x50=P  0x44=D  0x46=F  0x2D=-  0x31=1  0x2E=.  0x34=4
 */
const MOCK_PDF_BYTES = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34]);

/** バックエンドが正常に PDF を返すモックレスポンス */
function makePdfBackendResponse(): Response {
  // Uint8Array.buffer は独自の ArrayBuffer を持つため安全にコピー可能
  const buf = MOCK_PDF_BYTES.buffer.slice(0);
  return {
    ok: true,
    status: 200,
    arrayBuffer: () => Promise.resolve(buf),
  } as unknown as Response;
}

/** テスト用 POST リクエストを生成する（正常系ボディ）*/
function makeRequest(body?: unknown): NextRequest {
  return new NextRequest('http://localhost/api/v2/report_pdf', {
    method: 'POST',
    body: JSON.stringify(body ?? {
      items: [
        { id: 'li_001', description: 'ノートPC', amount: 250_000, verdict: 'CAPITAL_LIKE' },
      ],
      summary: { capital_total: 250_000, expense_total: 0, guidance_total: 0 },
    }),
    headers: { 'Content-Type': 'application/json' },
  });
}

// ─── セットアップ ─────────────────────────────────────────────────────────────

beforeEach(() => {
  // デフォルト: バックエンドが PDF を正常返却
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(makePdfBackendResponse()));
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ─── 1. 正常系 ───────────────────────────────────────────────────────────────

describe('POST /api/v2/report_pdf — 正常系', () => {
  it('バックエンドが PDF を返すと 200 + Content-Type: application/pdf', async () => {
    /**
     * CHECK-9: route.ts L65-70
     *   backendRes.ok === true → new NextResponse(pdfBytes, { headers: { 'Content-Type': 'application/pdf' } })
     *   → status: 200, Content-Type: application/pdf
     */
    const res = await POST(makeRequest());

    expect(res.status).toBe(200);
    expect(res.headers.get('Content-Type')).toBe('application/pdf');
  });

  it('Content-Disposition ヘッダーに attachment + fixed_asset_report_*.pdf が含まれる', async () => {
    /**
     * CHECK-9: route.ts L62-69
     *   today = new Date().toISOString().slice(0, 10).replace(/-/g, '') → YYYYMMDD
     *   filename = `fixed_asset_report_${today}.pdf`
     *   Content-Disposition: attachment; filename="fixed_asset_report_YYYYMMDD.pdf"
     */
    const res = await POST(makeRequest());

    const disposition = res.headers.get('Content-Disposition') ?? '';
    expect(disposition).toContain('attachment');
    expect(disposition).toContain('fixed_asset_report_');
    expect(disposition).toMatch(/fixed_asset_report_\d{8}\.pdf/);
  });

  it('PDF バイナリが正確に転送される（CHECK-7b）', async () => {
    /**
     * CHECK-7b:
     *   MOCK_PDF_BYTES = [0x25, 0x50, 0x44, 0x46, ...] = %PDF-1.4 先頭8バイト
     *   route.ts L61: pdfBytes = await backendRes.arrayBuffer() → バイト列を保持
     *   route.ts L65: new NextResponse(pdfBytes, ...) → 同一バッファを転送
     *   → 取得した先頭4バイトが %PDF と一致することを確認
     */
    const res = await POST(makeRequest());

    const buf = await res.arrayBuffer();
    const returned = new Uint8Array(buf);

    // %PDF の先頭4バイト確認
    expect(returned[0]).toBe(0x25); // %
    expect(returned[1]).toBe(0x50); // P
    expect(returned[2]).toBe(0x44); // D
    expect(returned[3]).toBe(0x46); // F
    expect(returned.length).toBe(MOCK_PDF_BYTES.length); // 8バイト
  });

  it('fetch が正しい URL・メソッド・Content-Type ヘッダーで呼ばれる', async () => {
    /**
     * CHECK-9: route.ts L41-46
     *   fetch(`${API_BASE}/report/pdf`, { method: 'POST',
     *     headers: { 'Content-Type': 'application/json' },
     *     body: JSON.stringify(body), signal: controller.signal })
     */
    const mockFetch = vi.fn().mockResolvedValue(makePdfBackendResponse());
    vi.stubGlobal('fetch', mockFetch);

    await POST(makeRequest());

    expect(mockFetch).toHaveBeenCalledOnce();
    const [url, opts] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/report\/pdf$/);
    expect(opts.method).toBe('POST');
    expect((opts.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });
});

// ─── 2. バックエンド到達不能（503）───────────────────────────────────────────

describe('POST /api/v2/report_pdf — バックエンド到達不能', () => {
  it('ネットワークエラー → 503 + エラーメッセージ', async () => {
    /**
     * CHECK-9: route.ts L47-51
     *   fetch が Error を throw → catch(err) → err instanceof Error → err.message
     *   → return NextResponse.json({ error: msg }, { status: 503 })
     */
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connect ECONNREFUSED 127.0.0.1:8000')));

    const res = await POST(makeRequest());

    expect(res.status).toBe(503);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('connect ECONNREFUSED 127.0.0.1:8000');
  });

  it('fetch が非 Error 値を throw → 503 + "Backend unreachable"', async () => {
    /**
     * CHECK-9: route.ts L49
     *   err instanceof Error → false → msg = 'Backend unreachable'
     *   → return NextResponse.json({ error: 'Backend unreachable' }, { status: 503 })
     */
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue('unexpected string error'));

    const res = await POST(makeRequest());

    expect(res.status).toBe(503);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Backend unreachable');
  });
});

// ─── 3. 不正 JSON リクエスト ──────────────────────────────────────────────────

describe('POST /api/v2/report_pdf — 不正 JSON', () => {
  it('リクエストボディが不正 JSON → 400 + Invalid JSON', async () => {
    /**
     * CHECK-9: route.ts L29-32
     *   req.json() が SyntaxError → catch → 400 { error: 'Invalid JSON' }
     */
    const req = new NextRequest('http://localhost/api/v2/report_pdf', {
      method: 'POST',
      body: '{ invalid json !!! }',
      headers: { 'Content-Type': 'application/json' },
    });

    const res = await POST(req);

    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Invalid JSON');
  });
});

// ─── 4. バックエンドエラー中継 ───────────────────────────────────────────────

describe('POST /api/v2/report_pdf — バックエンドエラー中継', () => {
  it('バックエンド 503 → 503 + "Backend error: ..." 中継', async () => {
    /**
     * CHECK-9: route.ts L55-58
     *   !backendRes.ok → text = await backendRes.text()
     *   → NextResponse.json({ error: `Backend error: ${text}` }, { status: backendRes.status })
     *   backendRes.status=503 → 503 を中継
     */
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve('Service Unavailable'),
    } as unknown as Response));

    const res = await POST(makeRequest());

    expect(res.status).toBe(503);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Backend error: Service Unavailable');
  });

  it('バックエンド 422 (Unprocessable Entity) → 422 + エラー中継', async () => {
    /**
     * CHECK-9: route.ts L57 → status = backendRes.status (422)
     *   422 は Pydantic バリデーションエラー等で発生し得る
     */
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: () => Promise.resolve('Validation error: items is required'),
    } as unknown as Response));

    const res = await POST(makeRequest());

    expect(res.status).toBe(422);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Backend error: Validation error: items is required');
  });

  it('バックエンド 500 (Internal Server Error) → 500 + エラー中継', async () => {
    /**
     * CHECK-9: route.ts L57 → status = backendRes.status (500)
     */
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Internal Server Error'),
    } as unknown as Response));

    const res = await POST(makeRequest());

    expect(res.status).toBe(500);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Backend error: Internal Server Error');
  });
});
