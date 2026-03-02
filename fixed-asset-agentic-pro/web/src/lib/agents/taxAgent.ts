/**
 * Tax Agent: 税務判定エージェント
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.3 / 3.5 / 4.2
 *
 * Claude Haiku を @anthropic-ai/sdk で呼び出し、固定資産・費用の税務判定を行う。
 *   - 資本的支出 vs 修繕費の形式基準（基通7-8-3〜6）
 *   - 一括償却資産の3段階判定（10万/20万/30万）
 *   - 勘定科目・法定耐用年数の自動判定
 *
 * エラー耐性（根拠: Section 6 エラーハンドリング）:
 *   - ANTHROPIC_API_KEY 未設定 → dry-run モック（UNCERTAIN 全件）
 *   - API 呼び出し失敗 → UNCERTAIN 全件
 *   - JSON パースエラー → UNCERTAIN 全件
 */

import Anthropic from '@anthropic-ai/sdk';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';
import type { TaxAgentResult } from '@/types/multi_agent';

// ─── 設定 ─────────────────────────────────────────────────────────────────

export interface TaxAgentConfig {
  model?: string;
  max_tokens?: number;
}

export const TAX_AGENT_DEFAULT_MODEL = 'claude-haiku-4-5-20251001';
export const TAX_AGENT_DEFAULT_MAX_TOKENS = 2048;
export const TAX_AGENT_DEFAULT_TIMEOUT_MS = 30_000;

// ─── システムプロンプト ────────────────────────────────────────────────────

/**
 * Tax Agent システムプロンプト
 * 根拠: Section 3.3 判定ロジック（形式基準6段階・一括償却3段階・勘定科目マッピング）
 *
 * CHECK-9: 条文番号・判定基準は設計書 Section 3.3 から直接引用
 */
