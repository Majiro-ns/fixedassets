import type { Decision } from './classify';

// ─── ユーザー補正アクション ────────────────────────────────────────────
export type UserAction =
  | 'approved'         // AI判定をそのまま承認
  | 'changed_expense'  // 費用に変更
  | 'changed_capital'  // 固定資産に変更
  | 'manual_edit'      // 手入力で補正
  | 'pending';         // 未確定（初期値）

// ─── 補正状態を持つ明細 ───────────────────────────────────────────────
export interface LineItemWithAction {
  id: string;
  description: string;
  amount?: number;
  verdict: Decision;       // AIの判定結果
  confidence: number;      // 信頼度 0-1
  rationale?: string;      // 判定根拠
  userAction: UserAction;  // ユーザーのアクション（初期: 'pending'）
  finalVerdict: Decision;  // 確定後の判定（初期はverdict）
}

// ─── CSV エクスポート行 ────────────────────────────────────────────────
export interface CsvRow {
  品目名: string;
  金額: string;
  AI判定: string;
  確定判定: string;
  操作: string;
}
