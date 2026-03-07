"""Pipeline service - runs M1-M5 in background with progress tracking."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

# scripts/ をインポートパスに追加
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from m1_pdf_agent import extract_report  # noqa: E402
from m2_law_agent import load_law_context  # noqa: E402
from m3_gap_analysis_agent import analyze_gaps, GapItem as M3GapItem  # noqa: E402
from m4_proposal_agent import generate_proposals, ProposalSet  # noqa: E402
from m5_report_agent import generate_report, _m3_gap_to_m4_gap  # noqa: E402

from api.models.schemas import (
    PipelineStep,
    PipelineStatus,
    AnalysisResult,
    GapItemResponse,
    NoGapItemResponse,
    GapSummaryResponse,
    ProposalResponse,
    ProposalSetResponse,
)

logger = logging.getLogger(__name__)

PIPELINE_STEPS = [
    "M1: PDF解析",
    "M2: 法令取得",
    "M3: ギャップ分析",
    "M4: 提案生成",
    "M5: レポート統合",
]

# In-memory task store
_tasks: dict[str, PipelineStatus] = {}


def get_task(task_id: str) -> Optional[PipelineStatus]:
    return _tasks.get(task_id)


def create_task() -> str:
    task_id = str(uuid.uuid4())[:8]
    steps = [
        PipelineStep(step=i + 1, name=name, status="pending")
        for i, name in enumerate(PIPELINE_STEPS)
    ]
    _tasks[task_id] = PipelineStatus(
        task_id=task_id, status="queued", steps=steps
    )
    return task_id


def _update_step(task_id: str, step_idx: int, status: str, detail: str = "") -> None:
    task = _tasks.get(task_id)
    if not task:
        return
    task.steps[step_idx].status = status
    task.steps[step_idx].detail = detail
    task.current_step = step_idx + 1
    task.status = "running"


async def run_pipeline_async(
    task_id: str,
    pdf_path: str,
    company_name: str,
    fiscal_year: int,
    fiscal_month_end: int,
    level: str,
    use_mock: bool = True,
    doc_type: str = "yuho",
) -> None:
    """Execute the M1-M5 pipeline in a background thread."""
    task = _tasks.get(task_id)
    if not task:
        return

    try:
        # Set mock mode
        if use_mock:
            os.environ["USE_MOCK_LLM"] = "true"

        loop = asyncio.get_event_loop()

        # Step 1: M1 PDF解析
        _update_step(task_id, 0, "running")
        structured_report = await loop.run_in_executor(
            None,
            lambda: extract_report(
                pdf_path=pdf_path,
                company_name=company_name,
                fiscal_year=fiscal_year,
                fiscal_month_end=fiscal_month_end,
                doc_type=doc_type,
            ),
        )
        company_display = structured_report.company_name or company_name or "分析対象企業"
        _update_step(task_id, 0, "done", f"{len(structured_report.sections)}セクション検出")

        # Step 2: M2 法令取得
        _update_step(task_id, 1, "running")
        law_context = await loop.run_in_executor(
            None,
            lambda: load_law_context(
                fiscal_year=fiscal_year,
                fiscal_month_end=fiscal_month_end,
            ),
        )
        _update_step(task_id, 1, "done", f"{len(law_context.applicable_entries)}件の法令エントリ")

        # Step 3: M3 ギャップ分析
        _update_step(task_id, 2, "running")
        gap_result = await loop.run_in_executor(
            None,
            lambda: analyze_gaps(
                report=structured_report,
                law_context=law_context,
                use_mock=use_mock,
            ),
        )
        has_gap_count = sum(1 for g in gap_result.gaps if g.has_gap)
        _update_step(task_id, 2, "done", f"ギャップ{has_gap_count}件検出")

        # Step 4: M4 提案生成
        _update_step(task_id, 3, "running")
        proposals: list[ProposalSet] = []

        def _generate_proposals():
            for gap in gap_result.gaps:
                if gap.has_gap:
                    m4_gap = _m3_gap_to_m4_gap(gap)
                    ps = generate_proposals(m4_gap)
                    proposals.append(ps)

        await loop.run_in_executor(None, _generate_proposals)
        _update_step(task_id, 3, "done", f"{len(proposals)}件の提案セット")

        # Step 5: M5 レポート統合
        _update_step(task_id, 4, "running")
        report_md = await loop.run_in_executor(
            None,
            lambda: generate_report(
                structured_report=structured_report,
                law_context=law_context,
                gap_result=gap_result,
                proposal_set=proposals,
                level=level,
            ),
        )
        _update_step(task_id, 4, "done", f"{len(report_md)}文字のレポート")

        # Build result
        result = AnalysisResult(
            company_name=company_display,
            fiscal_year=fiscal_year,
            level=level,
            summary=GapSummaryResponse(
                total_gaps=gap_result.summary.total_gaps,
                by_change_type=gap_result.summary.by_change_type,
            ),
            gaps=[
                GapItemResponse(
                    gap_id=g.gap_id,
                    section_heading=g.section_heading,
                    change_type=g.change_type,
                    has_gap=g.has_gap,
                    disclosure_item=g.disclosure_item,
                    reference_law_title=g.reference_law_title,
                    reference_url=g.reference_url,
                    evidence_hint=g.evidence_hint,
                    confidence=g.confidence,
                    gap_description=g.gap_description,
                )
                for g in gap_result.gaps
            ],
            no_gap_items=[
                NoGapItemResponse(
                    disclosure_item=ng.disclosure_item,
                    reference_law_id=ng.reference_law_id,
                    evidence_hint=ng.evidence_hint,
                )
                for ng in gap_result.no_gap_items
            ],
            proposals=[
                ProposalSetResponse(
                    gap_id=ps.gap_id,
                    disclosure_item=ps.disclosure_item,
                    reference_law_id=ps.reference_law_id,
                    matsu=ProposalResponse(
                        level="松",
                        text=ps.matsu.text,
                        char_count=ps.matsu.quality.char_count,
                        status=ps.matsu.status,
                    ),
                    take=ProposalResponse(
                        level="竹",
                        text=ps.take.text,
                        char_count=ps.take.quality.char_count,
                        status=ps.take.status,
                    ),
                    ume=ProposalResponse(
                        level="梅",
                        text=ps.ume.text,
                        char_count=ps.ume.quality.char_count,
                        status=ps.ume.status,
                    ),
                )
                for ps in proposals
            ],
            report_markdown=report_md,
        )

        task.result = result
        task.status = "done"

    except Exception as e:
        logger.exception("Pipeline error for task %s", task_id)
        task.status = "error"
        task.error = str(e)
        # Mark current step as error
        for step in task.steps:
            if step.status == "running":
                step.status = "error"
                step.detail = str(e)