export const TAX_AGENT_SYSTEM_PROMPT = `あなたは日本の法人税法・所得税法・耐用年数省令に基づく税務判定エージェントです。

## 役割
入力された明細リストを受け取り、各明細を以下のいずれかに判定してください:
- CAPITAL: 資本的支出（固定資産計上）
- EXPENSE: 費用（修繕費・消耗品費等）
- UNCERTAIN: 判定不能（情報不足・ユーザー判断が必要）

## 判定ルール

### ルール1: 一括償却資産の3段階判定（根拠: 法人税法施行令第133条・第133条の2, 措置法第67条の5）
金額（税抜）に基づいて最初に判定する:
- 10万円未満 → EXPENSE（即時費用化）/ 勘定科目: 消耗品費
- 10万円以上〜20万円未満 → EXPENSE または CAPITAL（選択可）/ 勘定科目: 一括償却資産
- 20万円以上〜30万円未満 → EXPENSE または CAPITAL（中小企業者の少額減価償却資産特例あり）
- 30万円以上 → 通常の固定資産判定へ進む

### ルール2: 資本的支出 vs 修繕費の形式基準（根拠: 法人税基本通達7-8-3〜6）
品名・摘要に「修繕」「修理」「交換」「補修」「改修」「メンテナンス」が含まれる場合に適用:
| Step | 条件 | 判定 | 根拠 | formal_criteria_step |
|------|------|------|------|----------------------|
| 1 | 支出額 < 20万円 | EXPENSE（修繕費） | 基通7-8-3(1) | 1 |
| 2 | 修繕周期が概ね3年以内 | EXPENSE（修繕費） | 基通7-8-3(2) | 2 |
| 3 | 支出額 < 60万円 | EXPENSE（修繕費） | 基通7-8-4(1) | 3 |
| 4 | 支出額 < 前期末取得価額×10% | EXPENSE（修繕費） | 基通7-8-4(2) | 4 |
| 5 | 資産の価値を高める or 耐用年数を延長することが明らか | CAPITAL（資本的支出） | 法人税法施行令第132条 | 5 |
| 6 | 上記いずれにも該当しない | UNCERTAIN | ユーザー判断 | 6 |

### ルール3: 勘定科目マッピング（根拠: 耐用年数省令別表一）
CAPITAL判定時は以下のマッピングを参照:
| 品名キーワード | 勘定科目 | 法定耐用年数 |
|---|---|---|
| エアコン・空調・冷暖房 | 建物附属設備 | 13年 |
| PC・パソコン・ノートPC | 器具備品 | 4年 |
| サーバー | 器具備品 | 5年 |
| 複合機・プリンター | 器具備品 | 5年 |
| 社用車・営業車・自動車 | 車両運搬具 | 6年 |
| 机・椅子・家具 | 器具備品 | 8年 |
| ソフトウェア（自社利用） | ソフトウェア | 5年 |
| 間仕切り・パーティション | 建物附属設備 | 15年 |
| 防犯カメラ・セキュリティ | 器具備品 | 6年 |
| ガス設備 | 建物附属設備 | 15年 |
| スプリンクラー | 建物附属設備 | 8年 |
| 空調ダクト | 建物附属設備 | 13年 |
| 棚・ロッカー（金属製） | 器具備品 | 15年 |
| 棚（木製） | 器具備品 | 8年 |
| 会議テーブル（金属製） | 器具備品 | 15年 |
| 会議テーブル（木製） | 器具備品 | 8年 |
| ホワイトボード | 器具備品 | 8年 |
| テレビ | 器具備品 | 5年 |
| 冷蔵庫 | 器具備品 | 6年 |
| カーテン | 器具備品 | 3年 |
| 自動販売機 | 器具備品 | 5年 |
| 電動台車 | 器具備品 | 4年 |
| 原付・原動機付自転車 | 車両運搬具 | 3年 |
EXPENSE判定時も account_category を出力: 修繕費・消耗品費・雑費等

## 出力形式
必ず以下のJSON配列のみを返してください（前後に説明文・コードブロック等を追加しないこと）:
[
  {
    "line_item_id": "入力のline_item_idをそのまま使用",
    "verdict": "CAPITAL または EXPENSE または UNCERTAIN",
    "rationale": "判定根拠（日本語・簡潔に50文字以内）",
    "article_ref": "適用条文・通達番号（例: 基通7-8-3(1)）または null",
    "account_category": "勘定科目名（例: 器具備品）または null",
    "useful_life": 耐用年数（数値・年）または null,
    "formal_criteria_step": 形式基準ステップ番号（1〜6）または null
  }
]

## 制約
- 企業固有の方針は考慮せず、税法のみで判定する
- article_ref は必ず記載する（不明な場合は「法人税法施行令等」）
- 金額が0または入力がない場合は UNCERTAIN で判定する
`;

// ─── 耐用年数マスタ（cmd_146k_sub3: 14品目追加）─────────────────────────

/**
 * 法定耐用年数マスタ（減価償却資産の耐用年数等に関する省令 別表第一に基づく）
 *
 * キーワードマッチングによりLLM呼び出し前に耐用年数を確定する用途を想定。
 * 根拠: 耐用年数省令 別表第一
 *
 * ★ 2026-03-02 cmd_146k_sub3 で14品目追加（A3 cmd_144k_sub5 拡張提案より）
 */
export interface UsefulLifeEntry {
  years: number;
  category: string;
  basis: string;
  note?: string;
}

