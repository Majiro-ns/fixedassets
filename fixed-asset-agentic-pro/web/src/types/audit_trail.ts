/**
 * Audit Trail 型定義
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Phase 2 Audit Trail基盤
 */

// ─── AuditRecord ──────────────────────────────────────────────────────────────

/**
 * 1回の判定実行を記録する監査証跡レコード
 * 根拠: Phase 2 Audit Trail基盤 — append 後に GET /api/v2/audit_trail/:id で取得可能にする
 */
export interface AuditRecord {
  /** 監査証跡ID（classify_pdf レスポンスの audit_trail_id と一致） */
  audit_trail_id: string;

  /** 内部リクエスト UUID */
  request_id: string;

  /** 記録日時（ISO 8601） */
  timestamp: string;

  /** PDF ファイル名 */
  pdf_filename: string;

  /** 判定対象の明細件数 */
  line_items_count: number;

  /** Tax Agent の判定結果（第1明細の代表値） */
  tax_verdict: string;

  /** Practice Agent の判定結果（第1明細の代表値） */
  practice_verdict: string;

  /** 最終判定結果（Aggregator 出力の第1明細） */
  final_verdict: string;

  /** 信頼度（0.0 〜 1.0） */
  confidence: number;

  /** 勘定科目（null = 未確定） */
  account_category: string | null;

  /** 法定耐用年数（年。null = 費用計上） */
  useful_life: number | null;

  /** 処理時間（ミリ秒） */
  elapsed_ms: number;

  /** 使用モデル識別子 */
  model_used: string;
}

// ─── AuditStore ───────────────────────────────────────────────────────────────

/**
 * Audit Trail ストアのインターフェース
 * Phase 2 MVP はインメモリ実装。将来的に DB / Redis 等に差し替え可能。
 */
export interface AuditStore {
  /** レコードを追加する */
  append(record: AuditRecord): void;

  /** audit_trail_id でレコードを取得する。見つからない場合は null */
  getById(id: string): AuditRecord | null;

  /** 最新順でレコードを取得する（limit 省略時は全件） */
  list(limit?: number): AuditRecord[];
}
