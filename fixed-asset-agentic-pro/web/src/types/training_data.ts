export type TrainingLabel = '固定資産' | '費用' | '要確認';

export interface TrainingRecord {
  item: string;        // 品目（必須）
  amount: number;      // 金額（必須、円）
  label: TrainingLabel; // 分類（必須）
  notes?: string;      // 備考（任意）
}

export interface CsvImportResult {
  records: TrainingRecord[];
  errorRows: Array<{ row: number; reason: string }>;
}
