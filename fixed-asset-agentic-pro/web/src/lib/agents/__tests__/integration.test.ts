/**
 * integration.test.ts
 * Phase 2 統合テスト: PDF→抽出→3エージェント→フロントエンド全通し
 *
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.5 / 5.2 / 6
 *
 * CHECK-9: テスト期待値の根拠
 *   - 合議ルール 8 パターン: Section 3.5 合議ルール表
 *   - 勘定科目一致ボーナス (+0.05): Section 3.5 「勘定科目一致時の信頼度加算」(git 2521ecc W-1修正)
 *   - サマリー計算: Section 5.2 summary フィールド定義
 *   - エラー耐性 (null Agent): Section 6 エラーハンドリング
 *
 * CHECK-7b 手計算検算:
 *   B1: CAPITAL+CAPITAL+勘定科目一致: 0.95 + 0.05 = 1.00 (上限クランプ)
 *   B2: EXPENSE+EXPENSE+勘定科目一致: 0.95 + 0.05 = 1.00 (上限クランプ)
 *   B3: CAPITAL+UNCERTAIN(practice): 0.80 (Practice=null→比較不可→加算なし)
 *   B4: UNCERTAIN+UNCERTAIN:         0.30 → GUIDANCE (Section 3.5 パターン8)
 *   B5: CAPITAL+CAPITAL+勘定科目不一致: 0.95 (加算なし)
 *   C1: capital_total=250,000 / expense_total=50,000 / guidance_total=0
 *   C2: 同勘定科目2件 → by_account.count=2, total=250,000
 *   C3: 2勘定科目 → by_account 2エントリ
 *   D1: Tax=null → UNCERTAIN扱い → Practice=CAPITAL → パターン4 → CAPITAL_LIKE, 0.80
 *   D2: Practice=null → UNCERTAIN扱い → Tax=EXPENSE → パターン5 → EXPENSE_LIKE, 0.80
 */

import { describe, it, expect } from 'vitest';
import { runTaxAgent } from '../taxAgent';
import { runPracticeAgent } from '../practiceAgent';
import { aggregate } from '../aggregator';
import { transformAggregatedToV2 } from '@/app/api/v2/classify_pdf/route.helpers';
import type { TaxAgentResult, PracticeAgentResult, AgentVerdict } from '@/types/multi_agent';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';

// ─── テスト用定数 ─────────────────────────────────────────────────────────────

/** E2Eテスト用明細: ノートPC 250,000円 + 修繕費 50,000円 */
const TEST_LINE_ITEMS: ExtractedLineItem[] = [
  { line_item_id: 'li_notebook_001', description: 'ノートPC Dell XPS', amount: 250000 },
  { line_item_id: 'li_repair_001', description: '修繕費 外壁補修', amount: 50000 },
];

// ─── ファクトリ関数 ───────────────────────────────────────────────────────────

function makeTax(
  line_item_id: string,
  verdict: AgentVerdict,
  opts?: Partial<Omit<TaxAgentResult, 'line_item_id' | 'verdict'>>,
): TaxAgentResult {
  return { line_item_id, verdict, rationale: '[integration-test]', ...opts };
}

function makePractice(
  line_item_id: string,
  verdict: AgentVerdict,
  opts?: Partial<Omit<PracticeAgentResult, 'line_item_id' | 'verdict'>>,
): PracticeAgentResult {
  return { line_item_id, verdict, similar_cases: [], rationale: '[integration-test]', ...opts };
}

// ─── A. Phase 2 E2E フロー（dry-run）─────────────────────────────────────────

