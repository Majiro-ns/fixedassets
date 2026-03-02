/**
 * taxAgent.test.ts
 *
 * CHECK-9: テスト期待値は DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.3 から直接引用。
 *   - 形式基準6段階（基通7-8-3〜6）の判定ルール
 *   - 一括償却資産3段階（10万/20万/30万）の判定ルール
 *   - 勘定科目マッピング（耐用年数省令別表一）
 *
 * CHECK-7b 手動検証:
 *   Step 1: < 20万円 → EXPENSE（基通7-8-3(1)）
 *   Step 3: < 60万円 → EXPENSE（基通7-8-4(1)）
 *   Step 5: 資産価値向上明確 → CAPITAL（令第132条）
 *
 * API モック方針: vi.mock('@anthropic-ai/sdk') で SDK を完全モック。
 *   ANTHROPIC_API_KEY は vi.stubEnv で各テストグループで制御。
 */

import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';

// ─── SDK モック（vi.hoisted で hoisting 問題を回避）──────────────────────

const { mockMessagesCreate } = vi.hoisted(() => ({
  mockMessagesCreate: vi.fn(),
}));

vi.mock('@anthropic-ai/sdk', () => ({
  default: function MockAnthropic() {
    return { messages: { create: mockMessagesCreate } };
  },
}));

// ─── テスト対象のインポート（モック後に行う）─────────────────────────────

import { runTaxAgent, parseResponse, TAX_AGENT_SYSTEM_PROMPT } from '../taxAgent';

// ─── テスト用ファクトリ関数 ─────────────────────────────────────────────────

function makeItem(
  line_item_id: string,
  description: string,
  amount: number,
): ExtractedLineItem {
  return { line_item_id, description, amount };
}

/** Anthropic API のモックレスポンスを生成する */
function mockApiResponse(results: object[]) {
  mockMessagesCreate.mockResolvedValue({
    content: [{ type: 'text', text: JSON.stringify(results) }],
  });
}

// ─── ドライランモード（APIキー未設定）────────────────────────────────────

describe('runTaxAgent: ドライランモード（根拠: Section 6 エラーハンドリング）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', '');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('APIキー未設定 → 全件 UNCERTAIN を返す', async () => {
    const items = [makeItem('L1', 'ノートPC', 150000)];
    const results = await runTaxAgent(items);

    expect(results).toHaveLength(1);
    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].rationale).toContain('DRY-RUN');
    expect(results[0].line_item_id).toBe('L1');
  });

  it('APIキー未設定 → Anthropic SDK が呼ばれない', async () => {
    await runTaxAgent([makeItem('L1', 'PC', 500000)]);
    expect(mockMessagesCreate).not.toHaveBeenCalled();
  });

  it('APIキー未設定 + 複数明細 → 前処理済み明細はEXPENSE、LLM必要明細はUNCERTAIN', async () => {
    // NOTE: preScreenLineItems() 導入(cmd_144k_sub1)により振る舞い変更。
    //   前処理対象（10万未満等）はAPIキー不要でEXPENSE確定。
    //   LLM必要な明細のみ UNCERTAIN(DRY-RUN)。
    const items = [
      makeItem('L1', 'PC', 500000),       // LLM必要 → UNCERTAIN
      makeItem('L2', '消耗品', 50000),    // rule_a: 5万 < 10万 → EXPENSE
    ];
    const results = await runTaxAgent(items);

    expect(results).toHaveLength(2);

    const l1 = results.find((r) => r.line_item_id === 'L1')!;
    expect(l1.verdict).toBe('UNCERTAIN');
    expect(l1.rationale).toContain('DRY-RUN');

    const l2 = results.find((r) => r.line_item_id === 'L2')!;
    expect(l2.verdict).toBe('EXPENSE');
    expect(l2.article_ref).toContain('133条');
  });
});

// ─── 空入力 ─────────────────────────────────────────────────────────────────

describe('runTaxAgent: 空入力', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-test-key');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('lineItems = [] → 空配列を返す', async () => {
    const result = await runTaxAgent([]);
    expect(result).toEqual([]);
  });

  it('lineItems = [] → SDK が呼ばれない', async () => {
    await runTaxAgent([]);
    expect(mockMessagesCreate).not.toHaveBeenCalled();
  });
});

