/**
 * aggregator.test.ts
 *
 * CHECK-9: テスト期待値は DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.5
 *          「合議判定ルール表（8 パターン）」から直接引用。
 *
 * CHECK-7b 手計算検算:
 *   P1/P2（全員一致）        → 0.95
 *   P3〜P6（片方 UNCERTAIN） → 0.80
 *   P7/対称（分裂）          → 0.50
 *   P8（両方 UNCERTAIN）     → 0.30
 */

import { describe, it, expect } from 'vitest';
import { aggregate } from '../aggregator';
import type {
  TaxAgentResult,
  PracticeAgentResult,
  AgentVerdict,
} from '@/types/multi_agent';

// ─── テスト用ファクトリ関数 ─────────────────────────────────────────────────

function makeTax(
  line_item_id: string,
  verdict: AgentVerdict,
  opts?: Partial<Omit<TaxAgentResult, 'line_item_id' | 'verdict'>>,
): TaxAgentResult {
  return { line_item_id, verdict, rationale: 'test', ...opts };
}

function makePractice(
  line_item_id: string,
  verdict: AgentVerdict,
  opts?: Partial<Omit<PracticeAgentResult, 'line_item_id' | 'verdict'>>,
): PracticeAgentResult {
  return { line_item_id, verdict, similar_cases: [], rationale: 'test', ...opts };
}

// ─── 8パターン合議ルールテスト（Section 3.5）─────────────────────────────

describe('aggregate: 8パターン合議ルール（根拠: Section 3.5 合議ルール表）', () => {
  // パターン1（Section 3.5 #1）
  it('P1: Tax:CAPITAL + Practice:CAPITAL → CAPITAL_LIKE, confidence=0.95', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL')],
      [makePractice('L1', 'CAPITAL')],
    );
    expect(result).toHaveLength(1);
    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(0.95);
    expect(result[0].disagreement_reason).toBeUndefined();
  });

  // パターン2（Section 3.5 #2）
  it('P2: Tax:EXPENSE + Practice:EXPENSE → EXPENSE_LIKE, confidence=0.95', () => {
    const result = aggregate(
      [makeTax('L1', 'EXPENSE')],
      [makePractice('L1', 'EXPENSE')],
    );
    expect(result[0].final_verdict).toBe('EXPENSE_LIKE');
    expect(result[0].confidence).toBe(0.95);
    expect(result[0].disagreement_reason).toBeUndefined();
  });

  // パターン3（Section 3.5 #3）
  it('P3: Tax:CAPITAL + Practice:UNCERTAIN → CAPITAL_LIKE, confidence=0.80', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL')],
      [makePractice('L1', 'UNCERTAIN')],
    );
    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(0.80);
  });

  // パターン4（Section 3.5 #4）
  it('P4: Tax:UNCERTAIN + Practice:CAPITAL → CAPITAL_LIKE, confidence=0.80', () => {
    const result = aggregate(
      [makeTax('L1', 'UNCERTAIN')],
      [makePractice('L1', 'CAPITAL')],
    );
    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(0.80);
  });

  // パターン5（Section 3.5 #5）
  it('P5: Tax:EXPENSE + Practice:UNCERTAIN → EXPENSE_LIKE, confidence=0.80', () => {
    const result = aggregate(
      [makeTax('L1', 'EXPENSE')],
      [makePractice('L1', 'UNCERTAIN')],
    );
    expect(result[0].final_verdict).toBe('EXPENSE_LIKE');
    expect(result[0].confidence).toBe(0.80);
  });

  // パターン6（Section 3.5 #6）
  it('P6: Tax:UNCERTAIN + Practice:EXPENSE → EXPENSE_LIKE, confidence=0.80', () => {
    const result = aggregate(
      [makeTax('L1', 'UNCERTAIN')],
      [makePractice('L1', 'EXPENSE')],
    );
    expect(result[0].final_verdict).toBe('EXPENSE_LIKE');
    expect(result[0].confidence).toBe(0.80);
  });

  // パターン7（Section 3.5 #7）: 分裂
  it('P7: Tax:CAPITAL + Practice:EXPENSE → GUIDANCE, confidence=0.50（分裂）', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL')],
      [makePractice('L1', 'EXPENSE')],
    );
    expect(result[0].final_verdict).toBe('GUIDANCE');
    expect(result[0].confidence).toBe(0.50);
    expect(result[0].disagreement_reason).toContain('CAPITAL');
    expect(result[0].disagreement_reason).toContain('EXPENSE');
  });

  // パターン7（対称）: Tax:EXPENSE + Practice:CAPITAL も同じ GUIDANCE, 0.50
  it('P7対称: Tax:EXPENSE + Practice:CAPITAL → GUIDANCE, confidence=0.50', () => {
    const result = aggregate(
      [makeTax('L1', 'EXPENSE')],
      [makePractice('L1', 'CAPITAL')],
    );
    expect(result[0].final_verdict).toBe('GUIDANCE');
    expect(result[0].confidence).toBe(0.50);
    expect(result[0].disagreement_reason).toBeDefined();
  });

  // パターン8（Section 3.5 #8）
  it('P8: Tax:UNCERTAIN + Practice:UNCERTAIN → GUIDANCE, confidence=0.30', () => {
    const result = aggregate(
      [makeTax('L1', 'UNCERTAIN')],
      [makePractice('L1', 'UNCERTAIN')],
    );
    expect(result[0].final_verdict).toBe('GUIDANCE');
    expect(result[0].confidence).toBe(0.30);
    // 両方 UNCERTAIN は「分裂」ではないため disagreement_reason は設定しない
    expect(result[0].disagreement_reason).toBeUndefined();
  });
});