export const USEFUL_LIFE_MASTER: Record<string, UsefulLifeEntry> = {
  // ─── 建物附属設備（新規14品目のうち建物附属設備系）─────────────────────
  // 別表第一 建物附属設備（ガス設備）
  "ガス設備": { years: 15, category: "建物附属設備", basis: "別表第一 建物附属設備（ガス設備）" },
  // 別表第一 建物附属設備（消火設備）
  "スプリンクラー": { years: 8, category: "建物附属設備", basis: "別表第一 建物附属設備（消火設備）", note: "消火設備として8年" },
  // 別表第一 建物附属設備（冷暖房設備）— 建物組込型ダクト
  "空調ダクト": { years: 13, category: "建物附属設備", basis: "別表第一 建物附属設備（冷暖房設備）", note: "建物組込型。移動可能スポットエアコンは器具備品6年" },
  // 別表第一 建物附属設備（可動間仕切り、金属製）
  "間仕切り": { years: 15, category: "建物附属設備", basis: "別表第一 建物附属設備（可動間仕切り、金属製）", note: "固定式は建物の耐用年数に準じる" },

  // ─── 器具及び備品（家具・棚系）───────────────────────────────────────
  // 別表第一 器具及び備品 1（主として金属製のもの）— 事務机、事務いす
  "棚": { years: 15, category: "器具及び備品", basis: "別表第一 器具及び備品 1（主として金属製のもの）", note: "スチール棚・金属製棚は15年。木製棚は8年" },
  // 別表第一 器具及び備品 1（主として金属製のもの）
  "ロッカー": { years: 15, category: "器具及び備品", basis: "別表第一 器具及び備品 1（主として金属製のもの）" },
  // 別表第一 器具及び備品 1（主として金属製のもの）— 事務机
  "会議テーブル": { years: 15, category: "器具及び備品", basis: "別表第一 器具及び備品 1（主として金属製のもの）", note: "金属製は15年。木製は8年（その他のもの）" },
  // 別表第一 器具及び備品（その他のもの）— 木製棚（CR W-1対応 cmd_147k_sub1）
  "棚（木製）": { years: 8, category: "器具及び備品", basis: "別表第一 器具及び備品（その他のもの）", note: "木製棚は8年。金属製棚（スチール棚）は15年" },
  // 別表第一 器具及び備品（その他のもの）— 木製会議テーブル（CR W-1対応 cmd_147k_sub1）
  "会議テーブル（木製）": { years: 8, category: "器具及び備品", basis: "別表第一 器具及び備品（その他のもの）", note: "木製は8年（その他のもの）。金属製は15年" },
  // 別表第一 器具及び備品（その他のもの）
  "ホワイトボード": { years: 8, category: "器具及び備品", basis: "別表第一 器具及び備品（その他のもの）", note: "耐用年数省令に明確な区分なし。実務8年が一般的" },

  // ─── 器具及び備品（電気機器系）──────────────────────────────────────
  // 別表第一 器具及び備品（電気機器）
  "テレビ": { years: 5, category: "器具及び備品", basis: "別表第一 器具及び備品（電気機器）" },
  // 別表第一 器具及び備品（家庭用電器）
  "冷蔵庫": { years: 6, category: "器具及び備品", basis: "別表第一 器具及び備品（家庭用電器）" },
  // 別表第一 器具及び備品（自動販売機）
  "自動販売機": { years: 5, category: "器具及び備品", basis: "別表第一 器具及び備品（自動販売機）" },
  // 別表第一 器具及び備品（電気機器類に準じた解釈）
  "電動台車": { years: 4, category: "器具及び備品", basis: "別表第一 器具及び備品（電気機器類）", note: "実務3〜5年。要専門家確認" },

  // ─── 器具及び備品（その他）────────────────────────────────────────────
  // 別表第一 器具及び備品（その他のもの）
  "カーテン": { years: 3, category: "器具及び備品", basis: "別表第一 器具及び備品（その他のもの）" },

  // ─── 車両運搬具────────────────────────────────────────────────────────
  // 別表第一 車両及び運搬具（二輪自動車）— 125cc以下
  "原付": { years: 3, category: "車両運搬具", basis: "別表第一 車両及び運搬具（二輪自動車）", note: "125cc以下の原動機付自転車" },
};

// ─── 前処理（ルールベース）────────────────────────────────────────────────

/**
 * preScreenLineItems が確定した明細の内部表現
 */
export interface PreScreenedItem {
  item: ExtractedLineItem;
  result: TaxAgentResult;
  rule: string;
}

/**
 * preScreenLineItems の返却型
 */
export interface PreScreenResult {
  /** ルールベースで判定確定した明細とその結果 */
  autoResolved: PreScreenedItem[];
  /** LLM 判定が必要な明細 */
  needsLlm: ExtractedLineItem[];
}

