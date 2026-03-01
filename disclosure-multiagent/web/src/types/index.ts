export interface CompanyInfo {
  edinet_code: string;
  sec_code: string;
  company_name: string;
  company_name_en: string;
  industry: string;
  listing: string;
}

export interface EdinetDocument {
  doc_id: string;
  edinet_code: string;
  filer_name: string;
  doc_type_code: string;
  period_end: string;
  submit_date_time: string;
}

export interface GapItem {
  gap_id: string;
  section_heading: string;
  change_type: string;
  has_gap: boolean | null;
  disclosure_item: string;
  reference_law_title: string;
  reference_url: string;
  evidence_hint: string;
  confidence: string;
  gap_description?: string;
}

export interface NoGapItem {
  disclosure_item: string;
  reference_law_id: string;
  evidence_hint: string;
}

export interface GapSummary {
  total_gaps: number;
  by_change_type: Record<string, number>;
}

export interface Proposal {
  level: string;
  text: string;
  char_count: number;
  status: string;
}

export interface ProposalSet {
  gap_id: string;
  disclosure_item: string;
  reference_law_id: string;
  matsu: Proposal;
  take: Proposal;
  ume: Proposal;
}

export interface AnalysisResult {
  company_name: string;
  fiscal_year: number;
  level: string;
  summary: GapSummary;
  gaps: GapItem[];
  no_gap_items: NoGapItem[];
  proposals: ProposalSet[];
  report_markdown: string;
}

export interface PipelineStep {
  step: number;
  name: string;
  status: 'pending' | 'running' | 'done' | 'error';
  detail: string;
}

export interface PipelineStatus {
  task_id: string;
  status: 'queued' | 'running' | 'done' | 'error';
  current_step: number;
  steps: PipelineStep[];
  result: AnalysisResult | null;
  error: string | null;
}
