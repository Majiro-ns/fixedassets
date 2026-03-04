"""開示チェックリスト API ルーター

KPMGチェックリスト等の実務判断データに基づく開示項目照合エンドポイント。

エンドポイント:
  GET  /api/checklist          → チェックリスト一覧取得
  POST /api/checklist/validate → 開示テキストとチェックリストの照合
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from api.models.schemas import (
    ChecklistItem,
    ChecklistResponse,
    ValidateRequest,
    ValidateResponse,
    ChecklistMatchResult,
)

router = APIRouter(prefix="/api/checklist", tags=["checklist"])

_DATA_PATH = Path(__file__).parent.parent / "data" / "checklist_data.json"


@lru_cache(maxsize=1)
def _load_checklist() -> dict:
    """checklist_data.json を読み込む（起動後キャッシュ）。"""
    if not _DATA_PATH.exists():
        raise FileNotFoundError(f"checklist_data.json が見つかりません: {_DATA_PATH}")
    with open(_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _get_items(
    categories: Optional[list[str]] = None,
    required_only: bool = False,
) -> list[dict]:
    """チェックリスト項目を絞り込んで返す。"""
    data = _load_checklist()
    items = data["items"]

    if required_only:
        items = [it for it in items if it.get("required", False)]

    if categories:
        items = [it for it in items if it.get("category") in categories]

    return items


# ── GET /api/checklist ────────────────────────────────────────────────────────

@router.get("", response_model=ChecklistResponse)
async def list_checklist(
    category: Optional[str] = Query(None, description="カテゴリ絞り込み（例: 固定資産）"),
    required_only: bool = Query(False, description="必須項目のみ返す"),
):
    """開示チェックリスト一覧を返す。

    クエリパラメータ:
      - category: カテゴリ名で絞り込み（省略時は全件）
      - required_only: True の場合 required=true の項目のみ返す

    CHECK-9 根拠:
      - version / last_updated / source は checklist_data.json のメタデータから取得
      - items は絞り込み後のリスト
      - total は items の件数と一致
    """
    data = _load_checklist()
    categories = [category] if category else None
    raw_items = _get_items(categories=categories, required_only=required_only)

    items = [ChecklistItem(**it) for it in raw_items]

    return ChecklistResponse(
        version=data["version"],
        last_updated=data["last_updated"],
        source=data["source"],
        total=len(items),
        items=items,
    )


# ── POST /api/checklist/validate ─────────────────────────────────────────────

@router.post("/validate", response_model=ValidateResponse)
async def validate_checklist(request: ValidateRequest):
    """開示テキストとチェックリストを照合し、開示充足度を返す。

    照合ロジック:
      - 各チェックリスト項目の keywords が disclosure_text に含まれるか検索
      - 1つ以上の keyword がマッチすれば matched=True
      - coverage_rate = matched_count / total_checked

    CHECK-9 根拠:
      - matched は keywords の OR 検索（1件以上マッチで True）
      - unmatched_required_count は required=True かつ matched=False の件数
      - coverage_rate = matched_count / total_checked（total_checked=0 の場合は 0.0）
    """
    if not request.disclosure_text.strip():
        raise HTTPException(status_code=400, detail="disclosure_text が空です")

    raw_items = _get_items(
        categories=request.categories,
        required_only=request.required_only,
    )

    text_lower = request.disclosure_text.lower()
    results: list[ChecklistMatchResult] = []

    for it in raw_items:
        keywords = it.get("keywords", [])
        matched_kws = [kw for kw in keywords if kw in request.disclosure_text or kw.lower() in text_lower]
        matched = len(matched_kws) > 0

        results.append(ChecklistMatchResult(
            id=it["id"],
            category=it["category"],
            item=it["item"],
            required=it.get("required", False),
            matched=matched,
            matched_keywords=matched_kws,
            standard=it.get("standard", ""),
        ))

    total_checked = len(results)
    matched_count = sum(1 for r in results if r.matched)
    unmatched_required = [r for r in results if r.required and not r.matched]

    coverage_rate = matched_count / total_checked if total_checked > 0 else 0.0

    return ValidateResponse(
        total_checked=total_checked,
        matched_count=matched_count,
        unmatched_required_count=len(unmatched_required),
        coverage_rate=coverage_rate,
        results=results,
        unmatched_required_ids=[r.id for r in unmatched_required],
    )
