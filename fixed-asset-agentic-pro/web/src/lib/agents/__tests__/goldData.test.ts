/**
 * goldData.test.ts — Phase 1-C ゴールドデータ検証テスト (cmd_135k_sub1)
 *
 * ゴールドデータの目的:
 *   税法知識から「正解」を定義し、AIシステムの判定ロジックを検証する。
 *   各テストケースは法令・通達の具体的根拠とともに期待値を記録し、
 *   将来の実装変更による回帰を検知する。
 *
 * CHECK-9: テスト期待値の根拠（法令ベース）
 *   ルールa: 法人税法施行令第133条（10万円未満→即時費用化・消耗品費）
 *   ルールb: 法人税基本通達7-8-3(1)（修繕費20万円未満→費用）
 *   ルールc: 法人税基本通達7-8-3(2)（修繕周期3年以内→費用）
 *   ルールd: 法人税基本通達7-8-4(1)（修繕費60万円未満→費用）
 *   一括償却: 法人税法施行令第133条の2（10万〜20万未満→3年均等償却・一括償却資産）
 *   資本的支出: 法人税法施行令第132条（価値向上・耐用年数延長→CAPITAL）
 *   耐用年数: 減価償却資産の耐用年数等に関する省令 別表第一
 *
 * CHECK-7b 手計算検証:
 *   rule_a: 8,000円 < 100,000円 → EXPENSE ✓（令133条）
 *   rule_a: 3,000円 < 100,000円 → EXPENSE ✓（令133条）
 *   rule_b: 150,000円 < 200,000円 × "修理" → EXPENSE ✓（基通7-8-3(1)）
 *   rule_b: 180,000円 < 200,000円 × "補修" → EXPENSE ✓（基通7-8-3(1)）
 *   rule_d: 450,000円 < 600,000円 × "修繕" → EXPENSE ✓（基通7-8-4(1)）
 *   rule_d: 350,000円 < 600,000円 × "交換" → EXPENSE ✓（基通7-8-4(1)）
 *   PC 250,000円: 10万以上・非修繕 → needsLlm → CAPITAL, 器具備品, 4年 ✓
 *   サーバー 1,500,000円: 10万以上・非修繕 → needsLlm → CAPITAL, 機械装置, 5年 ✓
 *   タブレット 160,000円: 10万以上・非修繕 → needsLlm → EXPENSE, 一括償却資産 ✓
 *   屋根防水工事 900,000円: 60万以上・修繕外 → needsLlm → EXPENSE, 修繕費 ✓
 *   エレベーター機能向上 1,500,000円: → needsLlm → CAPITAL, 建物附属設備, 17年 ✓
 *
 * テスト構成:
 *   カテゴリ1: 明確固定資産（2件）— LLMモック使用
 *   カテゴリ2: 明確費用（3件）— preScreenLineItems確定ルール
 *   カテゴリ3: 少額資産（2件）— preScreenLineItems rule_a
 *   カテゴリ4: 一括償却資産（2件）— LLMモック使用
 *   カテゴリ5: 修繕vs資本的支出（4件）— preScreen(rule_d 2件) + LLMモック(2件)
 *   カテゴリ6: 分裂ケース/UNCERTAIN（2件）— LLMモック使用
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

import { preScreenLineItems, runTaxAgent } from '../taxAgent';

// ─── ヘルパー ──────────────────────────────────────────────────────────────

function makeItem(
  line_item_id: string,
  description: string,
  amount: number,
): ExtractedLineItem {
  return { line_item_id, description, amount };
}

/** LLM API のモックレスポンスを生成する（テスト用正解データ注入） */
function mockLlmResponse(results: object[]) {
  mockMessagesCreate.mockResolvedValue({
    content: [{ type: 'text', text: JSON.stringify(results) }],
  });
}

// ─── カテゴリ3: 少額資産（preScreenLineItems rule_a）─────────────────────

