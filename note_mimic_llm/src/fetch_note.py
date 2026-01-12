from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Iterable, List

import requests
from bs4 import BeautifulSoup  # type: ignore

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"


def _normalize_text(text: str) -> str:
    # Collapse 3+ line breaks down to 2 to keep structure but avoid sparse output.
    return re.sub(r"\n{3,}", "\n\n", text.strip())


def fetch_and_extract(urls: Iterable[str], raw_dir: Path, corpus_dir: Path) -> List[Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    corpus_paths: List[Path] = []
    for idx, url in enumerate(urls):
        raw_path = raw_dir / f"{idx:02d}.html"
        corpus_path = corpus_dir / f"{idx:02d}.txt"
        try:
            resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            raw_path.write_text(resp.text, encoding="utf-8", errors="ignore")

            soup = BeautifulSoup(resp.text, "html.parser")
            text = ""
            article = soup.find("article")
            if article:
                text = article.get_text("\n", strip=True)
            elif soup.body:
                text = soup.body.get_text("\n", strip=True)
            else:
                text = soup.get_text("\n", strip=True)

            cleaned = _normalize_text(text)
            corpus_path.write_text(cleaned, encoding="utf-8", errors="ignore")
            corpus_paths.append(corpus_path)
            print(f"[fetch] saved {url} -> {corpus_path}")
        except Exception as exc:  # pragma: no cover - network variability
            print(f"[fetch][warn] failed to fetch {url}: {exc}")
        time.sleep(1.2)
    return corpus_paths
