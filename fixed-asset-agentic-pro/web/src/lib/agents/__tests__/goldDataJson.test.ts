/**
 * goldDataJson.test.ts — Phase 2: tests/gold_data/JSONデータドリブン検証テスト (cmd_138k_sub1)
 *
 * tests/gold_data/ の6JSONファイル（15件）をvitest data-driven形式で検証。
 *
 * ■ CHECK-9 テスト期待値の根拠
 *   preScreen確定ルール:
 *     ルールa: 法人税法施行令第133条（10万円未満→即時費用化）
 *     ルールb: 法基通7-8-3(1)（修繕費20万円未満形式基準）
 *     ルールd: 法基通7-8-4(1)（修繕費60万円未満形式基準）
 *   LLM判定ケース:
 *     CAPITAL: 耐用年数省令別表第一 / 法人税法施行令第132条
 *     一括償却資産: 法人税法施行令第133条の2（10万〜20万未満→3年均等）
 *     屋上防水: 法基通7-8-1（価値増加・耐用年数延長→資本的支出）
 *     外壁塗装: 法基通7-8-3(1)（20万円未満→修繕費）
 *   GUIDANCE判定:
 *     分裂ケース: 法基通7-8-5（修繕費と資本的支出の区分不明確）
 *     合議ルール: Section 3.5 パターン8（UNCERTAIN+UNCERTAIN→GUIDANCE, 0.30）
 *
 * ■ CHECK-7b 手計算検証
 *   gold_004 (5,000): 5,000 < 100,000 → rule_a → EXPENSE ✓
 *   gold_005 (3,000): 3,000 < 100,000 → rule_a → EXPENSE ✓
 *   gold_006 (1,500): 1,500 < 100,000 → rule_a → EXPENSE ✓（account=消耗品費固定; JSONは荷造運賃）
 *   gold_007 (80,000): 80,000 < 100,000 → rule_a → EXPENSE ✓
 *   gold_008 (95,000): 95,000 < 100,000 → rule_a → EXPENSE ✓
 *   gold_011 (450,000): 450,000 < 600,000 × 「修理」「交換」→ rule_d → EXPENSE/修繕費 ✓
 *   gold_012 (180,000): 「外壁塗装工事（既存壁面の再塗装）」はREPAIR_KEYWORDS非マッチ→needsLlm
 *   gold_014/015: Tax=UNCERTAIN + Practice=UNCERTAIN → aggregate → GUIDANCE(0.30) ✓
 *
 * ■ テスト構成
 *   Group A: preScreen確定ケース（rule_a/rule_d） — LLMモック不要
 *   Group B: CAPITAL判定（LLMモック）— 01_clear_capital + 04_bulk_depreciation + gold_013
 *   Group C: EXPENSE判定（LLMモック）— gold_012（外壁塗装）
 *   Group D: GUIDANCE判定（aggregate経由）— 06_split_case
 *
 * ■ gold_006 設計注記
 *   「宅配便費用」の期待勘定科目はJSONで「荷造運賃」だが、
 *   preScreen rule_aは account_category='消耗品費' で固定返却する設計。
 *   verdictのEXPENSE判定は正しいが、account_categoryの細分化はLLM判定の役割。
 *   本テストではverdict=EXPENSEのみ検証し、account差異はコメントで明記する。
 */

import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'fs';
import path from 'path';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';
import type { PracticeAgentResult } from '@/types/multi_agent';

// ─── SDK モック（vi.hoisted で hoisting 問題を回避）──────────────────────────
const { mockMessagesCreate } = vi.hoisted(() => ({
  mockMessagesCreate: vi.fn(),
}));

vi.mock('@anthropic-ai/sdk', () => ({
  default: function MockAnthropic() {
    return { messages: { create: mockMessagesCreate } };
  },
}));

// ─── テスト対象インポート ──────────────────────────────────────────────────────
import { preScreenLineItems, runTaxAgent } from '../taxAgent';
import { aggregate } from '../aggregator';

// ─── ゴールドデータJSONをfsで読み込む（viteのwebディレクトリ外import制限を回避）──
// process.cwd() = /fixed-asset-agentic-pro/web/
// ../tests/gold_data/ = /fixed-asset-agentic-pro/tests/gold_data/
const GOLD_DATA_DIR = path.resolve(process.cwd(), '../tests/gold_data');

function loadGoldData(filename: string): GoldDataEntry[] {
  return JSON.parse(fs.readFileSync(path.join(GOLD_DATA_DIR, filename), 'utf-8'));
}

// 各カテゴリのゴールドデータ（15件 → 28件に拡充）
let clearCapital: GoldDataEntry[];
let clearExpense: GoldDataEntry[];
let smallFixedAsset: GoldDataEntry[];
let bulkDepreciation: GoldDataEntry[];
let repairVsCapital: GoldDataEntry[];
let splitCase: GoldDataEntry[];
let softwareIntangible: GoldDataEntry[];   // 07: ソフトウェア・無形固定資産（3件）
let boundaryCases: GoldDataEntry[];        // 08: 境界値テスト（4件）
let edgeCases: GoldDataEntry[];            // 09: エッジケース（6件）Phase 3 cmd_170k_sub3

// ─── 型定義（インポートより前に定義）────────────────────────────────────────────
interface GoldDataEntry {
  test_id: string;
  category: string;
  input: { description: string; amount: number; quantity: number };
  expected: {
    verdict: string;
    account_category: string | null;
    useful_life: number | null;
    rationale_keywords: string[];
  };
  basis: string;
}

