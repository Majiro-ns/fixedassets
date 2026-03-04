"""サプライヤー比較・最安値探索サービス (T008)

price_history テーブルの supplier_id / source フィールドを活用し、
複数サプライヤーの最新価格を比較する。

コスト最小化ロジック:
  - 現在: price をそのまま cost_score として使用
  - 拡張予定: リードタイムを加味したスコア = price * (1 + lead_days * weight / 100)
"""
from __future__ import annotations

from typing import List, Optional

from api.services.db import get_connection


# ─── 内部定数 ──────────────────────────────────────────────────────────────────

_SQL_LATEST_BY_SUPPLIER = """
    SELECT
        s.id    AS supplier_id,
        s.name  AS supplier_name,
        s.code  AS supplier_code,
        ph.price        AS latest_price,
        ph.fetched_at   AS price_date,
        ph.source
    FROM price_history ph
    JOIN suppliers s ON s.id = ph.supplier_id
    WHERE ph.part_id = ?
      AND ph.supplier_id IS NOT NULL
      AND ph.id IN (
          SELECT MAX(ph2.id)
          FROM price_history ph2
          WHERE ph2.part_id = ?
            AND ph2.supplier_id IS NOT NULL
          GROUP BY ph2.supplier_id
      )
    ORDER BY ph.price ASC
"""

_SQL_LATEST_BY_SOURCE = """
    SELECT
        NULL            AS supplier_id,
        ph.source       AS supplier_name,
        NULL            AS supplier_code,
        ph.price        AS latest_price,
        ph.fetched_at   AS price_date,
        ph.source
    FROM price_history ph
    WHERE ph.part_id = ?
      AND ph.supplier_id IS NULL
      AND ph.source IS NOT NULL
      AND ph.id IN (
          SELECT MAX(ph2.id)
          FROM price_history ph2
          WHERE ph2.part_id = ?
            AND ph2.supplier_id IS NULL
            AND ph2.source IS NOT NULL
          GROUP BY ph2.source
      )
    ORDER BY ph.price ASC
"""


# ─── 公開 API ──────────────────────────────────────────────────────────────────

def get_supplier_list() -> List[dict]:
    """登録サプライヤー一覧（suppliers テーブル）を返す。"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, code FROM suppliers WHERE is_active = 1 ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_supplier_price_comparison(part_number: str) -> Optional[dict]:
    """部品番号に対し、サプライヤー別最新価格一覧を返す。

    返り値:
        {
            "part_number": str,
            "description": str | None,
            "suppliers": [
                {
                    "supplier_id": int | None,
                    "supplier_name": str,
                    "supplier_code": str | None,
                    "latest_price": float,
                    "price_date": str,
                    "source": str | None,
                    "is_cheapest": bool,
                    "cost_score": float,
                },
                ...
            ],
            "cheapest_supplier": str | None,
            "cheapest_price": float | None,
        }
        部品が存在しない場合は None。
    """
    conn = get_connection()
    try:
        part_row = conn.execute(
            "SELECT id, description FROM parts WHERE part_number = ?",
            (part_number,),
        ).fetchone()
        if part_row is None:
            return None

        part_id = part_row["id"]

        # supplier_id 付きレコード
        rows_sup = conn.execute(_SQL_LATEST_BY_SUPPLIER, (part_id, part_id)).fetchall()

        # source のみのレコード（supplier_id なし）。supplier_id 側と重複する source は除外
        known_sources = {r["source"] for r in rows_sup if r["source"]}
        rows_src = conn.execute(_SQL_LATEST_BY_SOURCE, (part_id, part_id)).fetchall()
        rows_src = [r for r in rows_src if r["supplier_name"] not in known_sources]

        merged = sorted(
            [dict(r) for r in rows_sup] + [dict(r) for r in rows_src],
            key=lambda r: r["latest_price"],
        )

        if not merged:
            return {
                "part_number": part_number,
                "description": part_row["description"],
                "suppliers": [],
                "cheapest_supplier": None,
                "cheapest_price": None,
            }

        min_price = merged[0]["latest_price"]
        suppliers = [
            {
                **r,
                "is_cheapest": (r["latest_price"] == min_price),
                "cost_score": r["latest_price"],   # リードタイム考慮は拡張予定
            }
            for r in merged
        ]

        return {
            "part_number": part_number,
            "description": part_row["description"],
            "suppliers": suppliers,
            "cheapest_supplier": merged[0]["supplier_name"],
            "cheapest_price": min_price,
        }
    finally:
        conn.close()


def get_cheapest_supplier(part_number: str) -> Optional[dict]:
    """最安値サプライヤーのみを返す（発注先推奨）。

    返り値:
        {
            "part_number": str,
            "description": str | None,
            "supplier_id": int | None,
            "supplier_name": str,
            "supplier_code": str | None,
            "latest_price": float,
            "price_date": str,
            "source": str | None,
        }
        部品が存在しない、または価格データがない場合は None。
    """
    result = get_supplier_price_comparison(part_number)
    if result is None or not result["suppliers"]:
        return None
    cheapest = result["suppliers"][0]   # already sorted ASC
    return {
        "part_number": result["part_number"],
        "description": result["description"],
        "supplier_id": cheapest["supplier_id"],
        "supplier_name": cheapest["supplier_name"],
        "supplier_code": cheapest["supplier_code"],
        "latest_price": cheapest["latest_price"],
        "price_date": cheapest["price_date"],
        "source": cheapest["source"],
    }
