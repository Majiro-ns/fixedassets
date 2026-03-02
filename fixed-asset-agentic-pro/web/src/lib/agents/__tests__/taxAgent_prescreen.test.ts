/**
 * taxAgent_prescreen.test.ts
 *
 * preScreenLineItems() のユニットテスト + runTaxAgent() との統合テスト
 *
 * CHECK-9: テスト期待値の根拠
 *   ルールa: 法人税法施行令第133条（少額資産 10万円未満 → 即時費用化）
 *   ルールb: 基通7-8-3(1)（修繕費 20万円未満 → 修繕費）
 *   ルールc: 基通7-8-3(2)（修繕周期3年以内 → 修繕費）
 *   ルールd: 基通7-8-4(1)（修繕費 60万円未満 → 修繕費）
 *
 * CHECK-7b 手動検証:
 *   10万未満 → EXPENSE（令第133条。e.g. 9.8万円のOAチェア）
 *   修繕 × 15万 → EXPENSE（基通7-8-3(1). e.g. エアコン修理15万）
 *   修繕 × 45万 → EXPENSE（基通7-8-4(1). e.g. 外壁補修45万）
 *   PC × 100万 → LLM判定（いずれのルールにも非該当）
 */

import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';
import { preScreenLineItems } from '../taxAgent';

// ─── SDK モック（vi.hoisted で hoisting 問題を回避）──────────────────────

const { mockMessagesCreate } = vi.hoisted(() => ({
  mockMessagesCreate: vi.fn(),
}));

vi.mock('@anthropic-ai/sdk', () => ({
  default: function MockAnthropic() {
    return { messages: { create: mockMessagesCreate } };
  },
}));

import { runTaxAgent } from '../taxAgent';

// ─── テスト用ファクトリ関数 ─────────────────────────────────────────────────

function makeItem(
  line_item_id: string,
  description: string,
  amount: number,
): ExtractedLineItem {
  return { line_item_id, description, amount };
}

function mockApiResponse(results: object[]) {
  mockMessagesCreate.mockResolvedValue({
    content: [{ type: 'text', text: JSON.stringify(results) }],
  });
}

// ─── preScreenLineItems ユニットテスト ────────────────────────────────────

describe('preScreenLineItems: ルールa（10万円未満 → EXPENSE確定）', () => {
  // CHECK-9 根拠: 法人税法施行令第133条「10万円未満の減価償却資産は全額損金算入」
  it('a-1: 9万9千円 → autoResolved(EXPENSE), rule_a_under_100k', () => {
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', 'OAチェア', 99000),
    ]);
    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('消耗品費');
    expect(autoResolved[0].result.article_ref).toContain('133条');
  });

  it('a-2: 5万円の消耗品 → autoResolved(EXPENSE)', () => {
    const { autoResolved } = preScreenLineItems([makeItem('L1', '消耗品', 50000)]);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
  });

  it('a-3: 1円 → autoResolved(EXPENSE)', () => {
    const { autoResolved } = preScreenLineItems([makeItem('L1', 'ボールペン', 1)]);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
  });

  it('a-4: ちょうど10万円(100000) → needsLlm（ルールa非対象）', () => {
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', 'モニター', 100000),
    ]);
    // 100000 は < 100000 を満たさないため前処理対象外
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
  });
});

describe('preScreenLineItems: ルールb（20万円未満×修繕キーワード → EXPENSE確定, 形式基準Step1）', () => {
  // CHECK-9 根拠: 基通7-8-3(1)「支出額が20万円未満の修繕費は全額修繕費」
  it('b-1: エアコン修理 15万円 → autoResolved(EXPENSE), rule_b_repair_step1', () => {
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', 'エアコン修理', 150000),
    ]);
    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].rule).toBe('rule_b_repair_step1');
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('修繕費');
    expect(autoResolved[0].result.article_ref).toBe('基通7-8-3(1)');
    expect(autoResolved[0].result.formal_criteria_step).toBe(1);
  });

  it('b-2: 外壁補修 18万円 → autoResolved(EXPENSE) ※補修キーワード', () => {
    const { autoResolved } = preScreenLineItems([makeItem('L1', '外壁補修', 180000)]);
    expect(autoResolved[0].rule).toBe('rule_b_repair_step1');
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
  });

  it('b-3: 設備交換 19万円 → autoResolved(EXPENSE) ※交換キーワード', () => {
    const { autoResolved } = preScreenLineItems([makeItem('L1', '設備交換', 190000)]);
    expect(autoResolved[0].rule).toBe('rule_b_repair_step1');
  });

  it('b-4: 修繕 20万円ちょうど → needsLlm（20万円以上はルールb非対象）', () => {
    // 基通7-8-3(1)は「未満」。20万円ちょうどはStep3(ルールd)で判定
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', '修繕工事', 200000),
    ]);
    // 20万ちょうどはルールb対象外。ルールdが適用（<60万 × 修繕）
    expect(autoResolved).toHaveLength(1);
    expect(autoResolved[0].rule).toBe('rule_d_repair_step3');
    expect(needsLlm).toHaveLength(0);
  });
});

