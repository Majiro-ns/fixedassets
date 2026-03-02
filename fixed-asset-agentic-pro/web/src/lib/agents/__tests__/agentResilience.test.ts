/**
 * agentResilience.test.ts
 *
 * Phase 2 エージェント耐障害性テスト（cmd_138k_sub3）
 *
 * 検証対象:
 *   1. リトライ戦略: 1回目失敗→2回目成功 / 全失敗→UNCERTAIN
 *   2. キルスイッチ: TAX_AGENT_ENABLED / PRACTICE_AGENT_ENABLED の全パターン
 *   3. モデル切替: TAX_AGENT_MODEL / PRACTICE_AGENT_MODEL 環境変数
 *   4. タイムアウト: デフォルト定数確認
 *
 * CHECK-9: テスト期待値根拠
 *   - リトライ戦略: MAX_RETRIES=2（attempt 0,1,2 の3回試行）
 *   - 指数バックオフ: 100ms → 200ms（本テストでは実時間経過あり）
 *   - キルスイッチデフォルト: 環境変数未設定 = 有効（true）
 *   - モデルデフォルト: claude-haiku-4-5-20251001
 *   - タイムアウトデフォルト: 30,000ms
 *
 * API モック方針:
 *   vi.hoisted + vi.mock('@anthropic-ai/sdk') で SDK を完全モック。
 *   vi.stubEnv で環境変数を各テストで制御。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';
import type { TrainingRecord } from '@/types/training_data';

// ─── SDK モック（vi.hoisted で hoisting 問題を回避）──────────────────────

const { mockTaxCreate, mockPracticeCreate } = vi.hoisted(() => ({
  mockTaxCreate: vi.fn(),
  mockPracticeCreate: vi.fn(),
}));

// taxAgent と practiceAgent は同じ @anthropic-ai/sdk を使うが、
// ここでは共通のモックファクトリを使い、各テストで差し替える
vi.mock('@anthropic-ai/sdk', () => ({
  default: function MockAnthropic() {
    return { messages: { create: mockTaxCreate } };
  },
}));

// ─── テスト対象インポート ──────────────────────────────────────────────────

import {
  runTaxAgent,
  TAX_AGENT_DEFAULT_MODEL,
  TAX_AGENT_DEFAULT_TIMEOUT_MS,
} from '../taxAgent';
import {
  runPracticeAgent,
  PRACTICE_AGENT_DEFAULT_TIMEOUT_MS,
} from '../practiceAgent';
import { getFeatureFlags } from '@/app/api/v2/classify_pdf/route.helpers';

// ─── テストデータ ──────────────────────────────────────────────────────────

function makeItem(id: string, desc: string, amount: number): ExtractedLineItem {
  return { line_item_id: id, description: desc, amount };
}

const testItems: ExtractedLineItem[] = [
  makeItem('li_001', 'サーバー設備', 500_000),
];

const testTrainingRecords: TrainingRecord[] = [
  { item: 'サーバー', amount: 300_000, label: '固定資産' },
];

/** TaxAgent 成功レスポンスモック */
function taxSuccessResponse() {
  return {
    content: [
      {
        type: 'text',
        text: JSON.stringify([
          {
            line_item_id: 'li_001',
            verdict: 'CAPITAL',
            rationale: 'サーバー設備は固定資産',
            article_ref: '法人税法施行令第133条',
            account_category: '器具備品',
            useful_life: 5,
            formal_criteria_step: null,
            confidence: 0.9,
          },
        ]),
      },
    ],
  };
}

/** PracticeAgent 成功レスポンスモック */
function practiceSuccessResponse() {
  return {
    content: [
      {
        type: 'text',
        text: JSON.stringify([
          {
            line_item_id: 'li_001',
            verdict: 'CAPITAL',
            rationale: '類似事例あり',
            suggested_account: '器具備品',
            confidence: 0.85,
            similar_cases: [],
          },
        ]),
      },
    ],
  };
}

