"""
m1_pdf_agent.py
===============
disclosure-multiagent Phase 1-M1: PDF解析エージェント（M1-2/M1-3）

設計書: 22_MVP_Development_Checklist.md M1-2/M1-3
PoC参考: pdf_poc_extract.py（足軽2 subtask_063a2）
実装者: 足軽4 subtask_063a11
作成日: 2026-02-27

使用方法:
    # 実PDFで実行
    python3 m1_pdf_agent.py /path/to/yuho.pdf

    # PyMuPDFなし環境のテスト確認
    python3 m1_pdf_agent.py --test
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# M3のデータクラスをimport（再定義不要・m3_gap_analysis_agent.py は改変しない）
from m3_gap_analysis_agent import (
    StructuredReport,
    SectionData,
    TableData,
)

# ─────────────────────────────────────────────────────────
# 定数（pdf_poc_extract.py の成果を転用: DRYより明示性優先）
# ─────────────────────────────────────────────────────────

# 有報の人的資本関連セクション検出キーワード（pdf_poc_extract.py より転用）
JINJI_SECTION_KEYWORDS: list[str] = [
    # 直接記載（優先）
    "人的資本",
    "人材戦略",
    "人材の確保",
    "人材育成",
    "人材確保",
    # 代替キーワード（company_c等への対処）
    "従業員の状況",
    "エンゲージメント",
    "ダイバーシティ",
    "女性活躍",
    "育成方針",
    "人材の多様性",
    "サステナビリティ",
]

# 有報の標準的な大見出しパターン（pdf_poc_extract.py より転用）
HEADING_PATTERNS: list[re.Pattern] = [
    re.compile(r'^第[一二三四五六七八九十\d]+部'),        # 「第一部」「第2部」
    re.compile(r'^第[１２３４５６７８９\d]+【'),            # 「第１【企業の概況】」
    re.compile(r'^\d+【'),                                  # 「1【事業の概要】」
    re.compile(r'^【[^】]+】$'),                            # 「【表紙】」
    re.compile(r'^[（(]\d+[）)]\s*[\u4e00-\u9fff]'),        # 「（1）人的資本」
    re.compile(r'^\(\d+\)\s*[\u4e00-\u9fff]'),
    re.compile(r'^\d+\.\s*[\u4e00-\u9fff]{2,}'),           # 「1. 人材戦略」
    re.compile(r'^[①②③④⑤⑥⑦⑧⑨⑩]'),                   # 丸数字
]

# セクションテキストの最大文字数（チャンク処理で使用）
MAX_SECTION_CHARS = 8000

# PyMuPDF利用可否フラグ（importを遅延させてテストを可能にする）
_FITZ_AVAILABLE: Optional[bool] = None


def _check_fitz() -> bool:
    global _FITZ_AVAILABLE
    if _FITZ_AVAILABLE is None:
        try:
            import fitz  # noqa: F401
            _FITZ_AVAILABLE = True
        except ImportError:
            _FITZ_AVAILABLE = False
    return _FITZ_AVAILABLE


# ─────────────────────────────────────────────────────────
# M1-2: セクション分割ロジック（PDF非依存・テスト可能）
# ─────────────────────────────────────────────────────────

def _is_heading_line(line: str) -> bool:
    """行が見出しパターンにマッチするか判定する"""
    stripped = line.strip()
    if not stripped:
        return False
    return any(p.search(stripped) for p in HEADING_PATTERNS)


def split_sections_from_text(
    full_text: str,
    max_section_chars: int = MAX_SECTION_CHARS,
) -> list[SectionData]:
    """
    有報テキストをHEADING_PATTERNSに基づいてセクション分割する。
    PDF非依存のため、モックテキストでも動作する（テスト可能）。

    Args:
        full_text: PDFから抽出した全文テキスト
        max_section_chars: セクションテキストの最大文字数

    Returns:
        list[SectionData]（各セクションのsection_id, heading, textを設定）
    """
    lines = full_text.splitlines()
    sections: list[SectionData] = []
    current_heading: Optional[str] = None
    current_lines: list[str] = []
    section_counter = 0

    def _flush_section() -> None:
        nonlocal current_heading, current_lines, section_counter
        if current_heading is None:
            return
        body = "\n".join(current_lines).strip()
        if not body and not current_heading:
            return
        section_counter += 1
        section_id = f"SEC-{section_counter:03d}"
        sections.append(SectionData(
            section_id=section_id,
            heading=current_heading[:120],
            text=body[:max_section_chars],
            level=_infer_heading_level(current_heading),
        ))
        current_heading = None
        current_lines = []

    for line in lines:
        if _is_heading_line(line):
            _flush_section()
            current_heading = line.strip()
        else:
            current_lines.append(line)

    # 末尾の未フラッシュセクション
    _flush_section()

    # 見出しが1件も検出されなかった場合: 全文を1セクションとして返す
    if not sections and full_text.strip():
        sections.append(SectionData(
            section_id="SEC-001",
            heading="（見出し未検出）",
            text=full_text.strip()[:max_section_chars],
            level=1,
        ))

    return sections


def _infer_heading_level(heading: str) -> int:
    """見出しテキストからレベル（1〜4）を推定する"""
    h = heading.strip()
    if re.match(r'^第[一二三四五六七八九十\d]+部', h):
        return 1
    if re.match(r'^第[１２３４５６７８９\d]+【|^\d+【|^【[^】]+】$', h):
        return 2
    if re.match(r'^[（(]\d+[）)]|^\(\d+\)', h):
        return 3
    return 4


# ─────────────────────────────────────────────────────────
# テーブル抽出（PyMuPDF依存部分）
# ─────────────────────────────────────────────────────────

def _extract_tables_from_page(page) -> list[TableData]:
    """
    PyMuPDFページオブジェクトからテーブルを抽出する。
    テーブル検出に失敗した場合は空リストを返す（エラーで停止しない）。
    """
    tables: list[TableData] = []
    try:
        # PyMuPDF 1.23+ では find_tables() が利用可能
        tab = page.find_tables()
        for t in tab.tables:
            extracted = t.extract()
            if not extracted:
                continue
            # 1行目をキャプション候補として使用（なければ「テーブル」）
            caption = extracted[0][0] if extracted and extracted[0] else "テーブル"
            rows = [
                [str(cell) if cell is not None else "" for cell in row]
                for row in extracted
            ]
            tables.append(TableData(caption=str(caption)[:80], rows=rows))
    except AttributeError:
        # find_tables() が古いバージョンで利用不可 → スキップ
        pass
    except Exception as e:
        logging.getLogger(__name__).debug("テーブル抽出スキップ: %s", e)
    return tables


# ─────────────────────────────────────────────────────────
# M1-3: メインAPI
# ─────────────────────────────────────────────────────────

def extract_report(
    pdf_path: str,
    fiscal_year: Optional[int] = None,
    fiscal_month_end: int = 3,
    company_name: str = "",
    extract_tables: bool = True,
) -> StructuredReport:
    """
    PDFファイルを解析してStructuredReportを返すメインAPI（M1-3）。

    処理フロー:
      1. PDFファイルの存在確認
      2. PyMuPDF で全ページテキストを抽出
      3. split_sections_from_text() でセクション分割
      4. 各ページのテーブルをSectionDataに付与（ベストエフォート）
         ※ extract_tables=False の場合はテーブル抽出をスキップ（処理時間短縮）
      5. document_id（ファイル名ベース）を生成
      6. StructuredReportとして返す

    Args:
        pdf_path: PDFファイルのパス（ハードコード禁止: 呼び出し元が指定）
        fiscal_year: 事業年度（省略時はファイル名から推定を試みる）
        fiscal_month_end: 決算月（デフォルト3月）
        company_name: 企業名（省略時はPDFから自動抽出を試みる）
        extract_tables: テーブル抽出を行うか（デフォルト: True）。
            False にすると find_tables() をスキップし処理時間を大幅短縮できる。
            FINDING-001 対応: 処理時間 11.5秒 → ~0.5秒/社（実測）。

    Returns:
        StructuredReport

    Raises:
        FileNotFoundError: PDFファイルが存在しない場合
        RuntimeError: PyMuPDFが利用不可の場合
    """
    logger = logging.getLogger(__name__)
    path = Path(pdf_path)

    # ── STEP 1: ファイル存在確認 ──
    if not path.exists():
        raise FileNotFoundError(
            f"PDFファイルが見つかりません: {path}\n"
            f"正しいパスを指定してください。"
        )

    if not _check_fitz():
        raise RuntimeError(
            "PyMuPDF (fitz) が利用できません。"
            "'pip install pymupdf' を実行してください。"
        )

    import fitz

    # ── STEP 2: PDFテキスト抽出 ──
    logger.info("PDF解析開始: %s", path.name)
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        logger.warning("PDF開封エラー（空sectionsで継続）: %s", e)
        return StructuredReport(
            document_id=_make_document_id(path),
            company_name=company_name or path.stem,
            fiscal_year=fiscal_year or 0,
            fiscal_month_end=fiscal_month_end,
            sections=[],
            extraction_library="PyMuPDF",
        )

    # ── STEP 3: 全ページテキスト収集 + テーブル収集 ──
    page_texts: list[str] = []
    page_tables: dict[int, list[TableData]] = {}  # page_num → tables

    for page_num, page in enumerate(doc):
        text = page.get_text()
        page_texts.append(text)
        tables = _extract_tables_from_page(page) if extract_tables else []
        if tables:
            page_tables[page_num] = tables

    doc.close()
    full_text = "\n".join(page_texts)
    logger.info("テキスト抽出完了: %d文字 %dページ", len(full_text), len(page_texts))

    # ── STEP 4: セクション分割 ──
    sections = split_sections_from_text(full_text)
    logger.info("セクション分割完了: %d件", len(sections))

    # テーブルをセクションに付与（ページ→セクションのマッピングは近似）
    # Phase 1では全テーブルを最初のセクションに付与（簡易実装）
    all_tables = [t for tables in page_tables.values() for t in tables]
    if all_tables and sections:
        # テーブルを関連セクションに分散（先頭セクションに付与）
        sections[0] = SectionData(
            section_id=sections[0].section_id,
            heading=sections[0].heading,
            text=sections[0].text,
            level=sections[0].level,
            tables=all_tables[:10],  # 最大10テーブル
            parent_section_id=sections[0].parent_section_id,
        )

    # ── STEP 5: 企業名・年度の推定 ──
    if not company_name:
        company_name = _extract_company_name(full_text, path)
    if fiscal_year is None:
        fiscal_year = _infer_fiscal_year(path)

    return StructuredReport(
        document_id=_make_document_id(path),
        company_name=company_name,
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
        sections=sections,
        extraction_library="PyMuPDF",
        extracted_at=datetime.now().isoformat(),
    )


# ─────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────

def _make_document_id(path: Path) -> str:
    """ファイル名からdocument_idを生成する（ハードコードなし）"""
    stem = re.sub(r'[^\w\-]', '_', path.stem)[:20]
    h = hashlib.md5(path.name.encode()).hexdigest()[:6].upper()
    return f"{stem}_{h}"


def _extract_company_name(full_text: str, path: Path) -> str:
    """
    テキスト先頭から企業名の抽出を試みる（ベストエフォート）。
    失敗した場合はファイル名をベースにした名称を返す。
    """
    # 「会社名」「発行者名」「商号」などのパターンから抽出
    patterns = [
        r'会社名[　\s]*([^\n　\s]{2,30})',
        r'発行者名[　\s]*([^\n　\s]{2,30})',
        r'商号[　\s]*([^\n　\s]{2,30})',
    ]
    for pat in patterns:
        m = re.search(pat, full_text[:3000])
        if m:
            return m.group(1).strip()
    return path.stem[:30]


def _infer_fiscal_year(path: Path) -> int:
    """
    ファイル名から事業年度を推定する（例: yuho_2025_03.pdf → 2025）。
    推定できない場合は現在年度を返す。
    """
    m = re.search(r'(20\d{2})', path.stem)
    if m:
        return int(m.group(1))
    return datetime.now().year


# ─────────────────────────────────────────────────────────
# 人的資本セクション フィルタ
# ─────────────────────────────────────────────────────────

def get_human_capital_sections(report: StructuredReport) -> list[SectionData]:
    """
    StructuredReportから人的資本関連セクションのみを抽出する。

    JINJI_SECTION_KEYWORDS が見出しまたは本文（先頭200文字）に
    含まれるセクションを返す。

    Args:
        report: M1が生成したStructuredReport

    Returns:
        人的資本関連のSectionDataリスト（空の場合もある）
    """
    relevant = []
    for section in report.sections:
        heading_lower = section.heading
        body_head = section.text[:200]
        combined = heading_lower + body_head
        if any(kw in combined for kw in JINJI_SECTION_KEYWORDS):
            relevant.append(section)
    return relevant


# ─────────────────────────────────────────────────────────
# StructuredReport → dict（JSON化用）
# ─────────────────────────────────────────────────────────

def report_to_dict(report: StructuredReport) -> dict:
    """StructuredReportをJSON化可能なdictに変換する"""
    return {
        "document_id": report.document_id,
        "company_name": report.company_name,
        "fiscal_year": report.fiscal_year,
        "fiscal_month_end": report.fiscal_month_end,
        "extraction_library": report.extraction_library,
        "extracted_at": report.extracted_at,
        "sections": [
            {
                "section_id": s.section_id,
                "heading": s.heading,
                "level": s.level,
                "text": s.text[:500],  # プレビュー用に500文字まで
                "text_length": len(s.text),
                "tables": [
                    {"caption": t.caption, "rows_count": len(t.rows)}
                    for t in s.tables
                ],
            }
            for s in report.sections
        ],
    }


# ─────────────────────────────────────────────────────────
# CLI エントリポイント
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if "--test" in sys.argv:
        # PyMuPDFなし環境でのモックテスト
        print("=== m1_pdf_agent モックテスト ===")
        mock_text = """第一部 企業情報
1【事業の概要】
当社の事業概要を記載します。

2【サステナビリティに関する考え方及び取組】
人的資本の開示について記載します。
当社は人材育成を重視しています。

第二部 提出会社の保証会社等の情報
従業員の状況について記載します。
"""
        sections = split_sections_from_text(mock_text)
        print(f"セクション数: {len(sections)}")
        for s in sections:
            print(f"  [{s.section_id}] level={s.level} '{s.heading[:40]}'")
        print()
        mock_report = StructuredReport(
            document_id="MOCK_001",
            company_name="テスト株式会社",
            fiscal_year=2025,
            fiscal_month_end=3,
            sections=sections,
        )
        hc = get_human_capital_sections(mock_report)
        print(f"人的資本セクション: {len(hc)}件")
        for s in hc:
            print(f"  [{s.section_id}] '{s.heading[:40]}'")
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage: python3 m1_pdf_agent.py <pdf_path>")
        print("       python3 m1_pdf_agent.py --test  (モックテスト)")
        sys.exit(1)

    pdf_path = sys.argv[1]
    try:
        report = extract_report(pdf_path)
        print(json.dumps(report_to_dict(report), ensure_ascii=False, indent=2))
    except FileNotFoundError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(2)