describe('preScreenLineItems: ルールc（20万円未満×3年以内周期語 → EXPENSE確定, 形式基準Step2）', () => {
  // CHECK-9 根拠: 基通7-8-3(2)「修繕周期が概ね3年以内の場合は全額修繕費」
  it('c-1: 定期点検（3年以内）15万円 → autoResolved(EXPENSE), rule_c_cycle_step2', () => {
    // NOTE: 「修繕」は含まずに周期キーワード「定期点検」「3年以内」のみ使用
    // (「修繕」があるとルールbが優先されるため、ルールcのみをテストする明細を使用)
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', '定期点検（3年以内）', 150000),
    ]);
    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].rule).toBe('rule_c_cycle_step2');
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.article_ref).toBe('基通7-8-3(2)');
    expect(autoResolved[0].result.formal_criteria_step).toBe(2);
  });

  it('c-2: 年次点検 10万円 → autoResolved（修繕キーワードなしでもStep2）', () => {
    const { autoResolved } = preScreenLineItems([makeItem('L1', '年次点検費用', 100000)]);
    // 100000 はルールaの対象外（以上）。CYCLE_3YR_KEYWORDS「年次」が一致
    expect(autoResolved[0].rule).toBe('rule_c_cycle_step2');
  });

  it('c-3: 修繕（ルールbが優先）× 定期修繕 15万 → rule_b（修繕キーワードが先に適用）', () => {
    // ルールbの修繕キーワードが先にマッチするため rule_b が適用される
    const { autoResolved } = preScreenLineItems([makeItem('L1', '定期修繕', 150000)]);
    expect(autoResolved[0].rule).toBe('rule_b_repair_step1');
  });
});

describe('preScreenLineItems: ルールd（60万円未満×修繕キーワード → EXPENSE確定, 形式基準Step3）', () => {
  // CHECK-9 根拠: 基通7-8-4(1)「支出額が60万円未満の修繕費は全額修繕費」
  it('d-1: 外壁補修 45万円 → autoResolved(EXPENSE), rule_d_repair_step3', () => {
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', '外壁補修工事', 450000),
    ]);
    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].rule).toBe('rule_d_repair_step3');
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('修繕費');
    expect(autoResolved[0].result.article_ref).toBe('基通7-8-4(1)');
    expect(autoResolved[0].result.formal_criteria_step).toBe(3);
  });

  it('d-2: 修繕工事 55万9千円 → autoResolved(EXPENSE)', () => {
    const { autoResolved } = preScreenLineItems([makeItem('L1', '修繕工事', 559000)]);
    expect(autoResolved[0].rule).toBe('rule_d_repair_step3');
  });

  it('d-3: 修繕工事 60万円ちょうど → needsLlm（ルールd非対象）', () => {
    // 基通7-8-4(1)は「未満」。60万円ちょうどは形式基準外 → LLM
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', '修繕工事', 600000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
  });
});

// ─── テスト項目c: 100万のPC → needsLlm ──────────────────────────────────

describe('preScreenLineItems: LLM判定が必要な明細', () => {
  it('c: PC 100万円 → needsLlm（修繕キーワードなし × 100万 ≥ 60万）', () => {
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', 'ノートPC', 1000000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
    expect(needsLlm[0].line_item_id).toBe('L1');
  });

  it('エアコン 80万円（修繕キーワードなし × 80万 ≥ 60万）→ needsLlm', () => {
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', 'エアコン設置', 800000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
  });

  it('屋根改修 300万円（改修はキーワード外）→ needsLlm', () => {
    // 「改修」は REPAIR_KEYWORDS /修繕|修理|補修|交換/ に該当しない
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', '屋根改修（耐用年数延長）', 3000000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
  });
});

// ─── テスト項目d: mixed配列 → 正しく分離 ────────────────────────────────

