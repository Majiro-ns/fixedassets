"""
賭け式計算モジュール（競輪・競艇共通）
=====================================

競輪・競艇の各賭け式（3連複ながし、ワイド、2連複等）の
点数計算と投資額計算を行う。

settings.yaml の betting セクションと連携する。
"""

from itertools import combinations, permutations
from typing import List, Dict, Optional, Tuple


# ─────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────

DEFAULT_UNIT_BET = 500          # 1点あたりのデフォルト賭け金（円）
DEFAULT_WIDE_UNIT = 300         # ワイド1点あたりのデフォルト賭け金（円）
DEFAULT_MAX_DAILY = 12600       # 1日最大投資額（6レース × 2100円）


# ─────────────────────────────────────────────
# 3連複（競輪: 3車複、競艇: 3連複）
# ─────────────────────────────────────────────

def calc_sanrenpu_nagashi(
    axis: int,
    partners: List[int],
    unit_bet: int = DEFAULT_UNIT_BET,
) -> Dict:
    """
    3連複ながしの点数と投資額を計算する。

    軸（axis）1点 × 相手（partners）からC(n,2)通りの組み合わせ。

    Args:
        axis: 軸の艇番（競輪なら枠番）
        partners: 相手の艇番リスト
        unit_bet: 1点あたりの賭け金（円）

    Returns:
        {
            "bet_type": "3連複ながし",
            "axis": axis,
            "partners": partners,
            "combinations": [...],  # 実際の買い目リスト
            "num_bets": int,        # 点数
            "total_investment": int # 投資額（円）
        }

    Example:
        >>> calc_sanrenpu_nagashi(1, [2, 3, 4, 5], unit_bet=500)
        # 1-23, 1-24, 1-25, 1-34, 1-35, 1-45 → 6点 → 3000円
    """
    # deduplication: 重複番号・axis自身を除外（順序保持）
    partners_dedup = list(dict.fromkeys(p for p in partners if p != axis))
    if len(partners_dedup) < 2:
        raise ValueError(
            f"相手は2名以上必要です（dedup後: {len(partners_dedup)}名）"
            f" partners_raw={partners}"
        )

    # C(partners, 2) の組み合わせを生成
    combos = []
    for pair in combinations(sorted(partners_dedup), 2):
        # 3頭を昇順に並べて買い目を作成
        trio = tuple(sorted([axis] + list(pair)))
        # バリデーション: 3連複は3頭が全て異なる番号であること
        if len(set(trio)) < 3:
            continue
        combos.append(trio)

    if not combos:
        raise ValueError(
            f"有効な3連複組合せなし (axis={axis}, partners={partners_dedup})"
        )

    num_bets = len(combos)
    total = num_bets * unit_bet

    return {
        "bet_type": "3連複ながし",
        "axis": axis,
        "partners": partners_dedup,
        "combinations": combos,
        "num_bets": num_bets,
        "unit_bet": unit_bet,
        "total_investment": total,
        "display": _format_nagashi(axis, partners_dedup, "3連複"),
    }


def calc_sanrentan_nagashi(
    axis: int,
    partners: List[int],
    unit_bet: int = DEFAULT_UNIT_BET,
) -> Dict:
    """
    3連単軸1着ながしの点数と投資額を計算する。

    軸が1着固定、相手2〜3着の全順列。

    Args:
        axis: 1着固定の艇番
        partners: 2〜3着の相手艇番リスト
        unit_bet: 1点あたりの賭け金

    Returns:
        3連単ながしの計算結果

    Example:
        >>> calc_sanrentan_nagashi(1, [2, 3, 4], unit_bet=500)
        # 1-2-3, 1-2-4, 1-3-2, 1-3-4, 1-4-2, 1-4-3 → 6点 → 3000円
    """
    # deduplication: 重複番号・axis自身を除外（順序保持）
    partners_dedup = list(dict.fromkeys(p for p in partners if p != axis))
    if len(partners_dedup) < 2:
        raise ValueError(
            f"相手は2名以上必要です（dedup後: {len(partners_dedup)}名）"
            f" partners_raw={partners}"
        )

    combos = []
    for perm in permutations(partners_dedup, 2):
        combos.append((axis,) + perm)

    num_bets = len(combos)
    total = num_bets * unit_bet

    return {
        "bet_type": "3連単ながし（1着軸）",
        "axis": axis,
        "partners": partners_dedup,
        "combinations": combos,
        "num_bets": num_bets,
        "unit_bet": unit_bet,
        "total_investment": total,
        "display": _format_nagashi(axis, partners_dedup, "3連単"),
    }


