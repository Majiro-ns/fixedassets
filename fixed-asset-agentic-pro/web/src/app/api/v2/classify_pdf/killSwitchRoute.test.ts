/**
 * killSwitchRoute.test.ts
 * キルスイッチ + Phase 1フォールバック: route.ts レベル統合テスト（cmd_140k_sub2）
 *
 * 検証対象:
 *   1. キルスイッチ 4パターン: 両有効 / Tax無効 / Practice無効 / 両無効
 *   2. Phase 1フォールバック: 両無効時に aggregate が呼ばれず Phase 1形式で返る
 *   3. USE_MULTI_AGENT=false: エージェント呼ばれない
 *   4. 片方エージェント失敗(rejected): agentStatus=partial
 *   5. aggregate呼び出し引数: Tax/Practice 無効時に null が渡る
 *
 * CHECK-9: テスト期待値根拠
 *   - キルスイッチデフォルト: 環境変数未設定 = 有効（route.helpers.ts getFeatureFlags）
 *   - Phase 1フォールバック: TAX+PRACTICE 両方false → transformToV2 を使用（route.ts L141-144）
 *   - USE_MULTI_AGENT=false → multi-agentブロック未入場 → エージェント呼ばれない（route.ts L137）
 *   - agentStatus=partial: Promise.allSettled.rejected 時（route.ts L165-167）
 *
 * モック方針:
 *   - runTaxAgent / runPracticeAgent / aggregate を vi.mock でモック
 *   - global.fetch を vi.stubGlobal で Python backend レスポンスに差し替え
 *   - NextRequest で POST ハンドラを直接呼び出す
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { NextRequest } from 'next/server';
import type { ClassifyResponse } from '@/types/classify';
import type { TaxAgentResult, PracticeAgentResult } from '@/types/multi_agent';
import type { AggregatedResult } from '@/types/multi_agent';

// ─── エージェントモック（vi.hoisted で巻き上げ）─────────────────────────────

const { mockRunTaxAgent, mockRunPracticeAgent, mockAggregate } = vi.hoisted(() => ({
  mockRunTaxAgent: vi.fn(),
  mockRunPracticeAgent: vi.fn(),
  mockAggregate: vi.fn(),
}));

vi.mock('@/lib/agents/taxAgent', () => ({
  runTaxAgent: mockRunTaxAgent,
}));
vi.mock('@/lib/agents/practiceAgent', () => ({
  runPracticeAgent: mockRunPracticeAgent,
}));
vi.mock('@/lib/agents/aggregator', () => ({
  aggregate: mockAggregate,
}));
vi.mock('@/lib/agents/trainingDataStore', () => ({
  trainingDataStore: { getAll: vi.fn().mockReturnValue([]) },
}));

// ─── テスト対象インポート（モック定義後に行う）──────────────────────────────

import { POST } from './route';

// ─── テストフィクスチャ ──────────────────────────────────────────────────────

/** Python backend が返す ClassifyResponse モック（CAPITAL_LIKE 1明細）*/
const mockClassifyResponse: ClassifyResponse = {
  decision: 'CAPITAL_LIKE',
  reasons: ['テスト判定'],
  evidence: [],
  questions: [],
  metadata: {},
  is_valid_document: true,
  confidence: 0.9,
  trace: [],
  missing_fields: [],
  why_missing_matters: [],
  citations: [],
  disclaimer: '',
  line_items: [
    { description: 'サーバー設備', amount: 500_000, classification: 'CAPITAL_LIKE' },
  ],
};

/** Tax Agent 成功レスポンスモック */
const mockTaxResult: TaxAgentResult = {
  line_item_id: 'li_mock_001',
  verdict: 'CAPITAL',
  rationale: 'テスト用Tax判定',
  article_ref: null,
  account_category: '器具備品',
  useful_life: 5,
  formal_criteria_step: null,
  confidence: 0.9,
};

/** Practice Agent 成功レスポンスモック */
const mockPracticeResult: PracticeAgentResult = {
  line_item_id: 'li_mock_001',
  verdict: 'CAPITAL',
  rationale: 'テスト用Practice判定',
  similar_cases: [],
  suggested_account: '器具備品',
  confidence: 0.85,
};