describe('ゴールドデータ: カテゴリ3 少額資産（10万円未満 → 即時費用化）', () => {
  /**
   * CHECK-9 根拠: 法人税法施行令第133条
   * 「その取得価額が10万円未満の減価償却資産については、その業務の用に供した日の属する
   *  事業年度において全額損金算入できる」
   * → 10万未満の物品は全て消耗品費として即時費用化
   */

  it('GD-3a: マウス（光学式）8,000円 → EXPENSE, 消耗品費 [rule_a]', () => {
    // 手計算: 8,000円 < 100,000円 → 令133条 → EXPENSE確定
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-3a', '光学式マウス', 8_000),
    ]);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved).toHaveLength(1);
    const result = autoResolved[0].result;
    expect(result.verdict).toBe('EXPENSE');
    expect(result.account_category).toBe('消耗品費');
    expect(result.useful_life).toBeNull();
    expect(autoResolved[0].rule).toBe('rule_a_under_100k');
    // rationale/法令根拠の確認
    expect(result.article_ref).toContain('133条');
  });

  it('GD-3b: LANケーブル（Cat6, 5m）1,980円 → EXPENSE, 消耗品費 [rule_a]', () => {
    // 手計算: 1,980円 < 100,000円 → 令133条 → EXPENSE確定
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-3b', 'LANケーブル Cat6 5m', 1_980),
    ]);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('消耗品費');
  });
});

// ─── カテゴリ2: 明確費用（preScreenLineItems rule_a / rule_b）──────────

describe('ゴールドデータ: カテゴリ2 明確費用（修繕費・消耗品費）', () => {
  /**
   * CHECK-9 根拠:
   *   コピー用紙3,000円: 令133条（10万未満 → 消耗品費）
   *   エアコン修理150,000円: 基通7-8-3(1)（修繕費20万未満 → EXPENSE）
   *   窓ガラス補修180,000円: 基通7-8-3(1)（修繕費20万未満 × "補修" → EXPENSE）
   */

  it('GD-2a: コピー用紙 A4 500枚×3冊 3,000円 → EXPENSE, 消耗品費 [rule_a]', () => {
    // 手計算: 3,000円 < 100,000円 → 令133条 → EXPENSE確定
    // 消耗品: 使用によって消耗するため固定資産に該当しない
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-2a', 'コピー用紙 A4 500枚×3冊', 3_000),
    ]);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved[0].result.verdict).toBe('EXPENSE');
    expect(autoResolved[0].result.account_category).toBe('消耗品費');
  });

  it('GD-2b: エアコン修理費（冷媒補充・フィルター交換）150,000円 → EXPENSE, 修繕費 [rule_b]', () => {
    // 手計算: 150,000円 < 200,000円 × "修理" ∈ REPAIR_KEYWORDS → 基通7-8-3(1) → EXPENSE確定
    // 注意: rule_a(10万未満)は非該当(150,000 >= 100,000)。rule_b適用。
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-2b', 'エアコン修理費（冷媒補充・フィルター交換）', 150_000),
    ]);
    expect(needsLlm).toHaveLength(0);
    expect(autoResolved).toHaveLength(1);
    const result = autoResolved[0].result;
    expect(result.verdict).toBe('EXPENSE');
    expect(result.account_category).toBe('修繕費');
    expect(autoResolved[0].rule).toBe('rule_b_repair_step1');
    expect(result.article_ref).toContain('7-8-3');
  });

  it('GD-2c: 窓ガラス補修費 180,000円 → EXPENSE, 修繕費 [rule_b]', () => {
    // 手計算: 180,000円 < 200,000円 × "補修" ∈ REPAIR_KEYWORDS → 基通7-8-3(1) → EXPENSE確定
    // 原状回復目的の補修は典型的な修繕費（令132条の資本的支出に非該当）
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-2c', '窓ガラス補修費（ひび割れ補修）', 180_000),
    ]);
    expect(needsLlm).toHaveLength(0);
    const result = autoResolved[0].result;
    expect(result.verdict).toBe('EXPENSE');
    expect(result.account_category).toBe('修繕費');
    expect(autoResolved[0].rule).toBe('rule_b_repair_step1');
  });
});

// ─── カテゴリ5: 修繕vs資本的支出（preScreenLineItems rule_d）────────────

