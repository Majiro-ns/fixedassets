#!/usr/bin/env python3
"""
PDF解析 PoC (v2): PyMuPDF / pdfplumber / pymupdf4llm で有報PDFのテキスト抽出を比較する。

Usage:
  python scripts/pdf_poc_extract.py <samples_dir>
  python scripts/pdf_poc_extract.py 10_Research/samples/
  python scripts/pdf_poc_extract.py 10_Research/samples/ --json  # 構造化JSON出力

samples_dir: 有報PDFが入ったディレクトリ（.pdf のみ対象）

検証項目:
  1. テキスト抽出精度（文字数・文字化けなし）
  2. 人的資本セクションの検出（拡張キーワード対応）
  3. セクション境界の検出（フォントサイズ・見出しパターン）
  4. 処理速度
  5. 構造化出力 {title, page, text, chars}
"""

import sys
import io
import time
import re
import json
from contextlib import redirect_stdout
from pathlib import Path


# ─────────────────────────────────────────
# セクション定義（A. 代替キーワード対応）
# ─────────────────────────────────────────

# 有報の人的資本関連セクションを検出するキーワード（優先度順）
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

# 人的資本関連のカウント用キーワード
JINJI_COUNT_KEYWORDS: list[str] = [
    "人的資本", "人材", "従業員", "育成", "定着", "採用",
    "多様性", "ダイバーシティ", "エンゲージメント",
    "平均給与", "離職率", "女性活躍", "人材戦略",
]

# 有報の標準的な大見出しパターン（B. 境界精緻化用）
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

# ファンド型有報の識別パターン（事業会社有報と区別する）
# 注意: 「ファンド」単独は事業会社（子会社がファンド運営）でも出現するため除外。
# 「投資信託説明書」「基準価額」「純資産総額」等の純粋ファンド専用ワードを使用。
FUND_INDICATORS_STRICT: list[str] = [
    "投資信託説明書", "基準価額", "純資産総額", "受益証券",
    "投資法人債", "分配金", "受益者",
]
# STRICT条件: 3ワード以上マッチでファンド型確定（単語一致の誤検出を防ぐ）
FUND_INDICATORS_STRICT_THRESHOLD: int = 3

# 軟判定用（1ワードでも明確なファンド専用語）
FUND_INDICATORS_DEFINITE: list[str] = [
    "投資信託説明書", "基準価額", "受益者",
]


# ─────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────

def is_fund_report(text: str) -> bool:
    """
    ファンド型有報かどうか判定（人的資本記載なしが正常な有報種別）。

    判定ロジック（改訂版 v2.1）:
    - 「基準価額」「受益者」「投資信託説明書」いずれかが冒頭4000文字に存在: ファンド型確定
    - STRICT_INDICATORS が3ワード以上マッチ: ファンド型確定
    - 改訂前の「ファンド」単独マッチは誤検出の原因のため廃止
    """
    head = text[:4000]
    # 明確なファンド専用語が1件以上 → 確定
    if any(kw in head for kw in FUND_INDICATORS_DEFINITE):
        return True
    # STRICT ワードが3件以上 → 確定
    matched = sum(1 for kw in FUND_INDICATORS_STRICT if kw in head)
    return matched >= FUND_INDICATORS_STRICT_THRESHOLD


def check_mojibake(text: str) -> bool:
    """文字化けの簡易チェック（□や〓などの置換文字が多い場合）"""
    if not text or text.startswith("[ERROR]"):
        return False
    mojibake_chars = text.count("□") + text.count("〓") + text.count("\ufffd")
    ratio = mojibake_chars / max(len(text), 1)
    return ratio > 0.01


def count_keywords(text: str, keywords: list[str] = None) -> dict[str, int]:
    """キーワードの出現回数を集計"""
    if keywords is None:
        keywords = JINJI_COUNT_KEYWORDS
    return {kw: text.count(kw) for kw in keywords if kw in text}


def has_jinji_shihon(text: str) -> bool:
    """人的資本に関連するキーワードが含まれるか（拡張版）"""
    return any(kw in text for kw in JINJI_COUNT_KEYWORDS)


