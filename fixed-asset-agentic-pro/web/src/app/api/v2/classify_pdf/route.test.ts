/**
 * /api/v2/classify_pdf 変換ロジック ユニットテスト
 * 根拠: 設計書 Section 5.2 / Section 12
 *
 * テスト戦略:
 * - transformToV2() / normalizeVerdict() は依存ゼロ → 純粋ユニットテスト
 * - getFeatureFlags() は process.env を参照 → vi.stubEnv で差し替え
 * - Python backend 呼び出しは POST handler に閉じているため本ファイルでは省略
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  transformToV2,
  normalizeVerdict,
  getFeatureFlags,
  transformAggregatedToV2,
  extractLineItemsFromClassify,
} from './route.helpers';
import type { ClassifyResponse } from '@/types/classify';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';
import type { AggregatedResult } from '@/types/multi_agent';

// ─── テストデータ ───────────────────────────────────────────────────────────

/** 正常な ClassifyResponse モック（2明細） */
const mockClassifyResponse: ClassifyResponse = {
  decision: 'CAPITAL_LIKE',
  reasons: ['電子計算機 別表一', '取得価額25万円以上'],
  evidence: [],
  questions: [],
  metadata: {},
  is_valid_document: true,
  confidence: 0.92,
  trace: [],
  missing_fields: [],
  why_missing_matters: [],
  citations: [],
  useful_life: undefined,
  line_items: [
    { description: 'ノートPC', amount: 250000, classification: 'CAPITAL_LIKE' },
    { description: '消耗品', amount: 5000, classification: 'EXPENSE_LIKE' },
  ],
  disclaimer: '',
};

// ─── normalizeVerdict ───────────────────────────────────────────────────────

describe('normalizeVerdict', () => {
  it('CAPITAL_LIKE → CAPITAL_LIKE', () => {
    expect(normalizeVerdict('CAPITAL_LIKE')).toBe('CAPITAL_LIKE');
  });

  it('CAPITAL（旧形式）→ CAPITAL_LIKE', () => {
    expect(normalizeVerdict('CAPITAL')).toBe('CAPITAL_LIKE');
  });

  it('EXPENSE_LIKE → EXPENSE_LIKE', () => {
    expect(normalizeVerdict('EXPENSE_LIKE')).toBe('EXPENSE_LIKE');
  });

  it('EXPENSE（旧形式）→ EXPENSE_LIKE', () => {
    expect(normalizeVerdict('EXPENSE')).toBe('EXPENSE_LIKE');
  });

  it('GUIDANCE → GUIDANCE', () => {
    expect(normalizeVerdict('GUIDANCE')).toBe('GUIDANCE');
  });

  it('不明な値 → GUIDANCE（フォールバック）', () => {
    expect(normalizeVerdict('UNCERTAIN')).toBe('GUIDANCE');
    expect(normalizeVerdict('')).toBe('GUIDANCE');
  });
});

// ─── transformToV2 ──────────────────────────────────────────────────────────

describe('transformToV2: 基本変換', () => {
  it('レスポンス必須フィールドが全て存在すること', () => {
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 1500);
    expect(result.request_id).toBe('req-001');
    expect(result.status).toBeDefined();
    expect(result.extracted).toBeDefined();
    expect(result.line_results).toBeDefined();
    expect(result.summary).toBeDefined();
    expect(result.elapsed_ms).toBe(1500);
  });

  it('audit_trail_id=null の場合 null が返ること', () => {
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    expect(result.audit_trail_id).toBeNull();
  });

  it('audit_trail_id が渡された場合 そのまま返ること', () => {
    const result = transformToV2(mockClassifyResponse, 'req-001', 'trail_abc123', 100);
    expect(result.audit_trail_id).toBe('trail_abc123');
  });

  it('is_valid_document=true → status=success', () => {
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    expect(result.status).toBe('success');
  });

  it('is_valid_document=false → status=partial', () => {
    const partial = { ...mockClassifyResponse, is_valid_document: false };
    const result = transformToV2(partial, 'req-001', null, 0);
    expect(result.status).toBe('partial');
  });
});

