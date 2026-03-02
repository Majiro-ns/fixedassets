/**
 * Practice Agent: 実務判定エージェント
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.4
 *
 * 役割: 教師データ（TrainingRecord）と過去の実務事例を基に
 *       固定資産 / 費用 / UNCERTAIN を判定する。
 *
 * API: Claude Haiku (@anthropic-ai/sdk)
 * dry-run: ANTHROPIC_API_KEY 未設定時はモックデータ（UNCERTAIN）を返す
 * エラー耐性: API 失敗 / パース失敗時も全明細を UNCERTAIN で返す（Section 6 準拠）
 */

import Anthropic from '@anthropic-ai/sdk';
import type { PracticeAgentResult, SimilarCase, AgentVerdict } from '@/types/multi_agent';
import type { ExtractedLineItem } from '@/types/classify_pdf_v2';
import type { TrainingRecord } from '@/types/training_data';

// ─── 設定 ────────────────────────────────────────────────────────────────────

/** Practice Agent 実行設定 */
export interface PracticeAgentConfig {
  /** 使用モデル。デフォルト: claude-haiku-4-5-20251001（根拠: Section 3.4）*/
  model?: string;
  /** few-shot の最大件数。デフォルト: 10（根拠: Section 3.4 top-N 選択）*/
  maxFewShot?: number;
}

const DEFAULT_MODEL = 'claude-haiku-4-5-20251001';
const DEFAULT_MAX_FEW_SHOT = 10;
export const PRACTICE_AGENT_DEFAULT_TIMEOUT_MS = 30_000;

// ─── 類似度計算（Jaccard 係数） ──────────────────────────────────────────────

/**
 * 2 つの文字列間のキーワード重複率（Jaccard 係数）を算出する。
 * 根拠: Section 3.4 "類似事例ベースの判定"
 *
 * CHECK-7b 手計算検証:
 *   "ノートPC" vs "ノートPC" → tokens: {"ノートpc"} / {"ノートpc"} → 1/1 = 1.0
 *   "エアコン" vs "コピー用紙" → tokens: {"エアコン"} / {"コピー用紙"} → 0/2 = 0.0
 *   "ノートPC Dell" vs "デスクトップPC Dell" → {"ノートpc","dell"} / {"デスクトップpc","dell"} → 1/3 ≈ 0.33
 */
