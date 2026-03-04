"""api/services/analytics_service.py

価格トレンド分析・発注タイミング推奨の純粋ビジネスロジック。

DBアクセスは行わず、価格履歴リストを受け取って分析結果を返す。
テスト容易性のため、DBと分離して設計する。
"""
from __future__ import annotations

import statistics
from typing import Any


# ─── 定数 ─────────────────────────────────────────────────────────────────────

TREND_THRESHOLD_PCT = 2.0   # ±2%以内は「安定」とみなす
RISING_BUY_THRESHOLD = 5.0  # 5%以上の上昇 → BUY_NOW（さらに上がる前に買え）
FALLING_WAIT_THRESHOLD = -3.0  # 3%以上の下落 → WAIT（さらに下がるを待て）
NEAR_MIN_THRESHOLD = 1.05   # 現在価格が最安値の1.05倍以内 → BUY_NOW（底値圏）


# ─── トレンド分析 ──────────────────────────────────────────────────────────────

def compute_price_trend(history: list[dict[str, Any]]) -> dict[str, Any]:
    """価格履歴からトレンドを計算する。

    Args:
        history: [{"price": float, "fetched_at": str}, ...] を昇順（古→新）でソートしたもの。
                 呼び出し元が fetched_at ASC でソート済みであること。

    Returns:
        {
            "trend_direction": "rising" | "falling" | "stable" | "unknown",
            "trend_pct": float,          # 最古→最新の変動率(%)
            "avg_price": float,
            "min_price": float,
            "max_price": float,
            "latest_price": float,
            "data_points": int,
            "volatility_pct": float,     # 変動係数(%) = stdev/avg*100
        }
    """
    if not history:
        return {
            "trend_direction": "unknown",
            "trend_pct": 0.0,
            "avg_price": 0.0,
            "min_price": 0.0,
            "max_price": 0.0,
            "latest_price": 0.0,
            "data_points": 0,
            "volatility_pct": 0.0,
        }

    prices = [float(h["price"]) for h in history]
    latest_price = prices[-1]
    first_price = prices[0]
    avg_price = statistics.mean(prices)
    min_price = min(prices)
    max_price = max(prices)

    # トレンド率: (最新 - 最古) / 最古 * 100
    trend_pct = 0.0
    if first_price > 0:
        trend_pct = round((latest_price - first_price) / first_price * 100, 2)

    # トレンド方向
    if trend_pct > TREND_THRESHOLD_PCT:
        trend_direction = "rising"
    elif trend_pct < -TREND_THRESHOLD_PCT:
        trend_direction = "falling"
    else:
        trend_direction = "stable"

    # 変動係数（ボラティリティ）
    volatility_pct = 0.0
    if len(prices) >= 2 and avg_price > 0:
        stdev = statistics.stdev(prices)
        volatility_pct = round(stdev / avg_price * 100, 2)

    return {
        "trend_direction": trend_direction,
        "trend_pct": trend_pct,
        "avg_price": round(avg_price, 2),
        "min_price": round(min_price, 2),
        "max_price": round(max_price, 2),
        "latest_price": round(latest_price, 2),
        "data_points": len(prices),
        "volatility_pct": volatility_pct,
    }


# ─── 発注推奨 ──────────────────────────────────────────────────────────────────

def compute_buy_recommendation(
    trend_direction: str,
    trend_pct: float,
    current_price: float,
    min_price: float,
    avg_price: float,
) -> dict[str, Any]:
    """価格トレンドから発注タイミングを推奨する。

    Args:
        trend_direction: "rising" | "falling" | "stable" | "unknown"
        trend_pct: 最古→最新の変動率(%)
        current_price: 現在価格
        min_price: 履歴の最安値
        avg_price: 履歴の平均価格

    Returns:
        {
            "action": "BUY_NOW" | "WAIT" | "NEUTRAL",
            "reason": str,
            "score": float,   # 0〜100。高いほど「今すぐ買う」が推奨される
        }
    """
    if trend_direction == "unknown" or current_price <= 0:
        return {
            "action": "NEUTRAL",
            "reason": "価格データが不足しています。データが蓄積されるまでお待ちください。",
            "score": 50.0,
        }

    # ──── BUY_NOW 判定（先に確認）────────────────────────────────────────────
    # 底値圏: 現在価格が最安値の NEAR_MIN_THRESHOLD 倍以内
    is_near_min = min_price > 0 and (current_price <= min_price * NEAR_MIN_THRESHOLD)

    if is_near_min:
        score = min(100.0, 80.0 + abs(trend_pct))
        return {
            "action": "BUY_NOW",
            "reason": (
                f"現在価格({current_price:.0f}円)が履歴最安値({min_price:.0f}円)付近です。"
                "底値圏での発注を推奨します。"
            ),
            "score": round(score, 1),
        }

    # 急騰: 上昇トレンドが強いうちに買う
    if trend_pct >= RISING_BUY_THRESHOLD:
        score = min(100.0, 70.0 + trend_pct)
        return {
            "action": "BUY_NOW",
            "reason": (
                f"価格が{trend_pct:.1f}%上昇トレンドです。"
                "さらに値上がりする前に発注することを推奨します。"
            ),
            "score": round(score, 1),
        }

    # ──── WAIT 判定 ────────────────────────────────────────────────────────────
    # 下落トレンド: もう少し待てばさらに安くなる可能性がある
    if trend_pct <= FALLING_WAIT_THRESHOLD:
        score = max(0.0, 30.0 + trend_pct)  # trend_pctは負なので下がるほどスコア低下
        return {
            "action": "WAIT",
            "reason": (
                f"価格が{abs(trend_pct):.1f}%の下落トレンドです。"
                f"平均価格({avg_price:.0f}円)を下回るまで待つことを推奨します。"
            ),
            "score": round(score, 1),
        }

    # ──── NEUTRAL ─────────────────────────────────────────────────────────────
    # 安定 or 小幅上昇
    score = 50.0
    if trend_direction == "rising":
        reason = (
            f"価格が緩やかに上昇中({trend_pct:.1f}%)ですが、急騰ではありません。"
            "通常の発注タイミングで問題ありません。"
        )
        score = 55.0
    elif trend_direction == "falling":
        reason = (
            f"価格が緩やかに下落中({abs(trend_pct):.1f}%)です。"
            "急ぎでなければもう少し様子を見てもよいでしょう。"
        )
        score = 45.0
    else:
        reason = (
            f"価格は安定({trend_pct:+.1f}%)しています。"
            "通常の発注タイミングで問題ありません。"
        )

    return {
        "action": "NEUTRAL",
        "reason": reason,
        "score": round(score, 1),
    }