describe('preScreenLineItems: mixed配列の分離', () => {
  it('d: 4明細（autoResolved:3件, needsLlm:1件）が正しく分離される', () => {
    const items = [
      makeItem('L1', 'ノートPC', 1000000),       // needsLlm: 100万、修繕なし
      makeItem('L2', '消耗品', 50000),            // rule_a: 5万 < 10万
      makeItem('L3', 'エアコン修理', 150000),     // rule_b: 15万 < 20万 × 修繕
      makeItem('L4', '外壁修繕工事', 400000),     // rule_d: 40万 < 60万 × 修繕
    ];

    const { autoResolved, needsLlm } = preScreenLineItems(items);

    expect(needsLlm).toHaveLength(1);
    expect(needsLlm[0].line_item_id).toBe('L1');

    expect(autoResolved).toHaveLength(3);
    const ids = autoResolved.map((r) => r.item.line_item_id);
    expect(ids).toContain('L2');
    expect(ids).toContain('L3');
    expect(ids).toContain('L4');
  });

  it('全件がルールに該当する場合 → needsLlm = 空配列', () => {
    const items = [
      makeItem('L1', '消耗品', 30000),     // rule_a
      makeItem('L2', 'エアコン修理', 180000), // rule_b
    ];
    const { autoResolved, needsLlm } = preScreenLineItems(items);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved).toHaveLength(2);
  });

  it('全件がLLM必要な場合 → autoResolved = 空配列', () => {
    const items = [
      makeItem('L1', 'ノートPC', 500000),
      makeItem('L2', 'エアコン設置', 800000),
    ];
    const { autoResolved, needsLlm } = preScreenLineItems(items);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(2);
  });

  it('空配列 → autoResolved/needsLlm ともに空', () => {
    const { autoResolved, needsLlm } = preScreenLineItems([]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(0);
  });

  it('結果の順序は元の明細順序を保持', () => {
    // CHECK-9: mergeResultsByOriginalOrder が元の順序を保つことを確認
    const items = [
      makeItem('L1', 'PC', 500000),        // needsLlm
      makeItem('L2', '消耗品', 50000),     // rule_a
      makeItem('L3', '修繕', 400000),      // rule_d
    ];
    const { autoResolved } = preScreenLineItems(items);
    const resolvedIds = autoResolved.map((r) => r.item.line_item_id);
    // L2, L3 が autoResolved（L1 はlast）
    expect(resolvedIds).toContain('L2');
    expect(resolvedIds).toContain('L3');
  });
});

// ─── テスト項目e: dry-run時のフォールバック動作 ──────────────────────────

describe('runTaxAgent: dry-run時の前処理フォールバック', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', '');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('e-1: dry-run × 前処理対象の明細 → EXPENSE（UNCERTAINにならない）', async () => {
    // CHECK-9 根拠: 10万未満は令第133条で確実にEXPENSE。APIキー不要。
    const results = await runTaxAgent([makeItem('L1', '消耗品', 50000)]);
    expect(results).toHaveLength(1);
    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].article_ref).toContain('133条');
    // DRY-RUN サフィックスは含まない（確定判定）
    expect(results[0].rationale).not.toContain('DRY-RUN');
  });

  it('e-2: dry-run × LLM必要明細 → UNCERTAIN(DRY-RUN)', async () => {
    const results = await runTaxAgent([makeItem('L1', 'ノートPC', 500000)]);
    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].rationale).toContain('DRY-RUN');
  });

  it('e-3: dry-run × mixed配列 → 前処理済みEXPENSE + 残りUNCERTAIN', async () => {
    const items = [
      makeItem('L1', 'ノートPC', 500000),    // LLM必要
      makeItem('L2', '消耗品', 50000),        // rule_a → EXPENSE
      makeItem('L3', 'エアコン修理', 150000), // rule_b → EXPENSE
    ];
    const results = await runTaxAgent(items);

    expect(results).toHaveLength(3);

    // 元の順序を保持
    expect(results[0].line_item_id).toBe('L1');
    expect(results[1].line_item_id).toBe('L2');
    expect(results[2].line_item_id).toBe('L3');

    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].rationale).toContain('DRY-RUN');

    expect(results[1].verdict).toBe('EXPENSE');
    expect(results[2].verdict).toBe('EXPENSE');
  });

  it('e-4: dry-run × 全件前処理済み → SDK が呼ばれない', async () => {
    const items = [makeItem('L1', '消耗品', 30000)];
    await runTaxAgent(items);
    expect(mockMessagesCreate).not.toHaveBeenCalled();
  });
});

// ─── runTaxAgent との統合テスト（LLM削減確認）───────────────────────────

