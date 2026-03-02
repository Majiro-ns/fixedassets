/**
 * クライアント別ポリシー型定義
 * 根拠: cmd_170k_sub2 Phase 3 クライアント別ポリシー管理（F-10）
 */

/** クライアント別判定ポリシー */
export interface Policy {
  id: number;
  /** クライアント名（一意） */
  client_name: string;
  /** 固定資産とみなす閾値（円）。この金額以上は固定資産候補 */
  threshold_amount: number;
  /** カスタムキーワード（修繕判定等に使用） */
  keywords: string[];
  /** 追加ルール（将来拡張用 JSON） */
  rules: Record<string, unknown>;
  /** 作成日時（ISO 8601） */
  created_at: string;
  /** 更新日時（ISO 8601） */
  updated_at: string;
}

/** ポリシー作成リクエスト */
export interface CreatePolicyInput {
  client_name: string;
  threshold_amount?: number;
  keywords?: string[];
  rules?: Record<string, unknown>;
}

/** ポリシー更新リクエスト */
export interface UpdatePolicyInput {
  client_name?: string;
  threshold_amount?: number;
  keywords?: string[];
  rules?: Record<string, unknown>;
}

/** SQLite 行型（DB から直接読んだ raw データ） */
export interface PolicyRow {
  id: number;
  client_name: string;
  threshold_amount: number;
  keywords_json: string;
  rules_json: string;
  created_at: string;
  updated_at: string;
}