// ─── confidence境界値テスト ────────────────────────────────────────────────

describe('aggregate: confidence境界値（根拠: Section 3.5 信頼度算出式）', () => {
  it('0.95: 一致パターン CAPITAL/CAPITAL と EXPENSE/EXPENSE の 2 件を確認', () => {
    const r1 = aggregate([makeTax('L1', 'CAPITAL')], [makePractice('L1', 'CAPITAL')]);
    const r2 = aggregate([makeTax('L2', 'EXPENSE')], [makePractice('L2', 'EXPENSE')]);
    expect(r1[0].confidence).toBe(0.95);
    expect(r2[0].confidence).toBe(0.95);
  });

  it('0.80: 片方 UNCERTAIN の 4 パターン全てで 0.80 を確認', () => {
    const combos: Array<[AgentVerdict, AgentVerdict]> = [
      ['CAPITAL', 'UNCERTAIN'],
      ['UNCERTAIN', 'CAPITAL'],
      ['EXPENSE', 'UNCERTAIN'],
      ['UNCERTAIN', 'EXPENSE'],
    ];
    for (const [tv, pv] of combos) {
      const result = aggregate([makeTax('X', tv)], [makePractice('X', pv)]);
      expect(result[0].confidence).toBe(0.80);
    }
  });

  it('0.50: 分裂パターン（CAPITAL/EXPENSE, EXPENSE/CAPITAL）で 0.50 を確認', () => {
    const r1 = aggregate([makeTax('L1', 'CAPITAL')], [makePractice('L1', 'EXPENSE')]);
    const r2 = aggregate([makeTax('L1', 'EXPENSE')], [makePractice('L1', 'CAPITAL')]);
    expect(r1[0].confidence).toBe(0.50);
    expect(r2[0].confidence).toBe(0.50);
  });

  it('0.30: 両方 UNCERTAIN で最低 confidence 0.30 を確認', () => {
    const r = aggregate([makeTax('L1', 'UNCERTAIN')], [makePractice('L1', 'UNCERTAIN')]);
    expect(r[0].confidence).toBe(0.30);
  });
});

// ─── 片方Agent失敗ケース ──────────────────────────────────────────────────