# ─────────────────────────────────────────────
# ワイド（2頭複合）
# ─────────────────────────────────────────────

def calc_wide_nagashi(
    axis: int,
    partners: List[int],
    unit_bet: int = DEFAULT_WIDE_UNIT,
) -> Dict:
    """
    ワイドながしの点数と投資額を計算する。

    ワイド = 上位2着以内に指定の2艇が入れば的中（着順不問）。

    Args:
        axis: 軸の艇番
        partners: 相手の艇番リスト
        unit_bet: 1点あたりの賭け金（円）

    Returns:
        ワイドながしの計算結果
    """
    # deduplication: 重複番号・axis自身を除外（順序保持）
    partners_dedup = list(dict.fromkeys(p for p in partners if p != axis))

    combos = []
    for partner in partners_dedup:
        pair = tuple(sorted([axis, partner]))
        combos.append(pair)

    num_bets = len(combos)
    total = num_bets * unit_bet

    return {
        "bet_type": "ワイドながし",
        "axis": axis,
        "partners": partners_dedup,
        "combinations": combos,
        "num_bets": num_bets,
        "unit_bet": unit_bet,
        "total_investment": total,
        "display": _format_nagashi(axis, partners_dedup, "ワイド"),
    }


# ─────────────────────────────────────────────
# 2車複・2連複
# ─────────────────────────────────────────────

def calc_niren_nagashi(
    axis: int,
    partners: List[int],
    unit_bet: int = DEFAULT_UNIT_BET,
) -> Dict:
    """
    2連複ながし（競艇）/ 2車複ながし（競輪）の計算。

    Args:
        axis: 軸の艇番
        partners: 相手の艇番リスト
        unit_bet: 1点あたりの賭け金

    Returns:
        2連複ながしの計算結果
    """
    # deduplication: 重複番号・axis自身を除外（順序保持）
    partners_dedup = list(dict.fromkeys(p for p in partners if p != axis))
    combos = [tuple(sorted([axis, p])) for p in partners_dedup]
    num_bets = len(combos)
    total = num_bets * unit_bet

    return {
        "bet_type": "2連複ながし",
        "axis": axis,
        "partners": partners_dedup,
        "combinations": combos,
        "num_bets": num_bets,
        "unit_bet": unit_bet,
        "total_investment": total,
        "display": _format_nagashi(axis, partners_dedup, "2連複"),
    }


def calc_niren_tan_nagashi(
    axis: int,
    partners: List[int],
    unit_bet: int = DEFAULT_UNIT_BET,
) -> Dict:
    """
    2連単ながし（軸1着固定）の計算。

    Args:
        axis: 1着固定の艇番
        partners: 2着の相手艇番リスト
        unit_bet: 1点あたりの賭け金

    Returns:
        2連単ながしの計算結果
    """
    # deduplication: 重複番号・axis自身を除外（順序保持）
    partners_dedup = list(dict.fromkeys(p for p in partners if p != axis))
    combos = [(axis, p) for p in partners_dedup]
    num_bets = len(combos)
    total = num_bets * unit_bet

    return {
        "bet_type": "2連単ながし（1着軸）",
        "axis": axis,
        "partners": partners_dedup,
        "combinations": combos,
        "num_bets": num_bets,
        "unit_bet": unit_bet,
        "total_investment": total,
        "display": _format_nagashi(axis, partners_dedup, "2連単"),
    }


# ─────────────────────────────────────────────
# 投資額チェック
# ─────────────────────────────────────────────

def check_daily_budget(
    bets: List[Dict],
    max_daily: int = DEFAULT_MAX_DAILY,
) -> Dict:
    """
    1日の合計投資額が上限を超えていないか確認する。

    Args:
        bets: bet_calculator の返り値リスト
        max_daily: 1日最大投資額（円）

    Returns:
        {
            "total": int,       # 合計投資額
            "limit": int,       # 上限額
            "ok": bool,         # 上限内か
            "over_by": int,     # 超過額（okがFalseの場合）
        }
    """
    total = sum(b["total_investment"] for b in bets)
    ok = total <= max_daily
    return {
        "total": total,
        "limit": max_daily,
        "ok": ok,
        "over_by": max(0, total - max_daily),
    }