/** 修繕関連キーワード（ルールb・d共通）*/
const REPAIR_KEYWORDS = /修繕|修理|補修|交換/;

/** 3年以内周期キーワード（ルールc）*/
const CYCLE_3YR_KEYWORDS = /3年以内|3年ごと|3年毎|3年に[一1]回|毎年|年次|定期修繕|定期点検/;

/**
 * ルールベース前処理: LLM不要な明細を事前に確定判定する。
 *
 * 適用ルール（根拠: 法人税法施行令 / 法人税基本通達）:
 *   ルールa: amount < 10万円 → EXPENSE（少額資産, 令第133条）
 *   ルールb: amount < 20万円 × 修繕キーワード → EXPENSE（形式基準 Step1, 基通7-8-3(1)）
 *   ルールc: amount < 20万円 × 3年以内周期語 → EXPENSE（形式基準 Step2, 基通7-8-3(2)）
 *   ルールd: amount < 60万円 × 修繕キーワード → EXPENSE（形式基準 Step3, 基通7-8-4(1)）
 *
 * @param items 抽出済み明細リスト
 * @returns autoResolved（確定判定済み） と needsLlm（LLM必要）の分離結果
 */
export function preScreenLineItems(items: ExtractedLineItem[]): PreScreenResult {
  const autoResolved: PreScreenedItem[] = [];
  const needsLlm: ExtractedLineItem[] = [];

  for (const item of items) {
    const { amount, description, line_item_id } = item;

    // ルールa: 10万円未満 → EXPENSE確定（少額資産）
    if (amount < 100_000) {
      autoResolved.push({
        item,
        rule: 'rule_a_under_100k',
        result: {
          line_item_id,
          verdict: 'EXPENSE',
          rationale: '10万円未満のため即時費用化（少額資産）',
          article_ref: '法人税法施行令第133条',
          account_category: '消耗品費',
          useful_life: null,
          formal_criteria_step: null,
          confidence: 1,
        },
      });
      continue;
    }

    // ルールb: 20万円未満 × 修繕キーワード → EXPENSE確定（形式基準 Step1）
    if (amount < 200_000 && REPAIR_KEYWORDS.test(description)) {
      autoResolved.push({
        item,
        rule: 'rule_b_repair_step1',
        result: {
          line_item_id,
          verdict: 'EXPENSE',
          rationale: '修繕費20万円未満の形式基準（基通7-8-3(1)）',
          article_ref: '基通7-8-3(1)',
          account_category: '修繕費',
          useful_life: null,
          formal_criteria_step: 1,
          confidence: 1,
        },
      });
      continue;
    }

    // ルールc: 20万円未満 × 3年以内周期語 → EXPENSE確定（形式基準 Step2）
    if (amount < 200_000 && CYCLE_3YR_KEYWORDS.test(description)) {
      autoResolved.push({
        item,
        rule: 'rule_c_cycle_step2',
        result: {
          line_item_id,
          verdict: 'EXPENSE',
          rationale: '修繕周期3年以内の形式基準（基通7-8-3(2)）',
          article_ref: '基通7-8-3(2)',
          account_category: '修繕費',
          useful_life: null,
          formal_criteria_step: 2,
          confidence: 1,
        },
      });
      continue;
    }

    // ルールd: 60万円未満 × 修繕キーワード → EXPENSE確定（形式基準 Step3）
    if (amount < 600_000 && REPAIR_KEYWORDS.test(description)) {
      autoResolved.push({
        item,
        rule: 'rule_d_repair_step3',
        result: {
          line_item_id,
          verdict: 'EXPENSE',
          rationale: '修繕費60万円未満の形式基準（基通7-8-4(1)）',
          article_ref: '基通7-8-4(1)',
          account_category: '修繕費',
          useful_life: null,
          formal_criteria_step: 3,
          confidence: 1,
        },
      });
      continue;
    }

    needsLlm.push(item);
  }

  return { autoResolved, needsLlm };
}

/**
 * autoResolved と llmResults をマージし、元の明細順序で返す。
 * prescreen 結果が LLM 結果より優先される。
 */