describe('aggregate: 片方Agent失敗（根拠: Section 6 エラーハンドリング）', () => {
  it('Tax Agent失敗（null）→ Tax側を UNCERTAIN 扱い。P4相当: UNCERTAIN+CAPITAL → CAPITAL_LIKE, 0.80', () => {
    const result = aggregate(null, [makePractice('L1', 'CAPITAL')]);
    expect(result).toHaveLength(1);
    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(0.80);
    expect(result[0].tax_result).toBeNull();
    expect(result[0].practice_result).not.toBeNull();
  });

  it('Tax Agent失敗（null）+ Practice:EXPENSE → P6相当: EXPENSE_LIKE, 0.80', () => {
    const result = aggregate(null, [makePractice('L1', 'EXPENSE')]);
    expect(result[0].final_verdict).toBe('EXPENSE_LIKE');
    expect(result[0].confidence).toBe(0.80);
  });

  it('Tax Agent失敗（null）+ Practice:UNCERTAIN → P8相当: GUIDANCE, 0.30', () => {
    const result = aggregate(null, [makePractice('L1', 'UNCERTAIN')]);
    expect(result[0].final_verdict).toBe('GUIDANCE');
    expect(result[0].confidence).toBe(0.30);
  });

  it('Practice Agent失敗（null）→ Practice側を UNCERTAIN 扱い。P3相当: CAPITAL+UNCERTAIN → CAPITAL_LIKE, 0.80', () => {
    const result = aggregate([makeTax('L1', 'CAPITAL')], null);
    expect(result).toHaveLength(1);
    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(0.80);
    expect(result[0].tax_result).not.toBeNull();
    expect(result[0].practice_result).toBeNull();
  });

  it('Practice Agent失敗（null）+ Tax:EXPENSE → P5相当: EXPENSE_LIKE, 0.80', () => {
    const result = aggregate([makeTax('L1', 'EXPENSE')], null);
    expect(result[0].final_verdict).toBe('EXPENSE_LIKE');
    expect(result[0].confidence).toBe(0.80);
  });

  it('両方 Agent 失敗（null, null）→ 空配列', () => {
    expect(aggregate(null, null)).toHaveLength(0);
  });
});

// ─── 空入力（0明細）ケース ───────────────────────────────────────────────

describe('aggregate: 空入力（0明細）', () => {
  it('Tax空配列 + Practice空配列 → 空配列', () => {
    expect(aggregate([], [])).toEqual([]);
  });

  it('Tax null + Practice空配列 → 空配列', () => {
    expect(aggregate(null, [])).toHaveLength(0);
  });

  it('Tax空配列 + Practice null → 空配列', () => {
    expect(aggregate([], null)).toHaveLength(0);
  });
});

// ─── 複数明細のバッチ処理 ─────────────────────────────────────────────────

describe('aggregate: 複数明細バッチ処理', () => {
  it('3明細バッチ: 各明細が独立して合議判定される', () => {
    const taxResults = [
      makeTax('L1', 'CAPITAL'),
      makeTax('L2', 'EXPENSE'),
      makeTax('L3', 'UNCERTAIN'),
    ];
    const practiceResults = [
      makePractice('L1', 'CAPITAL'),   // L1: P1 → CAPITAL_LIKE, 0.95
      makePractice('L2', 'UNCERTAIN'), // L2: P5 → EXPENSE_LIKE, 0.80
      makePractice('L3', 'UNCERTAIN'), // L3: P8 → GUIDANCE, 0.30
    ];
    const results = aggregate(taxResults, practiceResults);
    expect(results).toHaveLength(3);
    expect(results[0]).toMatchObject({ line_item_id: 'L1', final_verdict: 'CAPITAL_LIKE', confidence: 0.95 });
    expect(results[1]).toMatchObject({ line_item_id: 'L2', final_verdict: 'EXPENSE_LIKE', confidence: 0.80 });
    expect(results[2]).toMatchObject({ line_item_id: 'L3', final_verdict: 'GUIDANCE', confidence: 0.30 });
  });

  it('Tax側の明細順を保持する', () => {
    const taxResults = [
      makeTax('L3', 'CAPITAL'),
      makeTax('L1', 'EXPENSE'),
      makeTax('L2', 'UNCERTAIN'),
    ];
    const practiceResults = [
      makePractice('L1', 'EXPENSE'),
      makePractice('L2', 'CAPITAL'),
      makePractice('L3', 'CAPITAL'),
    ];
    const results = aggregate(taxResults, practiceResults);
    expect(results.map((r) => r.line_item_id)).toEqual(['L3', 'L1', 'L2']);
  });

  it('5明細バッチ: 全パターン混在（P1/P2/P7/P8/P3）', () => {
    const tax = [
      makeTax('A', 'CAPITAL'),
      makeTax('B', 'EXPENSE'),
      makeTax('C', 'CAPITAL'),
      makeTax('D', 'UNCERTAIN'),
      makeTax('E', 'CAPITAL'),
    ];
    const pra = [
      makePractice('A', 'CAPITAL'),   // P1 → CAPITAL_LIKE, 0.95
      makePractice('B', 'EXPENSE'),   // P2 → EXPENSE_LIKE, 0.95
      makePractice('C', 'EXPENSE'),   // P7 → GUIDANCE, 0.50
      makePractice('D', 'UNCERTAIN'), // P8 → GUIDANCE, 0.30
      makePractice('E', 'UNCERTAIN'), // P3 → CAPITAL_LIKE, 0.80
    ];
    const results = aggregate(tax, pra);
    expect(results[0]).toMatchObject({ final_verdict: 'CAPITAL_LIKE', confidence: 0.95 });
    expect(results[1]).toMatchObject({ final_verdict: 'EXPENSE_LIKE', confidence: 0.95 });
    expect(results[2]).toMatchObject({ final_verdict: 'GUIDANCE', confidence: 0.50 });
    expect(results[3]).toMatchObject({ final_verdict: 'GUIDANCE', confidence: 0.30 });
    expect(results[4]).toMatchObject({ final_verdict: 'CAPITAL_LIKE', confidence: 0.80 });
  });
});

