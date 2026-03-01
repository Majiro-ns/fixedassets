"""EDINET API wrapper service - wraps scripts/m7_edinet_client.py."""
from __future__ import annotations

import sys
from pathlib import Path

# scripts/ をインポートパスに追加
_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from m7_edinet_client import (  # noqa: E402
    fetch_document_list,
    download_pdf,
    search_by_company,
    validate_doc_id,
)

from api.models.schemas import EdinetDocument


def get_documents_by_date(date: str, doc_type: str = "120") -> list[EdinetDocument]:
    """日付指定でEDINET書類一覧を取得."""
    raw = fetch_document_list(date, doc_type)
    return [
        EdinetDocument(
            doc_id=d.get("docID", ""),
            edinet_code=d.get("edinetCode", ""),
            filer_name=d.get("filerName", ""),
            doc_type_code=d.get("docTypeCode", ""),
            period_end=d.get("periodEnd", ""),
            submit_date_time=d.get("submitDateTime", ""),
        )
        for d in raw
    ]


def download_document_pdf(doc_id: str, output_dir: str = "/tmp/edinet_pdfs") -> str:
    """書類管理番号でPDFをダウンロード."""
    return download_pdf(doc_id, output_dir)


def search_documents_by_company(company_name: str, year: int) -> list[EdinetDocument]:
    """会社名・年度で有報を検索."""
    raw = search_by_company(company_name, year)
    return [
        EdinetDocument(
            doc_id=d.get("docID", ""),
            edinet_code=d.get("edinetCode", ""),
            filer_name=d.get("filerName", ""),
            doc_type_code=d.get("docTypeCode", ""),
            period_end=d.get("periodEnd", ""),
            submit_date_time=d.get("submitDateTime", ""),
        )
        for d in raw
    ]