# ─────────────────────────────────────────
# 抽出関数
# ─────────────────────────────────────────

def extract_pymupdf(pdf_path: Path) -> tuple[str, float]:
    """PyMuPDF (fitz) でテキスト抽出。(text, elapsed_sec) を返す"""
    try:
        import fitz
        t0 = time.perf_counter()
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts), time.perf_counter() - t0
    except Exception as e:
        return f"[ERROR] {e}", 0.0


def extract_pdfplumber(pdf_path: Path) -> tuple[str, float]:
    """pdfplumber でテキスト抽出。(text, elapsed_sec) を返す"""
    try:
        import pdfplumber
        t0 = time.perf_counter()
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        return "\n".join(text_parts), time.perf_counter() - t0
    except Exception as e:
        return f"[ERROR] {e}", 0.0


def extract_pymupdf4llm(pdf_path: Path) -> tuple[str, float]:
    """pymupdf4llm でMarkdown変換抽出。(text, elapsed_sec) を返す"""
    try:
        import pymupdf4llm
        t0 = time.perf_counter()
        md_text = pymupdf4llm.to_markdown(str(pdf_path))
        return md_text, time.perf_counter() - t0
    except Exception as e:
        return f"[ERROR] {e}", 0.0


# ─────────────────────────────────────────
# B. セクション境界の精緻化（PyMuPDF専用）
# ─────────────────────────────────────────

def detect_headings_pymupdf(pdf_path: Path) -> list[dict]:
    """
    PyMuPDFのフォント情報と見出しパターンで見出しを検出。
    [{page, size, text, is_pattern_heading}, ...] を返す。
    """
    import fitz
    doc = fitz.open(pdf_path)
    headings = []

    # ページごとの最大フォントサイズを収集
    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]
        page_max_size = 0.0

        # まずこのページの最大サイズを把握
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sz = span.get("size", 0)
                    if sz > page_max_size:
                        page_max_size = sz

        # 見出し候補を収集
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_text = "".join(s.get("text", "") for s in line.get("spans", []))
                line_text_stripped = line_text.strip()
                if not line_text_stripped:
                    continue

                # 各spanのサイズを確認
                for span in line.get("spans", []):
                    sz = span.get("size", 0)
                    span_text = span.get("text", "").strip()
                    if not span_text:
                        continue

                    # 見出し判定条件:
                    # 1. 相対的に大きいフォント（ページ内最大の90%以上）
                    # 2. または有報パターンにマッチ
                    is_large_font = page_max_size > 0 and sz >= page_max_size * 0.90 and sz >= 10.0
                    is_pattern = any(p.search(line_text_stripped) for p in HEADING_PATTERNS)

                    if is_large_font or is_pattern:
                        headings.append({
                            "page": page_num + 1,
                            "size": round(sz, 1),
                            "text": line_text_stripped[:80],
                            "is_pattern_heading": is_pattern,
                        })
                    break  # 1行につき1件

    doc.close()
    # 重複除去（同ページ同テキスト）
    seen = set()
    unique_headings = []
    for h in headings:
        key = (h["page"], h["text"])
        if key not in seen:
            seen.add(key)
            unique_headings.append(h)
    return unique_headings


# ─────────────────────────────────────────
# C. 構造化セクション抽出
# ─────────────────────────────────────────