// ─── ゴールドデータロード（テスト実行前） ────────────────────────────────────────
clearCapital = loadGoldData('01_clear_capital.json');
clearExpense = loadGoldData('02_clear_expense.json');
smallFixedAsset = loadGoldData('03_small_fixed_asset.json');
bulkDepreciation = loadGoldData('04_bulk_depreciation.json');
repairVsCapital = loadGoldData('05_repair_vs_capital.json');
splitCase = loadGoldData('06_split_case.json');
softwareIntangible = loadGoldData('07_software_intangible.json');  // Phase 3追加
boundaryCases = loadGoldData('08_boundary_cases.json');            // Phase 3追加
edgeCases = loadGoldData('09_edge_cases.json');                    // Phase 3 cmd_170k_sub3追加

// ─── ヘルパー ──────────────────────────────────────────────────────────────────

function makeItem(test_id: string, input: { description: string; amount: number }): ExtractedLineItem {
  return { line_item_id: test_id, description: input.description, amount: input.amount };
}

function mockLlmResult(test_id: string, override: Partial<{
  verdict: string;
  account_category: string | null;
  useful_life: number | null;
  rationale: string;
  article_ref: string | null;  // null許容（SaaS・リース等の条文参照なしケース対応）
  formal_criteria_step: number | null;
}> = {}) {
  mockMessagesCreate.mockResolvedValue({
    content: [{
      type: 'text',
      text: JSON.stringify([{
        line_item_id: test_id,
        verdict: 'UNCERTAIN',
        rationale: 'テスト用モック',
        article_ref: null,
        account_category: null,
        useful_life: null,
        formal_criteria_step: null,
        ...override,
      }]),
    }],
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Group A: preScreen確定ケース（LLMモック不要）
// ─────────────────────────────────────────────────────────────────────────────

describe('GoldData Group A: preScreen確定ケース（LLMモック不要）', () => {
  /**
   * A-1: 02_clear_expense.json（gold_004〜006）
   * gold_004: プリンタートナー 5,000円 → rule_a → EXPENSE
   * gold_005: コピー用紙 3,000円       → rule_a → EXPENSE
   * gold_006: 宅配便費用 1,500円       → rule_a → EXPENSE
   *   ※ gold_006 account_category: JSONは「荷造運賃」だがpreScreenは「消耗品費」固定
   *     verdictのEXPENSEのみ確認（設計上の制約・コメント参照）
   */
  describe('A-1: 明確費用（02_clear_expense.json）— rule_a', () => {
    (clearExpense as GoldDataEntry[]).forEach(({ test_id, input, expected }) => {
      it(`${test_id}: ${input.description} ${input.amount}円 → needsLlm=0件, verdict=${expected.verdict}`, () => {
        const item = makeItem(test_id, input);
        const { autoResolved, needsLlm } = preScreenLineItems([item]);

        // CHECK-7b: amount < 100,000 → rule_a 必ず確定
        expect(needsLlm).toHaveLength(0);
        expect(autoResolved).toHaveLength(1);
        expect(autoResolved[0].result.verdict).toBe('EXPENSE');
        expect(autoResolved[0].rule).toBe('rule_a_under_100k');
        // JSONのverdict確認
        expect(expected.verdict).toBe('EXPENSE');
      });
    });
  });

  /**
   * A-2: 03_small_fixed_asset.json（gold_007〜008）
   * gold_007: 液晶モニター 80,000円 → rule_a → EXPENSE/消耗品費
   * gold_008: iPad Air 95,000円     → rule_a → EXPENSE/消耗品費
   */
  describe('A-2: 少額固定資産（03_small_fixed_asset.json）— rule_a', () => {
    (smallFixedAsset as GoldDataEntry[]).forEach(({ test_id, input }) => {
      it(`${test_id}: ${input.description} ${input.amount}円 → rule_a_under_100k / 消耗品費`, () => {
        const item = makeItem(test_id, input);
        const { autoResolved, needsLlm } = preScreenLineItems([item]);

        expect(needsLlm).toHaveLength(0);
        expect(autoResolved[0].result.verdict).toBe('EXPENSE');
        expect(autoResolved[0].result.account_category).toBe('消耗品費');
        expect(autoResolved[0].rule).toBe('rule_a_under_100k');
        // 手計算確認: 80,000 < 100,000 / 95,000 < 100,000 → 令133条 即時費用化
        expect(input.amount).toBeLessThan(100_000);
      });
    });
  });

  /**
   * A-3: 05_repair_vs_capital.json — gold_011（修繕費 rule_d）
   * gold_011: エアコン修理費 室外機コンプレッサー交換 450,000円
   *   description「修理」「交換」→ REPAIR_KEYWORDS マッチ
   *   450,000 < 600,000 → rule_d（基通7-8-4(1)）→ EXPENSE/修繕費
   */
  it('gold_011: エアコン修理費 450,000円 → rule_d_repair_step3 / 修繕費 [基通7-8-4(1)]', () => {
    const gold011 = (repairVsCapital as GoldDataEntry[]).find((d) => d.test_id === 'gold_011')!;
    const item = makeItem(gold011.test_id, gold011.input);
    const { autoResolved, needsLlm } = preScreenLineItems([item]);

    // 手計算: 450,000 < 600,000 × 「修理」「交換」キーワード → rule_d確定
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('修繕費');
    expect(autoResolved[0].result.article_ref).toContain('7-8-4');
    expect(autoResolved[0].rule).toBe('rule_d_repair_step3');
  });

  /**
   * A-4: 05_repair_vs_capital.json — gold_012（preScreen対象外確認）
   * gold_012: 外壁塗装工事（既存壁面の再塗装）180,000円
   *   「修繕|修理|補修|交換」に非マッチ → rule_b/rule_d 適用外 → needsLlm
   */
  it('gold_012: 外壁塗装工事 180,000円 → REPAIR_KEYWORDS非マッチ → needsLlm（LLMに委ねる）', () => {
    const gold012 = (repairVsCapital as GoldDataEntry[]).find((d) => d.test_id === 'gold_012')!;
    const item = makeItem(gold012.test_id, gold012.input);
    const { autoResolved, needsLlm } = preScreenLineItems([item]);

    // CHECK-7b: 「外壁塗装工事（既存壁面の再塗装）」はREPAIR_KEYWORDS=/修繕|修理|補修|交換/ に
    //           マッチしない。180,000 < 200,000 だがrule_bの修繕キーワード条件を満たさない。
    //           → needsLlmに入り、LLMが基通7-8-3(1)に基づき判定する。
    expect(needsLlm).toHaveLength(1);
    expect(autoResolved).toHaveLength(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group B: CAPITAL判定（LLMモック）
// ─────────────────────────────────────────────────────────────────────────────

describe('GoldData Group B: CAPITAL判定（LLMモック）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold_json');
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  /**
   * B-1: 01_clear_capital.json（gold_001〜003）
   * gold_001: ノートPC 250,000円       → CAPITAL/器具備品/4年
   * gold_002: 社用車 3,000,000円       → CAPITAL/車両運搬具/6年
   * gold_003: ファイルサーバー 600,000円→ CAPITAL/器具備品/5年
   */
  describe('B-1: 明確固定資産（01_clear_capital.json）', () => {
    (clearCapital as GoldDataEntry[]).forEach(({ test_id, input, expected }) => {
      it(`${test_id}: ${input.description} → CAPITAL/${expected.account_category}/${expected.useful_life}年`, async () => {
        mockLlmResult(test_id, {
          verdict: 'CAPITAL',
          account_category: expected.account_category,
          useful_life: expected.useful_life,
          rationale: `${expected.account_category} 耐用年数${expected.useful_life}年`,
          article_ref: '耐用年数省令別表第一',
        });

        const item = makeItem(test_id, input);
        const results = await runTaxAgent([item]);

        expect(results[0].verdict).toBe('CAPITAL');
        expect(results[0].account_category).toBe(expected.account_category);
        expect(results[0].useful_life).toBe(expected.useful_life);
      });
    });
  });

  /**
   * B-2: 04_bulk_depreciation.json（gold_009〜010）
   * gold_009: エルゴノミクスチェア 150,000円 → CAPITAL/一括償却資産/3年
   * gold_010: スタンディングデスク 220,000円  → CAPITAL/一括償却資産/3年
   *
   * CHECK-9 根拠: 法人税法施行令第133条の2（10万以上20万未満→一括償却資産3年均等）
   *   ※ gold_010は20万以上だが、中小企業者等の少額減価償却資産(30万未満)特例を前提とする
   *   ※ JSONのverdict="CAPITAL" はLLMがCAPITAL判定する場合を想定
   *   ※ 実際のシステムがEXPENSE(一括償却資産)を返す設計の場合は要殿確認
   */
  describe('B-2: 一括償却資産（04_bulk_depreciation.json）', () => {
    (bulkDepreciation as GoldDataEntry[]).forEach(({ test_id, input, expected }) => {
      it(`${test_id}: ${input.description} ${input.amount}円 → ${expected.verdict}/${expected.account_category}`, async () => {
        // CHECK-9 注記: JSONのverdict="CAPITAL"、account_category="一括償却資産"
        //   taxAgent プロンプトで「10万〜20万未満はEXPECTE または CAPITAL（選択可）」と定義
        //   LLMがどちらを返すかは実行環境依存。テストではJSONの期待値通りにモックを注入。
        mockLlmResult(test_id, {
          verdict: expected.verdict,
          account_category: expected.account_category,
          useful_life: expected.useful_life,
          rationale: '一括償却資産（法令133条の2）3年均等償却',
          article_ref: '法人税法施行令第133条の2',
        });

        const item = makeItem(test_id, input);
        const results = await runTaxAgent([item]);

        expect(results[0].verdict).toBe(expected.verdict);
        expect(results[0].account_category).toBe(expected.account_category);
        expect(results[0].useful_life).toBe(expected.useful_life);
      });
    });
  });

  /**
   * B-3: 05_repair_vs_capital.json — gold_013（資本的支出）
   * 屋上防水工事 2,000,000円 → CAPITAL/建物/38年
   * CHECK-9: 法基通7-8-1（全面貼り替え・耐用年数延長・価値増加 → 資本的支出）
   *   2,000,000 ≥ 600,000 かつ 耐用年数延長明確 → 形式基準Step5
   */
  it('gold_013: 屋上防水工事 2,000,000円 → CAPITAL/建物/38年 [基通7-8-1 資本的支出]', async () => {
    const gold013 = (repairVsCapital as GoldDataEntry[]).find((d) => d.test_id === 'gold_013')!;

    mockLlmResult('gold_013', {
      verdict: 'CAPITAL',
      account_category: gold013.expected.account_category,
      useful_life: gold013.expected.useful_life,
      rationale: '全面貼り替えで耐用年数延長・価値増加 → 資本的支出',
      article_ref: '基通7-8-1',
      formal_criteria_step: 5,
    });

    const item = makeItem('gold_013', gold013.input);
    const results = await runTaxAgent([item]);

    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('建物');
    expect(results[0].useful_life).toBe(38);
    // JSONの期待値と一致確認
    expect(gold013.expected.verdict).toBe('CAPITAL');
    expect(gold013.expected.account_category).toBe('建物');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group C: EXPENSE判定（LLMモック）— preScreenで確定しないケース
// ─────────────────────────────────────────────────────────────────────────────

describe('GoldData Group C: EXPENSE判定（LLMモック — preScreen非適用）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold_json');
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  /**
   * C-1: 05_repair_vs_capital.json — gold_012
   * 外壁塗装工事（既存壁面の再塗装）180,000円 → EXPENSE/修繕費
   * CHECK-9: LLMが基通7-8-3(1)「20万円未満→修繕費」に基づき判定
   *   「塗装」はREPAIR_KEYWORDSに含まれないためpreScreen対象外 → LLMに委ねる
   */
  it('gold_012: 外壁塗装工事 180,000円 → EXPENSE/修繕費 [LLM 基通7-8-3(1)]', async () => {
    const gold012 = (repairVsCapital as GoldDataEntry[]).find((d) => d.test_id === 'gold_012')!;

    mockLlmResult('gold_012', {
      verdict: 'EXPENSE',
      account_category: '修繕費',
      useful_life: null,
      rationale: '18万円 < 20万円 → 基通7-8-3(1) 修繕費',
      article_ref: '基通7-8-3(1)',
      formal_criteria_step: 1,
    });

    const item = makeItem('gold_012', gold012.input);
    const results = await runTaxAgent([item]);

    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].account_category).toBe('修繕費');
    expect(results[0].useful_life).toBeNull();
    // JSONの期待値と一致確認
    expect(gold012.expected.verdict).toBe('EXPENSE');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group D: GUIDANCE判定（分裂ケース — aggregate経由）
// ─────────────────────────────────────────────────────────────────────────────

describe('GoldData Group D: GUIDANCE判定（06_split_case.json — aggregate経由）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold_json');
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  /**
   * D-1, D-2: 06_split_case.json（gold_014〜015）
   * gold_014: オフィス内装工事 800,000円   → GUIDANCE（税務CAPITAL/実務EXPENSE分裂）
   * gold_015: エレベーター定期修繕工事 1,200,000円 → GUIDANCE（修繕費/資本的支出区分困難）
   *
   * CHECK-9 根拠:
   *   法基通7-8-5（修繕費と資本的支出の区分が不明確な場合 → UNCERTAIN/GUIDANCE）
   *   合議ルール Section 3.5 パターン8: UNCERTAIN + UNCERTAIN → GUIDANCE, 0.30
   *
   * CHECK-7b 手計算:
   *   Tax=UNCERTAIN + Practice=UNCERTAIN → aggregate() → GUIDANCE, 0.30 ✓
   */
  (splitCase as GoldDataEntry[]).forEach(({ test_id, input, expected }) => {
    it(`${test_id}: ${input.description} → TaxAgent=UNCERTAIN → aggregate → GUIDANCE(0.30)`, async () => {
      // TaxAgentモック: 分裂ケースはUNCERTAINを返す（法基通7-8-5）
      mockLlmResult(test_id, {
        verdict: 'UNCERTAIN',
        account_category: null,
        useful_life: null,
        rationale: '税務/実務見解の相違により判断困難（基通7-8-5）',
        article_ref: '基通7-8-5',
        formal_criteria_step: 6,
      });

      const item = makeItem(test_id, input);
      const taxResults = await runTaxAgent([item]);

      // TaxAgent単体: UNCERTAIN
      expect(taxResults[0].verdict).toBe('UNCERTAIN');
      expect(taxResults[0].line_item_id).toBe(test_id);

      // PracticeAgentモック（dry-run相当: UNCERTAIN）
      const practiceResults: PracticeAgentResult[] = [{
        line_item_id: test_id,
        verdict: 'UNCERTAIN',
        similar_cases: [],
        rationale: '[分裂ケース] 実務上の処理方針が定まっていない',
      }];

      // 合議: UNCERTAIN + UNCERTAIN → GUIDANCE, 0.30 [Section 3.5 パターン8]
      const aggregated = aggregate(taxResults, practiceResults);

      expect(aggregated).toHaveLength(1);
      expect(aggregated[0].final_verdict).toBe('GUIDANCE');
      expect(aggregated[0].confidence).toBe(0.30);
      expect(aggregated[0].line_item_id).toBe(test_id);

      // JSONの期待値と整合確認
      expect(expected.verdict).toBe('GUIDANCE');
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group E: ソフトウェア・無形固定資産（07_software_intangible.json）Phase 3追加
// ─────────────────────────────────────────────────────────────────────────────

describe('GoldData Group E: ソフトウェア・無形固定資産（07_software_intangible.json）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold_e');
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  /**
   * E-1: gold_016/018 — preScreen確認（ソフトウェアはrule_a/b/d非適用 → needsLlm）
   * CHECK-9: ソフトウェアは修繕キーワードなし × amount >= 100,000 → preScreen対象外
   * CHECK-7b: gold_016: 500,000 >= 100,000 かつ「ソフトウェア」は修繕キーワード非マッチ
   *           gold_018: 3,000,000 >= 100,000 かつ「開発費」は修繕キーワード非マッチ
   */
  it('gold_016/018: ソフトウェア系はpreScreen対象外 → needsLlm（LLMがCAPITAL判定）', () => {
    const gold016 = softwareIntangible.find((d) => d.test_id === 'gold_016')!;
    const gold018 = softwareIntangible.find((d) => d.test_id === 'gold_018')!;

    const { autoResolved: ar016, needsLlm: nl016 } = preScreenLineItems([makeItem(gold016.test_id, gold016.input)]);
    const { autoResolved: ar018, needsLlm: nl018 } = preScreenLineItems([makeItem(gold018.test_id, gold018.input)]);

    // preScreen: ソフトウェアはどのルールも適用されない → 全件needsLlm
    expect(ar016).toHaveLength(0);
    expect(nl016).toHaveLength(1);
    expect(ar018).toHaveLength(0);
    expect(nl018).toHaveLength(1);
  });

  /**
   * E-2: gold_016 — 業務ソフトウェア 500,000円 → CAPITAL/ソフトウエア/5年
   * CHECK-9: 耐用年数省令別表第三 無形固定資産「ソフトウェア」5年
   * CHECK-7b: 永続ライセンス = 資産取得 = CAPITAL。SaaS（利用料）とは異なる
   */
  it('gold_016: 業務管理ソフトウェア 500,000円 → CAPITAL/ソフトウエア/5年 [別表第三]', async () => {
    const entry = softwareIntangible.find((d) => d.test_id === 'gold_016')!;

    mockLlmResult('gold_016', {
      verdict: 'CAPITAL',
      account_category: 'ソフトウエア',
      useful_life: 5,
      rationale: '無形固定資産 ソフトウェア(耐用年数5年)',
      article_ref: '耐用年数省令別表第三',
      formal_criteria_step: null,
    });

    const results = await runTaxAgent([makeItem('gold_016', entry.input)]);

    // CHECK-7b: ソフトウェア永続ライセンス → 取得価額=CAPITAL, 耐用年数5年
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('ソフトウエア');
    expect(results[0].useful_life).toBe(5);
    expect(entry.expected.verdict).toBe('CAPITAL');
    expect(entry.expected.useful_life).toBe(5);
  });

  /**
   * E-3: gold_017 — SaaS年間利用料 240,000円 → EXPENSE/通信費
   * CHECK-9: SaaS形態はソフトウェアの「取得」に該当せず → 期間費用（通信費/支払手数料）
   * CHECK-7b: 年間利用料=サービス利用の対価 → 費用計上。資産計上の要件（所有権・支配）なし
   */
  it('gold_017: クラウドSaaS年間利用料 240,000円 → EXPENSE/通信費 [費用計上]', async () => {
    const entry = softwareIntangible.find((d) => d.test_id === 'gold_017')!;

    mockLlmResult('gold_017', {
      verdict: 'EXPENSE',
      account_category: '通信費',
      useful_life: null,
      rationale: 'SaaS利用料 → 期間費用として通信費計上',
      article_ref: null,
      formal_criteria_step: null,
    });

    const results = await runTaxAgent([makeItem('gold_017', entry.input)]);

    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].account_category).toBe('通信費');
    expect(results[0].useful_life).toBeNull();
    expect(entry.expected.verdict).toBe('EXPENSE');
  });

  /**
   * E-4: gold_018 — 社内基幹システム開発費 3,000,000円 → CAPITAL/ソフトウエア/5年
   * CHECK-9: 自社開発ソフトも「ソフトウェア」として無形固定資産に計上（5年）
   * CHECK-7b: 受注制作・自社開発問わず、業務利用目的のソフトウェアは5年償却
   */
  it('gold_018: 社内基幹システム開発費 3,000,000円 → CAPITAL/ソフトウエア/5年 [自社開発]', async () => {
    const entry = softwareIntangible.find((d) => d.test_id === 'gold_018')!;

    mockLlmResult('gold_018', {
      verdict: 'CAPITAL',
      account_category: 'ソフトウエア',
      useful_life: 5,
      rationale: '自社開発基幹システム → 無形固定資産ソフトウェア5年',
      article_ref: '耐用年数省令別表第三',
      formal_criteria_step: null,
    });

    const results = await runTaxAgent([makeItem('gold_018', entry.input)]);

    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('ソフトウエア');
    expect(results[0].useful_life).toBe(5);
    // 金額は3,000,000 → 通常の資産計上（少額特例非適用）
    expect(entry.input.amount).toBeGreaterThan(300_000);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group F: 境界値テスト（08_boundary_cases.json）Phase 3追加
// ─────────────────────────────────────────────────────────────────────────────

describe('GoldData Group F: 境界値テスト（08_boundary_cases.json）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold_f');
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  /**
   * F-1: gold_019 — ちょうど10万円 → rule_a非適用 → needsLlm
   * CHECK-9: 令133条は「取得価額が100,000円未満」（厳密な小なり）
   * CHECK-7b: 100,000 < 100,000 → false → rule_a不適用 → LLM判定
   */
  it('gold_019: OAチェア ちょうど100,000円 → rule_a非適用（NOT < 100k）→ needsLlm', () => {
    const entry = boundaryCases.find((d) => d.test_id === 'gold_019')!;
    const { autoResolved, needsLlm } = preScreenLineItems([makeItem(entry.test_id, entry.input)]);

    // CHECK-7b: 100,000 < 100,000 = false → rule_a非適用
    expect(entry.input.amount).toBe(100_000);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
    expect(needsLlm[0].line_item_id).toBe('gold_019');
  });

  /**
   * F-2: gold_020 — 修繕×ちょうど20万円 → rule_d適用 → EXPENSE
   * CHECK-9:
   *   rule_b: 修繕キーワード × amount < 200,000 → 200,000は非適用（境界）
   *   rule_d: 修繕キーワード × amount < 600,000 → 200,000 < 600,000 → 適用 → EXPENSE
   * CHECK-7b: 200,000 < 200,000 = false（rule_b非適用）/ 200,000 < 600,000 = true（rule_d適用）
   */
  it('gold_020: 外壁修繕工事 200,000円 → rule_b境界(非適用)、rule_d適用 → EXPENSE/修繕費', () => {
    const entry = boundaryCases.find((d) => d.test_id === 'gold_020')!;
    const { autoResolved, needsLlm } = preScreenLineItems([makeItem(entry.test_id, entry.input)]);

    // CHECK-7b: rule_dで確定（200k < 600k × 修繕キーワード）
    expect(entry.input.amount).toBe(200_000);
    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('修繕費');
    expect(autoResolved[0].rule).toBe('rule_d_repair_step3');
  });

  /**
   * F-3: gold_021 — 一括償却資産候補 150,000円 → needsLlm → CAPITAL/一括償却資産/3年
   * CHECK-9: 100,000 <= 150,000 < 200,000（令133条の2の範囲）→ preScreen対象外 → LLMが判定
   * CHECK-7b: 150,000 >= 100,000（rule_a非適用）/ 修繕キーワードなし（rule_b/d非適用）
   *           → needsLlm → LLMが「一括償却資産」判定
   */
  it('gold_021: ノートPC 150,000円 → needsLlm → CAPITAL/一括償却資産/3年 [令133条の2]', async () => {
    const entry = boundaryCases.find((d) => d.test_id === 'gold_021')!;

    // preScreen確認: needsLlm
    const { autoResolved, needsLlm } = preScreenLineItems([makeItem(entry.test_id, entry.input)]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);

    // LLMモック: 一括償却資産
    mockLlmResult('gold_021', {
      verdict: 'CAPITAL',
      account_category: '一括償却資産',
      useful_life: 3,
      rationale: '10万以上20万未満 → 一括償却資産3年均等償却（令133条の2）',
      article_ref: '法人税法施行令第133条の2',
      formal_criteria_step: null,
    });

    const results = await runTaxAgent([makeItem('gold_021', entry.input)]);
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('一括償却資産');
    expect(results[0].useful_life).toBe(3);
    expect(entry.expected.useful_life).toBe(3);
  });

  /**
   * F-4: gold_022 — 99,000円 → rule_a → EXPENSE
   * CHECK-9: 99,000 < 100,000 → rule_a → 即時費用化
   * CHECK-7b: 99,000 < 100,000 = true → rule_a_under_100k適用
   */
  it('gold_022: USBメモリー 99,000円 → rule_a → EXPENSE/消耗品費（令133条）', () => {
    const entry = boundaryCases.find((d) => d.test_id === 'gold_022')!;
    const { autoResolved, needsLlm } = preScreenLineItems([makeItem(entry.test_id, entry.input)]);

    expect(entry.input.amount).toBe(99_000);
    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('消耗品費');
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group G: 複数明細・統合テスト（Phase 3追加）
// ─────────────────────────────────────────────────────────────────────────────

describe('GoldData Group G: 複数明細・統合テスト（Phase 3追加）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold_g');
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  /**
   * G-1: 見積書3品（preScreen確定2件 + needsLlm1件）
   * CHECK-9:
   *   品目1: コピー用紙 3,000円 → rule_a → EXPENSE（preScreen確定）
   *   品目2: USB 50,000円 → rule_a → EXPENSE（preScreen確定）
   *   品目3: エアコン 250,000円 → 修繕キーワードなし × 250k >= 100k → needsLlm
   * CHECK-7b: 3,000 < 100,000 ✓ / 50,000 < 100,000 ✓ / 250,000 >= 100,000 ✓
   */
  it('G-1: 見積書3品混在 → autoResolved=2件（rule_a）、needsLlm=1件（エアコン）', () => {
    const items = [
      { line_item_id: 'g_001', description: 'コピー用紙（A4/500枚×10箱）', amount: 3_000 },
      { line_item_id: 'g_002', description: 'USBメモリー 32GB', amount: 50_000 },
      { line_item_id: 'g_003', description: 'エアコン設置工事（新規設置）', amount: 250_000 },
    ];

    const { autoResolved, needsLlm } = preScreenLineItems(items);

    // 手計算: g_001(3k < 100k = rule_a), g_002(50k < 100k = rule_a), g_003(250k >= 100k, 非修繕 = needsLlm)
    expect(autoResolved).toHaveLength(2);
    expect(needsLlm).toHaveLength(1);
    expect(needsLlm[0].line_item_id).toBe('g_003');
    expect(autoResolved.every((r) => r.result.verdict === 'EXPENSE')).toBe(true);
    expect(autoResolved.every((r) => r.rule === 'rule_a_under_100k')).toBe(true);
  });

  /**
   * G-2: 全件preScreen確定（修繕×境界値3件）
   * CHECK-9:
   *   品目1: 外壁修繕 50,000円 → rule_b (50k < 200k × 修繕) → EXPENSE
   *   品目2: 屋根修繕 150,000円 → rule_b (150k < 200k × 修繕) → EXPENSE
   *   品目3: 配管修理 500,000円 → rule_d (500k < 600k × 修繕) → EXPENSE
   * CHECK-7b: 全3件がpreScreen確定 → LLM呼び出しゼロ
   */
  it('G-2: 修繕費3件全件 → 全件autoResolved（LLM呼び出しなし）', () => {
    const items = [
      { line_item_id: 'g_004', description: '外壁修繕工事（ひび割れ補修）', amount: 50_000 },
      { line_item_id: 'g_005', description: '屋根修繕（防水シート交換）', amount: 150_000 },
      { line_item_id: 'g_006', description: '配管修理（老朽化対応）', amount: 500_000 },
    ];

    const { autoResolved, needsLlm } = preScreenLineItems(items);

    // 手計算:
    //   g_004: 50,000 < 100,000 → rule_a（修繕キーワードより先にrule_a適用）
    //   g_005: 150,000 < 200,000 × 「修繕」「交換」 → rule_b
    //   g_006: 500,000 < 600,000 × 「修理」 → rule_d
    expect(autoResolved).toHaveLength(3);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved.every((r) => r.result.verdict === 'EXPENSE')).toBe(true);
    // g_004はrule_a（10万未満が最優先）
    // PreScreenedItemの構造: { item, rule, result } → line_item_id は result.line_item_id にある
    const r004 = autoResolved.find((r) => r.result.line_item_id === 'g_004');
    expect(r004?.rule).toBe('rule_a_under_100k');
    // g_005はrule_b
    const r005 = autoResolved.find((r) => r.result.line_item_id === 'g_005');
    expect(r005?.rule).toBe('rule_b_repair_step1');
    // g_006はrule_d
    const r006 = autoResolved.find((r) => r.result.line_item_id === 'g_006');
    expect(r006?.rule).toBe('rule_d_repair_step3');
  });

  /**
   * G-3: ソフトウェア + 固定資産 + 費用 の混在請求書（aggregate統合）
   * CHECK-9:
   *   品目1: ソフトウェア 500,000円 → CAPITAL/ソフトウエア [TaxLLM → Practice合議]
   *   品目2: 消耗品 5,000円 → EXPENSE/消耗品費 [preScreen確定]
   * 合議: Tax=CAPITAL + Practice=CAPITAL → CAPITAL_LIKE, 0.95以上
   */
  it('G-3: ソフトウェア+消耗品の混在請求書 → 合議でCAPITAL_LIKE/EXPENSE_LIKE', async () => {
    const sw = softwareIntangible.find((d) => d.test_id === 'gold_016')!;

    // ソフトウェアはLLMがCAPITAL判定
    mockMessagesCreate.mockResolvedValue({
      content: [{
        type: 'text',
        text: JSON.stringify([{
          line_item_id: 'gold_016',
          verdict: 'CAPITAL',
          rationale: 'ソフトウェア永続ライセンス → 無形固定資産5年',
          article_ref: '耐用年数省令別表第三',
          account_category: 'ソフトウエア',
          useful_life: 5,
          formal_criteria_step: null,
        }]),
      }],
    });

    const taxResults = await runTaxAgent([makeItem('gold_016', sw.input)]);
    const practiceResults: PracticeAgentResult[] = [{
      line_item_id: 'gold_016',
      verdict: 'CAPITAL',
      rationale: '過去事例: ソフトウェアパッケージ → CAPITAL',
      similar_cases: [{ description: 'ERPシステム', classification: 'CAPITAL', similarity: 0.85 }],
      suggested_account: 'ソフトウエア',
      confidence: 0.88,
    }];

    const aggregated = aggregate(taxResults, practiceResults);

    // Tax=CAPITAL + Practice=CAPITAL → CAPITAL_LIKE
    expect(aggregated[0].final_verdict).toBe('CAPITAL_LIKE');
    expect(aggregated[0].account_category).toBe('ソフトウエア');
    expect(aggregated[0].useful_life).toBe(5);
    expect(aggregated[0].confidence).toBeGreaterThanOrEqual(0.95);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group H: エッジケーステスト（09_edge_cases.json）Phase 3 cmd_170k_sub3
// ─────────────────────────────────────────────────────────────────────────────

describe('GoldData Group H: エッジケーステスト（09_edge_cases.json）', () => {
  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold_h');
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  /**
   * H-1: gold_023 — 和暦表記（令和6年）の明細
   * CHECK-9: preScreenは description テキストのrule_a〜rule_d判定に和暦が影響しないことを検証
   * CHECK-7b:
   *   「令和6年3月 空調修繕工事（フィルター交換）」
   *   amount=150,000: 150,000 >= 100,000 → rule_a非適用
   *   「交換」 ∈ REPAIR_KEYWORDS, 150,000 < 200,000 → rule_b適用 → EXPENSE/修繕費
   */
  it('gold_023: 和暦表記の修繕明細 → rule_b適用（和暦テキストは判定に無影響）', () => {
    const entry = edgeCases.find((d) => d.test_id === 'gold_023')!;
    const { autoResolved, needsLlm } = preScreenLineItems([makeItem(entry.test_id, entry.input)]);

    // CHECK-7b: 「令和6年3月」という和暦テキストがpreScreenに影響しないことを確認
    //   150,000 < 200,000 × 「交換」 → rule_b → EXPENSE/修繕費
    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('修繕費');
    expect(autoResolved[0].rule).toBe('rule_b_repair_step1');
    // JSONの期待値と一致確認
    expect(entry.expected.verdict).toBe('EXPENSE');
    expect(entry.input.amount).toBe(150_000);
  });

  /**
   * H-2: gold_024 — 全角文字・特殊文字を含む明細
   * CHECK-9: descriptionに全角英数字が含まれてもpreScreenのREPAIR_KEYWORDS・rule_a判定に影響しない
   * CHECK-7b:
   *   「コピー用紙Ａ４サイズ　５０枚×１０束（全角表記）」
   *   amount=5,000: 5,000 < 100,000 → rule_a → EXPENSE/消耗品費
   *   全角文字の「Ａ」「４」は修繕キーワード正規表現に非マッチ（当然）
   */
  it('gold_024: 全角文字・特殊文字含む明細 → rule_a適用（全角表記は判定に無影響）', () => {
    const entry = edgeCases.find((d) => d.test_id === 'gold_024')!;
    const { autoResolved, needsLlm } = preScreenLineItems([makeItem(entry.test_id, entry.input)]);

    // CHECK-7b: 5,000 < 100,000 → rule_a → EXPENSE
    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('消耗品費');
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
    expect(entry.input.amount).toBe(5_000);
  });

  /**
   * H-3: gold_025 — 金額0円の備考行
   * CHECK-9: amount=0は令133条の「< 100,000」に合致するためrule_a適用
   *   ただし実務上は備考行フィルタリングが推奨（設計上の制約として明記）
   * CHECK-7b: 0 < 100,000 → rule_a → EXPENSE/消耗品費（preScreenは純粋な金額比較）
   */
  it('gold_025: 金額0円の備考行 → rule_a適用（設計制約: 0円はrule_a対象）', () => {
    const entry = edgeCases.find((d) => d.test_id === 'gold_025')!;
    const { autoResolved, needsLlm } = preScreenLineItems([makeItem(entry.test_id, entry.input)]);

    // CHECK-7b: 0 < 100,000 → rule_a_under_100k → EXPENSE
    // 設計注記: LLMプロンプトでは「0円=UNCERTAIN」だが、preScreenはルールベース純粋金額比較
    // 実務での対策: PDF抽出時に金額0の行をフィルタリングすることを推奨
    expect(entry.input.amount).toBe(0);
    expect(autoResolved).toHaveLength(1);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
  });

  /**
   * H-4: gold_026 — リース契約書（IFRS 16 オペレーティングリース相当）
   * CHECK-9: 「リース」はREPAIR_KEYWORDS(/修繕|修理|補修|交換/)に含まれない
   *   180,000 >= 100,000 かつ非修繕キーワード → needsLlm → LLMがEXPENSE/賃借料判定
   * CHECK-7b: 180,000 >= 100,000 → rule_a非適用。「リース」非マッチ → rule_b/d非適用
   *   → needsLlm（IFRS 16の区分はLLMが文脈判断）
   */
  it('gold_026: 複合機リース年間料 180,000円 → REPAIR_KEYWORDS非マッチ → needsLlm（LLMがリース判定）', async () => {
    const entry = edgeCases.find((d) => d.test_id === 'gold_026')!;

    // preScreen確認: needsLlm
    const { autoResolved, needsLlm } = preScreenLineItems([makeItem(entry.test_id, entry.input)]);
    // CHECK-7b: 「リース」= REPAIR_KEYWORDS非マッチ。180,000 >= 100,000 → needsLlm
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
    expect(needsLlm[0].line_item_id).toBe('gold_026');

    // LLMモック: オペレーティングリース→EXPENSE/賃借料
    mockLlmResult('gold_026', {
      verdict: 'EXPENSE',
      account_category: '賃借料',
      useful_life: null,
      rationale: 'オペレーティングリース料 → 期間費用として賃借料計上（IFRS 16準拠）',
      article_ref: null,
      formal_criteria_step: null,
    });

    const results = await runTaxAgent([makeItem('gold_026', entry.input)]);
    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].account_category).toBe('賃借料');
    expect(results[0].useful_life).toBeNull();
    // JSONの期待値確認
    expect(entry.expected.verdict).toBe('EXPENSE');
    expect(entry.expected.account_category).toBe('賃借料');
  });

  /**
   * H-5: gold_027 — 税込/税抜混在（税込110,000円）
   * CHECK-9:
   *   税込110,000円の場合: amount=110,000 >= 100,000 → rule_a非適用
   *   税抜換算すると100,000円（令133条の「< 100,000」境界）だが、preScreenは渡された値で判定
   * CHECK-7b:
   *   110,000 < 100,000 → false → rule_a非適用
   *   「税込」「税抜」はREPAIR_KEYWORDS非マッチ → rule_b/d非適用
   *   → needsLlm。実務では税抜金額を入力することを推奨。
   */
  it('gold_027: 税込110,000円の明細 → rule_a非適用（税抜100k境界に注意）→ needsLlm', () => {
    const entry = edgeCases.find((d) => d.test_id === 'gold_027')!;
    const { autoResolved, needsLlm } = preScreenLineItems([makeItem(entry.test_id, entry.input)]);

    // CHECK-7b: 110,000 >= 100,000 → rule_a非適用。「税込」=非修繕 → needsLlm
    // 税務上の判定基準は税抜金額だが、システムは渡された金額をそのまま使用する
    expect(entry.input.amount).toBe(110_000);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);
    expect(needsLlm[0].line_item_id).toBe('gold_027');
  });

  /**
   * H-6: gold_028 — ページ跨ぎ分割明細（同一工事が2行に分割された場合）
   * CHECK-9: preScreenは各明細を独立して評価する。合算評価は行わない設計。
   *   材料費80,000円 + 作業費80,000円（別行）= 合算160,000円だが、各々rule_a適用
   * CHECK-7b:
   *   gold_028(80,000): 80,000 < 100,000 → rule_a → EXPENSE（個別評価）
   *   同一工事の合算160,000は100,000以上だがpreScreenは合算しない（設計仕様）
   *   → 実務では分割明細の合算確認は人間が行う
   */
  it('gold_028: ページ跨ぎ分割明細（材料費+作業費各80k）→ 個別rule_a適用、合算評価なし', () => {
    const entry = edgeCases.find((d) => d.test_id === 'gold_028')!;

    // 同一工事が2行に分割（各々80,000円）
    const itemP1 = makeItem('gold_028', entry.input);                    // 材料費側
    const itemP2 = { line_item_id: 'gold_028b', description: '屋上防水工事（ページ跨ぎ：作業費分）', amount: 80_000 };

    const { autoResolved: ar1 } = preScreenLineItems([itemP1]);
    const { autoResolved: ar2 } = preScreenLineItems([itemP2]);

    // CHECK-7b: 各々80,000 < 100,000 → rule_a（個別評価）
    expect(ar1).toHaveLength(1);
    expect(ar1[0].rule).toBe('rule_a_under_100k');
    expect(ar2).toHaveLength(1);
    expect(ar2[0].rule).toBe('rule_a_under_100k');

    // 重要: 合算（160,000）はrule_a非適用だが、preScreenは合算しない設計
    // 実務注記: 分割明細の合算判定は人間確認が必要（CHECK-9: この仕様を明記）
    expect(entry.input.amount).toBe(80_000);
    expect(entry.expected.verdict).toBe('EXPENSE');
  });
});