describe('ゴールドデータ: カテゴリ5a 修繕費（preScreen確定 — 60万円未満）', () => {
  /**
   * CHECK-9 根拠: 基通7-8-4(1)
   * 「修繕費の支出額が60万円に満たないとき → 修繕費として損金算入」
   * → 60万未満 + 修繕キーワードは一律EXPENSE（資本的支出との按分不要）
   */

  it('GD-5a: 駐車場舗装修繕費 450,000円 → EXPENSE, 修繕費 [rule_d]', () => {
    // 手計算: 450,000円 < 600,000円 × "修繕" ∈ REPAIR_KEYWORDS → 基通7-8-4(1) → EXPENSE確定
    // rule_a(10万未満)非該当, rule_b(20万未満)非該当 → rule_d適用
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-5a', '駐車場舗装修繕費（ひび割れ補修）', 450_000),
    ]);
    expect(needsLlm).toHaveLength(0);
    const result = autoResolved[0].result;
    expect(result.verdict).toBe('EXPENSE');
    expect(result.account_category).toBe('修繕費');
    expect(autoResolved[0].rule).toBe('rule_d_repair_step3');
    expect(result.article_ref).toContain('7-8-4');
  });

  it('GD-5b: 給湯器交換工事 350,000円 → EXPENSE, 修繕費 [rule_d]', () => {
    // 手計算: 350,000円 < 600,000円 × "交換" ∈ REPAIR_KEYWORDS → 基通7-8-4(1) → EXPENSE確定
    // 同一性能への交換（原状回復）= 修繕費。性能向上がある場合はLLM判定が必要だが
    // rule_dは金額基準のみで形式的に判定（60万未満×修繕キーワードは一律費用）
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-5b', '給湯器交換工事（同性能品への交換）', 350_000),
    ]);
    expect(needsLlm).toHaveLength(0);
    const result = autoResolved[0].result;
    expect(result.verdict).toBe('EXPENSE');
    expect(result.account_category).toBe('修繕費');
    expect(autoResolved[0].rule).toBe('rule_d_repair_step3');
  });
});

// ─── LLMモックを使用するテスト群 ─────────────────────────────────────────

describe('ゴールドデータ: カテゴリ1 明確固定資産（LLM判定・CAPITAL）', () => {
  /**
   * CHECK-9 根拠:
   *   ノートPC: 耐用年数省令別表第一「電子計算機のうちパーソナルコンピュータ→4年」
   *   サーバー機器: 同別表第一「電子計算機のうち1（パーソナルコンピュータ以外）→5年」
   *   → 250,000円・1,500,000円ともに10万以上・非修繕 → needsLlm → LLM = CAPITAL
   *
   * 手計算:
   *   PC 250,000円: rule_a(10万以上)・rule_b〜d(修繕外) → needsLlm ✓
   *   サーバー 1,500,000円: 同上 → needsLlm ✓
   *   LLMが正しく判定した場合の期待値:
   *     PC → CAPITAL, 器具備品, 4年（別表第一 5 電子計算機(1)パーソナルコンピュータ）
   *     サーバー → CAPITAL, 機械装置, 5年（別表第一 5 電子計算機(2)その他のもの）
   */

  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('GD-1a: ノートPC Dell XPS 250,000円 → needsLlm確認 + CAPITAL, 器具備品, 4年', async () => {
    // Step 1: preScreenで needsLlm に分類されることを確認
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-1a', 'ノートPC Dell XPS 13', 250_000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);

    // Step 2: LLMが正解を返した場合の処理結果を検証
    // 正解根拠: 別表第一 5 器具及び備品(1)電気・通信機器(ロ)パーソナルコンピュータ → 4年
    mockLlmResponse([{
      line_item_id: 'gd-1a',
      verdict: 'CAPITAL',
      rationale: 'ノートPCは器具及び備品（パーソナルコンピュータ）に該当。耐用年数4年。',
      article_ref: '耐用年数省令別表第一 5(1)ロ',
      account_category: '器具備品',
      useful_life: 4,
      formal_criteria_step: null,
      confidence: 0.95,
    }]);

    const results = await runTaxAgent([makeItem('gd-1a', 'ノートPC Dell XPS 13', 250_000)]);
    expect(results).toHaveLength(1);
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('器具備品');
    expect(results[0].useful_life).toBe(4);
  });

  it('GD-1b: サーバー機器（ラックマウント型）1,500,000円 → CAPITAL, 機械装置, 5年', async () => {
    // preScreen確認: 150万は10万以上・非修繕 → needsLlm
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-1b', 'サーバー機器 HP ProLiant DL380 Gen10', 1_500_000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);

    // 正解根拠: 別表第一 5 器具及び備品(1)電気・通信機器(イ)その他のもの（パーソナルコンピュータ以外）→ 5年
    mockLlmResponse([{
      line_item_id: 'gd-1b',
      verdict: 'CAPITAL',
      rationale: 'サーバー機器は電子計算機（パーソナルコンピュータ以外）に該当。耐用年数5年。',
      article_ref: '耐用年数省令別表第一 5(1)イ',
      account_category: '器具備品',
      useful_life: 5,
      formal_criteria_step: null,
      confidence: 0.95,
    }]);

    const results = await runTaxAgent([
      makeItem('gd-1b', 'サーバー機器 HP ProLiant DL380 Gen10', 1_500_000),
    ]);
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('器具備品');
    expect(results[0].useful_life).toBe(5);
  });
});

