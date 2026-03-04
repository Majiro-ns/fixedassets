"""チェックリスト評価履歴サービス (T010)

評価ロジック:
  - checklist_data.json の 25 項目とテキストをキーワードマッチング
  - 評価結果を SQLite の eval_history テーブルに保存
  - 評価 ID は UUID4（衝突確率 ≒ 0）

DB スキーマ:
  eval_history (
    eval_id                  TEXT PK  -- UUID4
    evaluated_at             TEXT     -- ISO 8601 datetime
    text_snippet             TEXT     -- 先頭 200 文字
    total_checked            INTEGER
    matched_count            INTEGER
    unmatched_required_count INTEGER
    coverage_rate            REAL
    results_json             TEXT     -- JSON: list[ChecklistMatchResult-like dict]
    unmatched_required_ids   TEXT     -- JSON: list[str]
  )
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from api.routers.checklist import _get_items

# ─── DB 設定 ──────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "data" / "disclosure.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS eval_history (
    eval_id                  TEXT PRIMARY KEY,
    evaluated_at             TEXT NOT NULL,
    text_snippet             TEXT NOT NULL,
    total_checked            INTEGER NOT NULL,
    matched_count            INTEGER NOT NULL,
    unmatched_required_count INTEGER NOT NULL,
    coverage_rate            REAL NOT NULL,
    results_json             TEXT NOT NULL,
    unmatched_required_ids   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_history_at ON eval_history(evaluated_at DESC);
"""


def get_db_path() -> str:
    """DB パスを環境変数 DISCLOSURE_DB_PATH から取得（テスト用に上書き可能）。"""
    return os.environ.get("DISCLOSURE_DB_PATH", str(_DEFAULT_DB_PATH))


def _get_connection() -> sqlite3.Connection:
    path = get_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_CREATE_TABLE_SQL)
    return conn


# ─── 公開 API ──────────────────────────────────────────────────────────────────

def evaluate_and_save(
    disclosure_text: str,
    categories: Optional[list[str]] = None,
    required_only: bool = False,
) -> dict:
    """開示テキストをチェックリストと照合し、評価結果を DB に保存してサマリを返す。

    返り値:
        {
            "eval_id": str (UUID4),
            "evaluated_at": str (ISO 8601),
            "text_snippet": str (先頭200文字),
            "total_checked": int,
            "matched_count": int,
            "unmatched_required_count": int,
            "coverage_rate": float,
        }

    例外:
        ValueError: disclosure_text が空の場合
    """
    if not disclosure_text.strip():
        raise ValueError("disclosure_text が空です")

    raw_items = _get_items(categories=categories, required_only=required_only)
    text_lower = disclosure_text.lower()
    results = []

    for it in raw_items:
        keywords = it.get("keywords", [])
        matched_kws = [
            kw for kw in keywords
            if kw in disclosure_text or kw.lower() in text_lower
        ]
        matched = len(matched_kws) > 0
        results.append({
            "id": it["id"],
            "category": it["category"],
            "item": it["item"],
            "required": it.get("required", False),
            "matched": matched,
            "matched_keywords": matched_kws,
            "standard": it.get("standard", ""),
        })

    total_checked = len(results)
    matched_count = sum(1 for r in results if r["matched"])
    unmatched_required = [r for r in results if r["required"] and not r["matched"]]
    coverage_rate = matched_count / total_checked if total_checked > 0 else 0.0

    eval_id = str(uuid.uuid4())
    evaluated_at = datetime.now().isoformat(timespec="seconds")
    text_snippet = disclosure_text[:200]
    unmatched_required_ids = [r["id"] for r in unmatched_required]

    conn = _get_connection()
    try:
        conn.execute(
            """INSERT INTO eval_history
               (eval_id, evaluated_at, text_snippet, total_checked, matched_count,
                unmatched_required_count, coverage_rate, results_json, unmatched_required_ids)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eval_id,
                evaluated_at,
                text_snippet,
                total_checked,
                matched_count,
                len(unmatched_required),
                coverage_rate,
                json.dumps(results, ensure_ascii=False),
                json.dumps(unmatched_required_ids, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "eval_id": eval_id,
        "evaluated_at": evaluated_at,
        "text_snippet": text_snippet,
        "total_checked": total_checked,
        "matched_count": matched_count,
        "unmatched_required_count": len(unmatched_required),
        "coverage_rate": coverage_rate,
    }


def get_evaluations(limit: int = 20) -> list[dict]:
    """評価履歴サマリ一覧（最新 limit 件）を返す。"""
    conn = _get_connection()
    try:
        rows = conn.execute(
            """SELECT eval_id, evaluated_at, text_snippet, total_checked, matched_count,
                      unmatched_required_count, coverage_rate
               FROM eval_history
               ORDER BY evaluated_at DESC, rowid DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_evaluation_detail(eval_id: str) -> Optional[dict]:
    """特定評価の詳細（全 results 含む）を返す。存在しない場合は None。"""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM eval_history WHERE eval_id = ?",
            (eval_id,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["results"] = json.loads(d.pop("results_json"))
        d["unmatched_required_ids"] = json.loads(d["unmatched_required_ids"])
        return d
    finally:
        conn.close()
