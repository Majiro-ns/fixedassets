/**
 * edge_cases.test.ts
 * Phase 2 エッジケーステスト（cmd_140k_sub4）
 *
 * 検証対象:
 *   1. 空の明細リスト: preScreenLineItems / runTaxAgent / runPracticeAgent
 *   2. 非常に長い品名（256文字超）: preScreen トークン化耐性
 *   3. 金額 0円 / マイナスのケース: preScreen ルールa適用確認
 *   4. preScreen で全件解決: LLM呼び出し不要（needsLlm = 0件）
 *   5. preScreen で0件解決: 全件LLM判定（dry-run → UNCERTAIN）
 *   6. 特殊文字・記号含む品名: preScreen / calcSimilarity 耐性
 *   7. 境界値: ちょうど10万円 / ちょうど20万円 / ちょうど60万円
 *
 * CHECK-9: テスト期待値根拠
 *   - ルールa: `amount < 100_000` （taxAgent.ts L224: 厳密な小なり比較）
 *   - amount=0: 0 < 100,000 → ルールa適用 → EXPENSE（消耗品費）
 *   - amount=負: 負値 < 100,000 → ルールa適用 → EXPENSE（設計上の許容挙動）
 *   - 256文字超: JavaScript文字列処理の制限なし → 正常動作
 *   - 境界100,000: NOT < 100,000 → needsLlm → dry-run → UNCERTAIN
 *   - calcSimilarity空文字: L44 `if (!a || !b) return 0` で早期return
 *
 * SDK モック方針:
 *   vi.hoisted + vi.mock('@anthropic-ai/sdk') でAPIキー未設定 dry-run挙動を活用。
 *   LLM不要テスト（preScreen全件解決）では ANTHROPIC_API_KEY を設定しない。
 */

import { describe, it, expect, vi } from 'vitest';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';
import { preScreenLineItems, runTaxAgent } from '../taxAgent';
import { runPracticeAgent, calcSimilarity } from '../practiceAgent';

// ─── SDK モック ─────────────────────────────────────────────────────────────

const { mockCreate } = vi.hoisted(() => ({
  mockCreate: vi.fn(),
}));

vi.mock('@anthropic-ai/sdk', () => ({
  default: function MockAnthropic() {
    return { messages: { create: mockCreate } };
  },
}));

// ─── ヘルパー ────────────────────────────────────────────────────────────────

function makeItem(id: string, desc: string, amount: number): ExtractedLineItem {
  return { line_item_id: id, description: desc, amount };
}

// ─── 1. 空の明細リスト ────────────────────────────────────────────────────────

describe('エッジケース: 空の明細リスト', () => {
  it('preScreenLineItems([]) → autoResolved=0, needsLlm=0 を返す', () => {
    // CHECK-9: taxAgent.ts L216 for...of ループが0回実行 → 空配列
    const result = preScreenLineItems([]);
    expect(result.autoResolved).toHaveLength(0);
    expect(result.needsLlm).toHaveLength(0);
  });

  it('runTaxAgent([]) → 即座に空配列を返す（LLM呼び出しなし）', async () => {
    // CHECK-9: taxAgent.ts L470 `if (lineItems.length === 0) return []`
    const result = await runTaxAgent([]);
    expect(result).toHaveLength(0);
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it('runPracticeAgent([], []) → 即座に空配列を返す（LLM呼び出しなし）', async () => {
    // CHECK-9: practiceAgent.ts L332 `if (lineItems.length === 0) return []`
    const result = await runPracticeAgent([], []);
    expect(result).toHaveLength(0);
    expect(mockCreate).not.toHaveBeenCalled();
  });
});

// ─── 2. 非常に長い品名（256文字超）──────────────────────────────────────────

describe('エッジケース: 長い品名（256文字超）', () => {
  it('256文字の品名 → preScreen が正常に処理できる（エラーなし）', () => {
    // 256文字の品名（修繕キーワードなし、金額30万円 → needsLlm）
    const longDescription = 'サーバー設備設置工事費用'.repeat(25).slice(0, 256);
    expect(longDescription.length).toBe(256);

    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', longDescription, 300_000),
    ]);

    // 30万円 × 修繕キーワードなし → いずれのルールにも非該当 → needsLlm
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
    expect(needsLlm[0].line_item_id).toBe('L1');
  });

  it('500文字の品名（修繕キーワード含む、15万円）→ ルールb: EXPENSE', () => {
    // CHECK-9: ルールb: 修繕キーワード × amount < 200,000 → EXPENSE（基通7-8-3(1)）
    const longRepairDesc = '修繕' + 'テスト品名詳細情報'.repeat(56);
    expect(longRepairDesc.length).toBeGreaterThan(500);

    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L2', longRepairDesc, 150_000),
    ]);

    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].rule).toBe('rule_b_repair_step1');
  });
});

