// ─── 減価償却計算 型定義 ──────────────────────────────────────────────────
// 対応バックエンド: POST /calculate_depreciation
// 根拠法令: 法人税法施行令第48条・第48条の2・第133条・第133条の2 / 租税特別措置法第67条の5

// ─── DepreciationRequest ────────────────────────────────────────────────
export interface DepreciationRequest {
  acquisition_cost: number;           // 取得価額（円）
  acquisition_date: string;           // 取得日（YYYY-MM-DD）
  useful_life: number;                // 耐用年数（年）
  method: 'declining_balance' | 'straight_line'; // 償却方法（定率法 / 定額法）
  is_sme_blue?: boolean;              // 中小企業青色申告フラグ
  calculate_asset_tax?: boolean;      // 償却資産税計算フラグ
}

// ─── SpecialTreatment ────────────────────────────────────────────────────
export interface SpecialTreatment {
  type: string;             // 例: "少額減価償却資産", "一括償却資産"
  treatment: string;        // 例: "全額損金算入（当期費用処理）"
  basis: string;            // 例: "法人税法施行令第133条"
  depreciation_years?: number;
  annual_amount?: number;   // 一括償却資産の年間均等額
  note?: string;            // 例: "青色申告法人・年間合計300万円まで"
}

// ─── DepreciationAnnualEntry ─────────────────────────────────────────────
export interface DepreciationAnnualEntry {
  year: number;
  depreciation: number;         // 当期償却額（円）
  book_value_end: number;       // 期末帳簿価額（円）
  asset_tax_value?: number;     // 償却資産税評価額（円）
  asset_tax_amount?: number;    // 償却資産税額（円）
}

// ─── DepreciationResponse ────────────────────────────────────────────────
export interface DepreciationResponse {
  special_treatment?: SpecialTreatment; // 特例区分（該当する場合のみ）
  annual_schedule: DepreciationAnnualEntry[];
  total_depreciation: number;  // 耐用年数終了時の総償却額（円）
  tax_basis: string;           // 根拠法令（例: "法人税法施行令第48条の2 (200%定率法)"）
}
