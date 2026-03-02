/**
 * /v2/classify_pdf API 型定義
 * 根拠: 設計書 DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 5.2
 */

// ─── リクエスト ────────────────────────────────────────────────────────────

export interface ClassifyPDFV2Options {
  include_audit_trail: boolean;
  parallel_agents: boolean;
}

export interface ClassifyPDFV2Request {
  pdf_base64: string;                // PDF バイナリの base64 エンコード
  company_id: string | null;         // 会社識別子（教師データ参照用）
  options: ClassifyPDFV2Options;
  /** クライアント別ポリシー ID（cmd_170k_sub2 F-10: ポリシー管理）
   *  指定された場合、PolicyStore からポリシーを読み込んで判定閾値に使用する。 */
  policy_id?: number;
}

// ─── 抽出結果 ──────────────────────────────────────────────────────────────

export interface ExtractedLineItem {
  line_item_id: string;
  description: string;
  amount: number;
  quantity?: number;
}

export interface ExtractedLineItems {
  document_date?: string;   // YYYY-MM-DD
  vendor?: string;
  items: ExtractedLineItem[];
}

// ─── 明細判定結果 ──────────────────────────────────────────────────────────

export type V2Verdict = 'CAPITAL_LIKE' | 'EXPENSE_LIKE' | 'GUIDANCE';
export type V2Status = 'success' | 'partial' | 'extraction_failed';

/** Section 5.2: line_results の各要素 */
export interface LineResultV2 {
  line_item_id: string;
  verdict: V2Verdict;
  confidence: number;                 // 0.0 〜 1.0
  account_category: string | null;
  useful_life: number | null;         // 耐用年数（年）
  tax_verdict: string;                // Tax Agent の判定
  tax_rationale: string;              // Tax Agent の根拠
  tax_account: string | null;
  practice_verdict: string;           // Practice Agent の判定
  practice_rationale: string;
  practice_account: string | null;
  similar_cases: string[];            // 類似事例 ID
}

// ─── サマリー ──────────────────────────────────────────────────────────────

export interface ByAccountSummary {
  account_category: string;
  count: number;
  total_amount: number;
}

export interface V2Summary {
  capital_total: number;
  expense_total: number;
  guidance_total: number;
  by_account: ByAccountSummary[];
}

// ─── レスポンス全体 ────────────────────────────────────────────────────────

/** Section 5.2: POST /v2/classify_pdf レスポンス */
export interface ClassifyPDFV2Response {
  request_id: string;
  status: V2Status;
  extracted: ExtractedLineItems | null;   // extraction_failed 時は null
  line_results: LineResultV2[];           // extraction_failed 時は []
  summary: V2Summary;
  audit_trail_id: string | null;
  elapsed_ms: number;
  /**
   * Phase 3 F-N09: 分割判定結果（Split Judge）
   * 一体資産(bundled) vs 個別計上(split) の判定グループ一覧。
   * extraction_failed 時は undefined（後方互換のため optional）。
   */
  split_groups?: import('@/types/split_judge').SplitGroup[];
}
