/**
 * GET /api/v2/audit_trail テスト（一覧取得エンドポイント）
 *
 * T013: audit_trail 一覧エンドポイント追加 (cmd_182k_A4b)
 *
 * 検証対象:
 *   1. 正常系（全件）: GET → AuditRecord[] 全件を 200 で返す
 *   2. 正常系（空）  : ストアが空 → [] を 200 で返す
 *   3. limit パラメータ: ?limit=N → auditStore.list(N) が呼ばれる
 *   4. limit 不正値  : ?limit=0, ?limit=-1, ?limit=abc → 400 Invalid limit
 *   5. エラー系      : auditStore.list() が例外 → 500 Internal server error
 *
 * CHECK-9: テスト期待値根拠（route.ts ライン番号で示す）
 *   - route.ts L(try-catch): auditStore.list() 例外 → 500 { error: msg }
 *   - route.ts L(list call): auditStore.list(limit) → records
 *   - route.ts L(limit validation): limit <= 0 or NaN → 400 { error: 'Invalid limit parameter' }
 *   - route.ts L(json return): NextResponse.json(records) → 200 + JSON 配列
 *
 * モック方針:
 *   - auditStore.list を vi.mock でスタブ（SQLite 依存を排除）
 *   - GET リクエストは new NextRequest で生成
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NextRequest } from 'next/server';
import type { AuditRecord } from '@/types/audit_trail';

// ─── モック（vi.hoisted で巻き上げ）─────────────────────────────────────────

const { mockList } = vi.hoisted(() => ({
  mockList: vi.fn<(limit?: number) => AuditRecord[]>(),
}));

vi.mock('@/lib/agents/auditStore', () => ({
  auditStore: { list: mockList },
}));

// ─── テスト対象インポート（モック定義後に行う）──────────────────────────────

import { GET } from '@/app/api/v2/audit_trail/route';

// ─── テストフィクスチャ ──────────────────────────────────────────────────────

function makeRecord(overrides?: Partial<AuditRecord>): AuditRecord {
  return {
    audit_trail_id: 'trail_test001',
    request_id: 'req_uuid_001',
    timestamp: '2026-03-03T10:00:00.000Z',
    pdf_filename: 'document.pdf',
    line_items_count: 2,
    tax_verdict: 'CAPITAL',
    practice_verdict: 'CAPITAL',
    final_verdict: 'CAPITAL_LIKE',
    confidence: 0.95,
    account_category: '器具備品',
    useful_life: 4,
    elapsed_ms: 1200,
    model_used: 'claude-haiku-4-5',
    ...overrides,
  };
}

/** テスト用 GET リクエストを生成する */
function makeGetRequest(queryString = ''): NextRequest {
  const url = `http://localhost/api/v2/audit_trail${queryString}`;
  return new NextRequest(url, { method: 'GET' });
}

// ─── セットアップ ─────────────────────────────────────────────────────────────

beforeEach(() => {
  // デフォルト: 空配列を返す
  mockList.mockReturnValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
});

// ─── 1. 正常系（全件）────────────────────────────────────────────────────────

describe('GET /api/v2/audit_trail — 正常系', () => {
  it('レコードが2件あるとき → 200 + 配列 JSON を返す', async () => {
    /**
     * CHECK-9: route.ts → NextResponse.json(records) → status 200
     * auditStore.list() が2件を返す → そのまま JSON 配列として返却
     */
    const records = [
      makeRecord({ audit_trail_id: 'trail_001', timestamp: '2026-03-03T11:00:00.000Z' }),
      makeRecord({ audit_trail_id: 'trail_002', timestamp: '2026-03-03T10:00:00.000Z' }),
    ];
    mockList.mockReturnValue(records);

    const res = await GET(makeGetRequest());

    // CHECK-9: 200 OK
    expect(res.status).toBe(200);

    const body = await res.json() as AuditRecord[];
    expect(body).toHaveLength(2);
    expect(body[0].audit_trail_id).toBe('trail_001');
    expect(body[1].audit_trail_id).toBe('trail_002');
  });

  it('レスポンス配列の各レコードに全フィールドが含まれる', async () => {
    /**
     * CHECK-9: route.ts → auditStore.list() の戻り値をそのまま JSON.stringify
     * AuditRecord の全フィールドが欠落なく返ること
     */
    const record = makeRecord({ audit_trail_id: 'trail_full' });
    mockList.mockReturnValue([record]);

    const res = await GET(makeGetRequest());
    const body = await res.json() as AuditRecord[];

    expect(body[0]).toMatchObject({
      audit_trail_id: 'trail_full',
      request_id: 'req_uuid_001',
      pdf_filename: 'document.pdf',
      line_items_count: 2,
      tax_verdict: 'CAPITAL',
      practice_verdict: 'CAPITAL',
      final_verdict: 'CAPITAL_LIKE',
      confidence: 0.95,
      account_category: '器具備品',
      useful_life: 4,
      elapsed_ms: 1200,
      model_used: 'claude-haiku-4-5',
    });
  });

  it('auditStore.list() がパラメータなしで呼ばれる（クエリなしの場合）', async () => {
    /**
     * CHECK-9: route.ts → limit === undefined → auditStore.list(undefined)
     * limit パラメータが省略されたとき list は引数なしで呼ばれること
     */
    await GET(makeGetRequest());

    expect(mockList).toHaveBeenCalledOnce();
    expect(mockList).toHaveBeenCalledWith(undefined);
  });
});

