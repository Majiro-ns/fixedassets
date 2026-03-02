/**
 * killswitch_integration.test.ts
 * Phase 2 キルスイッチ統合テスト（cmd_140k_sub4）
 *
 * 検証対象（4パターン）:
 *   1. 両エージェント有効: Tax + Practice で合議 → CAPITAL_LIKE
 *   2. Tax無効（null）: Practiceのみ → Aggregator が適切にハンドル
 *   3. Practice無効（null）: Taxのみ → Aggregator が適切にハンドル
 *   4. 両無効（null, null）: Aggregator が空配列を返す → フォールバック判定
 *
 * CHECK-9: テスト期待値根拠
 *   - 両有効 CAPITAL+CAPITAL → CAPITAL_LIKE, 0.95（Section 3.5 パターン1）
 *   - Tax null + Practice CAPITAL → CAPITAL_LIKE, 0.80（Section 3.5 パターン4）
 *   - Tax EXPENSE + Practice null → EXPENSE_LIKE, 0.80（Section 3.5 パターン5）
 *   - null + null → aggregate は空配列を返す（Section 6 エラー耐性）
 *
 * モック方針:
 *   runTaxAgent / runPracticeAgent を vi.mock でモック（dry-run不要）。
 *   aggregate は実装をそのまま使用して正しい合議結果を検証する。
 */

import { describe, it, expect } from 'vitest';
import type { TaxAgentResult, PracticeAgentResult } from '@/types/multi_agent';
import { aggregate } from '../aggregator';

// ─── テストデータ ────────────────────────────────────────────────────────────

/** Tax Agent 判定結果モック: サーバー → CAPITAL / 消耗品 → EXPENSE */
const TAX_RESULTS: TaxAgentResult[] = [
  {
    line_item_id: 'li_001',
    verdict: 'CAPITAL',
    rationale: 'サーバー設備は器具備品',
    article_ref: '別表第一',
    account_category: '器具備品',
    useful_life: 5,
    formal_criteria_step: null,
    confidence: 0.9,
  },
  {
    line_item_id: 'li_002',
    verdict: 'EXPENSE',
    rationale: '10万円未満 消耗品費',
    article_ref: '令第133条',
    account_category: '消耗品費',
    useful_life: null,
    formal_criteria_step: null,
    confidence: 1.0,
  },
];

/** Practice Agent 判定結果モック: サーバー → CAPITAL / 消耗品 → EXPENSE */
const PRACTICE_RESULTS: PracticeAgentResult[] = [
  {
    line_item_id: 'li_001',
    verdict: 'CAPITAL',
    rationale: '過去事例: サーバー購入',
    similar_cases: [{ description: 'サーバー Dell R740', classification: 'CAPITAL', similarity: 0.9 }],
    suggested_account: '器具備品',
    confidence: 0.85,
  },
  {
    line_item_id: 'li_002',
    verdict: 'EXPENSE',
    rationale: '消耗品',
    similar_cases: [],
    suggested_account: '消耗品費',
    confidence: 0.95,
  },
];

// ─── 1. 両エージェント有効: 通常の Phase 2 フロー ─────────────────────────────

describe('キルスイッチ統合: 両エージェント有効（通常フロー）', () => {
  it('Tax + Practice 両方有効 → aggregate が 2件を正常に合議する', () => {
    const result = aggregate(TAX_RESULTS, PRACTICE_RESULTS);

    expect(result).toHaveLength(2);
  });

  it('サーバー設備: Tax=CAPITAL + Practice=CAPITAL + 勘定科目一致 → CAPITAL_LIKE, confidence=1.0', () => {
    // CHECK-9: 手計算: パターン1(0.95) + 勘定科目一致(+0.05) = 1.0（上限クランプ）
    const result = aggregate(TAX_RESULTS, PRACTICE_RESULTS);
    const server = result.find((r) => r.line_item_id === 'li_001')!;

    expect(server.final_verdict).toBe('CAPITAL_LIKE');
    expect(server.confidence).toBe(1.0);
    expect(server.account_category).toBe('器具備品');
    expect(server.useful_life).toBe(5); // Tax Agent の値が採用される
  });

  it('消耗品費: Tax=EXPENSE + Practice=EXPENSE + 勘定科目一致 → EXPENSE_LIKE, confidence=1.0', () => {
    // CHECK-9: 手計算: パターン2(0.95) + 勘定科目一致(+0.05) = 1.0
    const result = aggregate(TAX_RESULTS, PRACTICE_RESULTS);
    const expense = result.find((r) => r.line_item_id === 'li_002')!;

    expect(expense.final_verdict).toBe('EXPENSE_LIKE');
    expect(expense.confidence).toBe(1.0);
  });

  it('両方の Agent 結果が line_results に正しく格納される', () => {
    const result = aggregate(TAX_RESULTS, PRACTICE_RESULTS);
    const server = result.find((r) => r.line_item_id === 'li_001')!;

    expect(server.tax_result).not.toBeNull();
    expect(server.practice_result).not.toBeNull();
    expect(server.tax_result?.verdict).toBe('CAPITAL');
    expect(server.practice_result?.verdict).toBe('CAPITAL');
  });
});