// ─── 1. リトライ戦略: TaxAgent ────────────────────────────────────────────

describe('TaxAgent: リトライ戦略', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test-key-tax');
    vi.stubEnv('TAX_AGENT_TIMEOUT_MS', '5000'); // テスト高速化
    mockTaxCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('1回目失敗→2回目成功: CAPITALを返す', async () => {
    mockTaxCreate
      .mockRejectedValueOnce(new Error('Network timeout'))
      .mockResolvedValueOnce(taxSuccessResponse());

    const results = await runTaxAgent(testItems);

    expect(results).toHaveLength(1);
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].line_item_id).toBe('li_001');
    // 2回呼ばれた（1回失敗 + 1回成功）
    expect(mockTaxCreate).toHaveBeenCalledTimes(2);
  }, 10_000);

  it('3回全失敗: UNCERTAIN を返す', async () => {
    mockTaxCreate.mockRejectedValue(new Error('API unavailable'));

    const results = await runTaxAgent(testItems);

    expect(results).toHaveLength(1);
    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].rationale).toContain('APIエラー');
    // 3回試みた（attempt 0,1,2）
    expect(mockTaxCreate).toHaveBeenCalledTimes(3);
  }, 10_000);

  it('1回目・2回目失敗→3回目成功: CAPITALを返す', async () => {
    mockTaxCreate
      .mockRejectedValueOnce(new Error('timeout'))
      .mockRejectedValueOnce(new Error('timeout'))
      .mockResolvedValueOnce(taxSuccessResponse());

    const results = await runTaxAgent(testItems);

    expect(results[0].verdict).toBe('CAPITAL');
    expect(mockTaxCreate).toHaveBeenCalledTimes(3);
  }, 10_000);
});

// ─── 2. リトライ戦略: PracticeAgent ───────────────────────────────────────

describe('PracticeAgent: リトライ戦略', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test-key-practice');
    vi.stubEnv('PRACTICE_AGENT_TIMEOUT_MS', '5000');
    mockTaxCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('1回目失敗→2回目成功: CAPITALを返す', async () => {
    mockTaxCreate
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValueOnce(practiceSuccessResponse());

    const results = await runPracticeAgent(testItems, testTrainingRecords);

    expect(results).toHaveLength(1);
    expect(results[0].verdict).toBe('CAPITAL');
    expect(mockTaxCreate).toHaveBeenCalledTimes(2);
  }, 10_000);

  it('3回全失敗: UNCERTAIN を返す', async () => {
    mockTaxCreate.mockRejectedValue(new Error('Service down'));

    const results = await runPracticeAgent(testItems, testTrainingRecords);

    expect(results).toHaveLength(1);
    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].rationale).toContain('APIエラー');
    expect(mockTaxCreate).toHaveBeenCalledTimes(3);
  }, 10_000);
});

// ─── 3. モデル切替: 環境変数オーバーライド ────────────────────────────────

