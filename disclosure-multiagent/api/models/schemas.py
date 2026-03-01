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