// ─── 2. 正常系（空）─────────────────────────────────────────────────────────

describe('GET /api/v2/audit_trail — 空のストア', () => {
  it('レコードなし → 200 + 空配列 []', async () => {
    /**
     * CHECK-9: route.ts → auditStore.list() が [] を返す
     * → NextResponse.json([]) → status 200, body = []
     */
    mockList.mockReturnValue([]);

    const res = await GET(makeGetRequest());

    expect(res.status).toBe(200);
    const body = await res.json() as AuditRecord[];
    expect(body).toEqual([]);
    expect(body).toHaveLength(0);
  });
});

// ─── 3. limit クエリパラメータ ────────────────────────────────────────────────

describe('GET /api/v2/audit_trail — limit パラメータ', () => {
  it('?limit=2 → auditStore.list(2) が呼ばれる', async () => {
    /**
     * CHECK-9: route.ts → limitParam = '2' → limit = parseInt('2', 10) = 2
     * → auditStore.list(2) が呼ばれ、2件以内のレコードを返す
     */
    const twoRecords = [
      makeRecord({ audit_trail_id: 'trail_A' }),
      makeRecord({ audit_trail_id: 'trail_B' }),
    ];
    mockList.mockReturnValue(twoRecords);

    const res = await GET(makeGetRequest('?limit=2'));

    expect(res.status).toBe(200);
    expect(mockList).toHaveBeenCalledWith(2);
    const body = await res.json() as AuditRecord[];
    expect(body).toHaveLength(2);
  });

  it('?limit=1 → auditStore.list(1) が呼ばれ1件のみ返る', async () => {
    /**
     * CHECK-9: route.ts → limit = parseInt('1', 10) = 1 → auditStore.list(1)
     */
    mockList.mockReturnValue([makeRecord({ audit_trail_id: 'trail_latest' })]);

    const res = await GET(makeGetRequest('?limit=1'));

    expect(res.status).toBe(200);
    expect(mockList).toHaveBeenCalledWith(1);
    const body = await res.json() as AuditRecord[];
    expect(body).toHaveLength(1);
  });

  it('?limit=0 → 400 Invalid limit parameter', async () => {
    /**
     * CHECK-9: route.ts → limit = parseInt('0', 10) = 0 → limit <= 0 → 400
     */
    const res = await GET(makeGetRequest('?limit=0'));

    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Invalid limit parameter');
  });

  it('?limit=-1 → 400 Invalid limit parameter', async () => {
    /**
     * CHECK-9: route.ts → limit = parseInt('-1', 10) = -1 → limit <= 0 → 400
     */
    const res = await GET(makeGetRequest('?limit=-1'));

    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Invalid limit parameter');
  });

  it('?limit=abc → 400 Invalid limit parameter', async () => {
    /**
     * CHECK-9: route.ts → limit = parseInt('abc', 10) = NaN → isNaN(limit) → 400
     */
    const res = await GET(makeGetRequest('?limit=abc'));

    expect(res.status).toBe(400);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Invalid limit parameter');
  });
});

// ─── 4. エラー系 ─────────────────────────────────────────────────────────────

describe('GET /api/v2/audit_trail — エラー系', () => {
  it('auditStore.list() が例外 → 500 + エラーメッセージ', async () => {
    /**
     * CHECK-9: route.ts → try { auditStore.list() } catch(err) → 500 { error: msg }
     * DB 障害等で list() が例外を投げた場合、500 を返すこと
     */
    mockList.mockImplementation(() => {
      throw new Error('Database connection lost');
    });

    const res = await GET(makeGetRequest());

    expect(res.status).toBe(500);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Database connection lost');
  });

  it('auditStore.list() が非 Error オブジェクトを throw → 500 + "Internal server error"', async () => {
    /**
     * CHECK-9: route.ts → err instanceof Error ? err.message : 'Internal server error'
     */
    mockList.mockImplementation(() => {
      throw 'unexpected string error'; // eslint-disable-line @typescript-eslint/no-throw-literal
    });

    const res = await GET(makeGetRequest());

    expect(res.status).toBe(500);
    const body = await res.json() as { error: string };
    expect(body.error).toBe('Internal server error');
  });
});
