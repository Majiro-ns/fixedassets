"""OCR router - PDF/画像からのテキスト抽出（T005b / F-19）."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File

from api.models.schemas import (
    OcrExtractRequest,
    OcrExtractResponse,
    OcrExtractedItem,
)

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


@router.post("/extract", response_model=OcrExtractResponse)
async def extract_from_file_path(req: OcrExtractRequest):
    """ファイルパスを指定してOCRテキストを抽出する。

    - force_mock=true: モックデータを返す（OCRエンジン不要）
    - force_mock=false: pdfplumber (PDF) または pytesseract (画像) を使用
    """
    try:
        from ocr_extractor import extract_text_from_file

        result = extract_text_from_file(
            file_path=req.file_path,
            force_mock=req.force_mock,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR処理エラー: {e}")

    return OcrExtractResponse(
        raw_text=result.raw_text,
        order_number=result.order_number,
        delivery_date=result.delivery_date,
        items=[
            OcrExtractedItem(
                part_number=item["part_number"],
                quantity=item.get("quantity"),
            )
            for item in result.items
        ],
        source_file=result.source_file,
        engine=result.engine,
        page_count=result.page_count,
        error=result.error,
    )


@router.post("/extract/upload", response_model=OcrExtractResponse)
async def extract_from_upload(
    file: UploadFile = File(...),
    force_mock: bool = False,
):
    """アップロードされたファイル（PDF/画像）からOCRテキストを抽出する。

    - force_mock=true: モックデータを返す（OCRエンジン不要）
    - force_mock=false: pdfplumber (PDF) または pytesseract (画像) を使用
    """
    try:
        from ocr_extractor import extract_text_from_bytes

        content = await file.read()
        filename = file.filename or "document.pdf"

        result = extract_text_from_bytes(
            content=content,
            filename=filename,
            force_mock=force_mock,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCRアップロード処理エラー: {e}")

    return OcrExtractResponse(
        raw_text=result.raw_text,
        order_number=result.order_number,
        delivery_date=result.delivery_date,
        items=[
            OcrExtractedItem(
                part_number=item["part_number"],
                quantity=item.get("quantity"),
            )
            for item in result.items
        ],
        source_file=result.source_file,
        engine=result.engine,
        page_count=result.page_count,
        error=result.error,
    )