describe('ゴールドデータ: カテゴリ4 一括償却資産（10万〜20万円未満）', () => {
  /**
   * CHECK-9 根拠: 法人税法施行令第133条の2
   * 「取得価額が10万円以上20万円未満の減価償却資産は、3年間で均等損金算入可能」
   * → 10万〜20万未満の業務用資産 = 一括償却資産として費用処理（EXPENSE）
   *
   * 注意: 20万〜30万円の場合は中小企業者の特例（租税特措法67条の5）が適用可能だが、
   *       企業規模の情報が必要なため「要殿レビュー」に準じる判断が必要。
   *
   * 手計算:
   *   タブレット 160,000円: 10万以上・非修繕 → needsLlm
   *   LLM正解: EXPENSE（一括償却資産として3年損金: 令133条の2）
   *   複合機 280,000円: 10万以上・非修繕 → needsLlm
   *   LLM正解: EXPENSE（中小企業者特例適用想定: 措法67条の5）
   *   ※中小企業者でない場合はCAPITALの可能性あり → 要殿レビューと明記
   */

  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('GD-4a: タブレットPC（業務用）160,000円 → EXPENSE, 一括償却資産 [令133条の2]', async () => {
    // preScreen確認: 16万は10万以上・非修繕 → needsLlm
    const { needsLlm } = preScreenLineItems([
      makeItem('gd-4a', 'タブレットPC Apple iPad Pro 12.9インチ', 160_000),
    ]);
    expect(needsLlm).toHaveLength(1);

    // 正解根拠: 10万以上20万未満の器具備品 → 一括償却資産（3年均等損金算入）
    // EXPENSE判定で account_category = 一括償却資産
    mockLlmResponse([{
      line_item_id: 'gd-4a',
      verdict: 'EXPENSE',
      rationale: '取得価額16万円は20万円未満のため一括償却資産に該当（令133条の2）。3年均等損金算入。',
      article_ref: '法人税法施行令第133条の2',
      account_category: '一括償却資産',
      useful_life: null,
      formal_criteria_step: null,
      confidence: 0.90,
    }]);

    const results = await runTaxAgent([
      makeItem('gd-4a', 'タブレットPC Apple iPad Pro 12.9インチ', 160_000),
    ]);
    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].account_category).toBe('一括償却資産');
  });

  it('GD-4b: 業務用複合機（コピー・スキャン）280,000円 → EXPENSE, 一括償却資産 [要殿レビュー: 中小企業者特例前提]', async () => {
    // preScreen確認: 28万は10万以上・非修繕 → needsLlm
    const { needsLlm } = preScreenLineItems([
      makeItem('gd-4b', '業務用複合機 Canon imageRUNNER', 280_000),
    ]);
    expect(needsLlm).toHaveLength(1);

    // 正解根拠（中小企業者特例前提）:
    //   措法67条の5: 中小企業者が取得した30万未満の資産は全額即時損金算入可能
    //   EXPENSE判定 account_category = 一括償却資産
    // 【要殿レビュー】: 中小企業者でない場合はCAPITAL（通常の減価償却）になる可能性あり
    //   器具備品として耐用年数: 複写機・複合機 → 別表第一 7(1) 5年
    mockLlmResponse([{
      line_item_id: 'gd-4b',
      verdict: 'EXPENSE',
      rationale: '中小企業者の少額減価償却資産特例（措法67条の5）適用により即時損金算入。要確認: 中小企業者に該当しない場合は固定資産計上（5年償却）。',
      article_ref: '租税特別措置法第67条の5',
      account_category: '一括償却資産',
      useful_life: null,
      formal_criteria_step: null,
      confidence: 0.75,
    }]);

    const results = await runTaxAgent([
      makeItem('gd-4b', '業務用複合機 Canon imageRUNNER', 280_000),
    ]);
    // 中小企業者特例適用想定でEXPENSE。要殿レビュー: 大企業の場合はCAPITALの可能性
    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].account_category).toBe('一括償却資産');
  });
});