// ─── 3. 金額 0円 / マイナスのケース ──────────────────────────────────────────

describe('エッジケース: 金額 0円 / マイナス', () => {
  it('金額 0円 → ルールa（0 < 100,000）→ EXPENSE（消耗品費）', () => {
    // CHECK-9: taxAgent.ts L224 `if (amount < 100_000)` → 0 < 100_000 = true
    // 設計書システムプロンプト: "金額が0または入力がない場合はUNCERTAIN"はLLMへの指示
    // preScreen（ルールベース）ではamount < 10万なのでルールa適用
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', 'テスト品目', 0),
    ]);

    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('消耗品費');
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
  });

  it('金額 -1円（マイナス）→ ルールa（-1 < 100,000）→ EXPENSE', () => {
    // CHECK-9: 負値は 100,000 より小さい → ルールa適用（設計上の許容挙動）
    // 実務では負値（返金・値引き）は通常発生しないが、コードの堅牢性確認
    const { autoResolved } = preScreenLineItems([
      makeItem('L1', '返金処理', -1),
    ]);

    expect(autoResolved).toHaveLength(1);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
  });

  it('金額 -500,000円（大きなマイナス）→ ルールa → EXPENSE', () => {
    // 大きなマイナスも同様（-500,000 < 100,000）
    const { autoResolved } = preScreenLineItems([
      makeItem('L1', '大型返金', -500_000),
    ]);

    expect(autoResolved).toHaveLength(1);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
  });
});

// ─── 4. preScreen で全件解決（LLM呼び出し不要）──────────────────────────────

describe('エッジケース: preScreen で全件解決（LLM不要）', () => {
  it('全3件が10万円未満 → needsLlm=0, runTaxAgent はLLM呼び出しなし', async () => {
    // CHECK-9: 全件ルールaで解決 → needsLlm=[] → LLM呼び出しスキップ（taxAgent.ts L484-487）
    // ANTHROPIC_API_KEY 未設定でも前処理済み結果は返る
    mockCreate.mockReset();

    const allUnder100k = [
      makeItem('L1', '文房具', 5_000),
      makeItem('L2', 'コピー用紙', 3_000),
      makeItem('L3', 'ボールペン', 500),
    ];

    const result = await runTaxAgent(allUnder100k);

    // 全件 preScreen で解決 → LLM呼び出しなし
    expect(mockCreate).not.toHaveBeenCalled();
    expect(result).toHaveLength(3);
    expect(result.every((r) => r.verdict === 'EXPENSE')).toBe(true);
    expect(result.every((r) => r.account_category === '消耗品費')).toBe(true);
  });

  it('修繕キーワード × 50万円 → ルールd(60万未満) → preScreen解決', () => {
    // CHECK-9: ルールd: 修繕 × 500,000 < 600,000 → EXPENSE（基通7-8-4(1)）
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', '外壁修繕工事', 500_000),
    ]);

    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].rule).toBe('rule_d_repair_step3');
  });
});

// ─── 5. preScreen で0件解決（全件LLM判定）──────────────────────────────────

describe('エッジケース: preScreen で0件解決（全件LLM）', () => {
  it('全3件がLLM必要 → dry-run で全件UNCERTAIN', async () => {
    // CHECK-9: amount >= 100k かつ修繕キーワードなし → 全件needsLlm → dry-run → UNCERTAIN
    // ANTHROPIC_API_KEY 未設定 → createDryRunResults → UNCERTAIN全件
    mockCreate.mockReset();

    const allNeedsLlm = [
      makeItem('L1', 'サーバー設備', 1_000_000),
      makeItem('L2', 'ノートPC', 300_000),
      makeItem('L3', 'エアコン設置', 500_000),
    ];

    const result = await runTaxAgent(allNeedsLlm);

    // dry-run: LLM呼び出しなし（APIキー未設定）
    expect(mockCreate).not.toHaveBeenCalled();
    expect(result).toHaveLength(3);
    expect(result.every((r) => r.verdict === 'UNCERTAIN')).toBe(true);
    expect(result[0].rationale).toContain('[DRY-RUN]');
  });

  it('preScreenLineItems: 全3件がneedsLlm（autoResolved=0）', () => {
    // 大金額・非修繕キーワード → いずれのルールにも非該当
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', 'サーバー設備', 2_000_000),
      makeItem('L2', 'ノートPC', 500_000),
      makeItem('L3', 'ソフトウェアライセンス', 800_000),
    ]);

    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(3);
  });
});

