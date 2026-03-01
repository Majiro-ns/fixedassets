"""
F8 期待配当推定モジュール (cmd_144k_sub2)

score_spread と出走人数から競輪レースの三連単期待配当を推定する。
オッズデータが存在する場合はオッズから直接計算（将来拡張）。
現在はルールベースの推定式を使用。

■ 推定式の根拠
  2/28 大垣S級一予選 9車立て 8レース実績 calibration:
  - 実績平均三連単: ¥7,151 (spread range: 12.70〜17.04)
  - spread 大 → 本命馬優位 → 低配当 (逆相関)
  - spread 小 → 拮抗 → 荒れやすい → 高配当
    ただし score_spread フィルター通過域 (>=12) は中配当帯

■ 推定誤差の想定
  個別レースで ±50〜200% の誤差が発生しうる（競輪は確率的）。
  F8フィルターとの統合時は「推定値」として使用し、確定値とみなしてはならない。

■ 手計算検算 (CHECK-7b, 2/28 大垣 S級一予選 9車立て 8レース):
  R2  (spread=17.04, 16-20zone): 12,000 × 0.5 = 6,000  実績=8,710
  R3  (spread=14.55, 12-16zone): 12,000 × 0.8 = 9,600  実績=5,060
  R5  (spread=14.12, 12-16zone): 12,000 × 0.8 = 9,600  実績=18,230
  R7  (spread=12.85, 12-16zone): 12,000 × 0.8 = 9,600  実績=17,100
  R8  (spread=15.00, 12-16zone): 12,000 × 0.8 = 9,600  実績=4,060
  R9  (spread=15.90, 12-16zone): 12,000 × 0.8 = 9,600  実績=1,500
  R10 (spread=14.02, 12-16zone): 12,000 × 0.8 = 9,600  実績=1,310
  R11 (spread=12.70, 12-16zone): 12,000 × 0.8 = 9,600  実績=1,240
  推定平均: 9,150円  実績平均: 7,151円  誤差: +28%
  → 全8レースとも推定値 < ¥20,000 → F8で正しく除外可能

使用例:
    from src.expected_payout import estimate_expected_payout

    # レースデータに expected_payout を補完してからフィルター適用
    race["expected_payout"] = estimate_expected_payout(race)
    engine = FilterEngine("config/keirin/filters.yaml")
    passed, reasons = engine.apply(race)
"""

from typing import List, Optional, Tuple


# ─── 基準配当（車立て別, S級一予選の歴史的中央値） ────────────────────────
# calibration: 2/28 大垣S級一予選 9車立て 8レース平均 ¥7,151 より設定
_BASE_PAYOUT_BY_ENTRY_COUNT: dict = {
    9: 12_000,   # 9車立て（一予選・予選で最多）
    8: 8_000,    # 8車立て
    7: 5_500,    # 7車立て
    6: 4_000,    # 6車立て（稀）
}
_DEFAULT_BASE_PAYOUT: float = 10_000  # 5車以下・不明時のデフォルト


# ─── score_spread 区間別配当乗数 ───────────────────────────────────────────
# 形式: (lower_bound_inclusive, upper_bound_exclusive, multiplier)
# 根拠: spread大→本命馬圧倒→低配当。spread小→実力拮抗→荒れやすい。
# 2/28 大垣実データと理論的な逆相関から設定。
_SPREAD_MULTIPLIER_TABLE: List[Tuple[float, float, float]] = [
    (20.0, float("inf"), 0.30),  # spread >= 20: 本命圧倒 → 非常に低配当
    (16.0, 20.0,         0.50),  # spread 16-20: 低配当
    (12.0, 16.0,         0.80),  # spread 12-16: フィルター通過ゾーン
    (8.0,  12.0,         1.50),  # spread  8-12: やや荒れ (score_spreadフィルターで除外済み)
    (0.0,   8.0,         2.50),  # spread  < 8:  荒れゾーン (score_spreadフィルターで除外済み)
]


def compute_score_spread(race: dict) -> Optional[float]:
    """
    レースの score_spread (競走得点 max - min) を計算する。

    entries の score フィールドから有効な正値を抽出して計算する。
    有効な得点が2つ未満の場合は None を返す（データ不足）。

    Args:
        race: レースデータ辞書（entries リストを含む）

    Returns:
        得点スプレッド (float, 単位: 点)。データ不足時は None。
    """
    entries = race.get("entries", [])
    scores = [
        float(e.get("score", 0) or 0)
        for e in entries
        if e.get("score") is not None and float(e.get("score", 0) or 0) > 0
    ]
    if len(scores) < 2:
        return None
    return max(scores) - min(scores)


def _get_spread_multiplier(spread: float) -> float:
    """
    score_spread から配当乗数を取得する。

    _SPREAD_MULTIPLIER_TABLE を参照して区間に対応する乗数を返す。
    区間外の場合は 1.0 を返す（フォールバック）。

    Args:
        spread: 競走得点スプレッド (0.0 以上の float)

    Returns:
        配当乗数 (float)
    """
    for lo, hi, mult in _SPREAD_MULTIPLIER_TABLE:
        if lo <= spread < hi:
            return mult
    return 1.0  # フォールバック（通常は到達しない）


def estimate_expected_payout(race: dict) -> Optional[float]:
    """
    レースの三連単期待配当を推定する。

    推定ロジック（優先順位）:
    1. race に "odds_favorite" フィールドが存在する場合:
       本命オッズから直接推定。formula: odds × 100 × 0.75
       (控除率25%を考慮した期待値。出典: 競輪控除率25%)
    2. score_spread が計算可能な場合:
       基準配当 × spread乗数 で推定
       base = _BASE_PAYOUT_BY_ENTRY_COUNT[num_entries]
       mult = _get_spread_multiplier(score_spread)
       expected = base × mult
    3. それ以外: None を返す（F8フィルターをスキップ）

    calibration (2/28 大垣S級一予選 9車立て, n=8):
      推定平均: ¥9,150  実績平均: ¥7,151  誤差: +28%
      全8レースとも推定値 < ¥20,000 → F8で正しく除外可能

    Args:
        race: レースデータ辞書。
              推奨フィールド: entries (score付き選手リスト)
              任意フィールド: odds_favorite (本命オッズ)

    Returns:
        推定期待配当 (float, 単位: 円)。推定不能の場合は None。

    Note:
        推定値は統計的中央値の近似であり、個別レースの実際の配当とは
        大きく乖離する場合がある（典型的誤差: ±50〜200%）。
        F8フィルターとの統合時は「推定値」として利用し、確定値とみなしてはならない。
    """
    # オプション1: オッズデータがある場合（将来拡張）
    odds_favorite = race.get("odds_favorite")
    if odds_favorite is not None:
        try:
            return float(odds_favorite) * 100.0 * 0.75
        except (TypeError, ValueError):
            pass  # オッズが不正値の場合は次の方法へ

    # オプション2: score_spread + 出走人数ベース推定
    spread = compute_score_spread(race)
    if spread is None:
        return None

    entries = race.get("entries", [])
    num_entries = len(entries)
    base = _BASE_PAYOUT_BY_ENTRY_COUNT.get(num_entries, _DEFAULT_BASE_PAYOUT)
    mult = _get_spread_multiplier(spread)
    return base * mult