/** Aggregator 結果モック */
const mockAggregatedResult: AggregatedResult = {
  line_item_id: 'li_mock_001',
  final_verdict: 'CAPITAL_LIKE',
  confidence: 0.95,
  account_category: '器具備品',
  useful_life: 5,
  tax_result: mockTaxResult,
  practice_result: mockPracticeResult,
};

/** テスト用 NextRequest を生成する */
function makeRequest(): NextRequest {
  const pdf_base64 = Buffer.from('%PDF-1.4 mock content').toString('base64');
  return new NextRequest('http://localhost/api/v2/classify_pdf', {
    method: 'POST',
    body: JSON.stringify({ pdf_base64 }),
    headers: { 'Content-Type': 'application/json' },
  });
}

// ─── セットアップ ────────────────────────────────────────────────────────────

beforeEach(() => {
  // Python backend mock
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(mockClassifyResponse),
  }));

  // エージェントデフォルト: 成功レスポンスを返す
  mockRunTaxAgent.mockResolvedValue([mockTaxResult]);
  mockRunPracticeAgent.mockResolvedValue([mockPracticeResult]);
  mockAggregate.mockReturnValue([mockAggregatedResult]);

  // デフォルト環境変数: マルチエージェント有効
  vi.stubEnv('USE_MULTI_AGENT', 'true');
  vi.stubEnv('ANTHROPIC_API_KEY', 'test-key');
  vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://localhost:8000');
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  mockRunTaxAgent.mockReset();
  mockRunPracticeAgent.mockReset();
  mockAggregate.mockReset();
});

// ─── 1. キルスイッチ: 両有効 ─────────────────────────────────────────────────

describe('キルスイッチ: 両有効（USE_MULTI_AGENT=true, 両フラグ未設定）', () => {
  it('Tax と Practice の両エージェントが呼び出される', async () => {
    // デフォルト: TAX_AGENT_ENABLED=true, PRACTICE_AGENT_ENABLED=true（未設定 = 有効）
    await POST(makeRequest());

    // CHECK-9: getFeatureFlags() 未設定時のデフォルトは true（route.helpers.ts L31-32）
    expect(mockRunTaxAgent).toHaveBeenCalledTimes(1);
    expect(mockRunPracticeAgent).toHaveBeenCalledTimes(1);
  });

  it('aggregate が呼ばれてマルチエージェントレスポンスを返す', async () => {
    const res = await POST(makeRequest());
    const body = await res.json();

    expect(mockAggregate).toHaveBeenCalledTimes(1);
    // マルチエージェント形式: line_results[0].tax_verdict が agent の値
    expect(body.line_results[0].tax_verdict).toBe('CAPITAL');
    expect(body.line_results[0].practice_verdict).toBe('CAPITAL');
  });
});

// ─── 2. キルスイッチ: Tax無効 ────────────────────────────────────────────────

describe('キルスイッチ: TAX_AGENT_ENABLED=false', () => {
  beforeEach(() => {
    vi.stubEnv('TAX_AGENT_ENABLED', 'false');
  });

  it('Tax は呼ばれず、Practice のみ呼ばれる', async () => {
    await POST(makeRequest());

    // CHECK-9: TAX_AGENT_ENABLED=false → route.ts L155-158 で taxPromise=null に解決
    expect(mockRunTaxAgent).not.toHaveBeenCalled();
    expect(mockRunPracticeAgent).toHaveBeenCalledTimes(1);
  });

  it('aggregate には taxResults=null が渡される', async () => {
    await POST(makeRequest());

    // CHECK-9: 根拠: route.ts L162-163 taxSettled.value = null
    const aggregateCall = mockAggregate.mock.calls[0];
    expect(aggregateCall[0]).toBeNull();      // taxResults = null
    expect(aggregateCall[1]).not.toBeNull();  // practiceResults = [mockPracticeResult]
  });
});

// ─── 3. キルスイッチ: Practice無効 ──────────────────────────────────────────