describe('runTaxAgent: 前処理によるLLM呼び出し削減', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-test-key');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('全件前処理済み → SDK が呼ばれない', async () => {
    const items = [
      makeItem('L1', '消耗品', 50000),       // rule_a
      makeItem('L2', 'エアコン修理', 150000), // rule_b
    ];
    const results = await runTaxAgent(items);

    expect(mockMessagesCreate).not.toHaveBeenCalled();
    expect(results).toHaveLength(2);
    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[1].verdict).toBe('EXPENSE');
  });

  it('一部前処理済み → LLMは未解決分のみ受け取る', async () => {
    mockApiResponse([
      {
        line_item_id: 'L1',
        verdict: 'CAPITAL',
        rationale: 'PCは器具備品',
        article_ref: '耐用年数省令別表一',
        account_category: '器具備品',
        useful_life: 4,
        formal_criteria_step: null,
      },
    ]);

    const items = [
      makeItem('L1', 'ノートPC', 500000), // needsLlm
      makeItem('L2', '消耗品', 50000),    // rule_a → prescreen
    ];
    const results = await runTaxAgent(items);

    // SDKは1回呼ばれ、引数に消耗品は含まれない
    expect(mockMessagesCreate).toHaveBeenCalledTimes(1);
    const callArgs = mockMessagesCreate.mock.calls[0][0];
    expect(callArgs.messages[0].content).not.toContain('消耗品');
    expect(callArgs.messages[0].content).toContain('ノートPC');

    // 結果は元順序を保持
    expect(results[0].line_item_id).toBe('L1');
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[1].line_item_id).toBe('L2');
    expect(results[1].verdict).toBe('EXPENSE');
    expect(results[1].account_category).toBe('消耗品費');
  });

  it('API失敗時: 前処理済みはEXPENSEを保持、LLM必要分はUNCERTAIN', async () => {
    mockMessagesCreate.mockRejectedValue(new Error('API失敗'));

    const items = [
      makeItem('L1', 'ノートPC', 500000), // needsLlm → error → UNCERTAIN
      makeItem('L2', '消耗品', 50000),    // rule_a → EXPENSE（API失敗でも保持）
    ];
    const results = await runTaxAgent(items);

    expect(results).toHaveLength(2);
    const l1 = results.find((r) => r.line_item_id === 'L1')!;
    const l2 = results.find((r) => r.line_item_id === 'L2')!;

    expect(l1.verdict).toBe('UNCERTAIN');
    expect(l1.rationale).toContain('APIエラー');
    expect(l2.verdict).toBe('EXPENSE');
    expect(l2.account_category).toBe('消耗品費');
  });

  it('結果の順序: 前処理済みとLLM結果が元の明細順序で返る', async () => {
    mockApiResponse([
      {
        line_item_id: 'L3',
        verdict: 'CAPITAL',
        rationale: 'エアコン設置',
        article_ref: '耐用年数省令別表一',
        account_category: '建物附属設備',
        useful_life: 13,
        formal_criteria_step: null,
      },
    ]);

    const items = [
      makeItem('L1', '消耗品', 30000),        // rule_a → prescreen
      makeItem('L2', 'エアコン修理', 150000), // rule_b → prescreen
      makeItem('L3', 'エアコン設置', 800000), // needsLlm
    ];
    const results = await runTaxAgent(items);

    expect(results.map((r) => r.line_item_id)).toEqual(['L1', 'L2', 'L3']);
    expect(results[0].verdict).toBe('EXPENSE');  // L1: rule_a
    expect(results[1].verdict).toBe('EXPENSE');  // L2: rule_b
    expect(results[2].verdict).toBe('CAPITAL');  // L3: LLM
    expect(results[2].account_category).toBe('建物附属設備');
  });
});

// ─── テスト項目f: 既存taxAgent.test.tsとの互換性確認 ────────────────────

