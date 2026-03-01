"""EDINETコードCSV → 証券コード変換サービス.

金融庁公式 EdinetcodeDlInfo.csv を読み込み、証券コードで企業を検索する。
CSV列: 0=EDINETコード, 1=提出者種別, 2=上場区分, 3=連結の有無,
        4=資本金, 5=決算日, 6=提出者名, 7=提出者名（英字表記）,
        8=提出者名（カナ）, 9=所在地, 10=提出者業種,
        11=証券コード, 12=提出者法人番号
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Optional

from api.models.schemas import CompanyInfo

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_CSV_PATH = _DATA_DIR / "EdinetcodeDlInfo.csv"

# In-memory index
_companies: list[CompanyInfo] = []
_by_sec_code: dict[str, list[CompanyInfo]] = {}
_by_edinet_code: dict[str, CompanyInfo] = {}
_by_name: list[tuple[str, CompanyInfo]] = []  # (lowercase_name, info)
_loaded = False


def _load_csv() -> None:
    global _loaded
    if _loaded:
        return

    if not _CSV_PATH.exists():
        logger.warning("EdinetcodeDlInfo.csv not found at %s. Using empty dataset.", _CSV_PATH)
        _loaded = True
        return

    with open(_CSV_PATH, "r", encoding="cp932", errors="replace") as f:
        reader = csv.reader(f)
        # Skip header (first line is typically a title row, second is column headers)
        for i, row in enumerate(reader):
            if i < 2:
                continue
            if len(row) < 12:
                continue
            edinet_code = row[0].strip()
            sec_code_raw = row[11].strip()
            company_name = row[6].strip()
            company_name_en = row[7].strip() if len(row) > 7 else ""
            industry = row[10].strip() if len(row) > 10 else ""
            listing = row[2].strip() if len(row) > 2 else ""

            if not edinet_code or not company_name:
                continue

            # Normalize sec_code: keep only 4-digit + optional trailing 0
            sec_code = sec_code_raw.replace(" ", "")

            info = CompanyInfo(
                edinet_code=edinet_code,
                sec_code=sec_code,
                company_name=company_name,
                company_name_en=company_name_en,
                industry=industry,
                listing=listing,
            )
            _companies.append(info)

            if sec_code:
                _by_sec_code.setdefault(sec_code, []).append(info)
                # Also index by first 4 digits
                if len(sec_code) >= 4:
                    _by_sec_code.setdefault(sec_code[:4], []).append(info)

            _by_edinet_code[edinet_code] = info
            _by_name.append((company_name.lower(), info))

    _loaded = True
    logger.info("Loaded %d companies from EdinetcodeDlInfo.csv", len(_companies))


def search_by_sec_code(sec_code: str) -> list[CompanyInfo]:
    """証券コードで検索（4桁 or 5桁）"""
    _load_csv()
    code = sec_code.strip()
    results = _by_sec_code.get(code, [])
    if not results and len(code) == 4:
        results = _by_sec_code.get(code + "0", [])
    return results


def search_by_edinet_code(edinet_code: str) -> Optional[CompanyInfo]:
    """EDINETコードで検索"""
    _load_csv()
    return _by_edinet_code.get(edinet_code.strip())


def search_by_name(query: str, limit: int = 20) -> list[CompanyInfo]:
    """企業名で部分一致検索"""
    _load_csv()
    q = query.lower()
    results = [info for name, info in _by_name if q in name]
    return results[:limit]


def get_edinet_code_for_sec_code(sec_code: str) -> Optional[str]:
    """証券コード → EDINETコード変換"""
    results = search_by_sec_code(sec_code)
    return results[0].edinet_code if results else None