# ─────────────────────────────────────────────
# 設定から賭け式を選択するファクトリー関数
# ─────────────────────────────────────────────

def calc_from_strategy(
    strategy: str,
    axis: int,
    partners: List[int],
    config: Dict,
) -> Dict:
    """
    config/settings.yaml の betting.default_strategy から賭け式を選択して計算する。

    Args:
        strategy: "sanrenpu_nagashi" | "sanrentan_nagashi" | "wide" | "niren" | "skip"
        axis: 軸の艇番
        partners: 相手の艇番リスト
        config: settings.yaml の betting セクション

    Returns:
        bet_calculator の返り値 or {"bet_type": "skip", "reason": ...}
    """
    unit_bet = config.get("unit_bet", DEFAULT_UNIT_BET)
    wide_unit = config.get("wide_unit", DEFAULT_WIDE_UNIT)

    strategy_map = {
        "sanrenpu_nagashi": lambda: calc_sanrenpu_nagashi(axis, partners, unit_bet),
        "sanrentan_nagashi": lambda: calc_sanrentan_nagashi(axis, partners, unit_bet),
        "wide": lambda: calc_wide_nagashi(axis, partners, wide_unit),
        "niren": lambda: calc_niren_nagashi(axis, partners, unit_bet),
        "niren_tan": lambda: calc_niren_tan_nagashi(axis, partners, unit_bet),
        "skip": lambda: {"bet_type": "skip", "reason": "フィルター条件未達・見送り"},
    }

    if strategy not in strategy_map:
        raise ValueError(f"不明な戦略: {strategy}。有効値: {list(strategy_map.keys())}")

    return strategy_map[strategy]()


# ─────────────────────────────────────────────
# フォーマット用ヘルパー
# ─────────────────────────────────────────────

def _format_nagashi(axis: int, partners: List[int], bet_type: str) -> str:
    """
    買い目の表示文字列を生成する。

    Args:
        axis: 軸
        partners: 相手リスト
        bet_type: 賭け式名

    Returns:
        "3連複ながし 1-2345" のような文字列
    """
    partners_str = "".join(str(p) for p in sorted(partners))
    return f"{bet_type}ながし {axis}-{partners_str}"