function mergeResultsByOriginalOrder(
  originalItems: ExtractedLineItem[],
  prescreenResults: TaxAgentResult[],
  llmResults: TaxAgentResult[],
): TaxAgentResult[] {
  // LLM → prescreen の順で積む（prescreen が上書き優先）
  const map = new Map<string, TaxAgentResult>(
    [...llmResults, ...prescreenResults].map((r) => [r.line_item_id, r]),
  );
  return originalItems.map((item) => map.get(item.line_item_id)!);
}

// ─── リトライユーティリティ ────────────────────────────────────────────────

/** 指数バックオフリトライ用スリープ */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Tax Agent API 呼び出し（指数バックオフ、最大2リトライ）
 *
 * - attempt 0: 即実行
 * - attempt 1: 100ms 待機後
 * - attempt 2: 200ms 待機後
 * - 全て失敗 → throw（呼び出し元で UNCERTAIN フォールバック）
 */
async function callTaxApiWithRetry(
  client: Anthropic,
  model: string,
  max_tokens: number,
  userPrompt: string,
  timeoutMs: number,
): Promise<string> {
  const MAX_RETRIES = 2;
  let lastError: unknown;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await client.messages.create(
        {
          model,
          max_tokens,
          system: TAX_AGENT_SYSTEM_PROMPT,
          messages: [{ role: 'user', content: userPrompt }],
        },
        { signal: controller.signal },
      );
      clearTimeout(timer);
      return response.content
        .filter((c) => c.type === 'text')
        .map((c) => (c as { type: 'text'; text: string }).text)
        .join('');
    } catch (err) {
      clearTimeout(timer);
      lastError = err;
      console.warn(`[TaxAgent] API呼び出し失敗 (attempt ${attempt + 1}/${MAX_RETRIES + 1}):`, err);
      if (attempt < MAX_RETRIES) {
        await sleep(100 * Math.pow(2, attempt)); // 100ms → 200ms
      }
    }
  }
  throw lastError;
}

// ─── ドライランモック ─────────────────────────────────────────────────────

/**
 * ANTHROPIC_API_KEY 未設定時のドライランモック。
 * LLM判定が必要な明細のみ UNCERTAIN で返す。前処理済み明細は含まない。
 */
function createDryRunResults(lineItems: ExtractedLineItem[]): TaxAgentResult[] {
  return lineItems.map((item) => ({
    line_item_id: item.line_item_id,
    verdict: 'UNCERTAIN' as const,
    rationale: `[DRY-RUN] ANTHROPIC_API_KEY未設定のため判定スキップ: ${item.description}`,
    article_ref: null,
    account_category: null,
    useful_life: null,
    formal_criteria_step: null,
    confidence: 0,
  }));
}

// ─── レスポンスパーサー ────────────────────────────────────────────────────

/**
 * LLM テキストレスポンスを TaxAgentResult[] に変換する。
 * パースエラー時は全明細を UNCERTAIN で返す（エラー耐性）。
 *
 * 根拠: Section 6 「Tax失敗 → GUIDANCEとして当該明細を処理」
 */