describe('transformToV2: line_items 変換', () => {
  it('2件の line_items → line_results も 2件になること', () => {
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    expect(result.line_results).toHaveLength(2);
    expect(result.extracted?.items).toHaveLength(2);
  });

  it('line_item_id が extracted と line_results で一致すること', () => {
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    const extractedIds = result.extracted!.items.map((i) => i.line_item_id);
    const resultIds = result.line_results.map((r) => r.line_item_id);
    expect(extractedIds).toEqual(resultIds);
  });

  it('verdict が CAPITAL_LIKE | EXPENSE_LIKE | GUIDANCE のいずれかであること', () => {
    const validVerdicts = ['CAPITAL_LIKE', 'EXPENSE_LIKE', 'GUIDANCE'];
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    for (const lr of result.line_results) {
      expect(validVerdicts).toContain(lr.verdict);
    }
  });

  it('confidence が 0〜1 の範囲内であること（手計算検算）', () => {
    // 根拠: mockClassifyResponse.confidence = 0.92
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    for (const lr of result.line_results) {
      expect(lr.confidence).toBeGreaterThanOrEqual(0);
      expect(lr.confidence).toBeLessThanOrEqual(1);
      expect(lr.confidence).toBe(0.92); // バックエンドの confidence をそのまま使用
    }
  });

  it('description と amount が extracted items に正しく入ること', () => {
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    expect(result.extracted!.items[0].description).toBe('ノートPC');
    expect(result.extracted!.items[0].amount).toBe(250000);
    expect(result.extracted!.items[1].description).toBe('消耗品');
    expect(result.extracted!.items[1].amount).toBe(5000);
  });
});

describe('transformToV2: line_items 空のケース', () => {
  it('line_items=[] の場合 decision を1行として扱うこと', () => {
    const emptyItems: ClassifyResponse = { ...mockClassifyResponse, line_items: [] };
    const result = transformToV2(emptyItems, 'req-001', null, 0);
    expect(result.line_results).toHaveLength(1);
    expect(result.line_results[0].verdict).toBe('CAPITAL_LIKE');
  });

  it('line_items=[] の場合 extracted.items も1件になること', () => {
    const emptyItems: ClassifyResponse = { ...mockClassifyResponse, line_items: [] };
    const result = transformToV2(emptyItems, 'req-001', null, 0);
    expect(result.extracted!.items).toHaveLength(1);
  });
});

describe('transformToV2: summary 計算（CHECK-7b 手計算検算）', () => {
  it('capital_total は CAPITAL_LIKE の金額合計であること', () => {
    // 手計算: ノートPC 250,000円 → CAPITAL_LIKE
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    expect(result.summary.capital_total).toBe(250000);
  });

  it('expense_total は EXPENSE_LIKE の金額合計であること', () => {
    // 手計算: 消耗品 5,000円 → EXPENSE_LIKE
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    expect(result.summary.expense_total).toBe(5000);
  });

  it('guidance_total は GUIDANCE の金額合計であること', () => {
    // 手計算: GUIDANCEアイテムなし → 0
    const result = transformToV2(mockClassifyResponse, 'req-001', null, 0);
    expect(result.summary.guidance_total).toBe(0);
  });

  it('全明細が GUIDANCE の場合 capital/expense は 0', () => {
    const guidanceRes: ClassifyResponse = {
      ...mockClassifyResponse,
      decision: 'GUIDANCE',
      line_items: [
        { description: '要確認品目', amount: 100000, classification: 'GUIDANCE' },
      ],
    };
    const result = transformToV2(guidanceRes, 'req-001', null, 0);
    expect(result.summary.capital_total).toBe(0);
    expect(result.summary.expense_total).toBe(0);
    expect(result.summary.guidance_total).toBe(100000);
  });

  it('amount が undefined の明細は 0 として集計される', () => {
    const noAmountRes: ClassifyResponse = {
      ...mockClassifyResponse,
      line_items: [
        { description: '金額不明品目', classification: 'CAPITAL_LIKE' },
      ],
    };
    const result = transformToV2(noAmountRes, 'req-001', null, 0);
    expect(result.summary.capital_total).toBe(0);
  });
});