describe('A: Phase 2 E2E フロー — dry-run（ANTHROPIC_API_KEY 未設定）', () => {
  it('A1: runTaxAgent → dry-run UNCERTAIN 全件 (根拠: Section 6 APIキー未設定フォールバック)', async () => {
    const taxResults = await runTaxAgent(TEST_LINE_ITEMS);

    expect(taxResults).toHaveLength(2);
    expect(taxResults.every((r) => r.verdict === 'UNCERTAIN')).toBe(true);
    // dry-run フラグ文字列が含まれることを確認
    expect(taxResults[0].rationale).toContain('[DRY-RUN]');
    expect(taxResults[1].rationale).toContain('[DRY-RUN]');
    // line_item_id が入力と対応
    expect(taxResults[0].line_item_id).toBe('li_notebook_001');
    expect(taxResults[1].line_item_id).toBe('li_repair_001');
  });

  it('A2: runPracticeAgent → dry-run UNCERTAIN 全件 (根拠: Section 6 APIキー未設定フォールバック)', async () => {
    const practiceResults = await runPracticeAgent(TEST_LINE_ITEMS, []);

    expect(practiceResults).toHaveLength(2);
    expect(practiceResults.every((r) => r.verdict === 'UNCERTAIN')).toBe(true);
    expect(practiceResults[0].rationale).toContain('[dry-run]');
    expect(practiceResults[0].line_item_id).toBe('li_notebook_001');
  });

  it('A3: dry-run E2E全通し — UNCERTAIN+UNCERTAIN → GUIDANCE, confidence=0.30 (手計算: パターン8)', async () => {
    // 手計算 (CHECK-7b): UNCERTAIN+UNCERTAIN → Section 3.5 パターン8 → GUIDANCE, 0.30
    const taxResults = await runTaxAgent(TEST_LINE_ITEMS);
    const practiceResults = await runPracticeAgent(TEST_LINE_ITEMS, []);
    const aggregated = aggregate(taxResults, practiceResults);

    expect(aggregated).toHaveLength(2);
    aggregated.forEach((r) => {
      expect(r.final_verdict).toBe('GUIDANCE');
      expect(r.confidence).toBe(0.30);
    });
  });

  it('A4: dry-run E2E全通し → transformAggregatedToV2 → V2レスポンス構造確認 (Section 5.2)', async () => {
    // dry-run: 全明細GUIDANCE → guidance_total=300,000 / capital=0 / expense=0
    // 手計算 (CHECK-7b): 250,000 + 50,000 = 300,000
    const taxResults = await runTaxAgent(TEST_LINE_ITEMS);
    const practiceResults = await runPracticeAgent(TEST_LINE_ITEMS, []);
    const aggregated = aggregate(taxResults, practiceResults);

    const v2 = transformAggregatedToV2(aggregated, TEST_LINE_ITEMS, 'req-a4-test', null, 150);

    // V2レスポンス構造 (Section 5.2)
    expect(v2.request_id).toBe('req-a4-test');
    expect(v2.status).toBe('success');
    expect(v2.line_results).toHaveLength(2);
    expect(v2.extracted?.items).toHaveLength(2);
    expect(v2.audit_trail_id).toBeNull();

    // 全明細 GUIDANCE → capital=0, expense=0, guidance=300,000
    expect(v2.summary.capital_total).toBe(0);
    expect(v2.summary.expense_total).toBe(0);
    expect(v2.summary.guidance_total).toBe(300000);
    expect(v2.summary.by_account).toHaveLength(0);

    // 各行の verdict
    v2.line_results.forEach((lr) => {
      expect(lr.verdict).toBe('GUIDANCE');
      expect(lr.confidence).toBe(0.30);
    });
  });
});

// ─── B. 3エージェント合議シナリオ ────────────────────────────────────────────