describe('ゴールドデータ: カテゴリ5b 修繕vs資本的支出（LLM判定 — 60万円以上）', () => {
  /**
   * CHECK-9 根拠:
   *   屋根防水工事（原状回復）900,000円:
   *     60万以上 → preScreen非該当 → needsLlm
   *     基通7-8-5: 「明らかに価値を増加させるものでない修繕的支出 = 修繕費」
   *     原状回復（現状維持）目的の防水工事 → EXPENSE, 修繕費
   *
   *   エレベーター機能向上工事 1,500,000円:
   *     60万以上 → preScreen非該当 → needsLlm
   *     令第132条: 「資産の価値を高め、または耐用年数を延長するもの = 資本的支出」
   *     機能向上（旧エレベーター → バリアフリー対応化）→ CAPITAL, 建物附属設備, 17年
   *     耐用年数根拠: 別表第一 1(3) 建物附属設備 エレベーター → 17年
   */

  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('GD-5c: 事務所屋根防水工事（原状回復）900,000円 → EXPENSE, 修繕費 [基通7-8-5]', async () => {
    // preScreen確認: 90万は60万以上 → needsLlm
    // "防水" は REPAIR_KEYWORDS(/修繕|修理|補修|交換/)に非該当 → needsLlm確定
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-5c', '事務所屋根防水工事（ウレタン防水・原状回復）', 900_000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);

    // 正解根拠: 基通7-8-5「その支出がもっぱら当該固定資産の現状を維持するために要したものか…
    //           これによって当該固定資産の価値が増加するものでないことが明らかなもの = 修繕費」
    // 防水層の原状回復は価値増加でなく現状維持 → EXPENSE
    mockLlmResponse([{
      line_item_id: 'gd-5c',
      verdict: 'EXPENSE',
      rationale: '屋根防水工事（原状回復目的）は資産価値を増加させない現状維持のための支出（基通7-8-5）。修繕費として損金算入。',
      article_ref: '法人税基本通達7-8-5',
      account_category: '修繕費',
      useful_life: null,
      formal_criteria_step: null,
      confidence: 0.88,
    }]);

    const results = await runTaxAgent([
      makeItem('gd-5c', '事務所屋根防水工事（ウレタン防水・原状回復）', 900_000),
    ]);
    expect(results[0].verdict).toBe('EXPENSE');
    expect(results[0].account_category).toBe('修繕費');
  });

  it('GD-5d: エレベーター機能向上工事（バリアフリー対応化）1,500,000円 → CAPITAL, 建物附属設備, 17年 [令132条]', async () => {
    // preScreen確認: 150万は60万以上 → needsLlm
    const { autoResolved, needsLlm } = preScreenLineItems([
      makeItem('gd-5d', 'エレベーター機能向上工事（バリアフリー対応・音声案内追加）', 1_500_000),
    ]);
    expect(autoResolved).toHaveLength(0);
    expect(needsLlm).toHaveLength(1);

    // 正解根拠: 法人税法施行令第132条「資産の価値を高め、または耐用年数を延長するための支出 = 資本的支出」
    // バリアフリー対応による機能向上 = 資産価値の増加 → CAPITAL
    // 耐用年数: 別表第一 1 建物附属設備(3) エレベーター → 17年
    mockLlmResponse([{
      line_item_id: 'gd-5d',
      verdict: 'CAPITAL',
      rationale: 'エレベーターのバリアフリー対応化は資産の価値を高める資本的支出（令132条）。建物附属設備（エレベーター）として計上。耐用年数17年。',
      article_ref: '法人税法施行令第132条 / 耐用年数省令別表第一 1(3)',
      account_category: '建物附属設備',
      useful_life: 17,
      formal_criteria_step: null,
      confidence: 0.92,
    }]);

    const results = await runTaxAgent([
      makeItem('gd-5d', 'エレベーター機能向上工事（バリアフリー対応・音声案内追加）', 1_500_000),
    ]);
    expect(results[0].verdict).toBe('CAPITAL');
    expect(results[0].account_category).toBe('建物附属設備');
    expect(results[0].useful_life).toBe(17);
  });
});

