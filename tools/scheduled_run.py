from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None


class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a+")
        if msvcrt is not None:
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._fh is None:
            return
        if msvcrt is not None:
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        self._fh.close()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _note_factory_root() -> Path:
    return _repo_root() / "note-factory"


def _theme_id_from_theme(theme: Dict[str, str]) -> str:
    payload = json.dumps(theme, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _load_theme_rows(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = [row for row in reader]

    if "status" not in fieldnames:
        fieldnames.append("status")
    for row in rows:
        if not row.get("status"):
            row["status"] = "new"
    return fieldnames, rows


def _write_theme_rows(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _select_theme_row(rows: List[Dict[str, str]]) -> Tuple[int, Dict[str, str]]:
    for idx, row in enumerate(rows):
        status = str(row.get("status") or "new").strip().lower()
        if status == "new":
            return idx, row
    raise RuntimeError("no themes with status=new")


def _set_theme_status(rows: List[Dict[str, str]], idx: int, status: str) -> None:
    rows[idx]["status"] = status


def _load_persona_ids(personas_csv: Path, role: str) -> List[str]:
    ids: List[str] = []
    with personas_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            persona_id = (row.get("persona_id") or "").strip()
            if not persona_id:
                continue
            enabled = (row.get("有効") or "").strip()
            if enabled == "0":
                continue
            persona_role = (row.get("役割") or "").strip()
            if persona_role != role:
                continue
            ids.append(persona_id)
    return ids


def _select_personas_round_robin(persona_ids: List[str], state_path: Path, n: int) -> List[str]:
    if not persona_ids:
        raise RuntimeError("no personas available for round-robin")
    state = {"index": 0}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {"index": 0}
    idx = int(state.get("index", 0)) % len(persona_ids)
    selected = [persona_ids[(idx + i) % len(persona_ids)] for i in range(n)]
    state["index"] = (idx + n) % len(persona_ids)
    state["persona_ids"] = persona_ids
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return selected


def _run_generate_batch(
    *,
    note_factory_root: Path,
    pipeline_name: str,
    engine: str,
    seed: int,
    experiment_id: str,
    theme: Dict[str, str],
    persona_id: str,
) -> Tuple[Optional[Path], int]:
    env = os.environ.copy()
    env["NOTE_FACTORY_EXPERIMENT_ID"] = experiment_id
    env["NOTE_FACTORY_THEME_OVERRIDE"] = json.dumps(theme, ensure_ascii=False)
    env["NOTE_FACTORY_FORCE_PERSONA"] = f"integrator:{persona_id}"

    cmd = [
        sys.executable,
        str(note_factory_root / "scripts" / "generate_batch.py"),
        "--pipeline",
        pipeline_name,
        "--auto",
        "--n",
        "1",
        "--engine",
        engine,
        "--seed",
        str(seed),
    ]
    proc = subprocess.run(cmd, cwd=str(note_factory_root), env=env, capture_output=True, text=True)
    if proc.returncode == 0 and proc.stdout.strip():
        run_dir_path = Path(proc.stdout.strip())
        return run_dir_path, int(proc.returncode)
    return None, int(proc.returncode)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", default="core")
    parser.add_argument("--pipeline", default="note_full")
    parser.add_argument("--n-personas", type=int, default=1)
    parser.add_argument("--engine", default="codex", choices=["codex", "gemini"])
    args = parser.parse_args(argv)

    note_factory_root = _note_factory_root()
    themes_csv = note_factory_root / "themes" / f"{args.pool}.csv"
    personas_csv = note_factory_root / "config" / "personas.csv"
    state_path = note_factory_root / "state" / "rr_persona_index.json"
    theme_lock = themes_csv.with_suffix(themes_csv.suffix + ".lock")
    state_lock = state_path.with_suffix(state_path.suffix + ".lock")

    with FileLock(theme_lock):
        fieldnames, rows = _load_theme_rows(themes_csv)
        idx, row = _select_theme_row(rows)
        _set_theme_status(rows, idx, "queued")
        _write_theme_rows(themes_csv, fieldnames, rows)

    theme = {
        "theme": (row.get("theme") or "").strip(),
        "catchcopy": (row.get("catchcopy") or "").strip(),
        "paid_flag": str((row.get("paid_flag") or "0")).strip(),
        "tags": (row.get("tags") or "").strip(),
    }
    theme_id = _theme_id_from_theme(theme)
    seed = int(theme_id[:8], 16)
    experiment_id = f"exp_{theme_id}"

    with FileLock(state_lock):
        persona_ids = _load_persona_ids(personas_csv, role="integrator")
        selected = _select_personas_round_robin(persona_ids, state_path, max(1, int(args.n_personas)))

    exit_code = 0
    run_produced_valid_article = False # New flag
    for persona_id in selected:
        run_dir, rc = _run_generate_batch(
            note_factory_root=note_factory_root,
            pipeline_name=args.pipeline,
            engine=args.engine,
            seed=seed,
            experiment_id=experiment_id,
            theme=theme,
            persona_id=persona_id,
        )
        if rc != 0:
            exit_code = rc
        
        if run_dir:
            article_path = run_dir / "article.md"
            if article_path.exists() and os.path.getsize(article_path) > 0:
                run_produced_valid_article = True # Set to True if any run produces a valid article

    with FileLock(theme_lock):
        fieldnames, rows = _load_theme_rows(themes_csv)
        if run_produced_valid_article: # Check this new flag
            _set_theme_status(rows, idx, "used")
        else:
            # If no run produced a valid article, revert to "new" if it was "queued"
            if rows[idx].get("status") == "queued":
                _set_theme_status(rows, idx, "new")
        _write_theme_rows(themes_csv, fieldnames, rows)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