describe('B: 3エージェント合議シナリオ (根拠: Section 3.5 合議ルール + W-1修正 git 2521ecc)', () => {
  it('B1: CAPITAL+CAPITAL+勘定科目一致 → CAPITAL_LIKE, confidence=1.0', () => {
    // 手計算 (CHECK-7b): パターン1基本 0.95 + 勘定科目一致+0.05 = 1.00 (上限クランプ)
    const tax = [makeTax('L1', 'CAPITAL', { account_category: '器具備品' })];
    const practice = [makePractice('L1', 'CAPITAL', { suggested_account: '器具備品' })];

    const result = aggregate(tax, practice);

    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(1.0);
    expect(result[0].account_category).toBe('器具備品');
  });

  it('B2: EXPENSE+EXPENSE+勘定科目一致 → EXPENSE_LIKE, confidence=1.0', () => {
    // 手計算 (CHECK-7b): パターン2基本 0.95 + 勘定科目一致+0.05 = 1.00 (上限クランプ)
    const tax = [makeTax('L1', 'EXPENSE', { account_category: '修繕費' })];
    const practice = [makePractice('L1', 'EXPENSE', { suggested_account: '修繕費' })];

    const result = aggregate(tax, practice);

    expect(result[0].final_verdict).toBe('EXPENSE_LIKE');
    expect(result[0].confidence).toBe(1.0);
  });

  it('B3: CAPITAL+UNCERTAIN → CAPITAL_LIKE, confidence=0.80 (勘定科目比較不可・加算なし)', () => {
    // 手計算 (CHECK-7b): パターン3 → 0.80
    // Practice=null suggested_account → Tax vs null 比較不可 → +0.05 加算なし
    const tax = [makeTax('L1', 'CAPITAL', { account_category: '器具備品' })];
    const practice = [makePractice('L1', 'UNCERTAIN', { suggested_account: null })];

    const result = aggregate(tax, practice);

    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(0.80);
  });

  it('B4: 両方UNCERTAIN → GUIDANCE, confidence=0.30', () => {
    // 手計算 (CHECK-7b): パターン8 → GUIDANCE, 0.30
    const tax = [makeTax('L1', 'UNCERTAIN')];
    const practice = [makePractice('L1', 'UNCERTAIN')];

    const result = aggregate(tax, practice);

    expect(result[0].final_verdict).toBe('GUIDANCE');
    expect(result[0].confidence).toBe(0.30);
  });

  it('B5: CAPITAL+CAPITAL+勘定科目不一致 → CAPITAL_LIKE, confidence=0.95 (加算なし)', () => {
    // 手計算 (CHECK-7b): パターン1基本 0.95 + 勘定科目不一致のため+0.05 なし = 0.95
    const tax = [makeTax('L1', 'CAPITAL', { account_category: '器具備品' })];
    const practice = [makePractice('L1', 'CAPITAL', { suggested_account: '建物附属設備' })];

    const result = aggregate(tax, practice);

    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(0.95);
  });
});

// ─── C. Summary 計算の正確性 ─────────────────────────────────────────────────

