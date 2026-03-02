/**
 * Split Judge 型定義（F-N09）
 * 根拠: cmd_170k_sub1 タスク仕様
 *
 * 一体資産(bundled) vs 個別計上(split) の判定結果型。
 * LLM実装への切り替えに対応するため、純粋な型定義ファイルとして分離。
 */

import type { ExtractedLineItem } from '@/types/classify_pdf_v2';

// ─── 判定値 ──────────────────────────────────────────────────────────────

/**
 * 分割判定の結果
 * - bundled: 一体資産として合計額で判定（例: PC+モニター+キーボード = 合計30万円で固定資産判定）
 * - split:   個別計上（各明細を独立して判定）
 */
export type SplitJudgment = 'bundled' | 'split';

// ─── グループ ─────────────────────────────────────────────────────────────

/**
 * 判定グループ（1件以上の明細を含む）
 * 根拠: 設計書 cmd_170k_sub1 出力仕様
 */
export interface SplitGroup {
  /** このグループに含まれる明細リスト */
  items: ExtractedLineItem[];

  /** 判定結果: bundled（一体資産）または split（個別計上） */
  judgment: SplitJudgment;

  /** 判定理由（日本語テキスト） */
  reason: string;

  /** グループ合計金額 */
  group_total: number;
}

// ─── 判定結果全体 ────────────────────────────────────────────────────────

/**
 * Split Judge の出力全体
 * 根拠: cmd_170k_sub1 出力仕様 `{ groups: [...] }`
 */
export interface SplitJudgeResult {
  groups: SplitGroup[];
}
