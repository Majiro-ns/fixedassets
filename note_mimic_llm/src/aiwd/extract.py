from __future__ import annotations
from pathlib import Path
from typing import Tuple, Optional


def _read_txt(path: Path) -> Tuple[str, Optional[str]]:
    encodings = ["utf-8", "utf-8-sig", "cp932", "shift_jis"]
    for enc in encodings:
        try:
            return path.read_text(encoding=enc), None
        except Exception:
            continue
    # binary fallback
    with open(path, "rb") as f:
        data = f.read()
    try:
        return data.decode("utf-8", errors="ignore"), None
    except Exception:
        return "", "Failed to decode text file"


def _read_pdf(path: Path) -> Tuple[str, Optional[str]]:
    try:
        import fitz  # PyMuPDF
    except Exception:
        return "", "Missing dependency: fitz (PyMuPDF) is required to extract from pdf"
    try:
        doc = fitz.open(path.as_posix())
        parts = []
        for page in doc:
            parts.append(page.get_text("text") or "")
        return "\n".join(parts), None
    except Exception:
        return "", "PDF extract error"


def _read_docx(path: Path) -> Tuple[str, Optional[str]]:
    try:
        import docx  # python-docx
    except Exception:
        return "", "Missing dependency: docx (python-docx) is required to extract from docx"
    try:
        d = docx.Document(path.as_posix())
        return "\n".join(p.text for p in d.paragraphs if p.text), None
    except Exception:
        return "", "DOCX extract error"


def extract_text(file_path: str | Path) -> Tuple[str, Optional[str]]:
    """Extract text from PDF/DOCX/TXT. Returns (text, error_message)."""
    p = Path(file_path)
    ext = p.suffix.lower()
    if ext not in {".pdf", ".docx", ".txt"}:
        return "", f"Unsupported file type: {ext or '<none>'}"

    try:
        if ext == ".pdf":
            text, err = _read_pdf(p)
        elif ext == ".docx":
            text, err = _read_docx(p)
        else:
            text, err = _read_txt(p)
        text = (text or "").strip()
        if err:
            return "", err
        if not text:
            return "", "No text extracted (empty file or unsupported content)"
        return text, None
    except Exception as e:
        return "", f"Extract error: {e}"


def iter_target_files(root: str | Path) -> list[Path]:
    root_p = Path(root)
    exts = {".pdf", ".docx", ".txt"}
    files = [p for p in root_p.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    return sorted(files)