describe('C: Summary 計算の正確性 (根拠: Section 5.2 summary フィールド)', () => {
  it('C1: capital_total / expense_total / guidance_total の手計算検証', () => {
    // 手計算 (CHECK-7b):
    //   ノートPC 250,000 → CAPITAL_LIKE → capital_total += 250,000
    //   修繕費   50,000  → EXPENSE_LIKE → expense_total += 50,000
    //   guidance_total   = 0
    const lineItems: ExtractedLineItem[] = [
      { line_item_id: 'li_001', description: 'ノートPC', amount: 250000 },
      { line_item_id: 'li_002', description: '修繕費', amount: 50000 },
    ];

    const aggResults = aggregate(
      [
        makeTax('li_001', 'CAPITAL', { account_category: '器具備品' }),
        makeTax('li_002', 'EXPENSE', { account_category: '修繕費' }),
      ],
      [
        makePractice('li_001', 'CAPITAL', { suggested_account: '器具備品' }),
        makePractice('li_002', 'EXPENSE', { suggested_account: '修繕費' }),
      ],
    );

    const v2 = transformAggregatedToV2(aggResults, lineItems, 'req-c1', null, 100);

    expect(v2.summary.capital_total).toBe(250000);
    expect(v2.summary.expense_total).toBe(50000);
    expect(v2.summary.guidance_total).toBe(0);
  });

  it('C2: by_account 集計 — 同勘定科目2件 → count=2, total=250,000', () => {
    // 手計算 (CHECK-7b):
    //   PC-A 100,000 + PC-B 150,000 → 器具備品 count=2, total=250,000
    const lineItems: ExtractedLineItem[] = [
      { line_item_id: 'li_pc_a', description: 'PC-A', amount: 100000 },
      { line_item_id: 'li_pc_b', description: 'PC-B', amount: 150000 },
    ];

    const aggResults = aggregate(
      [
        makeTax('li_pc_a', 'CAPITAL', { account_category: '器具備品' }),
        makeTax('li_pc_b', 'CAPITAL', { account_category: '器具備品' }),
      ],
      [
        makePractice('li_pc_a', 'CAPITAL', { suggested_account: '器具備品' }),
        makePractice('li_pc_b', 'CAPITAL', { suggested_account: '器具備品' }),
      ],
    );

    const v2 = transformAggregatedToV2(aggResults, lineItems, 'req-c2', null, 100);

    expect(v2.summary.capital_total).toBe(250000);
    expect(v2.summary.by_account).toHaveLength(1);
    const entry = v2.summary.by_account[0];
    expect(entry.account_category).toBe('器具備品');
    expect(entry.count).toBe(2);
    expect(entry.total_amount).toBe(250000);
  });

  it('C3: by_account 集計 — 複数勘定科目 (建物附属設備+器具備品)', () => {
    // 手計算 (CHECK-7b):
    //   エアコン 500,000 → 建物附属設備: count=1, total=500,000
    //   ノートPC 250,000 → 器具備品:     count=1, total=250,000
    //   capital_total = 750,000
    const lineItems: ExtractedLineItem[] = [
      { line_item_id: 'li_ac', description: 'エアコン', amount: 500000 },
      { line_item_id: 'li_pc', description: 'ノートPC', amount: 250000 },
    ];

    const aggResults = aggregate(
      [
        makeTax('li_ac', 'CAPITAL', { account_category: '建物附属設備' }),
        makeTax('li_pc', 'CAPITAL', { account_category: '器具備品' }),
      ],
      [
        makePractice('li_ac', 'CAPITAL', { suggested_account: '建物附属設備' }),
        makePractice('li_pc', 'CAPITAL', { suggested_account: '器具備品' }),
      ],
    );

    const v2 = transformAggregatedToV2(aggResults, lineItems, 'req-c3', null, 100);

    expect(v2.summary.capital_total).toBe(750000);
    expect(v2.summary.expense_total).toBe(0);
    expect(v2.summary.by_account).toHaveLength(2);

    const acEntry = v2.summary.by_account.find((b) => b.account_category === '建物附属設備');
    const pcEntry = v2.summary.by_account.find((b) => b.account_category === '器具備品');
    expect(acEntry?.total_amount).toBe(500000);
    expect(acEntry?.count).toBe(1);
    expect(pcEntry?.total_amount).toBe(250000);
    expect(pcEntry?.count).toBe(1);
  });

  it('C4: GUIDANCE 明細の金額は guidance_total に加算', () => {
    // 手計算 (CHECK-7b):
    //   エアコン 500,000 → GUIDANCE → guidance_total += 500,000
    //   capital=0, expense=0
    const lineItems: ExtractedLineItem[] = [
      { line_item_id: 'li_ac', description: 'エアコン', amount: 500000 },
    ];

    // Tax:CAPITAL vs Practice:EXPENSE → 分裂 → GUIDANCE, 0.50
    const aggResults = aggregate(
      [makeTax('li_ac', 'CAPITAL')],
      [makePractice('li_ac', 'EXPENSE')],
    );

    const v2 = transformAggregatedToV2(aggResults, lineItems, 'req-c4', null, 100);

    expect(v2.summary.guidance_total).toBe(500000);
    expect(v2.summary.capital_total).toBe(0);
    expect(v2.summary.expense_total).toBe(0);
    expect(v2.summary.by_account).toHaveLength(0);
  });
});

