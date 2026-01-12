from __future__ import annotations
from typing import Dict, Tuple


def _weighted_sum(values: Dict[str, float], weights: Dict[str, float]) -> float:
    active = {k: v for k, v in values.items() if k in weights}
    if not active:
        return 0.0
    sw = sum(weights[k] for k in active)
    if sw <= 0:
        return 0.0
    return sum(active[k] * weights[k] for k in active) / sw


def decide(score: float, length_chars: float, hi: float, mid: float) -> str:
    if length_chars < 300:
        return "INSUFFICIENT_TEXT"
    if score >= hi:
        return "AI_LIKE"
    if score >= mid:
        return "GREY"
    return "HUMAN_LIKE"


def ensemble_lite(feats: Dict[str, float], weights: Dict[str, float], thresholds: Dict[str, float]) -> Tuple[float, str]:
    score = _weighted_sum(feats, weights)
    decision = decide(score, feats.get("length_chars", 0.0), thresholds.get("hi", 0.45), thresholds.get("mid", 0.35))
    return score, decision


def ensemble_full(feats: Dict[str, float], clf_mean: float | None, clf_max: float | None,
                  lite_w: Dict[str, float], full_w: Dict[str, float], thresholds: Dict[str, float]) -> Tuple[float, str]:
    if clf_mean is None or clf_max is None:
        # fallback to lite
        return ensemble_lite(feats, lite_w, thresholds)
    values = dict(feats)
    values.update({"clf_mean": float(clf_mean), "clf_max": float(clf_max)})
    score = _weighted_sum(values, full_w)
    decision = decide(score, feats.get("length_chars", 0.0), thresholds.get("hi", 0.45), thresholds.get("mid", 0.35))
    return score, decision

