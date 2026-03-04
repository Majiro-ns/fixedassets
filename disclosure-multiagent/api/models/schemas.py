"""Pydantic schemas for disclosure-multiagent REST API."""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional


# ── Company / EDINET Search ──────────────────────────────

class CompanyInfo(BaseModel):
    edinet_code: str = Field(..., description="EDINETコード (E+5桁)")
    sec_code: str = Field(..., description="証券コード (4桁+0)")
    company_name: str = Field(..., description="提出者名")
    company_name_en: str = Field("", description="提出者名（英語表記）")
    industry: str = Field("", description="業種")
    listing: str = Field("", description="上場区分")


class CompanySearchResponse(BaseModel):
    results: list[CompanyInfo]
    total: int


# ── EDINET Document ──────────────────────────────────────

class EdinetDocument(BaseModel):
    doc_id: str
    edinet_code: str
    filer_name: str
    doc_type_code: str
    period_end: str
    submit_date_time: str


class EdinetDocumentsResponse(BaseModel):
    documents: list[EdinetDocument]
    total: int


# ── Analysis Request / Response ──────────────────────────

class AnalyzeRequest(BaseModel):
    edinet_code: Optional[str] = None
    sec_code: Optional[str] = None
    company_name: str = ""
    fiscal_year: int = 2025
    fiscal_month_end: int = 3
    level: str = Field("竹", pattern=r"^(松|竹|梅)$")
    pdf_doc_id: Optional[str] = None
    use_mock: bool = True


class AnalyzeResponse(BaseModel):
    task_id: str
    status: str = "queued"
    message: str = "パイプライン起動受付完了"


# ── Pipeline Status (SSE) ────────────────────────────────

class PipelineStep(BaseModel):
    step: int
    name: str
    status: str  # "pending" | "running" | "done" | "error"
    detail: str = ""


class PipelineStatus(BaseModel):
    task_id: str
    status: str  # "queued" | "running" | "done" | "error"
    current_step: int = 0
    steps: list[PipelineStep] = []
    result: Optional[AnalysisResult] = None
    error: Optional[str] = None


# ── Analysis Result ──────────────────────────────────────

class GapItemResponse(BaseModel):
    gap_id: str
    section_heading: str
    change_type: str
    has_gap: Optional[bool]
    disclosure_item: str
    reference_law_title: str
    reference_url: str
    evidence_hint: str
    confidence: str
    gap_description: Optional[str] = None


class NoGapItemResponse(BaseModel):
    disclosure_item: str
    reference_law_id: str
    evidence_hint: str


class GapSummaryResponse(BaseModel):
    total_gaps: int
    by_change_type: dict[str, int]


class ProposalResponse(BaseModel):
    level: str
    text: str
    char_count: int
    status: str


class ProposalSetResponse(BaseModel):
    gap_id: str
    disclosure_item: str
    reference_law_id: str
    matsu: ProposalResponse
    take: ProposalResponse
    ume: ProposalResponse


class AnalysisResult(BaseModel):
    company_name: str
    fiscal_year: int
    level: str
    summary: GapSummaryResponse
    gaps: list[GapItemResponse]
    no_gap_items: list[NoGapItemResponse]
    proposals: list[ProposalSetResponse]
    report_markdown: str


# Forward reference resolution
PipelineStatus.model_rebuild()


# ── Checklist (実務判断データ蓄積) ──────────────────────────

class ChecklistItem(BaseModel):
    """開示チェックリスト1項目"""
    id: str = Field(..., description="チェックリストID (例: CL-001)")
    category: str = Field(..., description="大分類 (例: 固定資産)")
    subcategory: str = Field(..., description="小分類 (例: 減損)")
    item: str = Field(..., description="開示項目名")
    required: bool = Field(..., description="必須開示かどうか")
    standard: str = Field(..., description="根拠基準 (例: 企業会計基準第9号 / IAS36)")
    trigger: str = Field(..., description="開示が必要となるトリガー条件")
    description: str = Field(..., description="開示内容の説明")
    keywords: list[str] = Field(default_factory=list, description="検索キーワード")


class ChecklistResponse(BaseModel):
    """GET /api/checklist レスポンス"""
    version: str
    last_updated: str
    source: str
    total: int
    items: list[ChecklistItem]


class ValidateRequest(BaseModel):
    """POST /api/checklist/validate リクエスト"""
    disclosure_text: str = Field(..., description="照合対象の開示テキスト（報告書本文等）")
    categories: Optional[list[str]] = Field(
        None,
        description="照合対象カテゴリ絞り込み（省略時は全カテゴリ）"
    )
    required_only: bool = Field(
        False,
        description="True の場合、required=true の項目のみ照合"
    )


class ChecklistMatchResult(BaseModel):
    """1項目の照合結果"""
    id: str
    category: str
    item: str
    required: bool
    matched: bool = Field(..., description="テキスト内にキーワードが含まれるかどうか")
    matched_keywords: list[str] = Field(default_factory=list, description="マッチしたキーワード")
    standard: str


class ValidateResponse(BaseModel):
    """POST /api/checklist/validate レスポンス"""
    total_checked: int = Field(..., description="照合した項目数")
    matched_count: int = Field(..., description="キーワードがマッチした項目数")
    unmatched_required_count: int = Field(..., description="未検出の必須項目数")
    coverage_rate: float = Field(..., description="カバー率 (0.0〜1.0)")
    results: list[ChecklistMatchResult]
    unmatched_required_ids: list[str] = Field(
        default_factory=list,
        description="未検出の必須項目ID一覧（要確認リスト）"
    )


# ── Checklist Evaluation History（評価履歴・バッチ評価 T010）────────────────────

class EvaluateRequest(BaseModel):
    """POST /api/checklist/evaluate リクエスト"""
    disclosure_text: str = Field(..., description="照合対象の開示テキスト")
    categories: Optional[list[str]] = Field(
        None,
        description="照合対象カテゴリ絞り込み（省略時は全カテゴリ）"
    )
    required_only: bool = Field(False, description="True の場合、required=true の項目のみ照合")


class EvaluateSummary(BaseModel):
    """評価サマリ（履歴一覧・POST レスポンスで使用）"""
    eval_id: str = Field(..., description="評価ID（UUID4）")
    evaluated_at: str = Field(..., description="評価日時（ISO 8601）")
    text_snippet: str = Field(..., description="開示テキスト先頭200字")
    total_checked: int = Field(..., description="照合項目数")
    matched_count: int = Field(..., description="マッチ項目数")
    unmatched_required_count: int = Field(..., description="未検出の必須項目数")
    coverage_rate: float = Field(..., description="カバー率 (0.0〜1.0)")


class EvaluateResponse(EvaluateSummary):
    """POST /api/checklist/evaluate レスポンス（サマリと同一フィールド）"""


class EvaluationsListResponse(BaseModel):
    """GET /api/checklist/evaluations レスポンス"""
    evaluations: list[EvaluateSummary]
    count: int


class EvaluationDetailResponse(EvaluateSummary):
    """GET /api/checklist/evaluations/{eval_id} レスポンス"""
    results: list[ChecklistMatchResult]
    unmatched_required_ids: list[str] = Field(default_factory=list)