describe('キルスイッチ: PRACTICE_AGENT_ENABLED=false', () => {
  beforeEach(() => {
    vi.stubEnv('PRACTICE_AGENT_ENABLED', 'false');
  });

  it('Practice は呼ばれず、Tax のみ呼ばれる', async () => {
    await POST(makeRequest());

    // CHECK-9: PRACTICE_AGENT_ENABLED=false → route.ts L159-160 で practicePromise=null
    expect(mockRunTaxAgent).toHaveBeenCalledTimes(1);
    expect(mockRunPracticeAgent).not.toHaveBeenCalled();
  });

  it('aggregate には practiceResults=null が渡される', async () => {
    await POST(makeRequest());

    const aggregateCall = mockAggregate.mock.calls[0];
    expect(aggregateCall[0]).not.toBeNull();  // taxResults = [mockTaxResult]
    expect(aggregateCall[1]).toBeNull();       // practiceResults = null
  });
});

// ─── 4. キルスイッチ: 両無効 → Phase 1フォールバック ────────────────────────

describe('キルスイッチ: 両方無効 → Phase 1フォールバック', () => {
  beforeEach(() => {
    vi.stubEnv('TAX_AGENT_ENABLED', 'false');
    vi.stubEnv('PRACTICE_AGENT_ENABLED', 'false');
  });

  it('Tax / Practice どちらも呼ばれない', async () => {
    await POST(makeRequest());

    // CHECK-9: 根拠: route.ts L141-144 両無効チェック後に即 Phase 1 return
    expect(mockRunTaxAgent).not.toHaveBeenCalled();
    expect(mockRunPracticeAgent).not.toHaveBeenCalled();
  });

  it('aggregate も呼ばれない（Phase 1 パスへの分岐）', async () => {
    await POST(makeRequest());

    expect(mockAggregate).not.toHaveBeenCalled();
  });

  it('レスポンスは Phase 1 形式（tax_verdict が classify 判定値）', async () => {
    const res = await POST(makeRequest());
    const body = await res.json();

    // CHECK-9: Phase 1 形式 = transformToV2() の出力
    // tax_verdict / practice_verdict はどちらも normalizeVerdict(classify.decision)
    // mockClassifyResponse.decision = 'CAPITAL_LIKE' → normalizeVerdict = 'CAPITAL_LIKE'
    expect(body.status).toBe('success');
    expect(body.line_results.length).toBeGreaterThan(0);
    expect(body.line_results[0].tax_verdict).toBe('CAPITAL_LIKE');
    expect(body.line_results[0].practice_verdict).toBe('CAPITAL_LIKE');
  });
});

// ─── 5. USE_MULTI_AGENT=false: Phase 1パス ───────────────────────────────────

describe('USE_MULTI_AGENT=false: Phase 1パス', () => {
  beforeEach(() => {
    vi.stubEnv('USE_MULTI_AGENT', 'false');
  });

  it('USE_MULTI_AGENT=false → エージェント呼ばれず Phase 1フォーマット', async () => {
    const res = await POST(makeRequest());

    // CHECK-9: route.ts L137 USE_MULTI_AGENT=false → L191 Phase 1 フォールバック
    expect(mockRunTaxAgent).not.toHaveBeenCalled();
    expect(mockRunPracticeAgent).not.toHaveBeenCalled();
    expect(mockAggregate).not.toHaveBeenCalled();

    const body = await res.json();
    expect(body.status).toBe('success');
    expect(body.request_id).toBeTruthy();
  });
});

// ─── 6. 片方エージェント失敗: agentStatus=partial ────────────────────────────

describe('片方エージェント失敗: agentStatus=partial', () => {
  it('Tax 失敗（rejected）→ status=partial を返す', async () => {
    mockRunTaxAgent.mockRejectedValue(new Error('Tax API down'));
    // aggregateはtaxResults=null, practiceResults=[...]で呼ばれる
    mockAggregate.mockReturnValue([mockAggregatedResult]);

    const res = await POST(makeRequest());
    const body = await res.json();

    // CHECK-9: route.ts L165-167 rejected → agentStatus='partial'
    // transformAggregatedToV2 に agentStatus='partial' が渡される → status='partial'
    expect(body.status).toBe('partial');
  });

  it('Practice 失敗（rejected）→ status=partial を返す', async () => {
    mockRunPracticeAgent.mockRejectedValue(new Error('Practice API down'));
    mockAggregate.mockReturnValue([mockAggregatedResult]);

    const res = await POST(makeRequest());
    const body = await res.json();

    expect(body.status).toBe('partial');
  });
});