// ─── extractLineItemsFromClassify ───────────────────────────────────────────

describe('extractLineItemsFromClassify', () => {
  it('line_items が2件ある場合 2件の ExtractedLineItem を返すこと', () => {
    const result = extractLineItemsFromClassify(mockClassifyResponse);
    expect(result).toHaveLength(2);
  });

  it('各 ExtractedLineItem に一意な line_item_id が付くこと', () => {
    const result = extractLineItemsFromClassify(mockClassifyResponse);
    const ids = result.map((i) => i.line_item_id);
    // line_item_id が 'li_' で始まること（根拠: route.ts extractLineItemsFromClassify）
    for (const id of ids) {
      expect(id).toMatch(/^li_/);
    }
    // 重複なし
    expect(new Set(ids).size).toBe(2);
  });

  it('description と amount が正しくマッピングされること', () => {
    const result = extractLineItemsFromClassify(mockClassifyResponse);
    expect(result[0].description).toBe('ノートPC');
    expect(result[0].amount).toBe(250000);
    expect(result[1].description).toBe('消耗品');
    expect(result[1].amount).toBe(5000);
  });

  it('line_items=[] の場合 decision 全体を1件として扱うこと', () => {
    const empty: ClassifyResponse = { ...mockClassifyResponse, line_items: [] };
    const result = extractLineItemsFromClassify(empty);
    expect(result).toHaveLength(1);
    expect(result[0].description).toBe('ドキュメント全体');
    expect(result[0].amount).toBe(0);
  });
});

// ─── transformAggregatedToV2 ─────────────────────────────────────────────────

/** テスト用 ExtractedLineItem */
const mockExtractedItems: ExtractedLineItem[] = [
  { line_item_id: 'li_aaa', description: 'ノートPC', amount: 250000 },
  { line_item_id: 'li_bbb', description: '修繕費', amount: 50000 },
];

/** テスト用 AggregatedResult: Tax/Practice 両方 CAPITAL（一致）→ CAPITAL_LIKE, confidence 0.95 */
const mockAggregatedCapital: AggregatedResult = {
  line_item_id: 'li_aaa',
  final_verdict: 'CAPITAL_LIKE',
  confidence: 0.95,
  account_category: '器具備品',
  useful_life: 4,
  tax_result: {
    line_item_id: 'li_aaa',
    verdict: 'CAPITAL',
    rationale: '電子計算機 別表一',
    article_ref: '法人税法施行令第133条',
    account_category: '器具備品',
    useful_life: 4,
    formal_criteria_step: null,
    confidence: 0.9,
  },
  practice_result: {
    line_item_id: 'li_aaa',
    verdict: 'CAPITAL',
    rationale: '過去事例：PC購入',
    similar_cases: [{ description: 'ノートPC Dell', classification: 'CAPITAL', similarity: 0.95 }],
    suggested_account: '器具備品',
    confidence: 0.88,
  },
};

/** テスト用 AggregatedResult: Tax EXPENSE / Practice UNCERTAIN → EXPENSE_LIKE, confidence 0.80 */
const mockAggregatedExpense: AggregatedResult = {
  line_item_id: 'li_bbb',
  final_verdict: 'EXPENSE_LIKE',
  confidence: 0.80,
  account_category: '修繕費',
  useful_life: null,
  tax_result: {
    line_item_id: 'li_bbb',
    verdict: 'EXPENSE',
    rationale: '基通7-8-3(1) 20万円未満',
    article_ref: '基通7-8-3(1)',
    account_category: '修繕費',
    useful_life: null,
    formal_criteria_step: 1,
    confidence: 0.95,
  },
  practice_result: {
    line_item_id: 'li_bbb',
    verdict: 'UNCERTAIN',
    rationale: '類似事例なし',
    similar_cases: [],
    suggested_account: null,
    confidence: 0.3,
  },
};

