/**
 * practiceAgent.test.ts
 *
 * CHECK-9: テスト期待値の根拠は全て設計書に基づく:
 *   - Section 3.4: Practice Agent 仕様（教師データ活用, similar_cases 形式, エラー耐性）
 *   - Section 6: エラーハンドリング（API 失敗 / パースエラー → UNCERTAIN フォールバック）
 *   - Section 12: Feature Flag（dry-run = ANTHROPIC_API_KEY 未設定時）
 *
 * CHECK-7b 手計算検証:
 *   calcSimilarity("ノートPC", "ノートPC") = 1.0
 *     → tokens: {"ノートpc"} ∩ {"ノートpc"} = 1 / union 1 = 1.0
 *   calcSimilarity("エアコン", "コピー用紙") = 0.0
 *     → tokens: {"エアコン"} ∩ {"コピー用紙"} = 0 / union 2 = 0.0
 *   selectFewShot("ノートPC Dell", records): "ノートPC" が "コピー用紙" より高スコア
 *     → "ノートPC Dell"→{"ノートpc","dell"}, "ノートPC"→{"ノートpc"}: 1/2=0.5
 *     → "ノートPC Dell"→{"ノートpc","dell"}, "コピー用紙"→{"コピー用紙"}: 0/3=0.0
 *
 * vi.mock はトップレベルで宣言（vitest ホイスティング必須）
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import Anthropic from '@anthropic-ai/sdk';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';
import type { TrainingRecord } from '@/types/training_data';

// ─── モック（トップレベル — ホイスティング必須） ─────────────────────────────
// vi.mock はファイル先頭にホイストされる。factory 内では vi.fn() のみ使用可。

vi.mock('@anthropic-ai/sdk', () => ({
  default: vi.fn(),
}));

// ─── テスト対象インポート ────────────────────────────────────────────────────

import {
  runPracticeAgent,
  calcSimilarity,
  selectFewShot,
  parsePracticeResults,
} from '../practiceAgent';

// ─── テストデータ ────────────────────────────────────────────────────────────

const mockLineItems: ExtractedLineItem[] = [
  { line_item_id: 'li_001', description: 'ノートPC Dell Latitude 5540', amount: 250000, quantity: 1 },
  { line_item_id: 'li_002', description: 'コピー用紙 A4 500枚', amount: 5000, quantity: 10 },
];

const mockTrainingRecords: TrainingRecord[] = [
  { item: 'ノートPC', amount: 120000, label: '固定資産', notes: '器具備品' },
  { item: 'デスクトップPC', amount: 200000, label: '固定資産', notes: '器具備品' },
  { item: 'コピー用紙', amount: 3000, label: '費用', notes: '消耗品費' },
  { item: '文房具', amount: 2000, label: '費用' },
  { item: 'サーバー', amount: 500000, label: '固定資産' },
];

// ─── モックレスポンスビルダー ────────────────────────────────────────────────

function makeAnthropicResponse(jsonText: string) {
  return {
    id: 'msg_test_001',
    type: 'message',
    role: 'assistant',
    model: 'claude-haiku-4-5-20251001',
    content: [{ type: 'text', text: jsonText }],
    stop_reason: 'end_turn',
    usage: { input_tokens: 100, output_tokens: 50 },
  };
}

const mockSuccessResponse = JSON.stringify([
  {
    line_item_id: 'li_001',
    verdict: 'CAPITAL',
    rationale: 'ノートPCは固定資産として過去3件計上実績あり',
    suggested_account: '器具備品',
    confidence: 0.9,
    similar_cases: [
      { description: 'ノートPC', classification: 'CAPITAL', similarity: 0.85 },
    ],
  },
  {
    line_item_id: 'li_002',
    verdict: 'EXPENSE',
    rationale: 'コピー用紙は消耗品として費用計上',
    suggested_account: '消耗品費',
    confidence: 0.95,
    similar_cases: [
      { description: 'コピー用紙', classification: 'EXPENSE', similarity: 0.9 },
    ],
  },
]);

// ─────────────────────────────────────────────────────────────────────────────
// calcSimilarity: Jaccard 係数（根拠: Section 3.4 類似事例ベース判定）
// ─────────────────────────────────────────────────────────────────────────────

describe('calcSimilarity: Jaccard 係数（CHECK-7b 手計算検証）', () => {
  it('完全一致の場合 1.0 を返すこと', () => {
    // CHECK-7b: {"ノートpc"} ∩ {"ノートpc"} = 1 / union 1 = 1.0
    expect(calcSimilarity('ノートPC', 'ノートPC')).toBe(1.0);
  });

  it('小文字統一後に完全一致する場合も 1.0 を返すこと', () => {
    // CHECK-7b: "ノートpc" vs "ノートpc" → tokens 完全一致
    expect(calcSimilarity('ノートpc', 'ノートpc')).toBe(1.0);
  });

  it('共通トークンなしの場合 0.0 を返すこと', () => {
    // CHECK-7b: {"エアコン"} ∩ {"コピー用紙"} = 0 / union 2 = 0.0
    expect(calcSimilarity('エアコン', 'コピー用紙')).toBe(0.0);
  });

  it('部分一致（英単語共通）の場合 0〜1 の範囲の値を返すこと', () => {
    // CHECK-7b: {"ノートpc","dell"} ∩ {"デスクトップpc","dell"} = 1 / union 3 ≈ 0.33 > 0
    const sim = calcSimilarity('ノートPC Dell', 'デスクトップPC Dell');
    expect(sim).toBeGreaterThan(0);
    expect(sim).toBeLessThanOrEqual(1);
  });

  it('a が空文字列の場合 0.0 を返すこと', () => {
    expect(calcSimilarity('', 'ノートPC')).toBe(0.0);
  });

  it('b が空文字列の場合 0.0 を返すこと', () => {
    expect(calcSimilarity('ノートPC', '')).toBe(0.0);
  });

  it('返り値は常に 0 以上 1 以下であること', () => {
    const cases = [
      ['ノートPC', 'デスクトップPC'],
      ['エアコン修理', 'エアコン'],
      ['社用車 200万円', '営業車両'],
    ];
    for (const [a, b] of cases) {
      const sim = calcSimilarity(a, b);
      expect(sim).toBeGreaterThanOrEqual(0);
      expect(sim).toBeLessThanOrEqual(1);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// selectFewShot: 類似度降順 top-N 選択（根拠: Section 3.4 教師データ活用）
// ─────────────────────────────────────────────────────────────────────────────

describe('selectFewShot: top-N 選択（根拠: Section 3.4）', () => {
  it('maxN=10 で 10件を超えないこと', () => {
    // CHECK-9: Section 3.4 "trainingRecords から top-N（10件）を選択"
    const records: TrainingRecord[] = Array.from({ length: 15 }, (_, i) => ({
      item: `品目${i}`,
      amount: 10000 * (i + 1),
      label: '固定資産',
    }));
    const result = selectFewShot('テスト', records, 10);
    expect(result.length).toBeLessThanOrEqual(10);
  });

  it('教師データが 0件の場合は空配列を返すこと', () => {
    expect(selectFewShot('ノートPC', [], 10)).toHaveLength(0);
  });

  it('類似度が高いレコードが先頭に来ること（CHECK-7b 手計算検証）', () => {
    // CHECK-7b: "ノートPC Dell" に対して
    //   "ノートPC" → similarity ≈ 0.5 > "コピー用紙" → similarity = 0.0
    const records: TrainingRecord[] = [
      { item: 'コピー用紙', amount: 3000, label: '費用' },
      { item: 'ノートPC', amount: 120000, label: '固定資産' },
    ];
    const result = selectFewShot('ノートPC Dell', records, 10);
    expect(result[0].item).toBe('ノートPC');
  });

  it('各エントリに _similarity フィールドが追加されること', () => {
    const result = selectFewShot('ノートPC', mockTrainingRecords, 5);
    for (const r of result) {
      expect(typeof r._similarity).toBe('number');
      expect(r._similarity).toBeGreaterThanOrEqual(0);
      expect(r._similarity).toBeLessThanOrEqual(1);
    }
  });

  it('maxN より少ない件数の教師データでは全件返すこと', () => {
    const result = selectFewShot('テスト', mockTrainingRecords, 10);
    expect(result.length).toBe(mockTrainingRecords.length);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// parsePracticeResults: レスポンスパース（根拠: Section 3.4 出力スキーマ）
// ─────────────────────────────────────────────────────────────────────────────

describe('parsePracticeResults: レスポンスパース（根拠: Section 3.4）', () => {
  it('正常な JSON → PracticeAgentResult[] に変換できること', () => {
    const results = parsePracticeResults(mockSuccessResponse, mockLineItems);
    expect(results).toHaveLength(2);
    expect(results[0].line_item_id).toBe('li_001');
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].suggested_account).toBe('器具備品');
    expect(results[1].verdict).toBe('EXPENSE');
  });

  it('JSON 配列が見つからない場合は例外を投げること', () => {
    expect(() => parsePracticeResults('JSONではありません', mockLineItems)).toThrow();
  });

  it('不正な verdict → UNCERTAIN に正規化されること', () => {
    const raw = JSON.stringify([
      { line_item_id: 'li_001', verdict: 'INVALID', rationale: 'test', similar_cases: [] },
      { line_item_id: 'li_002', verdict: 'EXPENSE', rationale: 'test', similar_cases: [] },
    ]);
    const results = parsePracticeResults(raw, mockLineItems);
    expect(results[0].verdict).toBe('UNCERTAIN'); // 不正値 → UNCERTAIN
    expect(results[1].verdict).toBe('EXPENSE');   // 正常値 → そのまま
  });

  it('response に line_item_id が存在しない場合 UNCERTAIN を返すこと', () => {
    const raw = JSON.stringify([]);
    const results = parsePracticeResults(raw, mockLineItems);
    expect(results).toHaveLength(2);
    for (const r of results) {
      expect(r.verdict).toBe('UNCERTAIN');
      expect(r.rationale).toContain('判定が返りませんでした');
    }
  });

  it('similar_cases は最大3件に制限されること（根拠: Section 3.4）', () => {
    // CHECK-9: Section 3.4 "similar_cases: [{description, classification, similarity}]"
    const raw = JSON.stringify([
      {
        line_item_id: 'li_001',
        verdict: 'CAPITAL',
        rationale: '事例多数',
        similar_cases: Array.from({ length: 5 }, (_, i) => ({
          description: `事例${i}`,
          classification: 'CAPITAL',
          similarity: 0.9 - i * 0.1,
        })),
      },
      {
        line_item_id: 'li_002',
        verdict: 'EXPENSE',
        rationale: '費用',
        similar_cases: [],
      },
    ]);
    const results = parsePracticeResults(raw, mockLineItems);
    expect(results[0].similar_cases.length).toBeLessThanOrEqual(3);
  });

  it('similar_cases の similarity は [0, 1] にクランプされること', () => {
    const raw = JSON.stringify([
      {
        line_item_id: 'li_001',
        verdict: 'CAPITAL',
        rationale: 'test',
        similar_cases: [
          { description: 'test', classification: 'CAPITAL', similarity: 1.5 }, // 超過
          { description: 'test2', classification: 'EXPENSE', similarity: -0.3 }, // 負値
        ],
      },
      {
        line_item_id: 'li_002',
        verdict: 'EXPENSE',
        rationale: 'test',
        similar_cases: [],
      },
    ]);
    const results = parsePracticeResults(raw, mockLineItems);
    for (const c of results[0].similar_cases) {
      expect(c.similarity).toBeGreaterThanOrEqual(0);
      expect(c.similarity).toBeLessThanOrEqual(1);
    }
  });

  it('suggested_account が null / undefined / 空文字の場合 null を返すこと', () => {
    const raw = JSON.stringify([
      {
        line_item_id: 'li_001',
        verdict: 'UNCERTAIN',
        rationale: 'test',
        suggested_account: null,
        similar_cases: [],
      },
      {
        line_item_id: 'li_002',
        verdict: 'UNCERTAIN',
        rationale: 'test',
        suggested_account: '',
        similar_cases: [],
      },
    ]);
    const results = parsePracticeResults(raw, mockLineItems);
    expect(results[0].suggested_account).toBeNull();
    expect(results[1].suggested_account).toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// dry-run モード: ANTHROPIC_API_KEY 未設定時（根拠: Section 12 Feature Flag）
// ─────────────────────────────────────────────────────────────────────────────

describe('dry-runモード: ANTHROPIC_API_KEY 未設定時（根拠: Section 12）', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.stubEnv('ANTHROPIC_API_KEY', '');
    vi.mocked(Anthropic).mockClear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('ANTHROPIC_API_KEY 未設定 → API 呼び出しなしで UNCERTAIN を返すこと', async () => {
    const results = await runPracticeAgent(mockLineItems, mockTrainingRecords);

    expect(results).toHaveLength(2);
    for (const r of results) {
      expect(r.verdict).toBe('UNCERTAIN');
      expect(Array.isArray(r.similar_cases)).toBe(true);
    }
    // Anthropic コンストラクタが呼ばれないこと
    expect(vi.mocked(Anthropic)).not.toHaveBeenCalled();
  });

  it('dry-run の rationale に "dry-run" が含まれること', async () => {
    const results = await runPracticeAgent(mockLineItems, []);
    expect(results[0].rationale).toMatch(/dry.?run/i);
  });

  it('lineItems が空配列の場合は空配列を返すこと', async () => {
    const results = await runPracticeAgent([], mockTrainingRecords);
    expect(results).toHaveLength(0);
    expect(vi.mocked(Anthropic)).not.toHaveBeenCalled();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 正常系: API 呼び出し + 判定（根拠: Section 3.4 Practice Agent 仕様）
// ─────────────────────────────────────────────────────────────────────────────

describe('runPracticeAgent: 正常系（根拠: Section 3.4）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-ant-test-key');
    vi.mocked(Anthropic).mockClear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('教師データありの場合、API を呼び出して PracticeAgentResult[] を返すこと', async () => {
    const mockCreate = vi.fn().mockResolvedValue(makeAnthropicResponse(mockSuccessResponse));
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    const results = await runPracticeAgent(mockLineItems, mockTrainingRecords);

    expect(results).toHaveLength(2);
    expect(results[0].line_item_id).toBe('li_001');
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].suggested_account).toBe('器具備品');
    expect(results[1].verdict).toBe('EXPENSE');
    expect(mockCreate).toHaveBeenCalledTimes(1);
  });

  it('教師データなしの場合も API を呼び出すこと', async () => {
    const noDataResponse = JSON.stringify([
      { line_item_id: 'li_001', verdict: 'UNCERTAIN', rationale: '教師データなし', similar_cases: [] },
      { line_item_id: 'li_002', verdict: 'UNCERTAIN', rationale: '教師データなし', similar_cases: [] },
    ]);
    const mockCreate = vi.fn().mockResolvedValue(makeAnthropicResponse(noDataResponse));
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    const results = await runPracticeAgent(mockLineItems, []); // 教師データ 0件
    expect(mockCreate).toHaveBeenCalledTimes(1);
    expect(results).toHaveLength(2);
  });

  it('similar_cases の構造が SimilarCase[] に準拠すること（根拠: Section 3.4）', async () => {
    // CHECK-9: Section 3.4 "similar_cases: [{description, classification, similarity}]"
    const mockCreate = vi.fn().mockResolvedValue(makeAnthropicResponse(mockSuccessResponse));
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    const results = await runPracticeAgent(mockLineItems, mockTrainingRecords);

    const sc = results[0].similar_cases;
    expect(sc.length).toBeGreaterThan(0);
    for (const c of sc) {
      expect(typeof c.description).toBe('string');
      expect(['CAPITAL', 'EXPENSE', 'UNCERTAIN']).toContain(c.classification);
      expect(typeof c.similarity).toBe('number');
      expect(c.similarity).toBeGreaterThanOrEqual(0);
      expect(c.similarity).toBeLessThanOrEqual(1);
    }
  });

  it('few-shot は最大 10件に制限されること（根拠: Section 3.4 top-N 選択）', async () => {
    // 15件の教師データ → システムプロンプト内の few-shot は 10件以下
    const manyRecords: TrainingRecord[] = Array.from({ length: 15 }, (_, i) => ({
      item: `品目${i}`,
      amount: 10000 * (i + 1),
      label: i % 2 === 0 ? '固定資産' : '費用',
    }));

    const singleItemResponse = JSON.stringify([
      { line_item_id: 'li_001', verdict: 'UNCERTAIN', rationale: 'test', similar_cases: [] },
      { line_item_id: 'li_002', verdict: 'UNCERTAIN', rationale: 'test', similar_cases: [] },
    ]);
    const mockCreate = vi.fn().mockResolvedValue(makeAnthropicResponse(singleItemResponse));
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    await runPracticeAgent(mockLineItems, manyRecords);

    const callArgs = mockCreate.mock.calls[0][0] as { system: string };
    const systemPrompt = callArgs.system;
    // システムプロンプトに "Few-shot N件" が含まれ N <= 10 であること
    const matches = systemPrompt.match(/Few-shot (\d+)件/);
    expect(matches).not.toBeNull();
    expect(parseInt(matches![1])).toBeLessThanOrEqual(10);
  });

  it('verdict が正しいフィールドで返ること', async () => {
    const mockCreate = vi.fn().mockResolvedValue(makeAnthropicResponse(mockSuccessResponse));
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    const results = await runPracticeAgent(mockLineItems, mockTrainingRecords);
    for (const r of results) {
      expect(['CAPITAL', 'EXPENSE', 'UNCERTAIN']).toContain(r.verdict);
      expect(typeof r.line_item_id).toBe('string');
      expect(typeof r.rationale).toBe('string');
      expect(Array.isArray(r.similar_cases)).toBe(true);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// エラーハンドリング（根拠: Section 6 エラーハンドリング）
// ─────────────────────────────────────────────────────────────────────────────

describe('runPracticeAgent: エラーハンドリング（根拠: Section 6）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'sk-ant-test-key');
    vi.mocked(Anthropic).mockClear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('API 呼び出し失敗時は全明細 UNCERTAIN を返すこと', async () => {
    // CHECK-9: Section 6 "Practice 失敗 → 当該明細を GUIDANCE 扱い"
    const mockCreate = vi.fn().mockRejectedValue(new Error('API Error 503: Service Unavailable'));
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    const results = await runPracticeAgent(mockLineItems, mockTrainingRecords);

    expect(results).toHaveLength(2);
    for (const r of results) {
      expect(r.verdict).toBe('UNCERTAIN');
      expect(r.rationale).toContain('APIエラー');
    }
  });

  it('不正な JSON レスポンス時は全明細 UNCERTAIN フォールバックを返すこと', async () => {
    const mockCreate = vi.fn().mockResolvedValue(
      makeAnthropicResponse('これはJSONではありません'),
    );
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    const results = await runPracticeAgent(mockLineItems, mockTrainingRecords);

    expect(results).toHaveLength(2);
    for (const r of results) {
      expect(r.verdict).toBe('UNCERTAIN');
    }
  });

  it('空配列 JSON レスポンス時は各 line_item_id の UNCERTAIN を返すこと', async () => {
    const mockCreate = vi.fn().mockResolvedValue(makeAnthropicResponse('[]'));
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    const results = await runPracticeAgent(mockLineItems, mockTrainingRecords);

    expect(results).toHaveLength(2);
    for (const r of results) {
      expect(r.verdict).toBe('UNCERTAIN');
    }
  });

  it('不正な verdict 値は UNCERTAIN に正規化されること', async () => {
    const invalidVerdictResponse = JSON.stringify([
      {
        line_item_id: 'li_001',
        verdict: 'INVALID_VERDICT', // 不正値
        rationale: 'テスト',
        similar_cases: [],
      },
      {
        line_item_id: 'li_002',
        verdict: 'EXPENSE', // 正常値
        rationale: 'テスト',
        similar_cases: [],
      },
    ]);
    const mockCreate = vi.fn().mockResolvedValue(makeAnthropicResponse(invalidVerdictResponse));
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    const results = await runPracticeAgent(mockLineItems, mockTrainingRecords);

    expect(results[0].verdict).toBe('UNCERTAIN'); // 不正値 → UNCERTAIN
    expect(results[1].verdict).toBe('EXPENSE');   // 正常値 → そのまま
  });

  it('content が空の場合（text ブロックなし）は UNCERTAIN フォールバックを返すこと', async () => {
    const mockCreate = vi.fn().mockResolvedValue({
      ...makeAnthropicResponse(''),
      content: [], // 空コンテンツ
    });
    vi.mocked(Anthropic).mockImplementation(function() {
      return { messages: { create: mockCreate } } as unknown as Anthropic;
    });

    const results = await runPracticeAgent(mockLineItems, mockTrainingRecords);

    expect(results).toHaveLength(2);
    for (const r of results) {
      expect(r.verdict).toBe('UNCERTAIN');
    }
  });
});