// ─── 正常系テスト（APIモック）────────────────────────────────────────────

describe('runTaxAgent: 正常系（根拠: Section 3.3 勘定科目マッピング）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-test-key');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  // CHECK-9 根拠: Section 3.3 勘定科目マッピング「PC → 器具備品, 4年」
  it('CAPITAL判定: PC 50万円 → 器具備品 4年（基通: 別表一）', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'CAPITAL',
        rationale: 'PCは器具備品（電子計算機）に該当',
        article_ref: '耐用年数省令別表一',
        account_category: '器具備品',
        useful_life: 4,
        formal_criteria_step: null,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', 'ノートPC', 500000)]);

    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('器具備品');
    expect(results[0].useful_life).toBe(4);
    expect(results[0].article_ref).toBeTruthy();
  });

  // CHECK-9 根拠: Section 3.3 勘定科目マッピング「エアコン → 建物附属設備, 13年」
  it('CAPITAL判定: エアコン 80万円 → 建物附属設備 13年', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'CAPITAL',
        rationale: 'エアコンは建物附属設備（冷暖房設備）に該当',
        article_ref: '耐用年数省令別表一',
        account_category: '建物附属設備',
        useful_life: 13,
        formal_criteria_step: null,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', 'エアコン設置', 800000)]);

    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('建物附属設備');
    expect(results[0].useful_life).toBe(13);
  });

  // CHECK-9 根拠: Section 3.3 一括償却「10万円未満 → 消耗品費」
  it('EXPENSE判定: 消耗品 5万円 → 消耗品費（法人税法施行令第133条）', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'EXPENSE',
        rationale: '10万円未満のため即時費用化',
        article_ref: '法人税法施行令第133条',
        account_category: '消耗品費',
        useful_life: null,
        formal_criteria_step: null,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', '文具・消耗品', 50000)]);

    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].account_category).toBe('消耗品費');
    expect(results[0].useful_life).toBeNull();
  });
});

// ─── 形式基準6段階テスト（Section 3.3 Step 1〜6）────────────────────────

describe('runTaxAgent: 資本的支出 vs 修繕費 形式基準（根拠: Section 3.3 基通7-8-3〜6）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-test-key');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  // CHECK-9 根拠: Section 3.3 Step 1「支出額 < 20万円 → 修繕費（基通7-8-3(1)）」
  it('Step 1: 修繕費 15万円（< 20万円）→ EXPENSE, 基通7-8-3(1), formal_criteria_step=1', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'EXPENSE',
        rationale: '支出額15万円 < 20万円のため少額修繕費',
        article_ref: '基通7-8-3(1)',
        account_category: '修繕費',
        useful_life: null,
        formal_criteria_step: 1,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', 'エアコン修理', 150000)]);

    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].article_ref).toBe('基通7-8-3(1)');
    expect(results[0].formal_criteria_step).toBe(1);
    expect(results[0].account_category).toBe('修繕費');
  });

  // CHECK-9 根拠: Section 3.3 Step 3「支出額 < 60万円 → 修繕費（基通7-8-4(1)）」
  it('Step 3: 修繕費 45万円（< 60万円）→ EXPENSE, 基通7-8-4(1), formal_criteria_step=3', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'EXPENSE',
        rationale: '支出額45万円 < 60万円の形式基準を満たす',
        article_ref: '基通7-8-4(1)',
        account_category: '修繕費',
        useful_life: null,
        formal_criteria_step: 3,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', '外壁補修工事', 450000)]);

    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].article_ref).toBe('基通7-8-4(1)');
    expect(results[0].formal_criteria_step).toBe(3);
  });

  // CHECK-9 根拠: Section 3.3 Step 5「資産価値向上 → 資本的支出（令第132条）」
  it('Step 5: 資産価値向上が明らか → CAPITAL, 法人税法施行令第132条, formal_criteria_step=5', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'CAPITAL',
        rationale: '建物の耐用年数が明らかに延長される改修のため資本的支出',
        article_ref: '法人税法施行令第132条',
        account_category: '建物',
        useful_life: 30,
        formal_criteria_step: 5,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', '屋根改修（耐用年数延長）', 3000000)]);

    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].article_ref).toBe('法人税法施行令第132条');
    expect(results[0].formal_criteria_step).toBe(5);
  });

  // CHECK-9 根拠: Section 3.3 Step 6「上記いずれにも該当しない → UNCERTAIN」
  it('Step 6: 判定不能 → UNCERTAIN, formal_criteria_step=6', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'UNCERTAIN',
        rationale: '形式基準のいずれにも明確に該当しない',
        article_ref: '基通7-8-6',
        account_category: null,
        useful_life: null,
        formal_criteria_step: 6,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', '工事（詳細不明）', 1500000)]);

    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].formal_criteria_step).toBe(6);
  });
});