// ─── 6. 特殊文字・記号含む品名 ───────────────────────────────────────────────

describe('エッジケース: 特殊文字・記号含む品名', () => {
  it('記号多用の品名: preScreen トークン化が空セット → needsLlm（エラーなし）', () => {
    // CHECK-9: calcSimilarity の tokenize は記号を区切り文字として扱う
    // "!@#$%^&*()" → トークンが空 → preScreen キーワードマッチなし → needsLlm
    const specialCharsDesc = '!@#$%^&*()[]{}|<>/\\';
    const amount = 200_000; // ルールbの閾値以上（修繕キーワードなし）

    // preScreenLineItems はエラーを投げない
    expect(() => {
      preScreenLineItems([makeItem('L1', specialCharsDesc, amount)]);
    }).not.toThrow();

    const { needsLlm } = preScreenLineItems([makeItem('L1', specialCharsDesc, amount)]);
    expect(needsLlm).toHaveLength(1);
  });

  it('絵文字含む品名 → preScreen が正常動作（エラーなし）', () => {
    // 絵文字も JavaScript 文字列として正常処理
    const emojiDesc = '🖥️ サーバー設備 💻 ノートPC';

    expect(() => {
      preScreenLineItems([makeItem('L1', emojiDesc, 300_000)]);
    }).not.toThrow();
  });
});

// ─── 7. calcSimilarity エッジケース ──────────────────────────────────────────

describe('エッジケース: calcSimilarity（practiceAgent）', () => {
  it('空文字列 a → 0 を返す', () => {
    // CHECK-9: practiceAgent.ts L44 `if (!a || !b) return 0`
    expect(calcSimilarity('', 'サーバー設備')).toBe(0);
  });

  it('空文字列 b → 0 を返す', () => {
    expect(calcSimilarity('サーバー設備', '')).toBe(0);
  });

  it('両方空文字列 → 0 を返す', () => {
    expect(calcSimilarity('', '')).toBe(0);
  });

  it('完全一致 → 1.0 を返す', () => {
    // CHECK-9: 手計算: intersection=1, union=1 → 1/1 = 1.0
    expect(calcSimilarity('サーバー', 'サーバー')).toBe(1.0);
  });

  it('完全不一致 → 0 を返す', () => {
    // CHECK-9: 手計算: intersection=0 → 0/union = 0
    expect(calcSimilarity('エアコン', 'コピー用紙')).toBe(0);
  });
});

// ─── 8. 境界値テスト ──────────────────────────────────────────────────────────

describe('エッジケース: preScreen 境界値', () => {
  it('ちょうど10万円（100,000）→ ルールa非該当 → needsLlm', () => {
    // CHECK-9: amount < 100,000（厳密な小なり）→ 100,000 は非該当
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', 'OAチェア', 100_000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
  });

  it('ちょうど20万円（200,000）× 修繕 → ルールb非該当 → ルールd確認', () => {
    // CHECK-9: ルールb: amount < 200,000（厳密） → 200,000は非該当
    // ルールd: amount < 600,000 × 修繕 → 200,000は該当 → EXPENSE
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', '外壁修繕', 200_000),
    ]);
    // ルールbは非該当だが、ルールdが適用（200k < 600k × 修繕）
    expect(autoResolved).toHaveLength(1);
    expect(autoResolved[0].rule).toBe('rule_d_repair_step3');
    expect(needsLlm).toHaveLength(0);
  });

  it('ちょうど60万円（600,000）× 修繕 → ルールd非該当 → needsLlm', () => {
    // CHECK-9: ルールd: amount < 600,000（厳密） → 600,000は非該当 → needsLlm
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('L1', '外壁修繕工事', 600_000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
  });
});