// ─── D. エラー耐性 ────────────────────────────────────────────────────────────

describe('D: エラー耐性 (根拠: Section 6 エラーハンドリング)', () => {
  it('D1: Tax Agent 失敗(null) → Practice のみで合議 — UNCERTAIN+CAPITAL → CAPITAL_LIKE, 0.80', () => {
    // 手計算 (CHECK-7b): Tax=null → UNCERTAIN扱い, Practice=CAPITAL
    // → Section 3.5 パターン4 (UNCERTAIN+CAPITAL) → CAPITAL_LIKE, 0.80
    const practice = [makePractice('L1', 'CAPITAL')];
    const result = aggregate(null, practice);

    expect(result).toHaveLength(1);
    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(0.80);
    expect(result[0].tax_result).toBeNull();
    expect(result[0].practice_result).not.toBeNull();
  });

  it('D2: Practice Agent 失敗(null) → Tax のみで合議 — EXPENSE+UNCERTAIN → EXPENSE_LIKE, 0.80', () => {
    // 手計算 (CHECK-7b): Tax=EXPENSE, Practice=null → UNCERTAIN扱い
    // → Section 3.5 パターン5 (EXPENSE+UNCERTAIN) → EXPENSE_LIKE, 0.80
    const tax = [makeTax('L1', 'EXPENSE')];
    const result = aggregate(tax, null);

    expect(result).toHaveLength(1);
    expect(result[0].final_verdict).toBe('EXPENSE_LIKE');
    expect(result[0].confidence).toBe(0.80);
    expect(result[0].tax_result).not.toBeNull();
    expect(result[0].practice_result).toBeNull();
  });

  it('D3: 両方失敗(null, null) → 空配列を返す', () => {
    const result = aggregate(null, null);
    expect(result).toHaveLength(0);
  });

  it('D4: Tax 失敗(null) + partial status → V2 status=partial で CAPITAL_LIKE を返す', () => {
    // Tax Agent 失敗 → agentStatus='partial' で V2 生成
    const lineItems: ExtractedLineItem[] = [
      { line_item_id: 'L1', description: 'ノートPC', amount: 300000 },
    ];

    const aggResults = aggregate(null, [makePractice('L1', 'CAPITAL')]);
    const v2 = transformAggregatedToV2(aggResults, lineItems, 'req-d4', null, 200, 'partial');

    expect(v2.status).toBe('partial');
    expect(v2.line_results).toHaveLength(1);
    // Tax=null→UNCERTAIN, Practice=CAPITAL → CAPITAL_LIKE
    expect(v2.line_results[0].verdict).toBe('CAPITAL_LIKE');
    expect(v2.line_results[0].confidence).toBe(0.80);
    expect(v2.line_results[0].tax_verdict).toBe('UNCERTAIN');
    expect(v2.line_results[0].practice_verdict).toBe('CAPITAL');
  });

  it('D5: 両方失敗 → V2 空のline_results, summary 全0', () => {
    const v2 = transformAggregatedToV2([], [], 'req-d5', null, 100);

    expect(v2.line_results).toHaveLength(0);
    expect(v2.summary.capital_total).toBe(0);
    expect(v2.summary.expense_total).toBe(0);
    expect(v2.summary.guidance_total).toBe(0);
    expect(v2.summary.by_account).toHaveLength(0);
  });

  it('D6: 個別明細で両方UNCERTAIN → GUIDANCE 判定 (Section 6: 「GUIDANCE として処理」)', () => {
    // 手計算 (CHECK-7b): UNCERTAIN+UNCERTAIN → パターン8 → GUIDANCE, 0.30
    const lineItems: ExtractedLineItem[] = [
      { line_item_id: 'L1', description: '不明品目', amount: 100000 },
    ];

    const aggResults = aggregate(
      [makeTax('L1', 'UNCERTAIN')],
      [makePractice('L1', 'UNCERTAIN')],
    );
    const v2 = transformAggregatedToV2(aggResults, lineItems, 'req-d6', null, 100);

    expect(v2.line_results[0].verdict).toBe('GUIDANCE');
    expect(v2.line_results[0].confidence).toBe(0.30);
    expect(v2.summary.guidance_total).toBe(100000);
  });
});