def format_bet_summary(bet_result: Dict) -> str:
    """
    賭け式計算結果を人間が読みやすい文字列にフォーマットする。

    Args:
        bet_result: calc_* 関数の返り値

    Returns:
        フォーマットされた文字列
    """
    if bet_result.get("bet_type") == "skip":
        return f"[見送り] {bet_result.get('reason', '')}"

    lines = [
        f"【{bet_result['bet_type']}】",
        f"  軸: {bet_result.get('axis', '-')}番",
        f"  相手: {', '.join(str(p) for p in bet_result.get('partners', []))}番",
        f"  点数: {bet_result['num_bets']}点",
        f"  単価: {bet_result['unit_bet']}円",
        f"  合計: {bet_result['total_investment']}円",
        f"  買い目: {bet_result.get('display', '')}",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────
# 期待値計算（参考）
# ─────────────────────────────────────────────

def calc_expected_value(
    bet_result: Dict,
    estimated_odds: Optional[float],
    hit_probability: Optional[float],
) -> Optional[float]:
    """
    期待値を計算する（参考値）。

    期待値 = 的中確率 × 払戻金 - 投資額

    Args:
        bet_result: calc_* の返り値
        estimated_odds: 推定オッズ（例: 15.0 = 15倍）
        hit_probability: 推定的中確率（例: 0.15 = 15%）

    Returns:
        期待値（円）、計算不可な場合はNone
    """
    if estimated_odds is None or hit_probability is None:
        return None

    investment = bet_result["total_investment"]
    unit = bet_result["unit_bet"]
    payout = unit * estimated_odds * hit_probability * bet_result["num_bets"]
    ev = payout - investment
    return ev


# ─────────────────────────────────────────────
# Kelly最適配分（Mr.T 842件データ由来）
# ─────────────────────────────────────────────

# フィルター別デフォルト配分テーブル（base_budget=10000円の場合）
# 出典: mr_t_cognitive_profile.yaml / optimal_filters セクション
_KELLY_TABLE: Dict[str, Dict[str, list]] = {
    "keirin": {
        # filter_C: 堅実型 hit_rate=0.583 (mr_t_cognitive_profile.yaml filter_C)
        "C": [
            {"bet_function": "calc_sanrenpu_nagashi", "unit_bet": 1200, "num_bets": 6},
            {"bet_function": "calc_wide_nagashi",     "unit_bet": 1400, "num_bets": 2},
        ],
        # filter_A: 標準型 hit_rate=0.244 (mr_t_cognitive_profile.yaml filter_A)
        "A": [
            {"bet_function": "calc_sanrenpu_nagashi", "unit_bet": 1200, "num_bets": 6},
            {"bet_function": "calc_wide_nagashi",     "unit_bet": 1100, "num_bets": 2},
        ],
        # filter_B: 穴狙い型 hit_rate=0.179 (mr_t_cognitive_profile.yaml filter_B)
        "B": [
            {"bet_function": "calc_sanrenpu_nagashi", "unit_bet":  700, "num_bets": 10},
            {"bet_function": "calc_wide_nagashi",     "unit_bet": 1000, "num_bets":  3},
        ],
    },
    "kyotei": {
        # 競艇 filter_C: 堅実型
        "C": [
            {"bet_function": "calc_niren_tan_nagashi", "unit_bet": 2000, "num_bets": 3},
            {"bet_function": "calc_niren_nagashi",     "unit_bet": 2000, "num_bets": 2},
        ],
        # 競艇 filter_A: 標準型
        "A": [
            {"bet_function": "calc_sanrenpu_nagashi", "unit_bet": 1000, "num_bets": 6},
            {"bet_function": "calc_wide_nagashi",     "unit_bet": 1000, "num_bets": 2},
            {"bet_function": "calc_niren_nagashi",    "unit_bet": 1000, "num_bets": 2},
        ],
        # 競艇 filter_B: 穴狙い型
        "B": [
            {"bet_function": "calc_sanrentan_nagashi", "unit_bet": 1000, "num_bets": 6},
            {"bet_function": "calc_sanrenpu_nagashi",  "unit_bet": 1000, "num_bets": 4},
        ],
    },
}

# SKIPゾーン定義
# 出典: mr_t_cognitive_profile.yaml / shift_patterns.high_expected
# expected_payout 50,000〜100,000円: 回収率87.5%で最悪ゾーン（収支 -420,130円）
_SKIP_ZONE_LOW  = 50_000
_SKIP_ZONE_HIGH = 100_000


def _scale_unit_bet(unit_bet: int, scale: float, min_bet: int = 100) -> int:
    """
    unit_bet を budget スケールに合わせて100円単位に切り捨てる。

    Args:
        unit_bet: ベーステーブル（base_budget=10000）での1点賭け金（円）
        scale: budget / 10000
        min_bet: 最低賭け金（円）

    Returns:
        スケール後の賭け金（100円単位）
    """
    scaled = int(unit_bet * scale)
    # 100円単位に切り捨て
    floored = (scaled // 100) * 100
    return max(floored, min_bet)


def calc_kelly_allocation(
    filter_type: str,
    expected_payout: int,
    budget: int = 10_000,
    sport: str = "keirin",
) -> Dict:
    """
    Mr.T 842件データから導出したフィルター別最適配分を返す。

    SKIPゾーン（expected_payout 50,000〜100,000円）は無条件でスキップを返す。
    それ以外は filter_type・sport に応じた買い目配分計画を返す。

    axis / partners はレースデータから別途設定するため、この関数では計算しない。
    実際の点数・投資額計算には calc_sanrenpu_nagashi 等を別途呼び出すこと。

    Args:
        filter_type: "C"（堅実型 hit_rate=0.583）|
                     "A"（標準型 hit_rate=0.244）|
                     "B"（穴狙い型 hit_rate=0.179）
                     出典: mr_t_cognitive_profile.yaml / optimal_filters
        expected_payout: 推定払戻額（円）。50,000〜100,000円はSKIPゾーン。
                         出典: mr_t_cognitive_profile.yaml / shift_patterns.high_expected
        budget: 1レースの予算（デフォルト10,000円）
        sport: "keirin"（競輪）| "kyotei"（競艇）

    Returns:
        SKIPの場合:
            {"bet_type": "skip", "reason": "最悪ゾーン..."}
        通常の場合:
            {
                "filter_type": str,
                "sport": str,
                "budget": int,
                "total_investment": int,
                "allocation_plan": [
                    {"bet_function": str, "unit_bet": int, "num_bets": int, "subtotal": int},
                    ...
                ],
                "notes": str,
            }

    Raises:
        ValueError: filter_type または sport が不正な値の場合
    """
    # ─── SKIPゾーン判定 ───────────────────────────────────────────
    if _SKIP_ZONE_LOW <= expected_payout <= _SKIP_ZONE_HIGH:
        return {
            "bet_type": "skip",
            "reason": (
                f"最悪ゾーン（expected_payout {expected_payout:,}円 は "
                f"{_SKIP_ZONE_LOW:,}〜{_SKIP_ZONE_HIGH:,}円に該当、"
                "mr_t回収率87.5%: 出典 mr_t_cognitive_profile.yaml shift_patterns.high_expected）"
            ),
        }

    # ─── 入力バリデーション ─────────────────────────────────────
    valid_sports = list(_KELLY_TABLE.keys())
    if sport not in valid_sports:
        raise ValueError(f"不明な sport: {sport!r}。有効値: {valid_sports}")

    valid_filters = list(_KELLY_TABLE[sport].keys())
    if filter_type not in valid_filters:
        raise ValueError(f"不明な filter_type: {filter_type!r}。有効値: {valid_filters}")

    # ─── 配分テーブル取得・スケーリング ─────────────────────────
    scale = budget / 10_000
    base_rows = _KELLY_TABLE[sport][filter_type]

    # フィルター別の的中率ノート
    _hit_rate_notes = {
        "C": "hit_rate=0.583",
        "A": "hit_rate=0.244",
        "B": "hit_rate=0.179",
    }

    allocation_plan = []
    total_investment = 0

    for row in base_rows:
        unit_bet = _scale_unit_bet(row["unit_bet"], scale)
        num_bets = row["num_bets"]
        subtotal = unit_bet * num_bets
        allocation_plan.append({
            "bet_function": row["bet_function"],
            "unit_bet": unit_bet,
            "num_bets": num_bets,
            "subtotal": subtotal,
        })
        total_investment += subtotal

    filter_name = {
        "C": "堅実型",
        "A": "標準型",
        "B": "穴狙い型",
    }.get(filter_type, filter_type)

    return {
        "filter_type": filter_type,
        "sport": sport,
        "budget": budget,
        "total_investment": total_investment,
        "allocation_plan": allocation_plan,
        "notes": (
            f"出典: mr_t_cognitive_profile.yaml filter_{filter_type}"
            f"（{filter_name}, {_hit_rate_notes.get(filter_type, '')}）"
        ),
    }


# ─────────────────────────────────────────────
# メイン（動作確認用）
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=== bet_calculator.py 動作確認 ===\n")

    # 3連複ながし: 軸1番、相手2-3-4-5番
    result = calc_sanrenpu_nagashi(axis=1, partners=[2, 3, 4, 5], unit_bet=500)
    print(format_bet_summary(result))
    print(f"  買い目詳細: {result['combinations']}\n")

    # ワイドながし: 軸1番、相手2-3-4番
    result_w = calc_wide_nagashi(axis=1, partners=[2, 3, 4], unit_bet=300)
    print(format_bet_summary(result_w))
    print()

    # 2連複ながし: 軸1番、相手2-3-4番
    result_n = calc_niren_nagashi(axis=1, partners=[2, 3, 4], unit_bet=500)
    print(format_bet_summary(result_n))
    print()

    # 1日予算チェック
    all_bets = [result, result_w, result_n]
    budget = check_daily_budget(all_bets, max_daily=12600)
    print(f"=== 1日予算チェック ===")
    print(f"  合計投資額: {budget['total']}円")
    print(f"  上限: {budget['limit']}円")
    print(f"  OK: {budget['ok']}")
    if not budget["ok"]:
        print(f"  超過: {budget['over_by']}円")

    print("\n=== calc_kelly_allocation 動作確認 ===")

    # filter_C（堅実型）: expected_payout=30000円（ずらし最適ゾーン内）
    plan_c = calc_kelly_allocation("C", 30000, 10000, "keirin")
    print(f"filter_C (堅実型): {plan_c}")

    # filter_B + 最悪ゾーン（expected_payout=75000円 → SKIP）
    plan_skip = calc_kelly_allocation("B", 75000, 10000, "keirin")
    print(f"filter_B + 最悪ゾーン(75000円): {plan_skip}")

    # 競艇 filter_A
    plan_kyotei = calc_kelly_allocation("A", 30000, 10000, "kyotei")
    print(f"競艇 filter_A: {plan_kyotei}")
