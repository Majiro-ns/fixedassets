"""ocr_extractor.py - OCR連携モジュール（T005b / F-19）

PDF・画像ファイルから文字を抽出する。

実装スコープ:
    - pytesseractによるOCR（インストール済みの場合）
    - pdfplumberによるPDFテキスト抽出（既存の依存関係）
    - mockableインターフェース（実際のOCRエンジンなしでテスト可能）
    - 抽出テキストからの発注情報抽出（email_parser との統合）

依存関係（オプション）:
    - pytesseract + Tesseract OCR（画像OCR）
    - pdfplumber（PDF テキスト抽出、requirements.txt に記載済み）
    - Pillow（画像処理）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from email_parser import (
    EmailData,
    _extract_delivery_date,
    _extract_items,
    _extract_order_number,
)


# ---------------------------------------------------------------------------
# OCR 結果データクラス
# ---------------------------------------------------------------------------

@dataclass
class OcrResult:
    """OCR抽出結果。

    Attributes:
        raw_text:       抽出した生テキスト
        order_number:   発注番号（見つからない場合は None）
        delivery_date:  納品予定日（YYYY-MM-DD 形式、見つからない場合は None）
        items:          抽出品番・数量リスト
        source_file:    入力ファイルパス
        engine:         使用エンジン ('pdfplumber' | 'tesseract' | 'mock')
        page_count:     処理ページ数
        error:          エラーメッセージ（正常時は None）
    """

    raw_text: str
    order_number: Optional[str] = None
    delivery_date: Optional[str] = None
    items: list[dict] = field(default_factory=list)
    source_file: str = ""
    engine: str = "mock"
    page_count: int = 0
    error: Optional[str] = None

    def to_email_data(self) -> EmailData:
        """OcrResult を EmailData に変換する（email_parser との統合用）。"""
        return EmailData(
            subject="",
            sender="",
            body=self.raw_text,
            order_number=self.order_number,
            delivery_date=self.delivery_date,
            extracted_items=self.items,
            source=f"ocr_{self.engine}",
        )


# ---------------------------------------------------------------------------
# OCR インターフェース（プロトコル）
# ---------------------------------------------------------------------------

class OcrBackend:
    """OCRバックエンドの基底クラス。

    サブクラスで extract_text をオーバーライドする。
    """

    def extract_text(self, file_path: Path) -> tuple[str, int]:
        """ファイルからテキストを抽出する。

        Args:
            file_path: 入力ファイルパス

        Returns:
            (text, page_count): 抽出テキストとページ数のタプル
        """
        raise NotImplementedError


class PdfPlumberBackend(OcrBackend):
    """pdfplumber を使ったPDFテキスト抽出バックエンド。"""

    def extract_text(self, file_path: Path) -> tuple[str, int]:
        """PDFからテキストを抽出する。

        Args:
            file_path: PDFファイルパス

        Returns:
            (text, page_count)

        Raises:
            ImportError: pdfplumber がインストールされていない場合
            FileNotFoundError: ファイルが見つからない場合
        """
        import pdfplumber

        if not file_path.exists():
            raise FileNotFoundError(f"ファイルが見つかりません: {file_path}")

        texts = []
        with pdfplumber.open(str(file_path)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texts.append(t)

        return "\n".join(texts), page_count


class TesseractBackend(OcrBackend):
    """pytesseract を使った画像OCRバックエンド。"""

    def __init__(self, lang: str = "jpn+eng"):
        self.lang = lang

    def extract_text(self, file_path: Path) -> tuple[str, int]:
        """画像ファイルからOCRでテキストを抽出する。

        Args:
            file_path: 画像ファイルパス（PNG, JPG, TIFF等）

        Returns:
            (text, page_count)

        Raises:
            ImportError: pytesseract または Pillow がインストールされていない場合
            FileNotFoundError: ファイルが見つからない場合
        """
        import pytesseract
        from PIL import Image

        if not file_path.exists():
            raise FileNotFoundError(f"ファイルが見つかりません: {file_path}")

        img = Image.open(str(file_path))
        text = pytesseract.image_to_string(img, lang=self.lang)
        return text, 1


class MockOcrBackend(OcrBackend):
    """テスト用モックOCRバックエンド。

    実際のOCRエンジンなしでテストを実行可能にする。
    """

    def __init__(self, mock_text: Optional[str] = None):
        self._mock_text = mock_text or (
            "発注番号: PO-2026-MOCK-001\n"
            "品番: SFJ6-30 数量: 50\n"
            "納品予定日: 2026年04月01日\n"
            "合計金額: 28,500円（税込）\n"
        )

    def extract_text(self, file_path: Path) -> tuple[str, int]:
        """モックテキストを返す。ファイルの存在確認は行わない。"""
        return self._mock_text, 1


# ---------------------------------------------------------------------------
# バックエンド選択ユーティリティ
# ---------------------------------------------------------------------------

def _select_backend(file_path: Path, force_mock: bool = False) -> tuple[OcrBackend, str]:
    """ファイル拡張子とインストール状況に応じてバックエンドを選択する。

    Args:
        file_path:   処理対象ファイル
        force_mock:  True の場合は常にモックバックエンドを使用

    Returns:
        (backend, engine_name): バックエンドインスタンスとエンジン名
    """
    if force_mock:
        return MockOcrBackend(), "mock"

    ext = file_path.suffix.lower()

    if ext == ".pdf":
        try:
            import pdfplumber  # noqa: F401
            return PdfPlumberBackend(), "pdfplumber"
        except ImportError:
            pass

    if ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"):
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401
            return TesseractBackend(), "tesseract"
        except ImportError:
            pass

    # フォールバック: モックバックエンド
    return MockOcrBackend(), "mock"


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

def extract_text_from_file(
    file_path: str,
    force_mock: bool = False,
    backend: Optional[OcrBackend] = None,
) -> OcrResult:
    """ファイル（PDF または画像）からテキストを抽出し、発注情報を解析する。

    Args:
        file_path:   入力ファイルパス（PDF / PNG / JPG 等）
        force_mock:  True の場合は実OCRを行わずモックデータを返す
        backend:     カスタムOCRバックエンド（テスト・拡張用）

    Returns:
        OcrResult: 抽出結果（エラー時も graceful handling）
    """
    p = Path(file_path)

    # バックエンド選択
    if backend is not None:
        selected_backend = backend
        # クラス名から engine 名を生成: MockOcrBackend -> "mock"
        cls_name = type(backend).__name__  # e.g. "MockOcrBackend"
        if isinstance(backend, MockOcrBackend):
            engine_name = "mock"
        elif isinstance(backend, PdfPlumberBackend):
            engine_name = "pdfplumber"
        elif isinstance(backend, TesseractBackend):
            engine_name = "tesseract"
        else:
            engine_name = cls_name.lower().replace("backend", "").rstrip("_") or "custom"
    else:
        selected_backend, engine_name = _select_backend(p, force_mock=force_mock)

    try:
        raw_text, page_count = selected_backend.extract_text(p)
    except FileNotFoundError as e:
        return OcrResult(
            raw_text="",
            source_file=str(file_path),
            engine=engine_name,
            error=f"ファイルが見つかりません: {e}",
        )
    except Exception as e:
        return OcrResult(
            raw_text="",
            source_file=str(file_path),
            engine=engine_name,
            error=f"OCR処理エラー: {e}",
        )

    # 発注情報を抽出
    order_number = _extract_order_number(raw_text)
    delivery_date = _extract_delivery_date(raw_text)
    items = _extract_items(raw_text)

    return OcrResult(
        raw_text=raw_text,
        order_number=order_number,
        delivery_date=delivery_date,
        items=items,
        source_file=str(file_path),
        engine=engine_name,
        page_count=page_count,
        error=None,
    )


def extract_text_from_bytes(
    content: bytes,
    filename: str = "document.pdf",
    force_mock: bool = False,
    backend: Optional[OcrBackend] = None,
) -> OcrResult:
    """バイトデータ（アップロードされたファイル）からテキストを抽出する。

    Args:
        content:    ファイルバイトデータ
        filename:   元ファイル名（拡張子判定に使用）
        force_mock: True の場合はモックデータを返す
        backend:    カスタムOCRバックエンド

    Returns:
        OcrResult: 抽出結果
    """
    import tempfile

    ext = Path(filename).suffix.lower() or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        return extract_text_from_file(tmp_path, force_mock=force_mock, backend=backend)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