// ─── E. エッジケース ──────────────────────────────────────────────────────────

describe('E: エッジケース', () => {
  it('E1: 空の明細リスト → 各エージェントが空配列を返す (dry-run)', async () => {
    const taxResults = await runTaxAgent([]);
    const practiceResults = await runPracticeAgent([], []);

    expect(taxResults).toHaveLength(0);
    expect(practiceResults).toHaveLength(0);
  });

  it('E2: Aggregator への空配列入力 → 空配列を返す', () => {
    const result = aggregate([], []);
    expect(result).toHaveLength(0);
  });

  it('E3: 分裂判定 (Tax:CAPITAL vs Practice:EXPENSE) → GUIDANCE, confidence=0.50, disagreement_reason あり', () => {
    // 手計算 (CHECK-7b): Section 3.5 パターン7（分裂）→ GUIDANCE, 0.50
    const tax = [makeTax('L1', 'CAPITAL')];
    const practice = [makePractice('L1', 'EXPENSE')];

    const result = aggregate(tax, practice);

    expect(result[0].final_verdict).toBe('GUIDANCE');
    expect(result[0].confidence).toBe(0.50);
    expect(result[0].disagreement_reason).toBeDefined();
    expect(result[0].disagreement_reason).toContain('判定分裂');
  });

  it('E4: 逆分裂 (Tax:EXPENSE vs Practice:CAPITAL) → GUIDANCE, confidence=0.50', () => {
    // 手計算 (CHECK-7b): 対称ケース → パターン7と同一 → GUIDANCE, 0.50
    const tax = [makeTax('L1', 'EXPENSE')];
    const practice = [makePractice('L1', 'CAPITAL')];

    const result = aggregate(tax, practice);

    expect(result[0].final_verdict).toBe('GUIDANCE');
    expect(result[0].confidence).toBe(0.50);
  });

  it('E5: 複数明細のIDが正しくマッピングされる (line_item_id 順序保持)', () => {
    const tax = [
      makeTax('li_a', 'CAPITAL', { account_category: '器具備品' }),
      makeTax('li_b', 'EXPENSE', { account_category: '修繕費' }),
      makeTax('li_c', 'UNCERTAIN'),
    ];
    const practice = [
      makePractice('li_a', 'CAPITAL', { suggested_account: '器具備品' }),
      makePractice('li_b', 'EXPENSE', { suggested_account: '修繕費' }),
      makePractice('li_c', 'UNCERTAIN'),
    ];

    const result = aggregate(tax, practice);

    expect(result).toHaveLength(3);
    expect(result[0].line_item_id).toBe('li_a');
    expect(result[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(result[0].confidence).toBe(1.0); // 勘定科目一致 → 0.95+0.05=1.0
    expect(result[1].line_item_id).toBe('li_b');
    expect(result[1].final_verdict).toBe('EXPENSE_LIKE');
    expect(result[1].confidence).toBe(1.0); // 勘定科目一致 → 0.95+0.05=1.0
    expect(result[2].line_item_id).toBe('li_c');
    expect(result[2].final_verdict).toBe('GUIDANCE');
    expect(result[2].confidence).toBe(0.30);
  });

  it('E6: useful_life は Tax Agent の値が採用される (Section 3.5 耐用年数合議ルール)', () => {
    // Tax: 器具備品 4年 / Practice: 5年 → Tax優先で 4年
    const tax = [makeTax('L1', 'CAPITAL', { account_category: '器具備品', useful_life: 4 })];
    const practice = [makePractice('L1', 'CAPITAL', { suggested_account: '器具備品' })];

    const result = aggregate(tax, practice);

    expect(result[0].useful_life).toBe(4);
  });
});