// ─── 一括償却資産3段階テスト（Section 3.3）───────────────────────────────

describe('runTaxAgent: 一括償却資産3段階判定（根拠: Section 3.3 法人税法施行令第133条等）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-test-key');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  // CHECK-9 根拠: Section 3.3「10万円未満 → EXPENSE, 消耗品費（令第133条）」
  it('< 10万円 → EXPENSE, 消耗品費, 令第133条', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'EXPENSE',
        rationale: '9.8万円 < 10万円のため即時費用化',
        article_ref: '法人税法施行令第133条',
        account_category: '消耗品費',
        useful_life: null,
        formal_criteria_step: null,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', '椅子', 98000)]);

    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].account_category).toBe('消耗品費');
    expect(results[0].article_ref).toContain('133条');
  });

  // CHECK-9 根拠: Section 3.3「10〜20万円未満 → 選択可（一括償却資産）令第133条の2」
  it('10〜20万円未満 → EXPENSE（一括償却資産として処理可）, 令第133条の2', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'EXPENSE',
        rationale: '15万円: 一括償却資産（3年均等）を選択',
        article_ref: '法人税法施行令第133条の2',
        account_category: '一括償却資産',
        useful_life: null,
        formal_criteria_step: null,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', '椅子（高品質）', 150000)]);

    expect(results[0].article_ref).toContain('133条');
  });

  // CHECK-9 根拠: Section 3.3「30万円以上 → 通常の固定資産（CAPITAL）」
  it('>= 30万円 → CAPITAL（通常の固定資産として減価償却）', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'CAPITAL',
        rationale: '50万円 ≥ 30万円のため固定資産計上（通常の減価償却）',
        article_ref: '耐用年数省令別表一',
        account_category: '器具備品',
        useful_life: 4,
        formal_criteria_step: null,
      },
    ]);

    const results = await runTaxAgent([makeItem('L1', 'ノートPC', 500000)]);

    expect(results[0].verdict).toBe('CAPITAL');
  });
});

// ─── エラー処理テスト ─────────────────────────────────────────────────────

describe('runTaxAgent: エラー処理（根拠: Section 6 エラーハンドリング）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-test-key');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('API呼び出し失敗（throw）→ 全件 UNCERTAIN を返す', async () => {
    mockMessagesCreate.mockRejectedValue(new Error('API接続エラー'));

    const results = await runTaxAgent([makeItem('L1', 'PC', 500000)]);

    expect(results).toHaveLength(1);
    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].rationale).toContain('APIエラー');
    expect(results[0].line_item_id).toBe('L1');
  });

  it('API呼び出し失敗（複数明細）→ 前処理済みはEXPENSE保持、LLM必要分はUNCERTAIN', async () => {
    // NOTE: preScreenLineItems() 導入(cmd_144k_sub1)により振る舞い変更。
    //   前処理対象（rule_a: 3万/rule_d: 修繕20万）はAPI失敗時もEXPENSEを保持。
    //   LLM必要な明細のみ UNCERTAIN(APIエラー)。
    mockMessagesCreate.mockRejectedValue(new Error('タイムアウト'));

    const items = [
      makeItem('L1', 'PC', 500000),       // LLM必要 → API失敗 → UNCERTAIN
      makeItem('L2', '消耗品', 30000),    // rule_a: 3万 < 10万 → EXPENSE
      makeItem('L3', '修繕', 200000),     // rule_d: 修繕 < 60万 → EXPENSE
    ];
    const results = await runTaxAgent(items);

    expect(results).toHaveLength(3);
    expect(results.map((r) => r.line_item_id)).toEqual(['L1', 'L2', 'L3']);

    const l1 = results.find((r) => r.line_item_id === 'L1')!;
    expect(l1.verdict).toBe('UNCERTAIN');
    expect(l1.rationale).toContain('APIエラー');

    const l2 = results.find((r) => r.line_item_id === 'L2')!;
    expect(l2.verdict).toBe('EXPENSE');  // rule_a: 3万は前処理確定

    const l3 = results.find((r) => r.line_item_id === 'L3')!;
    expect(l3.verdict).toBe('EXPENSE');  // rule_d: 修繕20万は前処理確定
    expect(l3.article_ref).toBe('基通7-8-4(1)');
  });
});

