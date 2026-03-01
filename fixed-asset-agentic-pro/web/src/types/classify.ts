export type Decision = 'CAPITAL_LIKE' | 'EXPENSE_LIKE' | 'GUIDANCE';

export interface ClassifyRequest {
  description: string;
  amount?: number;
  account?: string;
  answers?: Record<string, string>;
}

export interface LineItem {
  description: string;
  amount?: number;
  classification: Decision;
  flags?: string[];
  ai_hint?: string;
}

export interface ClassifyResponse {
  decision: Decision;
  reasons: string[];
  evidence: Record<string, unknown>[];
  questions: string[];
  metadata: Record<string, unknown>;
  is_valid_document: boolean;
  confidence: number;
  error_code?: string;
  trace: string[];
  missing_fields: string[];
  why_missing_matters: string[];
  citations: Record<string, unknown>[];
  useful_life?: Record<string, unknown>;
  line_items: LineItem[];
  disclaimer: string;
}

export interface HistoryEntry {
  request: ClassifyRequest;
  response: ClassifyResponse;
  timestamp: string; // ISO 8601
}