// ─── line_item_id 不一致時の処理 ──────────────────────────────────────────

describe('aggregate: line_item_id 不一致', () => {
  it('PracticeのみにあるIDはTax側を UNCERTAIN 扱いで末尾に追加', () => {
    const taxResults = [makeTax('L1', 'CAPITAL')];
    const practiceResults = [
      makePractice('L1', 'CAPITAL'),
      makePractice('L2', 'EXPENSE'), // L2 は Tax に存在しない
    ];
    const results = aggregate(taxResults, practiceResults);
    expect(results).toHaveLength(2);
    expect(results[0].line_item_id).toBe('L1');
    expect(results[1].line_item_id).toBe('L2');
    // L2: Tax:UNCERTAIN(不在) + Practice:EXPENSE → P6: EXPENSE_LIKE, 0.80
    expect(results[1]).toMatchObject({ final_verdict: 'EXPENSE_LIKE', confidence: 0.80 });
    expect(results[1].tax_result).toBeNull();
    expect(results[1].practice_result).not.toBeNull();
  });

  it('TaxのみにあるIDはPractice側を UNCERTAIN 扱いで処理', () => {
    const taxResults = [
      makeTax('L1', 'CAPITAL'),
      makeTax('L2', 'EXPENSE'), // L2 は Practice に存在しない
    ];
    const practiceResults = [makePractice('L1', 'CAPITAL')];
    const results = aggregate(taxResults, practiceResults);
    expect(results).toHaveLength(2);
    // L2: Tax:EXPENSE + Practice:UNCERTAIN(不在) → P5: EXPENSE_LIKE, 0.80
    expect(results[1]).toMatchObject({ line_item_id: 'L2', final_verdict: 'EXPENSE_LIKE', confidence: 0.80 });
    expect(results[1].practice_result).toBeNull();
  });

  it('全ID不一致: TaxのID順 + PracticeのIDを末尾追加', () => {
    const taxResults = [makeTax('T1', 'CAPITAL')];
    const practiceResults = [makePractice('P1', 'EXPENSE')];
    const results = aggregate(taxResults, practiceResults);
    expect(results).toHaveLength(2);
    expect(results[0].line_item_id).toBe('T1');
    expect(results[1].line_item_id).toBe('P1');
    // T1: Tax:CAPITAL + Practice:UNCERTAIN(不在) → CAPITAL_LIKE, 0.80
    expect(results[0]).toMatchObject({ final_verdict: 'CAPITAL_LIKE', confidence: 0.80 });
    // P1: Tax:UNCERTAIN(不在) + Practice:EXPENSE → EXPENSE_LIKE, 0.80
    expect(results[1]).toMatchObject({ final_verdict: 'EXPENSE_LIKE', confidence: 0.80 });
  });
});

