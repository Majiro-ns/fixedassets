/**
 * マルチエージェント判定の型定義
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.3/3.4/3.5/4.2
 */

// ─── エージェント内部 verdict ────────────────────────────────────────────────

/**
 * エージェントの生出力 verdict（正規化前）
 * 根拠: Section 1.2 判定値の用語対応
 *   CAPITAL/EXPENSE は内部表現 → CAPITAL_LIKE/EXPENSE_LIKE に正規化して UI へ返す
 */
export type AgentVerdict = 'CAPITAL' | 'EXPENSE' | 'UNCERTAIN';

/**
 * 正規化後の最終 verdict（UI / ClassifyResponse と統一）
 * 根拠: Section 1.2 — CAPITAL_LIKE / EXPENSE_LIKE / GUIDANCE
 */
export type FinalVerdict = 'CAPITAL_LIKE' | 'EXPENSE_LIKE' | 'GUIDANCE';

// ─── Tax Agent ───────────────────────────────────────────────────────────────

/**
 * Tax Agent の明細単位出力
 * 根拠: Section 4.2 Tax Agent 出力スキーマ
 */
export interface TaxAgentResult {
  line_item_id: string;
  verdict: AgentVerdict;

  /**
   * 勘定科目名（例: 建物附属設備, 器具備品, 修繕費）
   * 根拠: Section 3.3 勘定科目判定（CAPITAL/EXPENSE 時に出力）
   */
  account_category?: string | null;

  /**
   * 法定耐用年数（年）。EXPENSE 判定時は null
   * 根拠: Section 3.3 勘定科目判定
   */
  useful_life?: number | null;

  /**
   * 根拠条文番号（例: "法人税法施行令第132条", "基通7-8-3(1)"）
   * 根拠: Section 4.2 Tax Agent 出力 article_ref（必須）
   */
  article_ref?: string | null;

  /**
   * 資本的支出 vs 修繕費 形式基準の適用ステップ番号（1〜6）
   * 根拠: Section 3.3 資本的支出 vs 修繕費の形式基準（Step 1〜6）
   */
  formal_criteria_step?: number | null;

  rationale: string;
  confidence?: number | null;
}

// ─── Practice Agent ──────────────────────────────────────────────────────────

/**
 * Practice Agent が参照する類似事例
 * 根拠: Section 4.2 Practice Agent 出力 similar_cases
 */
export interface SimilarCase {
  description: string;
  classification: AgentVerdict;
  similarity: number; // 0-1
}

/**
 * Practice Agent の明細単位出力
 * 根拠: Section 4.2 Practice Agent 出力スキーマ
 */
export interface PracticeAgentResult {
  line_item_id: string;
  verdict: AgentVerdict;
  similar_cases: SimilarCase[];

  /**
   * 過去事例での勘定科目（教師データから）
   * 根拠: Section 4.2 Practice Agent 出力 suggested_account（Tax 側と突合用）
   */
  suggested_account?: string | null;

  rationale: string;
  confidence?: number | null;
}

// ─── Aggregator ──────────────────────────────────────────────────────────────

/**
 * 合議判定結果（Aggregator 出力）
 * 根拠: Section 3.5 Aggregator 合議判定
 */
export interface AggregatedResult {
  line_item_id: string;

  /** 正規化済み最終 verdict */
  final_verdict: FinalVerdict;

  /**
   * 信頼度（0.95 / 0.80 / 0.50 / 0.30 の 4 値）
   * 根拠: Section 3.5 信頼度算出式
   *   一致 → 0.95 / 片方 UNCERTAIN → 0.80 / 分裂 → 0.50 / 両方 UNCERTAIN → 0.30
   */
  confidence: number;

  /**
   * 採用する勘定科目（Tax 優先、Tax 不明時は Practice の suggested_account）
   * 根拠: Section 3.5 勘定科目の合議ルール
   */
  account_category: string | null;

  /**
   * 法定耐用年数（Tax Agent の値を正とする）
   * 根拠: Section 3.5 "耐用年数は Tax Agent の値を正とする（法定耐用年数は税法根拠のため）"
   */
  useful_life: number | null;

  /** 元の Tax Agent 結果（Agent 失敗時は null） */
  tax_result: TaxAgentResult | null;

  /** 元の Practice Agent 結果（Agent 失敗時は null） */
  practice_result: PracticeAgentResult | null;

  /** 分裂時の理由（Tax:CAPITAL vs Practice:EXPENSE 等） */
  disagreement_reason?: string;
}