export function parseResponse(
  content: string,
  lineItems: ExtractedLineItem[],
): TaxAgentResult[] {
  try {
    // LLM がコードブロックで包む場合も対応
    const jsonMatch = content.match(/\[[\s\S]*\]/);
    if (!jsonMatch) {
      throw new Error('JSONが見つかりません');
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const parsed: any[] = JSON.parse(jsonMatch[0]);

    if (!Array.isArray(parsed)) {
      throw new Error('JSON配列ではありません');
    }

    const validVerdicts = new Set(['CAPITAL', 'EXPENSE', 'UNCERTAIN']);

    return parsed.map((item) => ({
      line_item_id: typeof item.line_item_id === 'string' ? item.line_item_id : '',
      verdict: validVerdicts.has(item.verdict as string)
        ? (item.verdict as TaxAgentResult['verdict'])
        : 'UNCERTAIN',
      rationale: typeof item.rationale === 'string' ? item.rationale : '不明',
      article_ref: typeof item.article_ref === 'string' ? item.article_ref : null,
      account_category:
        typeof item.account_category === 'string' ? item.account_category : null,
      useful_life: typeof item.useful_life === 'number' ? item.useful_life : null,
      formal_criteria_step:
        typeof item.formal_criteria_step === 'number' ? item.formal_criteria_step : null,
      confidence: typeof item.confidence === 'number' ? item.confidence : null,
    }));
  } catch {
    // パースエラー: 全明細を UNCERTAIN で返す
    return lineItems.map((item) => ({
      line_item_id: item.line_item_id,
      verdict: 'UNCERTAIN' as const,
      rationale: '[パースエラー] Tax Agent のレスポンスを解析できませんでした',
      article_ref: null,
      account_category: null,
      useful_life: null,
      formal_criteria_step: null,
      confidence: 0,
    }));
  }
}

// ─── メイン関数 ──────────────────────────────────────────────────────────────

/**
 * Tax Agent を実行する。
 *
 * @param lineItems 抽出済み明細リスト（ExtractedLineItem[]）
 * @param config    設定（モデル・トークン数等）
 * @returns         TaxAgentResult[]（各明細の税務判定結果）
 *
 * エラー耐性（根拠: Section 6）:
 *   - ANTHROPIC_API_KEY 未設定 → dry-run モック（全件 UNCERTAIN）
 *   - API 呼び出し失敗 → 全件 UNCERTAIN
 *   - JSON パースエラー → 全件 UNCERTAIN
 */
export async function runTaxAgent(
  lineItems: ExtractedLineItem[],
  config?: TaxAgentConfig,
): Promise<TaxAgentResult[]> {
  // 空入力は即座に空配列を返す
  if (lineItems.length === 0) return [];

  // 前処理: ルールベースで確定できる明細を分離
  const { autoResolved, needsLlm } = preScreenLineItems(lineItems);
  const prescreenResults = autoResolved.map((r) => r.result);

  // ドライランチェック（APIキー未設定）
  // 前処理済み明細は確定結果を返す。LLM必要な明細のみ UNCERTAIN。
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    const dryRunResults = createDryRunResults(needsLlm);
    return mergeResultsByOriginalOrder(lineItems, prescreenResults, dryRunResults);
  }

  // 全明細が前処理で解決済みの場合はLLM呼び出し不要
  if (needsLlm.length === 0) {
    return prescreenResults;
  }

  const model = config?.model ?? process.env.TAX_AGENT_MODEL ?? TAX_AGENT_DEFAULT_MODEL;
  const max_tokens = config?.max_tokens ?? TAX_AGENT_DEFAULT_MAX_TOKENS;
  const timeoutMs =
    parseInt(process.env.TAX_AGENT_TIMEOUT_MS ?? '', 10) || TAX_AGENT_DEFAULT_TIMEOUT_MS;

  // LLM には前処理で未解決の明細のみ送信
  const userPrompt = `以下の明細リストを税務判定してください:\n\n${JSON.stringify(needsLlm, null, 2)}`;

  const client = new Anthropic({ apiKey });

  try {
    const textContent = await callTaxApiWithRetry(client, model, max_tokens, userPrompt, timeoutMs);
    const llmResults = parseResponse(textContent, needsLlm);
    return mergeResultsByOriginalOrder(lineItems, prescreenResults, llmResults);
  } catch {
    // 全リトライ失敗: LLM必要明細を UNCERTAIN で返す。前処理済みは確定結果を保持。
    const errorResults = needsLlm.map((item) => ({
      line_item_id: item.line_item_id,
      verdict: 'UNCERTAIN' as const,
      rationale: '[APIエラー] Tax Agent の呼び出しに失敗しました（リトライ3回）',
      article_ref: null,
      account_category: null,
      useful_life: null,
      formal_criteria_step: null,
      confidence: 0,
    }));
    return mergeResultsByOriginalOrder(lineItems, prescreenResults, errorResults);
  }
}