describe('transformAggregatedToV2: 基本構造（設計書 Section 5.2 スキーマ検証）', () => {
  it('必須フィールドが全て存在すること', () => {
    const result = transformAggregatedToV2(
      [mockAggregatedCapital, mockAggregatedExpense],
      mockExtractedItems,
      'req-multi-001',
      'trail_abc',
      1200,
    );
    // 設計書 Section 5.2 の必須フィールド
    expect(result.request_id).toBe('req-multi-001');
    expect(result.status).toBe('success');
    expect(result.extracted).toBeDefined();
    expect(result.line_results).toBeDefined();
    expect(result.summary).toBeDefined();
    expect(result.audit_trail_id).toBe('trail_abc');
    expect(result.elapsed_ms).toBe(1200);
  });

  it('line_results に設計書 Section 5.2 の全フィールドが存在すること', () => {
    const result = transformAggregatedToV2(
      [mockAggregatedCapital],
      mockExtractedItems,
      'req-multi-001',
      null,
      500,
    );
    const lr = result.line_results[0];
    // Section 5.2 LineResultV2 フィールド
    expect(lr).toHaveProperty('line_item_id');
    expect(lr).toHaveProperty('verdict');
    expect(lr).toHaveProperty('confidence');
    expect(lr).toHaveProperty('account_category');
    expect(lr).toHaveProperty('useful_life');
    expect(lr).toHaveProperty('tax_verdict');
    expect(lr).toHaveProperty('tax_rationale');
    expect(lr).toHaveProperty('tax_account');
    expect(lr).toHaveProperty('practice_verdict');
    expect(lr).toHaveProperty('practice_rationale');
    expect(lr).toHaveProperty('practice_account');
    expect(lr).toHaveProperty('similar_cases');
  });

  it('audit_trail_id=null の場合 null が返ること', () => {
    const result = transformAggregatedToV2([], [], 'req-001', null, 0);
    expect(result.audit_trail_id).toBeNull();
  });
});

describe('transformAggregatedToV2: 3エージェント合議 正常系（Section 5.2 verdict検証）', () => {
  it('CAPITAL_LIKE の line_result が Aggregator 結果と一致すること（手計算検算）', () => {
    // 根拠: mockAggregatedCapital.final_verdict = CAPITAL_LIKE, confidence = 0.95
    const result = transformAggregatedToV2(
      [mockAggregatedCapital, mockAggregatedExpense],
      mockExtractedItems,
      'req-001',
      null,
      800,
    );
    const capitalItem = result.line_results.find((r) => r.line_item_id === 'li_aaa');
    expect(capitalItem?.verdict).toBe('CAPITAL_LIKE');
    expect(capitalItem?.confidence).toBe(0.95);
    expect(capitalItem?.account_category).toBe('器具備品');
    expect(capitalItem?.useful_life).toBe(4);
  });

  it('EXPENSE_LIKE の line_result が Aggregator 結果と一致すること（手計算検算）', () => {
    // 根拠: mockAggregatedExpense.final_verdict = EXPENSE_LIKE, confidence = 0.80
    const result = transformAggregatedToV2(
      [mockAggregatedCapital, mockAggregatedExpense],
      mockExtractedItems,
      'req-001',
      null,
      800,
    );
    const expenseItem = result.line_results.find((r) => r.line_item_id === 'li_bbb');
    expect(expenseItem?.verdict).toBe('EXPENSE_LIKE');
    expect(expenseItem?.confidence).toBe(0.80);
    expect(expenseItem?.tax_verdict).toBe('EXPENSE');
    expect(expenseItem?.practice_verdict).toBe('UNCERTAIN');
  });

  it('tax_verdict / tax_rationale / tax_account が Tax Agent 結果から取得されること', () => {
    const result = transformAggregatedToV2(
      [mockAggregatedCapital],
      mockExtractedItems,
      'req-001',
      null,
      100,
    );
    const lr = result.line_results[0];
    expect(lr.tax_verdict).toBe('CAPITAL');
    expect(lr.tax_rationale).toBe('電子計算機 別表一');
    expect(lr.tax_account).toBe('器具備品');
  });

  it('practice_verdict / practice_rationale / practice_account が Practice Agent 結果から取得されること', () => {
    const result = transformAggregatedToV2(
      [mockAggregatedCapital],
      mockExtractedItems,
      'req-001',
      null,
      100,
    );
    const lr = result.line_results[0];
    expect(lr.practice_verdict).toBe('CAPITAL');
    expect(lr.practice_rationale).toBe('過去事例：PC購入');
    expect(lr.practice_account).toBe('器具備品');
  });

  it('similar_cases が Practice Agent の similar_cases[].description に変換されること', () => {
    const result = transformAggregatedToV2(
      [mockAggregatedCapital],
      mockExtractedItems,
      'req-001',
      null,
      100,
    );
    const lr = result.line_results[0];
    expect(lr.similar_cases).toEqual(['ノートPC Dell']);
  });
});

