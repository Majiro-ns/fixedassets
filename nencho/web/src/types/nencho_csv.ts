/**
 * nencho CSVインポート用型定義
 * CSVカラム → CalculateRequest フィールドのマッピング
 */

/** CSVの1行 = 1従業員分の教師データ */
export interface NenchoCsvRecord {
  /** 従業員名（必須） */
  employee_name: string;
  /** 給与収入（年間・円）（必須） */
  salary_income: number;
  /** 社会保険料（年間・円）（必須） */
  social_insurance_paid: number;
  /** 扶養人数（任意・デフォルト0） */
  dependent_count?: number;
  /** 新契約生命保険料（円）（任意） */
  life_insurance_new?: number;
  /** 旧契約生命保険料（円）（任意） */
  life_insurance_old?: number;
  /** 配偶者あり（任意） */
  has_spouse?: boolean;
  /** 備考（任意） */
  notes?: string;
}

/** CSVパース結果 */
export interface NenchoCsvImportResult {
  records: NenchoCsvRecord[];
  errorRows: Array<{ row: number; reason: string }>;
}