def extract_sections(
    pdf_path: Path,
    keywords: list[str] = None,
) -> list[dict]:
    """
    PyMuPDFで人的資本関連セクションを構造化抽出。
    [{title, page_start, text, chars, matched_keyword}, ...] を返す。

    Args:
        pdf_path: PDFファイルパス
        keywords: セクション検出キーワードリスト（省略時はJINJI_SECTION_KEYWORDS）
    """
    if keywords is None:
        keywords = JINJI_SECTION_KEYWORDS

    import fitz
    doc = fitz.open(pdf_path)

    # ページ単位でテキストを収集
    pages = []
    for page_num, page in enumerate(doc):
        pages.append({
            "page": page_num + 1,
            "text": page.get_text(),
        })
    doc.close()

    sections = []
    for i, page_data in enumerate(pages):
        text = page_data["text"]
        page_num = page_data["page"]

        for kw in keywords:
            if kw not in text:
                continue
            # キーワード周辺のコンテキストを抽出
            idx = text.find(kw)
            # セクション開始行を特定（前後の改行で区切る）
            start = text.rfind("\n", 0, idx)
            start = 0 if start == -1 else start + 1
            # セクションテキスト（最大3000文字）
            section_text = text[start:start + 3000].strip()
            title_line = text[start:text.find("\n", start)].strip()
            if not title_line:
                title_line = kw

            entry = {
                "title": title_line[:60],
                "page_start": page_num,
                "matched_keyword": kw,
                "text": section_text,
                "chars": len(section_text),
            }
            # 同一キーワード・同一ページの重複を防ぐ
            if not any(
                s["matched_keyword"] == kw and s["page_start"] == page_num
                for s in sections
            ):
                sections.append(entry)

    return sections


# ─────────────────────────────────────────
# 旧API互換（後方互換性維持）
# ─────────────────────────────────────────

def detect_section_boundaries(text: str) -> list[str]:
    """
    [後方互換] 見出しパターンでセクション境界を検出。検出した見出し一覧を返す。
    新規コードでは extract_sections() の使用を推奨。
    """
    detected = []
    for pattern in JINJI_SECTION_KEYWORDS:
        matches = re.findall(r'.{0,20}' + re.escape(pattern) + r'.{0,20}', text)
        for m in matches[:3]:
            clean = m.strip().replace("\n", " ")
            if clean and clean not in detected:
                detected.append(clean)
    return detected


# ─────────────────────────────────────────
# 分析・レポート
# ─────────────────────────────────────────

def analyze_pdf(pdf_path: Path) -> dict:
    """1ファイルを3ライブラリで解析し、結果を返す"""
    result = {"name": pdf_path.name, "libs": {}, "sections": [], "is_fund": False}

    # PyMuPDF でまずフル抽出（ファンド判定・構造化抽出に使用）
    pymupdf_text, _ = extract_pymupdf(pdf_path)
    result["is_fund"] = is_fund_report(pymupdf_text)

    # 構造化セクション抽出（PyMuPDF専用）
    result["sections"] = extract_sections(pdf_path)

    # 3ライブラリ比較
    for lib_name, extract_fn in [
        ("PyMuPDF", extract_pymupdf),
        ("pdfplumber", extract_pdfplumber),
        ("pymupdf4llm", extract_pymupdf4llm),
    ]:
        text, elapsed = extract_fn(pdf_path)
        is_error = text.startswith("[ERROR]")

        result["libs"][lib_name] = {
            "chars": len(text) if not is_error else 0,
            "elapsed_sec": round(elapsed, 3),
            "has_jinji": has_jinji_shihon(text) if not is_error else False,
            "jinji_keywords": count_keywords(text) if not is_error else {},
            "sections": detect_section_boundaries(text) if not is_error else [],
            "mojibake": check_mojibake(text),
            "error": text if is_error else None,
            "preview": text[:300].replace("\n", " ") if not is_error else "",
        }

    return result