// ─── 2. Tax無効（null）: Practice のみで判定 ─────────────────────────────────

describe('キルスイッチ統合: Tax無効（null）→ Practiceのみ', () => {
  it('Tax=null → aggregate が Practice 結果のみで合議', () => {
    // キルスイッチ: TAX_AGENT_ENABLED=false → taxResults=null → aggregate(null, PRACTICE_RESULTS)
    const result = aggregate(null, PRACTICE_RESULTS);

    expect(result).toHaveLength(2);
  });

  it('Tax=null + Practice=CAPITAL → CAPITAL_LIKE, confidence=0.80（パターン4）', () => {
    // CHECK-9: 手計算: Tax=null→UNCERTAIN, Practice=CAPITAL → パターン4 → 0.80
    const result = aggregate(null, PRACTICE_RESULTS);
    const server = result.find((r) => r.line_item_id === 'li_001')!;

    expect(server.final_verdict).toBe('CAPITAL_LIKE');
    expect(server.confidence).toBe(0.80);
    expect(server.tax_result).toBeNull();           // Tax は null
    expect(server.practice_result).not.toBeNull();   // Practice は有効
  });

  it('Tax=null + Practice=EXPENSE → EXPENSE_LIKE, confidence=0.80（パターン5逆）', () => {
    // CHECK-9: Tax=null→UNCERTAIN, Practice=EXPENSE → パターン4相当 → 0.80
    const result = aggregate(null, PRACTICE_RESULTS);
    const expense = result.find((r) => r.line_item_id === 'li_002')!;

    expect(expense.final_verdict).toBe('EXPENSE_LIKE');
    expect(expense.confidence).toBe(0.80);
  });
});

// ─── 3. Practice無効（null）: Tax のみで判定 ─────────────────────────────────

describe('キルスイッチ統合: Practice無効（null）→ Taxのみ', () => {
  it('Practice=null → aggregate が Tax 結果のみで合議', () => {
    // キルスイッチ: PRACTICE_AGENT_ENABLED=false → practiceResults=null → aggregate(TAX_RESULTS, null)
    const result = aggregate(TAX_RESULTS, null);

    expect(result).toHaveLength(2);
  });

  it('Tax=CAPITAL + Practice=null → CAPITAL_LIKE, confidence=0.80（パターン3）', () => {
    // CHECK-9: 手計算: Tax=CAPITAL, Practice=null→UNCERTAIN → パターン3 → 0.80
    const result = aggregate(TAX_RESULTS, null);
    const server = result.find((r) => r.line_item_id === 'li_001')!;

    expect(server.final_verdict).toBe('CAPITAL_LIKE');
    expect(server.confidence).toBe(0.80);
    expect(server.tax_result).not.toBeNull();  // Tax は有効
    expect(server.practice_result).toBeNull(); // Practice は null
  });

  it('Tax=EXPENSE + Practice=null → EXPENSE_LIKE, confidence=0.80（パターン5）', () => {
    // CHECK-9: Tax=EXPENSE, Practice=null→UNCERTAIN → パターン5 → 0.80
    const result = aggregate(TAX_RESULTS, null);
    const expense = result.find((r) => r.line_item_id === 'li_002')!;

    expect(expense.final_verdict).toBe('EXPENSE_LIKE');
    expect(expense.confidence).toBe(0.80);
  });

  it('Tax 結果から useful_life が採用される（useful_life: 5）', () => {
    // CHECK-9: Section 3.5 「useful_life は Tax Agent の値が正」
    const result = aggregate(TAX_RESULTS, null);
    const server = result.find((r) => r.line_item_id === 'li_001')!;

    expect(server.useful_life).toBe(5);
  });
});

// ─── 4. 両無効（null, null）: 空配列を返す ──────────────────────────────────

describe('キルスイッチ統合: 両無効（null, null）→ 空配列', () => {
  it('aggregate(null, null) → 空配列を返す', () => {
    // CHECK-9: Section 6 / integration.test.ts D3
    // キルスイッチ: 両方無効 → route.ts では Phase 1 フォールバック（aggregate 呼ばれない）
    // ここでは aggregate に null が渡された場合の動作を確認
    const result = aggregate(null, null);

    expect(result).toHaveLength(0);
    expect(Array.isArray(result)).toBe(true);
  });

  it('aggregate(null, null) → 空配列はfalsyでなくtruthyなArray', () => {
    // 空配列のため downstream の forEach/map が安全に実行できる
    const result = aggregate(null, null);

    expect(() => result.forEach(() => {})).not.toThrow();
    expect(() => result.map((r) => r)).not.toThrow();
  });
});
