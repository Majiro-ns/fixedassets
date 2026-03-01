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
import { transformToV2, normalizeVerdict, getFeatureFlags } from './route';
import type { ClassifyResponse } from '@/types/classify';

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