// ─── 勘定科目・耐用年数の優先順位 ────────────────────────────────────────

describe('aggregate: 勘定科目・耐用年数（根拠: Section 3.5 勘定科目の合議ルール）', () => {
  it('account_category: Tax優先（Tax と Practice 両方ある場合は Tax を採用）', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL', { account_category: '建物附属設備' })],
      [makePractice('L1', 'CAPITAL', { suggested_account: '器具備品' })],
    );
    expect(result[0].account_category).toBe('建物附属設備');
  });

  it('account_category: Tax の account_category が null の場合は Practice の suggested_account を採用', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL', { account_category: null })],
      [makePractice('L1', 'CAPITAL', { suggested_account: '器具備品' })],
    );
    expect(result[0].account_category).toBe('器具備品');
  });

  it('account_category: 両方 null の場合は null', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL', { account_category: null })],
      [makePractice('L1', 'CAPITAL', { suggested_account: null })],
    );
    expect(result[0].account_category).toBeNull();
  });

  it('useful_life: Tax の値を正とする（法定耐用年数は税法根拠）', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL', { useful_life: 15 })],
      [makePractice('L1', 'CAPITAL')],
    );
    expect(result[0].useful_life).toBe(15);
  });

  it('useful_life: Tax が null の場合は null（Practice の値は採用しない）', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL', { useful_life: null })],
      [makePractice('L1', 'CAPITAL')],
    );
    expect(result[0].useful_life).toBeNull();
  });
});

// ─── disagreement_reason ─────────────────────────────────────────────────

describe('aggregate: disagreement_reason（分裂時のみ設定）', () => {
  it('分裂（CAPITAL vs EXPENSE）→ disagreement_reason に両 verdict を含む文字列', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL')],
      [makePractice('L1', 'EXPENSE')],
    );
    expect(result[0].disagreement_reason).toBeDefined();
    expect(result[0].disagreement_reason).toContain('CAPITAL');
    expect(result[0].disagreement_reason).toContain('EXPENSE');
  });

  it('分裂対称（EXPENSE vs CAPITAL）→ disagreement_reason 設定あり', () => {
    const result = aggregate(
      [makeTax('L1', 'EXPENSE')],
      [makePractice('L1', 'CAPITAL')],
    );
    expect(result[0].disagreement_reason).toBeDefined();
  });

  it('一致パターン（CAPITAL/CAPITAL）→ disagreement_reason は undefined', () => {
    const result = aggregate(
      [makeTax('L1', 'CAPITAL')],
      [makePractice('L1', 'CAPITAL')],
    );
    expect(result[0].disagreement_reason).toBeUndefined();
  });

  it('P8（両方 UNCERTAIN）→ GUIDANCE だが disagreement_reason は undefined（分裂ではない）', () => {
    const result = aggregate(
      [makeTax('L1', 'UNCERTAIN')],
      [makePractice('L1', 'UNCERTAIN')],
    );
    expect(result[0].disagreement_reason).toBeUndefined();
  });
});

// ─── 元の Agent 結果の保持確認 ────────────────────────────────────────────

describe('aggregate: 元の Agent 結果の保持', () => {
  it('tax_result と practice_result に元の結果が保持される', () => {
    const tax = makeTax('L1', 'CAPITAL', { article_ref: '基通7-8-3(1)', useful_life: 10 });
    const pra = makePractice('L1', 'CAPITAL', { suggested_account: '器具備品' });
    const result = aggregate([tax], [pra]);
    expect(result[0].tax_result).toStrictEqual(tax);
    expect(result[0].practice_result).toStrictEqual(pra);
  });

  it('Agent 失敗（null 入力）時は対応する *_result が null', () => {
    const result = aggregate(null, [makePractice('L1', 'CAPITAL')]);
    expect(result[0].tax_result).toBeNull();
    expect(result[0].practice_result).not.toBeNull();
  });
});