export function calcSimilarity(a: string, b: string): number {
  if (!a || !b) return 0;

  const tokenize = (s: string): Set<string> =>
    new Set(
      s
        .toLowerCase()
        .split(/[\s\u3000、。・「」【】（）()¥,・\d]+/)
        .filter((t) => t.length > 0),
    );

  const setA = tokenize(a);
  const setB = tokenize(b);

  if (setA.size === 0 || setB.size === 0) return 0;

  let intersection = 0;
  for (const t of setA) {
    if (setB.has(t)) intersection++;
  }

  const union = setA.size + setB.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

// ─── Few-shot 選択 ───────────────────────────────────────────────────────────

/**
 * description に最も類似した教師データを最大 maxN 件選択して返す。
 * 類似度（Jaccard）降順でソート。
 * 根拠: Section 3.4 "教師データ（TrainingRecord）の活用パターン"
 */
export function selectFewShot(
  description: string,
  trainingRecords: TrainingRecord[],
  maxN: number = DEFAULT_MAX_FEW_SHOT,
): Array<TrainingRecord & { _similarity: number }> {
  return trainingRecords
    .map((r) => ({ ...r, _similarity: calcSimilarity(description, r.item) }))
    .sort((a, b) => b._similarity - a._similarity)
    .slice(0, maxN);
}

// ─── ラベル → AgentVerdict 変換 ──────────────────────────────────────────────

function labelToVerdict(label: string): AgentVerdict {
  if (label === '固定資産') return 'CAPITAL';
  if (label === '費用') return 'EXPENSE';
  return 'UNCERTAIN';
}

// ─── システムプロンプト構築 ──────────────────────────────────────────────────

/**
 * 教師データを few-shot として注入したシステムプロンプトを生成する。
 * 根拠: Section 3.4 few-shot examples の注入方法
 *   - /classify route の buildFewShotSection と同じ形式（CHECK-7b: 整合確認済み）
 */
function buildSystemPrompt(trainingRecords: TrainingRecord[]): string {
  const fewShotLines = trainingRecords.map((r) => {
    const verdict = labelToVerdict(r.label);
    const notesStr = r.notes ? ` / 備考: ${r.notes}` : '';
    return `- 品目: ${r.item} / ¥${r.amount.toLocaleString()} → ${verdict}（${r.label}）${notesStr}`;
  });

  const fewShotSection =
    fewShotLines.length > 0
      ? `\n【教師データ（Few-shot ${fewShotLines.length}件）】\n${fewShotLines.join('\n')}\n`
      : '';

  return `あなたは固定資産・経費の実務判定エージェントです。
過去の実務事例・教師データに基づき、各明細が固定資産（CAPITAL）・費用（EXPENSE）・判断保留（UNCERTAIN）のいずれかを判定してください。
${fewShotSection}
## 判定ルール（根拠: Section 3.4）
- 過去事例と類似している場合は同じ判定を優先する（企業実務・会計慣行を重視）
- 類似事例がない場合も状況から最善の判定を試みる
- 確信が持てない場合は UNCERTAIN を返す

## 出力フォーマット（JSON配列のみ出力。前後にテキスト不要）
[
  {
    "line_item_id": "li_001",
    "verdict": "CAPITAL",
    "rationale": "判断理由（日本語）",
    "suggested_account": "器具備品",
    "confidence": 0.85,
    "similar_cases": [
      { "description": "過去事例の品目名", "classification": "CAPITAL", "similarity": 0.8 }
    ]
  }
]

## フィールド仕様
- verdict: "CAPITAL" | "EXPENSE" | "UNCERTAIN" のいずれか
- similar_cases: 最大3件。similarity は 0〜1 の数値（根拠: Section 3.4 similar_cases 出力形式）
- suggested_account: 勘定科目名（教師データから推定。不明なら null）
- confidence: 0〜1 の確信度
- 全ての line_item_id に対して必ず判定を返すこと`;
}

// ─── リトライユーティリティ ────────────────────────────────────────────────

/** 指数バックオフリトライ用スリープ */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Practice Agent API 呼び出し（指数バックオフ、最大2リトライ）
 *
 * - attempt 0: 即実行
 * - attempt 1: 100ms 待機後
 * - attempt 2: 200ms 待機後
 * - 全て失敗 → throw（呼び出し元で UNCERTAIN フォールバック）
 */
async function callPracticeApiWithRetry(
  client: Anthropic,
  model: string,
  systemPrompt: string,
  userPrompt: string,
  timeoutMs: number,
): Promise<string> {
  const MAX_RETRIES = 2;
  let lastError: unknown;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const message = await client.messages.create(
        {
          model,
          max_tokens: 2048,
          system: systemPrompt,
          messages: [{ role: 'user', content: userPrompt }],
        },
        { signal: controller.signal },
      );
      clearTimeout(timer);
      const block = message.content.length > 0 ? message.content[0] : null;
      return block?.type === 'text' ? block.text : '';
    } catch (err) {
      clearTimeout(timer);
      lastError = err;
      console.warn(
        `[PracticeAgent] API呼び出し失敗 (attempt ${attempt + 1}/${MAX_RETRIES + 1}):`,
        err,
      );
      if (attempt < MAX_RETRIES) {
        await sleep(100 * Math.pow(2, attempt)); // 100ms → 200ms
      }
    }
  }
  throw lastError;
}

// ─── dry-run モック ──────────────────────────────────────────────────────────

/** ANTHROPIC_API_KEY 未設定時のモックデータ（UNCERTAIN 固定） */
function buildDryRunResults(lineItems: ExtractedLineItem[]): PracticeAgentResult[] {
  return lineItems.map((item) => ({
    line_item_id: item.line_item_id,
    verdict: 'UNCERTAIN' as AgentVerdict,
    rationale: '[dry-run] ANTHROPIC_API_KEY 未設定のためモックデータを返しています',
    similar_cases: [],
    suggested_account: null,
    confidence: 0,
  }));
}

// ─── UNCERTAIN フォールバック ────────────────────────────────────────────────

/** API 失敗 / パースエラー時の UNCERTAIN フォールバック */
function buildFallbackResults(
  lineItems: ExtractedLineItem[],
  reason: string,
): PracticeAgentResult[] {
  return lineItems.map((item) => ({
    line_item_id: item.line_item_id,
    verdict: 'UNCERTAIN' as AgentVerdict,
    rationale: reason,
    similar_cases: [],
    suggested_account: null,
    confidence: null,
  }));
}

// ─── レスポンスパース ────────────────────────────────────────────────────────

interface RawResult {
  line_item_id?: unknown;
  verdict?: unknown;
  rationale?: unknown;
  suggested_account?: unknown;
  confidence?: unknown;
  similar_cases?: unknown;
}

/**
 * LLM のレスポンステキストから JSON 配列を抽出し PracticeAgentResult[] に変換する。
 * 変換失敗時は例外を投げる（呼び出し元でキャッチして UNCERTAIN フォールバック）。
 */