def print_report(results: list[dict], show_sections: bool = True) -> None:
    """コンソールにレポートを表示"""
    print("=" * 80)
    print("PDF解析 PoC 結果レポート (v2: セクション抽出精緻化版)")
    print("=" * 80)

    lib_names = ["PyMuPDF", "pdfplumber", "pymupdf4llm"]

    for r in results:
        fund_label = " [ファンド型]" if r["is_fund"] else ""
        print(f"\n### {r['name']}{fund_label}")
        if r["is_fund"]:
            print("  ⚠️  投資信託/ファンド有報のため人的資本記載なしが正常")

        print(f"\n{'ライブラリ':<15} {'文字数':>10} {'時間(秒)':>10} {'人的資本':>8} {'文字化け':>8}")
        print("-" * 60)
        for lib in lib_names:
            d = r["libs"].get(lib, {})
            if d.get("error"):
                print(f"  {lib:<13} {'ERROR':>10}")
                continue
            print(
                f"  {lib:<13} {d['chars']:>10,} {d['elapsed_sec']:>10.3f}"
                f" {'○' if d['has_jinji'] else '×':>8} {'あり' if d['mojibake'] else 'なし':>8}"
            )

        # 構造化セクション抽出結果（C.）
        sections = r.get("sections", [])
        print(f"\n  [構造化セクション抽出] {len(sections)}件")
        for sec in sections[:5]:
            print(f"    p{sec['page_start']:>3} '{sec['matched_keyword']}' → {sec['title'][:40]} ({sec['chars']}chars)")

        # 人的資本キーワード出現数
        print("\n  [人的資本キーワード (PyMuPDF top-5)]")
        pymupdf_kw = r["libs"].get("PyMuPDF", {}).get("jinji_keywords", {})
        for kw, cnt in sorted(pymupdf_kw.items(), key=lambda x: -x[1])[:5]:
            print(f"    '{kw}': {cnt}回")

    # サマリ
    print("\n" + "=" * 80)
    print("サマリ比較表")
    print("=" * 80)
    print(f"\n{'ライブラリ':<15} {'平均文字数':>12} {'平均時間(秒)':>14} {'人的資本検出率':>14} {'セクション抽出数':>16}")
    print("-" * 80)

    for lib in lib_names:
        valid = [r for r in results if not r["libs"][lib].get("error")]
        if not valid:
            print(f"  {lib:<13} {'ERROR':>12}")
            continue
        avg_chars = sum(r["libs"][lib]["chars"] for r in valid) / len(valid)
        avg_elapsed = sum(r["libs"][lib]["elapsed_sec"] for r in valid) / len(valid)
        jinji_rate = sum(r["libs"][lib]["has_jinji"] for r in valid) / len(valid) * 100
        avg_sec = sum(len(r["sections"]) for r in results) / len(results)
        print(
            f"  {lib:<13} {avg_chars:>12,.0f} {avg_elapsed:>14.3f}"
            f" {jinji_rate:>13.0f}% {avg_sec:>15.1f}"
        )

    # ファンド型有報の扱いに関する注記
    fund_count = sum(1 for r in results if r["is_fund"])
    if fund_count > 0:
        print(f"\n  ⚠️  ファンド型有報: {fund_count}社（人的資本記載なしが正常）")

    print()


# ─────────────────────────────────────────
# メイン
# ─────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python pdf_poc_extract.py <samples_dir> [--json]")
        sys.exit(1)

    samples_dir = Path(sys.argv[1])
    output_json = "--json" in sys.argv

    if not samples_dir.exists():
        print(f"Directory not found: {samples_dir}")
        sys.exit(1)

    pdf_files = list(samples_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files in {samples_dir}")
        sys.exit(1)

    if not output_json:
        print(f"Found {len(pdf_files)} PDF(s): {[p.name for p in pdf_files]}")
        print()

    results = []
    for pdf_path in sorted(pdf_files):
        if not output_json:
            print(f"Analyzing: {pdf_path.name} ...", flush=True)
        # JSONモード時はライブラリの警告をstderrに退避（JSON出力を汚染しないため）
        if output_json:
            with redirect_stdout(io.TextIOWrapper(open(sys.stderr.fileno(), 'wb', closefd=False), encoding='utf-8', errors='replace')):
                r = analyze_pdf(pdf_path)
        else:
            r = analyze_pdf(pdf_path)
        results.append(r)

    if output_json:
        # C. 構造化JSON出力
        output = []
        for r in results:
            output.append({
                "file": r["name"],
                "is_fund": r["is_fund"],
                "sections": r["sections"],
                "stats": {
                    lib: {
                        "chars": r["libs"][lib]["chars"],
                        "elapsed_sec": r["libs"][lib]["elapsed_sec"],
                        "has_jinji": r["libs"][lib]["has_jinji"],
                    }
                    for lib in ["PyMuPDF", "pdfplumber", "pymupdf4llm"]
                },
            })
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_report(results)
        print("Done.")
        print("→ 結果を 10_Research/PDF_PoC_Result.md に記録してください。")

    return results


if __name__ == "__main__":
    main()
