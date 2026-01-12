from __future__ import annotations
import csv
import os
import subprocess
from pathlib import Path
from typing import Iterable, Dict


def write_csv(rows: Iterable[Dict[str, object]], out_path: str | Path, encoding: str = "cp932") -> str:
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "filename", "length_chars", "clf_ai_prob_mean", "clf_ai_prob_max",
        "ttr", "avg_sentence_len", "connective_rate", "trigram_repeat_ratio",
        "rhythm_variance", "abstract_rate", "punct_density",
        "ensemble_score", "decision",
    ]
    with open(out_p, "w", newline="", encoding=encoding, errors="strict") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return out_p.as_posix()


def open_in_explorer_select(file_path: str | Path) -> None:
    # Windows only
    p = Path(file_path)
    if os.name == "nt":
        try:
            subprocess.Popen(["explorer.exe", f"/select,\"{p.as_posix()}\""])
        except Exception:
            pass