describe('transformAggregatedToV2: summary 計算（CHECK-7b 手計算検算）', () => {
  it('capital_total は CAPITAL_LIKE 明細の金額合計であること', () => {
    // 手計算: li_aaa (ノートPC 250,000) → CAPITAL_LIKE
    const result = transformAggregatedToV2(
      [mockAggregatedCapital, mockAggregatedExpense],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    expect(result.summary.capital_total).toBe(250000);
  });

  it('expense_total は EXPENSE_LIKE 明細の金額合計であること', () => {
    // 手計算: li_bbb (修繕費 50,000) → EXPENSE_LIKE
    const result = transformAggregatedToV2(
      [mockAggregatedCapital, mockAggregatedExpense],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    expect(result.summary.expense_total).toBe(50000);
  });

  it('guidance_total は GUIDANCE 明細の金額合計であること', () => {
    // 手計算: GUIDANCEアイテムなし → 0
    const result = transformAggregatedToV2(
      [mockAggregatedCapital, mockAggregatedExpense],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    expect(result.summary.guidance_total).toBe(0);
  });

  it('by_account に CAPITAL_LIKE の勘定科目集計が含まれること', () => {
    const result = transformAggregatedToV2(
      [mockAggregatedCapital],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    const byAccount = result.summary.by_account;
    expect(byAccount).toHaveLength(1);
    expect(byAccount[0].account_category).toBe('器具備品');
    expect(byAccount[0].count).toBe(1);
    expect(byAccount[0].total_amount).toBe(250000);
  });

  it('EXPENSE_LIKE は by_account に含まれないこと（CAPITAL のみ集計）', () => {
    const result = transformAggregatedToV2(
      [mockAggregatedExpense],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    expect(result.summary.by_account).toHaveLength(0);
  });
});

describe('transformAggregatedToV2: 片方エージェント失敗（部分障害耐性）', () => {
  it('Tax Agent 失敗（null）の場合 tax_verdict が UNCERTAIN になること', () => {
    const aggWithNullTax: AggregatedResult = {
      line_item_id: 'li_aaa',
      final_verdict: 'GUIDANCE',
      confidence: 0.30,
      account_category: null,
      useful_life: null,
      tax_result: null,
      practice_result: null,
    };
    const result = transformAggregatedToV2(
      [aggWithNullTax],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    expect(result.line_results[0].tax_verdict).toBe('UNCERTAIN');
    expect(result.line_results[0].tax_rationale).toBe('');
    expect(result.line_results[0].tax_account).toBeNull();
  });

  it('Practice Agent 失敗（null）の場合 practice_verdict が UNCERTAIN になること', () => {
    const aggWithNullPractice: AggregatedResult = {
      line_item_id: 'li_aaa',
      final_verdict: 'CAPITAL_LIKE',
      confidence: 0.80,
      account_category: '器具備品',
      useful_life: 4,
      tax_result: {
        line_item_id: 'li_aaa',
        verdict: 'CAPITAL',
        rationale: 'Tax判定',
        article_ref: null,
        account_category: '器具備品',
        useful_life: 4,
        formal_criteria_step: null,
        confidence: 0.9,
      },
      practice_result: null,
    };
    const result = transformAggregatedToV2(
      [aggWithNullPractice],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    expect(result.line_results[0].practice_verdict).toBe('UNCERTAIN');
    expect(result.line_results[0].practice_rationale).toBe('');
    expect(result.line_results[0].practice_account).toBeNull();
    expect(result.line_results[0].similar_cases).toEqual([]);
  });

  it('agentStatus=partial → status=partial が返ること', () => {
    const result = transformAggregatedToV2(
      [mockAggregatedCapital],
      mockExtractedItems,
      'req-001',
      null,
      0,
      'partial',  // agentStatus
    );
    expect(result.status).toBe('partial');
  });

  it('両方 Agent 失敗（両方 null result）の場合 summary は全て 0 になること', () => {
    const aggBothNull: AggregatedResult = {
      line_item_id: 'li_aaa',
      final_verdict: 'GUIDANCE',
      confidence: 0.30,
      account_category: null,
      useful_life: null,
      tax_result: null,
      practice_result: null,
    };
    const result = transformAggregatedToV2(
      [aggBothNull],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    expect(result.summary.capital_total).toBe(0);
    expect(result.summary.expense_total).toBe(0);
    expect(result.summary.guidance_total).toBe(250000); // li_aaa は GUIDANCE, amount=250000
    expect(result.line_results[0].verdict).toBe('GUIDANCE');
  });
});

describe('transformAggregatedToV2: Promise.allSettled 部分成功パターン', () => {
  it('Tax 成功・Practice 成功のケースで status=success、confidence=0.95', () => {
    // Tax:CAPITAL + Practice:CAPITAL → CAPITAL_LIKE, 0.95（Section 3.5 パターン1）
    const result = transformAggregatedToV2(
      [mockAggregatedCapital],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    expect(result.status).toBe('success');
    expect(result.line_results[0].confidence).toBe(0.95);
  });

  it('Tax 成功・Practice UNCERTAIN のケースで confidence=0.80（Section 3.5 パターン3相当）', () => {
    // Tax:EXPENSE + Practice:UNCERTAIN → EXPENSE_LIKE, confidence=0.80
    const result = transformAggregatedToV2(
      [mockAggregatedExpense],
      mockExtractedItems,
      'req-001',
      null,
      0,
    );
    expect(result.line_results[0].confidence).toBe(0.80);
    expect(result.line_results[0].verdict).toBe('EXPENSE_LIKE');
  });

  it('agentStatus=partial で status=partial が返ること（Promise.allSettled 失敗時）', () => {
    // Promise.allSettled で片方が rejected → agentStatus='partial' → status: 'partial'
    const result = transformAggregatedToV2(
      [mockAggregatedCapital],
      mockExtractedItems,
      'req-multi-partial',
      null,
      0,
      'partial',
    );
    expect(result.status).toBe('partial');
    // 成功した Agent の結果は正しく返ること
    expect(result.line_results[0].verdict).toBe('CAPITAL_LIKE');
  });
});

// ─── getFeatureFlags ────────────────────────────────────────────────────────

describe('getFeatureFlags', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('USE_MULTI_AGENT 未設定 → false（デフォルト）', () => {
    vi.stubEnv('USE_MULTI_AGENT', '');
    const flags = getFeatureFlags();
    expect(flags.useMultiAgent).toBe(false);
  });

  it('USE_MULTI_AGENT=true → true', () => {
    vi.stubEnv('USE_MULTI_AGENT', 'true');
    const flags = getFeatureFlags();
    expect(flags.useMultiAgent).toBe(true);
  });

  it('PARALLEL_AGENTS 未設定 → true（デフォルト）', () => {
    vi.stubEnv('PARALLEL_AGENTS', '');
    const flags = getFeatureFlags();
    expect(flags.parallelAgents).toBe(true);
  });

  it('PARALLEL_AGENTS=false → false', () => {
    vi.stubEnv('PARALLEL_AGENTS', 'false');
    const flags = getFeatureFlags();
    expect(flags.parallelAgents).toBe(false);
  });

  it('AUDIT_TRAIL_ENABLED 未設定 → true（デフォルト）', () => {
    vi.stubEnv('AUDIT_TRAIL_ENABLED', '');
    const flags = getFeatureFlags();
    expect(flags.auditTrailEnabled).toBe(true);
  });

  it('AUDIT_TRAIL_ENABLED=false → false', () => {
    vi.stubEnv('AUDIT_TRAIL_ENABLED', 'false');
    const flags = getFeatureFlags();
    expect(flags.auditTrailEnabled).toBe(false);
  });
});