// ─── parseResponse テスト（ユニット）────────────────────────────────────

describe('parseResponse: レスポンスパーサー（ユニット）', () => {
  const lineItems = [makeItem('L1', 'PC', 500000)];

  it('正常なJSON → TaxAgentResult[] を返す', () => {
    const json = JSON.stringify([
      {
        line_item_id: 'L1',
        verdict: 'CAPITAL',
        rationale: '固定資産',
        article_ref: '別表一',
        account_category: '器具備品',
        useful_life: 4,
        formal_criteria_step: null,
      },
    ]);
    const results = parseResponse(json, lineItems);
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('器具備品');
    expect(results[0].useful_life).toBe(4);
  });

  it('JSON が ```json...``` コードブロックで包まれていても解析できる', () => {
    const json = '```json\n' + JSON.stringify([
      { line_item_id: 'L1', verdict: 'EXPENSE', rationale: '消耗品', article_ref: null, account_category: '消耗品費', useful_life: null, formal_criteria_step: null },
    ]) + '\n```';
    const results = parseResponse(json, lineItems);
    expect(results[0].verdict).toBe('EXPENSE');
  });

  it('JSON がない場合 → 全件 UNCERTAIN（エラー耐性）', () => {
    const results = parseResponse('JSONが見つかりません', lineItems);
    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].rationale).toContain('パースエラー');
  });

  it('不正な JSON → 全件 UNCERTAIN（エラー耐性）', () => {
    const results = parseResponse('[{ broken json }]', lineItems);
    expect(results[0].verdict).toBe('UNCERTAIN');
  });

  it('不正な verdict → UNCERTAIN に正規化', () => {
    const json = JSON.stringify([
      { line_item_id: 'L1', verdict: 'INVALID_VERDICT', rationale: '不正', article_ref: null, account_category: null, useful_life: null, formal_criteria_step: null },
    ]);
    const results = parseResponse(json, lineItems);
    expect(results[0].verdict).toBe('UNCERTAIN');
  });

  it('useful_life が文字列の場合は null に正規化', () => {
    const json = JSON.stringify([
      { line_item_id: 'L1', verdict: 'CAPITAL', rationale: 'テスト', article_ref: null, account_category: '器具備品', useful_life: '4年', formal_criteria_step: null },
    ]);
    const results = parseResponse(json, lineItems);
    expect(results[0].useful_life).toBeNull();
  });

  it('formal_criteria_step が文字列の場合は null に正規化', () => {
    const json = JSON.stringify([
      { line_item_id: 'L1', verdict: 'EXPENSE', rationale: 'テスト', article_ref: '基通7-8-3(1)', account_category: '修繕費', useful_life: null, formal_criteria_step: '1' },
    ]);
    const results = parseResponse(json, lineItems);
    expect(results[0].formal_criteria_step).toBeNull();
  });
});

// ─── システムプロンプト内容確認（CHECK-9）────────────────────────────────

