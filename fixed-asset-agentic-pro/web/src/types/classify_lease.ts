// ─── IFRS 16 リース会計 型定義 ────────────────────────────────────────
// 作成: subtask_108_frontend（足軽4）
// 注意: A3（subtask_108_backend）の classify_lease.ts と統合する際は
//       このファイルを上書きし、importパスを '@/types/classify_lease' に維持すること。

import type { Decision } from './classify';

// ─── LeaseType ─────────────────────────────────────────────────────────
export type LeaseType =
  | 'NOT_A_LEASE'       // リース識別なし（サービス契約）
  | 'EXEMPT_SHORT_TERM' // 短期リース免除（IFRS 16 §B34: ≤12ヶ月）
  | 'EXEMPT_LOW_VALUE'  // 少額資産リース免除（IFRS 16 BC100: ≤USD 5,000）
  | 'QUALIFYING_LEASE'; // 認識対象リース（ROU資産・リース負債計上）

// ─── LeaseClassifyRequest ──────────────────────────────────────────────
export interface LeaseClassifyRequest {
  // ── リース識別 ───────────────────────────────────────────────────────
  description: string;
  is_substitution_right_substantive?: boolean; // 供給者に実質的代替権あり → リースなし（§B14）

  // ── 期間・金額（必須）────────────────────────────────────────────────
  contract_term_months: number;  // 更新オプション考慮後の実質リース期間（月数）
  monthly_payment: number;       // 月額リース料（円）

  // ── 免除判定 ─────────────────────────────────────────────────────────
  asset_new_value_usd?: number;       // 原資産の新品時公正価値（USD）少額免除判定用
  has_purchase_option_certain?: boolean; // 購入オプション行使確実 → 短期免除不可

  // ── 測定インプット ───────────────────────────────────────────────────
  annual_ibr?: number;               // 追加借入利子率（年率: 例 0.03 = 3%）§26-28
  initial_direct_costs?: number;     // 当初直接費用（円）§24
  prepaid_lease_payments?: number;   // 前払リース料（円）§24
  restoration_cost_estimate?: number; // 原状回復費用見積（円）§24 / IAS 37
  lease_incentives_received?: number; // 受取リースインセンティブ（円）§24
}

// ─── LeaseClassifyResponse ─────────────────────────────────────────────
export interface LeaseClassifyResponse {
  // ── 判定結果 ─────────────────────────────────────────────────────────
  decision: Decision;       // 'CAPITAL_LIKE' | 'EXPENSE_LIKE' | 'GUIDANCE'
  lease_type: LeaseType;    // 上記4種別

  // ── 免除フラグ ───────────────────────────────────────────────────────
  is_short_term: boolean;
  is_low_value: boolean;

  // ── 測定結果（QUALIFYING_LEASE + CAPITAL_LIKE のみ）─────────────────
  lease_liability?: number; // 初期リース負債（円）§26
  rou_asset?: number;       // ROU資産初期帳簿価額（円）§24

  // ── 説明・根拠 ───────────────────────────────────────────────────────
  reasons: string[];
  confidence: number;        // 0.0〜1.0
  missing_fields: string[];  // 追加入力が必要なフィールド名
  disclaimer: string;
}