describe('モデル切替: 環境変数', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test-key');
    vi.stubEnv('TAX_AGENT_TIMEOUT_MS', '5000');
    vi.stubEnv('PRACTICE_AGENT_TIMEOUT_MS', '5000');
    mockTaxCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('TAX_AGENT_MODEL 未設定: デフォルトモデルを使用', async () => {
    mockTaxCreate.mockResolvedValueOnce(taxSuccessResponse());
    await runTaxAgent(testItems);

    expect(mockTaxCreate).toHaveBeenCalledWith(
      expect.objectContaining({ model: TAX_AGENT_DEFAULT_MODEL }),
      expect.anything(),
    );
  });

  it('TAX_AGENT_MODEL=claude-sonnet-4-6: Sonnetを使用', async () => {
    vi.stubEnv('TAX_AGENT_MODEL', 'claude-sonnet-4-6');
    mockTaxCreate.mockResolvedValueOnce(taxSuccessResponse());
    await runTaxAgent(testItems);

    expect(mockTaxCreate).toHaveBeenCalledWith(
      expect.objectContaining({ model: 'claude-sonnet-4-6' }),
      expect.anything(),
    );
  });

  it('config.model が環境変数より優先される', async () => {
    vi.stubEnv('TAX_AGENT_MODEL', 'claude-sonnet-4-6');
    mockTaxCreate.mockResolvedValueOnce(taxSuccessResponse());
    await runTaxAgent(testItems, { model: 'claude-opus-4-6' });

    expect(mockTaxCreate).toHaveBeenCalledWith(
      expect.objectContaining({ model: 'claude-opus-4-6' }),
      expect.anything(),
    );
  });

  it('PRACTICE_AGENT_MODEL=claude-sonnet-4-6: Sonnetを使用', async () => {
    vi.stubEnv('PRACTICE_AGENT_MODEL', 'claude-sonnet-4-6');
    mockTaxCreate.mockResolvedValueOnce(practiceSuccessResponse());
    await runPracticeAgent(testItems, testTrainingRecords);

    expect(mockTaxCreate).toHaveBeenCalledWith(
      expect.objectContaining({ model: 'claude-sonnet-4-6' }),
      expect.anything(),
    );
  });
});

// ─── 4. タイムアウト: デフォルト定数確認 ──────────────────────────────────

describe('タイムアウト: デフォルト定数', () => {
  it('TAX_AGENT_DEFAULT_TIMEOUT_MS は 30,000ms', () => {
    expect(TAX_AGENT_DEFAULT_TIMEOUT_MS).toBe(30_000);
  });

  it('PRACTICE_AGENT_DEFAULT_TIMEOUT_MS は 30,000ms', () => {
    expect(PRACTICE_AGENT_DEFAULT_TIMEOUT_MS).toBe(30_000);
  });
});

// ─── 5. キルスイッチ: getFeatureFlags ─────────────────────────────────────

describe('getFeatureFlags: キルスイッチ', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('デフォルト（環境変数未設定）: 両エージェント有効', () => {
    const flags = getFeatureFlags();
    expect(flags.taxAgentEnabled).toBe(true);
    expect(flags.practiceAgentEnabled).toBe(true);
  });

  it('TAX_AGENT_ENABLED=false: Tax無効', () => {
    vi.stubEnv('TAX_AGENT_ENABLED', 'false');
    const flags = getFeatureFlags();
    expect(flags.taxAgentEnabled).toBe(false);
    expect(flags.practiceAgentEnabled).toBe(true);
  });

  it('PRACTICE_AGENT_ENABLED=false: Practice無効', () => {
    vi.stubEnv('PRACTICE_AGENT_ENABLED', 'false');
    const flags = getFeatureFlags();
    expect(flags.taxAgentEnabled).toBe(true);
    expect(flags.practiceAgentEnabled).toBe(false);
  });

  it('両方 false: 両エージェント無効', () => {
    vi.stubEnv('TAX_AGENT_ENABLED', 'false');
    vi.stubEnv('PRACTICE_AGENT_ENABLED', 'false');
    const flags = getFeatureFlags();
    expect(flags.taxAgentEnabled).toBe(false);
    expect(flags.practiceAgentEnabled).toBe(false);
  });

  it('TAX_AGENT_ENABLED=true: Tax有効（明示的true）', () => {
    vi.stubEnv('TAX_AGENT_ENABLED', 'true');
    const flags = getFeatureFlags();
    expect(flags.taxAgentEnabled).toBe(true);
  });

  it('getFeatureFlags は既存フラグを破壊しない', () => {
    vi.stubEnv('USE_MULTI_AGENT', 'true');
    vi.stubEnv('PARALLEL_AGENTS', 'false');
    const flags = getFeatureFlags();
    expect(flags.useMultiAgent).toBe(true);
    expect(flags.parallelAgents).toBe(false);
    expect(flags.taxAgentEnabled).toBe(true);
    expect(flags.practiceAgentEnabled).toBe(true);
  });
});
