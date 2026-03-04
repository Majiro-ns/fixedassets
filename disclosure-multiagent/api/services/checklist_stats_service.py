"""チェックリスト評価統計サービス (T011)

評価統計の集計ロジック:
  - eval_history テーブルの全レコードから coverage_rate を集計
  - results_json を解析して item_id 別マッチ回数をランキング

設計方針:
  - compute_summary / compute_top_items は純粋関数（DB非依存・テスト容易）
  - _fetch_rows は DB アクセスのみ担当
  - 公開 API (get_summary / get_top_items) が fetch + compute を連結
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from api.services.checklist_eval_service import _get_connection


# ─── 純粋関数（ユニットテスト可能） ───────────────────────────────────────────

def compute_summary(rows: list[dict]) -> dict:
    """coverage_rate フィールドを持つ行リストから統計サマリを計算する。

    Args:
        rows: eval_history 行の dict リスト。coverage_rate (float) を含むこと。

    Returns:
        {
            "total_evaluations": int,
            "avg_coverage_rate": float,  # 小数点2桁に丸める
            "max_coverage_rate": float,
            "min_coverage_rate": float,  # 0件時は 0.0
        }
    """
    total = len(rows)
    if total == 0:
        return {
            "total_evaluations": 0,
            "avg_coverage_rate": 0.0,
            "max_coverage_rate": 0.0,
            "min_coverage_rate": 0.0,
        }

    rates = [r["coverage_rate"] for r in rows]
    avg = round(sum(rates) / total, 2)
    return {
        "total_evaluations": total,
        "avg_coverage_rate": avg,
        "max_coverage_rate": max(rates),
        "min_coverage_rate": min(rates),
    }


def compute_top_items(
    rows: list[dict],
    top_n: int = 10,
) -> dict:
    """results_json を解析して最多マッチ項目ランキングを計算する。

    Args:
        rows: eval_history 行の dict リスト。results_json (str|list) を含むこと。
        top_n: 上位何件を返すか（デフォルト10）。

    Returns:
        {
            "total_evaluations": int,
            "items": [
                {
                    "item_id": str,
                    "item_name": str,
                    "match_count": int,
                    "match_rate": float,  # 全評価中のマッチ率(%)、小数点1桁
                }
            ],
            "count": int,
        }

    Notes:
        - 同一評価内で同一 item_id が複数回マッチしても 1 カウントとして扱う。
        - match_rate = match_count / total_evaluations * 100
    """
    total = len(rows)

    # item_id → item_name マッピングと match カウンター
    id_to_name: dict[str, str] = {}
    match_counter: Counter = Counter()

    for row in rows:
        results_raw = row.get("results_json", "[]")
        if isinstance(results_raw, str):
            try:
                results = json.loads(results_raw)
            except json.JSONDecodeError:
                results = []
        else:
            results = results_raw  # すでにリストの場合（テスト用）

        for item in results:
            if not item.get("matched", False):
                continue
            item_id = item.get("id", "")
            if not item_id:
                continue
            if item_id not in id_to_name:
                id_to_name[item_id] = item.get("item", "")
            match_counter[item_id] += 1

    top = match_counter.most_common(top_n)
    items = [
        {
            "item_id": item_id,
            "item_name": id_to_name.get(item_id, ""),
            "match_count": cnt,
            "match_rate": round(cnt / total * 100, 1) if total > 0 else 0.0,
        }
        for item_id, cnt in top
    ]

    return {
        "total_evaluations": total,
        "items": items,
        "count": len(items),
    }


# ─── DB アクセス ───────────────────────────────────────────────────────────────

def _fetch_rows() -> list[dict]:
    """eval_history の全行を取得する（coverage_rate + results_json 含む）。"""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT coverage_rate, results_json FROM eval_history ORDER BY evaluated_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── 公開 API ──────────────────────────────────────────────────────────────────

def get_summary() -> dict:
    """評価統計サマリを返す。"""
    rows = _fetch_rows()
    return compute_summary(rows)


def get_top_items(top_n: int = 10) -> dict:
    """最多マッチチェックリスト項目ランキングを返す。"""
    rows = _fetch_rows()
    return compute_top_items(rows, top_n=top_n)
