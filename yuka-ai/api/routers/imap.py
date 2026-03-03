"""IMAP router - メールボックス自動取得（T005b / F-18）."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.models.schemas import (
    ImapFetchRequest,
    ImapFetchResponse,
    ImapFetchedEmail,
    ParsedEmailItem,
)

router = APIRouter(prefix="/api/imap", tags=["imap"])


@router.post("/fetch", response_model=ImapFetchResponse)
async def fetch_imap_emails(req: ImapFetchRequest):
    """メールボックスから請求書・発注確認メールを自動取得する。

    - dry_run=true (デフォルト): モックデータを返す（IMAP設定不要）
    - dry_run=false: 環境変数 IMAP_HOST/IMAP_USER/IMAP_PASSWORD でIMAP接続
    """
    try:
        from imap_fetcher import fetch_invoice_emails, ImapConfig

        config = ImapConfig.from_env()
        result = fetch_invoice_emails(
            config=config,
            limit=req.limit,
            subject_filter=req.subject_filter,
            dry_run=req.dry_run,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IMAP取得エラー: {e}")

    emails = [
        ImapFetchedEmail(
            subject=e.subject,
            sender=e.sender,
            body=e.body,
            order_number=e.order_number,
            delivery_date=e.delivery_date,
            extracted_items=[
                ParsedEmailItem(
                    part_number=item["part_number"],
                    quantity=item.get("quantity"),
                )
                for item in e.extracted_items
            ],
            source=e.source,
        )
        for e in result.emails
    ]

    return ImapFetchResponse(
        emails=emails,
        fetched_count=result.fetched_count,
        mode=result.mode,
        error=result.error,
    )
