"""Analysis pipeline endpoints."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from typing import Optional

from api.auth import verify_api_key
from api.models.schemas import AnalyzeRequest, AnalyzeResponse
from api.services.pipeline import create_task, run_pipeline_async
from api.services.edinet_service import download_document_pdf
from api.services.company_service import get_edinet_code_for_sec_code

router = APIRouter(prefix="/api", tags=["analyze"])

_UPLOAD_DIR = Path("/tmp/disclosure_uploads")
_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@router.post("/analyze", response_model=AnalyzeResponse)
async def start_analysis(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    _auth: None = Depends(verify_api_key),
):
    """パイプライン起動 - task_idを即返却し、バックグラウンドで処理."""
    task_id = create_task()

    # Resolve PDF path
    pdf_path = ""
    if request.pdf_doc_id:
        try:
            pdf_path = download_document_pdf(request.pdf_doc_id)
        except Exception as e:
            raise HTTPException(400, f"PDF取得失敗: {e}")
    else:
        # Use mock sample PDF for demo
        scripts_dir = Path(__file__).parent.parent.parent / "scripts"
        samples_dir = scripts_dir.parent / "10_Research" / "samples"
        sample = samples_dir / "company_a.pdf"
        if sample.exists():
            pdf_path = str(sample)
        else:
            # Create a minimal placeholder for mock mode
            pdf_path = str(sample)

    # Resolve company name from sec_code if needed
    company_name = request.company_name
    if not company_name and request.sec_code:
        from api.services.company_service import search_by_sec_code
        results = search_by_sec_code(request.sec_code)
        if results:
            company_name = results[0].company_name

    background_tasks.add_task(
        run_pipeline_async,
        task_id=task_id,
        pdf_path=pdf_path,
        company_name=company_name,
        fiscal_year=request.fiscal_year,
        fiscal_month_end=request.fiscal_month_end,
        level=request.level,
        use_mock=request.use_mock,
        doc_type=request.doc_type_code.value,
    )

    return AnalyzeResponse(task_id=task_id)


@router.post("/analyze/upload", response_model=AnalyzeResponse)
async def start_analysis_with_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    company_name: str = Form(""),
    fiscal_year: int = Form(2025),
    fiscal_month_end: int = Form(3),
    level: str = Form("竹"),
    use_mock: bool = Form(True),
    _auth: None = Depends(verify_api_key),
):
    """PDF直接アップロードでパイプライン起動."""

    # ── バリデーション（3段階 + サイズ上限）──────────────────────────

    # 1. 拡張子チェック（.pdf のみ許可）
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF files are accepted.",
        )

    # 2. Content-Type チェック（application/pdf のみ許可）
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF files are accepted.",
        )

    # 3. ファイル内容を読み込み（サイズ・マジックバイト検証用）
    content = await file.read()

    # 4. ファイルサイズ上限（20MB）
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum size is 20MB.",
        )

    # 5. マジックバイトチェック（先頭4バイトが %PDF であること）
    if not content.startswith(b"%PDF"):
        raise HTTPException(
            status_code=400,
            detail="File content does not match PDF format.",
        )

    # ── ファイル保存 ──────────────────────────────────────────────
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    task_id = create_task()
    pdf_path = _UPLOAD_DIR / f"{task_id}_{filename}"

    with open(pdf_path, "wb") as f:
        f.write(content)

    background_tasks.add_task(
        run_pipeline_async,
        task_id=task_id,
        pdf_path=str(pdf_path),
        company_name=company_name,
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
        level=level,
        use_mock=use_mock,
    )

    return AnalyzeResponse(task_id=task_id)