describe('ゴールドデータ: カテゴリ6 分裂ケース / UNCERTAIN（判断困難）', () => {
  /**
   * CHECK-9 根拠:
   *   GD-6a: PC本体+周辺機器セット購入 合計 250,000円（明細内訳なし）
   *     → 内訳が不明（PC本体: CAPITAL、マウス・ケーブル: EXPENSE の可能性）
   *     → 個別明細への分離が必要 → UNCERTAIN（情報不足）
   *
   *   GD-6b: 建物リノベーション一式 2,000,000円（一部資本的支出・一部修繕費）
   *     → 按分が必要（令132条2項「明らかに区分できない部分は7:3で按分」）
   *     → 詳細見積書なしには判断不可 → UNCERTAIN
   *
   * 【要殿レビュー】: 分裂ケースの判定基準・案内文言についてご確認をお願いします
   */

  beforeEach(() => {
    vi.stubEnv('ANTHROPIC_API_KEY', 'test_key_gold');
    mockMessagesCreate.mockReset();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('GD-6a: PC+周辺機器セット 250,000円（内訳なし）→ UNCERTAIN（明細分離が必要）', async () => {
    // preScreen確認: 25万は10万以上・非修繕 → needsLlm
    const { needsLlm } = preScreenLineItems([
      makeItem('gd-6a', 'PC本体・周辺機器一式（内訳不明）', 250_000),
    ]);
    expect(needsLlm).toHaveLength(1);

    // LLMが「内訳なしでは判定不能」と正しく応答することを想定
    // 正解: UNCERTAIN（情報不足。内訳明細の提出が必要）
    mockLlmResponse([{
      line_item_id: 'gd-6a',
      verdict: 'UNCERTAIN',
      rationale: 'PC本体と周辺機器が一括計上されており個別判定が不可能。PC本体はCAPITAL（器具備品4年）、マウス等は消耗品費（令133条）になる可能性。内訳明細を確認してください。',
      article_ref: null,
      account_category: null,
      useful_life: null,
      formal_criteria_step: null,
      confidence: 0.20,
    }]);

    const results = await runTaxAgent([
      makeItem('gd-6a', 'PC本体・周辺機器一式（内訳不明）', 250_000),
    ]);
    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].account_category).toBeNull();
    expect(results[0].useful_life).toBeNull();
    // rationale に判断理由が含まれること（情報不足の説明）
    expect(results[0].rationale).toBeTruthy();
  });

  it('GD-6b: 建物リノベーション一式 2,000,000円（資本+修繕混在）→ UNCERTAIN（按分必要）', async () => {
    // preScreen確認: 200万は60万以上・非修繕キーワード → needsLlm
    const { needsLlm } = preScreenLineItems([
      makeItem('gd-6b', '事務所リノベーション工事一式（内装改装・床・天井）', 2_000_000),
    ]);
    expect(needsLlm).toHaveLength(1);

    // 正解根拠（要殿レビュー）:
    //   令132条2項: 「修繕費か資本的支出かが明らかでない部分は、7:3で按分可能」
    //   ただし内装改装の詳細見積書なしには按分の根拠がなく判定不能 → UNCERTAIN
    mockLlmResponse([{
      line_item_id: 'gd-6b',
      verdict: 'UNCERTAIN',
      rationale: 'リノベーション工事は原状回復（修繕費）と価値向上（資本的支出）が混在する可能性。詳細見積書による按分が必要（令132条2項）。内訳確認後に再判定を推奨。',
      article_ref: '法人税法施行令第132条第2項',
      account_category: null,
      useful_life: null,
      formal_criteria_step: null,
      confidence: 0.15,
    }]);

    const results = await runTaxAgent([
      makeItem('gd-6b', '事務所リノベーション工事一式（内装改装・床・天井）', 2_000_000),
    ]);
    expect(results[0].verdict).toBe('UNCERTAIN');
    expect(results[0].useful_life).toBeNull();
  });
});