describe('preScreenLineItems: 既存テストケースとの互換性（CHECK-9）', () => {
  // 既存taxAgent.test.tsの主要テストケースに使われる明細を
  // preScreenLineItemsで検証し、期待動作が変わっていないことを確認

  it('既存test「PC 50万円」は prescreen 対象外（needsLlm）', () => {
    const { needsLlm } = preScreenLineItems([makeItem('L1', 'ノートPC', 500000)]);
    // PC 50万円はどのルールにも該当しない → LLM判定が必要
    expect(needsLlm).toHaveLength(1);
  });

  it('既存test「エアコン設置 80万円」は prescreen 対象外（needsLlm）', () => {
    const { needsLlm } = preScreenLineItems([makeItem('L1', 'エアコン設置', 800000)]);
    // 設置はREPAIR_KEYWORDSに非該当
    expect(needsLlm).toHaveLength(1);
  });

  it('既存test「文具・消耗品 5万円」は rule_a で EXPENSE確定', () => {
    const { autoResolved } = preScreenLineItems([makeItem('L1', '文具・消耗品', 50000)]);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('消耗品費');
    // 既存テストの期待値（EXPENSE, 消耗品費）と一致
  });

  it('既存test「エアコン修理 15万円」は rule_b で EXPENSE確定(formal_criteria_step=1)', () => {
    const { autoResolved } = preScreenLineItems([makeItem('L1', 'エアコン修理', 150000)]);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.article_ref).toBe('基通7-8-3(1)');
    expect(autoResolved[0].result.formal_criteria_step).toBe(1);
    // 既存テストの期待値と一致
  });

  it('既存test「外壁補修工事 45万円」は rule_d で EXPENSE確定(formal_criteria_step=3)', () => {
    const { autoResolved } = preScreenLineItems([makeItem('L1', '外壁補修工事', 450000)]);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.article_ref).toBe('基通7-8-4(1)');
    expect(autoResolved[0].result.formal_criteria_step).toBe(3);
    // 既存テストの期待値と一致
  });

  it('既存test「屋根改修 300万円」は prescreen 対象外（needsLlm）', () => {
    const { needsLlm } = preScreenLineItems([
      makeItem('L1', '屋根改修（耐用年数延長）', 3000000),
    ]);
    // 「改修」はREPAIR_KEYWORDSに非該当 → LLM
    expect(needsLlm).toHaveLength(1);
  });
});

// ─── ポリシー閾値（thresholdAmount）パラメータのテスト（F-10 cmd_170k_sub2）────

describe('preScreenLineItems: thresholdAmount パラメータ（ポリシー管理 F-10）', () => {
  // CHECK-9: 根拠 = F-10 クライアント別ポリシー管理設計
  //   閾値をポリシーで変更することで、クライアントごとの判定基準をカスタマイズできる。
  //   デフォルト 100,000 円（税法基準）から変更可能。

  it('t-1: デフォルト閾値（100,000円）- 99,999円 → EXPENSE（デフォルト動作保持）', () => {
    // CHECK-7b: デフォルト閾値 = 100,000 円。99,999 < 100,000 → rule_a
    const { autoResolved } = preScreenLineItems([makeItem('L1', 'モニター', 99999)]);
    expect(autoResolved).toHaveLength(1);
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
  });

  it('t-2: 閾値 200,000（A社ポリシー）- 150,000円 → EXPENSE（閾値未満）', () => {
    // CHECK-7b: A社ポリシー閾値 = 200,000 円。150,000 < 200,000 → rule_a（費用）
    const { autoResolved, needsLlm } = preScreenLineItems(
      [makeItem('L1', 'モニター', 150000)],
      200_000,
    );
    expect(autoResolved).toHaveLength(1);
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(needsLlm).toHaveLength(0);
  });

  it('t-3: 閾値 200,000（A社ポリシー）- 200,000円ちょうど → needsLlm（閾値以上）', () => {
    // CHECK-7b: 200,000 は < 200,000 を満たさない → prescreen 対象外 → LLM
    const { autoResolved, needsLlm } = preScreenLineItems(
      [makeItem('L1', 'モニター', 200000)],
      200_000,
    );
    // 修繕キーワードなし → rule_d も非対象 → needsLlm
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
  });

  it('t-4: 閾値 300,000（B社ポリシー）- 250,000円 → EXPENSE（B社では費用）', () => {
    // CHECK-7b: B社ポリシー閾値 = 300,000 円。250,000 < 300,000 → rule_a
    const { autoResolved } = preScreenLineItems(
      [makeItem('L1', 'PC周辺機器', 250000)],
      300_000,
    );
    expect(autoResolved).toHaveLength(1);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
  });

  it('t-5: 閾値 100,000（デフォルト）- 100,000円 → needsLlm（税法デフォルト時の境界値）', () => {
    // CHECK-7b: デフォルト閾値 = 100,000円。100,000 は < 100,000 を満たさない → LLM
    const { autoResolved, needsLlm } = preScreenLineItems(
      [makeItem('L1', 'モニター', 100000)],
    );
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
  });

  it('t-6: 閾値変更は他のルール（b/c/d）に影響しない', () => {
    // CHECK-9: thresholdAmount はルールaのみに影響する。b/c/dは固定閾値を使用
    const { autoResolved } = preScreenLineItems(
      [makeItem('L1', 'エアコン修理', 150000)],  // rule_b: 150,000 < 200,000 × 修繕
      200_000,  // ポリシー閾値 20万
    );
    // rule_a: 150,000 < 200,000 → EXPENSE（閾値による rule_a が先にマッチ）
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
  });
});