describe('TAX_AGENT_SYSTEM_PROMPT: 重要条文・ルールが含まれていることを確認（CHECK-9）', () => {
  // CHECK-9 根拠: Section 3.3 形式基準の条文番号が含まれること
  it('形式基準の条文番号が含まれる（基通7-8-3(1), 基通7-8-4(1), 令第132条）', () => {
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('基通7-8-3(1)');
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('基通7-8-4(1)');
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('第132条');
  });

  it('一括償却資産の条文番号が含まれる（第133条, 第133条の2）', () => {
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('第133条');
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('第133条の2');
  });

  it('金額閾値が含まれる（10万/20万/30万/60万）', () => {
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('10万円');
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('20万円');
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('30万円');
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('60万円');
  });

  it('修繕キーワードが含まれる（形式基準トリガー）', () => {
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('修繕');
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('メンテナンス');
  });
});

// ─── 複数明細バッチ処理テスト ─────────────────────────────────────────────

describe('runTaxAgent: 複数明細バッチ処理', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-test-key');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('3明細バッチ: CAPITAL / EXPENSE / UNCERTAIN が混在して正しく返る', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'CAPITAL',
        rationale: 'PC 50万円',
        article_ref: '別表一',
        account_category: '器具備品',
        useful_life: 4,
        formal_criteria_step: null,
      },
      {
        line_item_id: 'L2',
        verdict: 'EXPENSE',
        rationale: '消耗品 5万円',
        article_ref: '令第133条',
        account_category: '消耗品費',
        useful_life: null,
        formal_criteria_step: null,
      },
      {
        line_item_id: 'L3',
        verdict: 'UNCERTAIN',
        rationale: '判定不能',
        article_ref: null,
        account_category: null,
        useful_life: null,
        formal_criteria_step: 6,
      },
    ]);

    const results = await runTaxAgent([
      makeItem('L1', 'ノートPC', 500000),
      makeItem('L2', '消耗品', 50000),
      makeItem('L3', '工事（詳細不明）', 1000000),
    ]);

    expect(results).toHaveLength(3);
    expect(results[0]).toMatchObject({ line_item_id: 'L1', verdict: 'CAPITAL', account_category: '器具備品', useful_life: 4 });
    expect(results[1]).toMatchObject({ line_item_id: 'L2', verdict: 'EXPENSE', account_category: '消耗品費' });
    expect(results[2]).toMatchObject({ line_item_id: 'L3', verdict: 'UNCERTAIN', formal_criteria_step: 6 });
  });

  it('SDK に正しいモデル・systemプロンプトが渡される', async () => {
    mockApiResponse([
      { line_item_id: 'L1', verdict: 'CAPITAL', rationale: 'テスト', article_ref: null, account_category: null, useful_life: null, formal_criteria_step: null },
    ]);

    await runTaxAgent([makeItem('L1', 'PC', 500000)]);

    const callArgs = mockMessagesCreate.mock.calls[0][0];
    expect(callArgs.model).toBe('claude-haiku-4-5-20251001');
    expect(callArgs.system).toContain('税務判定エージェント');
    expect(callArgs.messages[0].role).toBe('user');
    expect(callArgs.messages[0].content).toContain('PC');
  });
});

// ─── F-N06 Step4 台帳未連携スキップ確認 ─────────────────────────────────────

describe('TAX_AGENT_SYSTEM_PROMPT: F-N06 Step4 台帳未連携スキップ確認', () => {
  /**
   * TA-S4-1: プロンプトに「台帳未連携」の文言が含まれること
   * CHECK-9: F-N06 Step4（基通7-8-4(2)）は台帳データ未連携のためスキップ方針を
   *   プロンプトに明記。LLMが誤って Step4 を適用しないよう制御する。
   */
  it('TA-S4-1: プロンプトに「台帳未連携」の文言が含まれる（Step4スキップ明記）', () => {
    expect(TAX_AGENT_SYSTEM_PROMPT).toContain('台帳未連携');
  });

  /**
   * TA-S4-2: プロンプトに Step4 スキップ指示が含まれること
   * CHECK-9: 「適用しない」または「スキップ」がプロンプトに含まれ、
   *   LLMに Step4 を実行させない指示が明記されている。
   */
  it('TA-S4-2: プロンプトに「Step 4 はスキップ」または「適用しない」の指示が含まれる', () => {
    const hasSkipInstruction =
      TAX_AGENT_SYSTEM_PROMPT.includes('スキップ') ||
      TAX_AGENT_SYSTEM_PROMPT.includes('適用しない');
    expect(hasSkipInstruction).toBe(true);
  });
});