export function parsePracticeResults(
  content: string,
  lineItems: ExtractedLineItem[],
): PracticeAgentResult[] {
  const jsonMatch = content.match(/\[[\s\S]*\]/);
  if (!jsonMatch) {
    throw new Error(`JSONパース失敗: 配列が見つかりません (content=${content.slice(0, 100)})`);
  }

  let parsed: RawResult[];
  try {
    parsed = JSON.parse(jsonMatch[0]) as RawResult[];
  } catch (e) {
    throw new Error(`JSONパース失敗: ${String(e)}`);
  }

  const validVerdicts = new Set<string>(['CAPITAL', 'EXPENSE', 'UNCERTAIN']);

  return lineItems.map((item) => {
    const raw = parsed.find((r) => r.line_item_id === item.line_item_id);

    if (!raw) {
      return {
        line_item_id: item.line_item_id,
        verdict: 'UNCERTAIN' as AgentVerdict,
        rationale: 'エージェントから判定が返りませんでした',
        similar_cases: [],
        suggested_account: null,
        confidence: 0,
      };
    }

    const verdictStr = String(raw.verdict ?? '');
    const verdict: AgentVerdict = validVerdicts.has(verdictStr)
      ? (verdictStr as AgentVerdict)
      : 'UNCERTAIN';

    // similar_cases の正規化（最大3件、similarity は [0,1] クランプ）
    const rawCases = Array.isArray(raw.similar_cases)
      ? (raw.similar_cases as Record<string, unknown>[])
      : [];
    const similar_cases: SimilarCase[] = rawCases.slice(0, 3).map((c) => ({
      description: String(c.description ?? ''),
      classification: validVerdicts.has(String(c.classification ?? ''))
        ? (String(c.classification) as AgentVerdict)
        : 'UNCERTAIN',
      similarity:
        typeof c.similarity === 'number'
          ? Math.min(1, Math.max(0, c.similarity))
          : 0,
    }));

    return {
      line_item_id: item.line_item_id,
      verdict,
      rationale: String(raw.rationale ?? ''),
      suggested_account:
        raw.suggested_account != null && raw.suggested_account !== ''
          ? String(raw.suggested_account)
          : null,
      confidence: typeof raw.confidence === 'number' ? raw.confidence : null,
      similar_cases,
    };
  });
}

// ─── メイン関数 ──────────────────────────────────────────────────────────────

/**
 * Practice Agent を実行する。
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.4
 *
 * @param lineItems       判定対象の明細一覧（Section 4.1 ExtractedLineItem）
 * @param trainingRecords 教師データ（few-shot の元データ）
 * @param config          実行設定（model / maxFewShot）
 * @returns PracticeAgentResult[] — 各明細の判定結果
 *
 * エラー耐性（根拠: Section 6 エラーハンドリング）:
 *   - ANTHROPIC_API_KEY 未設定 → dry-run モック（UNCERTAIN）を返す
 *   - API 呼び出し失敗          → 全明細を UNCERTAIN で返す
 *   - JSON パースエラー          → 全明細を UNCERTAIN で返す
 */
export async function runPracticeAgent(
  lineItems: ExtractedLineItem[],
  trainingRecords: TrainingRecord[],
  config: PracticeAgentConfig = {},
): Promise<PracticeAgentResult[]> {
  if (lineItems.length === 0) return [];

  const apiKey = process.env.ANTHROPIC_API_KEY;
  const model = config.model ?? process.env.PRACTICE_AGENT_MODEL ?? DEFAULT_MODEL;
  const maxFewShot = config.maxFewShot ?? DEFAULT_MAX_FEW_SHOT;
  const timeoutMs =
    parseInt(process.env.PRACTICE_AGENT_TIMEOUT_MS ?? '', 10) || PRACTICE_AGENT_DEFAULT_TIMEOUT_MS;

  // ─── dry-run モード（ANTHROPIC_API_KEY 未設定） ──────────────────────────
  if (!apiKey) {
    return buildDryRunResults(lineItems);
  }

  // ─── few-shot 選択 ───────────────────────────────────────────────────────
  // 全明細の description を結合して類似度スコアリング（シンプル実装）
  const allDescriptions = lineItems.map((i) => i.description).join(' ');
  const selectedRecords = selectFewShot(allDescriptions, trainingRecords, maxFewShot);

  const systemPrompt = buildSystemPrompt(selectedRecords);
  const userPrompt = `以下の明細を判定してください:\n${JSON.stringify(lineItems, null, 2)}`;

  const client = new Anthropic({ apiKey });

  // ─── API 呼び出し（リトライ付き） ────────────────────────────────────────
  let content: string;
  try {
    content = await callPracticeApiWithRetry(client, model, systemPrompt, userPrompt, timeoutMs);
  } catch (err) {
    console.error('[PracticeAgent] 全リトライ失敗:', err);
    return buildFallbackResults(lineItems, `APIエラー: ${String(err)}`);
  }

  // ─── レスポンスパース ────────────────────────────────────────────────────
  try {
    return parsePracticeResults(content, lineItems);
  } catch (parseErr) {
    console.error('[PracticeAgent] レスポンスパースエラー:', parseErr);
    return buildFallbackResults(lineItems, `パースエラー: ${String(parseErr)}`);
  }
}
