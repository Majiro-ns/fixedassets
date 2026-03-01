"""EDINET related endpoints - company search, document listing, PDF download."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from api.models.schemas import (
    CompanySearchResponse,
    EdinetDocumentsResponse,
)
from api.services.company_service import (
    search_by_sec_code,
    search_by_edinet_code,
    search_by_name,
)
from api.services.edinet_service import (
    get_documents_by_date,
    download_document_pdf,
)

router = APIRouter(prefix="/api/edinet", tags=["edinet"])


@router.get("/search", response_model=CompanySearchResponse)
async def search_company(
    sec_code: str = Query(None, description="証券コード (4桁)"),
    edinet_code: str = Query(None, description="EDINETコード"),
    name: str = Query(None, description="企業名 (部分一致)"),
    limit: int = Query(20, ge=1, le=100),
):
    """証券コード・EDINETコード・企業名で企業を検索."""
    if sec_code:
        results = search_by_sec_code(sec_code)
    elif edinet_code:
        info = search_by_edinet_code(edinet_code)
        results = [info] if info else []
    elif name:
        results = search_by_name(name, limit=limit)
    else:
        raise HTTPException(400, "sec_code, edinet_code, or name is required")

    return CompanySearchResponse(results=results[:limit], total=len(results))


@router.get("/documents", response_model=EdinetDocumentsResponse)
async def get_documents(
    date: str = Query(..., description="検索日 (YYYY-MM-DD)"),
    doc_type: str = Query("120", description="書類種別コード (120=有報)"),
):
    """日付指定でEDINET書類一覧を取得."""
    docs = get_documents_by_date(date, doc_type)
    return EdinetDocumentsResponse(documents=docs, total=len(docs))


@router.get("/download/{doc_id}")
async def download_pdf(doc_id: str):
    """書類管理番号でPDFをダウンロード."""
    try:
        pdf_path = download_document_pdf(doc_id)
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=f"{doc_id}.pdf",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
