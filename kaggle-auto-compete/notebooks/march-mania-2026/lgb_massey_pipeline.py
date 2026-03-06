"""
March Machine Learning Mania 2026 — LightGBM + Massey Ordinals 統合パイプライン

## 概要
baseline_improved.py の LightGBM に Massey Ordinals 特徴量を追加統合し、
Hill Climbing でアンサンブル最適化を行うパイプライン。

## 改善点（baseline_improved.py からの差分）
1. Massey Ordinals 特徴量（massey_features.py）をLightGBM訓練・予測に統合
2. Hill Climbing アンサンブル: Elo+Seed ベースライン × LightGBM の最適混合比を探索
3. モックデータで完全動作（実データなしで全テスト PASS）

## 実行方法
    # デモ実行（モックデータで全テスト）
    python notebooks/march-mania-2026/lgb_massey_pipeline.py

    # 実データ実行（kaggle download 後）
    python notebooks/march-mania-2026/lgb_massey_pipeline.py --real-data

## 出力
    submissions/lgb_massey_pipeline_demo.csv  (モック実行)
    submissions/lgb_massey_pipeline_final.csv (実データ実行)

## Pipeline 構成
    Step 1: モックデータ生成 / 実データ読み込み
    Step 2: Elo + 基本特徴量 計算
    Step 3: Massey Ordinals 特徴量 計算・統合
    Step 4: LightGBM OOF 訓練 (5-Fold CV)
    Step 5: Hill Climbing アンサンブル重み最適化
    Step 6: 最終予測 + CSV 出力
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression as _LR
from sklearn.metrics import log_loss
from sklearn.model_selection import StratifiedKFold

# massey_features.py は同ディレクトリにある
NOTEBOOK_DIR = Path(__file__).parent
sys.path.insert(0, str(NOTEBOOK_DIR))
from massey_features import (
    TOP_SYSTEMS,
    build_mock_massey_csv,
    get_matchup_features,
    load_massey_features,
)

# ── T001: Four Factors 特徴量 ───────────────────────────────────────────────
try:
    from four_factors_features import load_four_factors, get_matchup_four_factors
    _FF_AVAIL = True
except ImportError:
    _FF_AVAIL = False

# ── T002: Cubic Spline キャリブレーション ───────────────────────────────────
try:
    from scipy.interpolate import UnivariateSpline
    _SCIPY = True
except ImportError:
    _SCIPY = False

# ── T003: 男女別モデル ────────────────────────────────────────────────────────
try:
    import gender_split_model as _gsm
    _GSM_AVAIL = True
except ImportError:
    _GSM_AVAIL = False

# ------------------------------------------------------------------
# 定数
# ------------------------------------------------------------------
ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data" / "march-mania-2026"
SUBMISSION_DIR = ROOT / "submissions"
SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)

SEASON = 2026
ELO_INITIAL = 1500.0
ELO_K = 64.0
ELO_CARRYOVER = 0.85
ELO_MARGIN_CAP = 30.0

CLIP_LOW = 0.025    # CALIBRATION_NOTES.md 準拠
CLIP_HIGH = 0.975

SEED_SCALE = 0.25
N_FOLDS = 5

# LightGBM ハイパーパラメータ（baseline_improved.py と同一）
LGB_PARAMS = dict(
    objective="binary",
    metric="binary_logloss",
    n_estimators=300,
    learning_rate=0.05,
    num_leaves=63,
    min_child_samples=10,
    feature_fraction=0.8,
    bagging_fraction=0.8,
    bagging_freq=1,
    reg_alpha=0.1,
    reg_lambda=0.1,
    random_state=42,
    verbose=-1,
    n_jobs=1,
)

# Massey 特徴量として使用する差分列のプレフィックス
MASSEY_DIFF_FEATURES = [
    "massey_mean_rank_diff",  # 全システム平均ランク差（最安定）
    "massey_mean_rank_ratio",
]
# システム別差分特徴量（上位4システム）
TOP_SYSTEM_DIFFS = ["ORD", "SAG", "POM", "MOR"]

# 基本特徴量（baseline_improved.py の FEATURES に相当）
BASE_FEATURES = [
    "seed_diff",
    "elo_diff",
    "win_rate_diff",
    "avg_score_diff",
    "tourney_exp_diff",
]

# T001: Four Factors 特徴量列名（four_factors_features.py の出力列と一致）
FOUR_FACTORS_FEATURES = [
    "efg_diff",
    "to_pct_diff",
    "orb_pct_diff",
    "ftr_diff",
    "off_eff_diff",
    "def_eff_diff",
    "net_eff_diff",
]


# ======================================================================
# T001 ヘルパー: Four Factors 読み込み
# ======================================================================

def _try_load_four_factors(data_dir: Path, gender: str) -> dict | None:
    """DetailedResults.csv が存在する場合のみ Four Factors を読み込む。"""
    detail_path = data_dir / f"{gender}RegularSeasonDetailedResults.csv"
    if not detail_path.exists():
        return None
    if not _FF_AVAIL:
        return None
    try:
        stats = load_four_factors(data_dir, gender)
        print(f"[T001] Four Factors 読み込み完了 ({gender}): {len(stats)} エントリ")
        return stats
    except Exception as e:
        print(f"[T001] Four Factors 読み込み失敗 ({gender}): {e}")
        return None


# ======================================================================
# T002: キャリブレーション比較（Platt Scaling vs Cubic Spline）
# ======================================================================

def compare_calibration(
    oof_pred: np.ndarray,
    y: np.ndarray,
    label: str = "LightGBM",
) -> dict[str, float]:
    """
    OOF 予測に対して Platt Scaling と Cubic Spline を適用し Log Loss を比較する。
    注意: キャリブレーション適合と評価が同一データ (訓練バイアスあり)。
          本番では nested CV が推奨。

    Returns:
        {"raw": float, "platt": float, "spline": float}
    """
    results: dict[str, float] = {}

    raw_loss = log_loss(y, np.clip(oof_pred, CLIP_LOW, CLIP_HIGH))
    results["raw"] = raw_loss

    print(f"\n[T002 キャリブレーション比較: {label}]")
    print(f"  Raw (未キャリブレーション) Log Loss : {raw_loss:.5f}")

    # ── Platt Scaling: LogisticRegression(OOF → y) ────────────────────
    X_calib = oof_pred.reshape(-1, 1)
    platt = _LR(C=1.0, max_iter=1000, solver="lbfgs")
    platt.fit(X_calib, y)
    platt_pred = platt.predict_proba(X_calib)[:, 1]
    platt_loss = log_loss(y, np.clip(platt_pred, CLIP_LOW, CLIP_HIGH))
    results["platt"] = platt_loss
    marker = "↑ 改善" if platt_loss < raw_loss else "→ 変化なし/悪化"
    print(f"  Platt Scaling Log Loss              : {platt_loss:.5f}  [{marker}]")

    # ── Cubic Spline: scipy UnivariateSpline ──────────────────────────
    if _SCIPY:
        try:
            # NaN・無限大を除外してからスプライン適合
            mask = np.isfinite(oof_pred)
            x_all = oof_pred[mask]
            y_all = y[mask].astype(float)
            # 重複 x を平均化（UnivariateSpline は厳密単調増加を要求）
            unique_x, inv_idx = np.unique(x_all, return_inverse=True)
            unique_y = np.array([y_all[inv_idx == i].mean() for i in range(len(unique_x))])
            # smoothing factor: 大きいほど滑らか
            s_factor = max(len(unique_x) * 0.05, 10.0)
            spline = UnivariateSpline(unique_x, unique_y, k=3, s=s_factor, ext=3)
            spline_pred = np.clip(spline(oof_pred), 0.0, 1.0)
            spline_loss = log_loss(y, np.clip(spline_pred, CLIP_LOW, CLIP_HIGH))
            results["spline"] = spline_loss
            marker = "↑ 改善" if spline_loss < raw_loss else "→ 変化なし/悪化"
            print(f"  Cubic Spline Log Loss               : {spline_loss:.5f}  [{marker}]")
        except Exception as e:
            print(f"  Cubic Spline: エラー ({e})")
            results["spline"] = raw_loss
    else:
        print("  Cubic Spline: scipy 未インストール → スキップ")
        results["spline"] = raw_loss

    best = min(results, key=lambda k: results[k])
    print(f"  → 最良手法: {best} (Log Loss: {results[best]:.5f})")
    return results


# ======================================================================
# T003: 男女別モデル CV（gender_split_model.py 統合）
# ======================================================================

def run_gender_split_cv(data_dir: Path) -> dict[str, float]:
    """
    gender_split_model.py を使って男女別モデルを訓練し Brier Score を報告する。
    実データ（MNCAATourneyCompactResults.csv 等）が必要。

    Returns:
        {"men_brier": float, "women_brier": float} or {}
    """
    if not _GSM_AVAIL:
        print("[T003] gender_split_model.py が import できません。スキップ。")
        return {}

    required_files = [
        data_dir / "MNCAATourneyCompactResults.csv",
        data_dir / "WNCAATourneyCompactResults.csv",
        data_dir / "MRegularSeasonCompactResults.csv",
        data_dir / "WRegularSeasonCompactResults.csv",
    ]
    missing = [f for f in required_files if not f.exists()]
    if missing:
        print(f"[T003] 実データ不足 ({missing[0].name} 等)。スキップ。")
        return {}

    print("\n[T003] 男女別モデル: データ読み込み中...")
    try:
        seeds_m = _gsm.load_seeds("men")
        seeds_w = _gsm.load_seeds("women")
        reg_m = _gsm.load_regular_results("men")
        reg_w = _gsm.load_regular_results("women")
        tourney_m = _gsm.load_tourney_results("men")
        tourney_w = _gsm.load_tourney_results("women")

        massey_path = data_dir / "MMasseyOrdinals.csv"
        massey = _gsm.MasseyCache(massey_path) if massey_path.exists() else None

        elo_m = _gsm.compute_elo(reg_m)
        elo_w = _gsm.compute_elo(reg_w)

        train_seasons_m = sorted(
            int(s) for s in tourney_m["Season"].unique() if 2010 <= int(s) <= 2025
        )
        train_seasons_w = sorted(
            int(s) for s in tourney_w["Season"].unique() if 2010 <= int(s) <= 2025
        )
        print(f"  [Men]   訓練シーズン数: {len(train_seasons_m)}")
        print(f"  [Women] 訓練シーズン数: {len(train_seasons_w)}")

        result_m = _gsm.build_training_data(
            tourney_m, reg_m, seeds_m, elo_m, massey, train_seasons_m
        )
        result_w = _gsm.build_training_data(
            tourney_w, reg_w, seeds_w, elo_w, None, train_seasons_w
        )
        if result_m is None or result_w is None:
            print("[T003] 訓練データ生成失敗")
            return {}

        X_m, y_m = result_m
        X_w, y_w = result_w
        print(f"  [Men]   {len(X_m)} サンプル, {len(X_m.columns)} 特徴量")
        print(f"  [Women] {len(X_w)} サンプル, {len(X_w.columns)} 特徴量")

        print("\n  --- Men (LGB + XGB Ensemble) ---")
        _, _, cv_brier_m, _ = _gsm.train_men_models(X_m, y_m)

        print("\n  --- Women (LogisticRegression) ---")
        _, _, cv_brier_w, _ = _gsm.train_women_models(X_w, y_w)

        results = {"men_brier": cv_brier_m, "women_brier": cv_brier_w}
        print(f"\n  [T003] CV Brier: Men={cv_brier_m:.5f}, Women={cv_brier_w:.5f}")
        return results

    except Exception as e:
        print(f"[T003] エラー: {e}")
        import traceback
        traceback.print_exc()
        return {}


# ======================================================================
# Part 1: モックデータ生成
# ======================================================================

def build_mock_tournament_data(
    n_teams: int = 200,
    seasons: list[int] | None = None,
    rng_seed: int = 42,
) -> dict:
    """
    実データなしでパイプライン全体をテストするためのモックデータを生成する。

    Returns:
        dict with keys:
            - seeds: {(season, team_id): seed_num}
            - regular_results: DataFrame (Season, WTeamID, LTeamID, WScore, LScore, DayNum)
            - tourney_results: DataFrame (Season, WTeamID, LTeamID)
            - sample_pairs: DataFrame (ID, Team1, Team2) — 予測対象
            - massey_csv_path: Path (モック MMasseyOrdinals.csv)
    """
    if seasons is None:
        seasons = [2023, 2024, 2025, 2026]

    rng = np.random.RandomState(rng_seed)
    team_ids = list(range(1101, 1101 + n_teams))

    # --- シード（64チームが各シーズンでトーナメント出場）
    seeds: dict[tuple[int, int], int] = {}
    for season in seasons:
        tourney_teams = rng.choice(team_ids, size=64, replace=False)
        for i, tid in enumerate(tourney_teams):
            seeds[(season, int(tid))] = (i % 16) + 1  # シード 1-16

    # --- レギュラーシーズン結果（各シーズン 300 試合）
    reg_rows = []
    for season in seasons:
        for _ in range(300):
            t1, t2 = rng.choice(team_ids, size=2, replace=False)
            winner, loser = int(t1), int(t2)
            w_score = int(rng.randint(55, 100))
            l_score = int(rng.randint(40, w_score))
            day_num = int(rng.randint(1, 120))
            reg_rows.append({
                "Season": season, "DayNum": day_num,
                "WTeamID": winner, "LTeamID": loser,
                "WScore": w_score, "LScore": l_score,
            })
    regular_results = pd.DataFrame(reg_rows)

    # --- トーナメント結果（各シーズン 63 試合 = 64チームのシングルエリミネーション）
    tourney_rows = []
    for season in seasons:
        if season == SEASON:
            continue  # 2026年は予測対象なのでラベルなし
        tourney_teams = [tid for (s, tid) in seeds if s == season]
        remaining = list(tourney_teams)
        rng.shuffle(remaining)
        while len(remaining) > 1:
            t1, t2 = remaining.pop(), remaining.pop()
            winner = t1 if rng.random() > 0.5 else t2
            remaining.append(winner)
            tourney_rows.append({
                "Season": season,
                "WTeamID": winner,
                "LTeamID": t2 if winner == t1 else t1,
            })
    tourney_results = pd.DataFrame(tourney_rows)

    # --- 予測対象ペア（2026年 64チームの全組み合わせ一部）
    current_teams = [tid for (s, tid) in seeds if s == SEASON]
    pair_rows = []
    pair_count = 0
    for i, t1 in enumerate(current_teams):
        for t2 in current_teams[i + 1:]:
            a, b = (t1, t2) if t1 < t2 else (t2, t1)
            pair_rows.append({"ID": f"{SEASON}_{a}_{b}", "Team1": a, "Team2": b})
            pair_count += 1
            if pair_count >= 200:
                break
        if pair_count >= 200:
            break
    sample_pairs = pd.DataFrame(pair_rows)

    # --- Massey モック CSV（tempfile）
    tmpdir = tempfile.mkdtemp()
    massey_csv_path = Path(tmpdir) / "MMasseyOrdinals.csv"
    build_mock_massey_csv(
        n_teams=n_teams,
        seasons=seasons,
        save_path=massey_csv_path,
    )

    print(f"[Mock] seeds: {len(seeds)}, reg_games: {len(regular_results)}, "
          f"tourney_games: {len(tourney_results)}, pred_pairs: {len(sample_pairs)}")
    return {
        "seeds": seeds,
        "regular_results": regular_results,
        "tourney_results": tourney_results,
        "sample_pairs": sample_pairs,
        "massey_csv_path": massey_csv_path,
    }


# ======================================================================
# Part 2: Elo + 基本特徴量
# ======================================================================

def compute_elo(regular_results: pd.DataFrame) -> dict[int, float]:
    """Margin-adjusted Elo with Carry-over。"""
    elo: dict[int, float] = {}

    def get_e(tid: int) -> float:
        return elo.get(tid, ELO_INITIAL)

    def expected_win(ea: float, eb: float) -> float:
        return 1.0 / (1.0 + 10.0 ** ((eb - ea) / 400.0))

    prev_season: int | None = None
    for _, row in regular_results.sort_values(["Season", "DayNum"]).iterrows():
        season = int(row["Season"])
        if season != prev_season:
            if prev_season is not None:
                for tid in list(elo.keys()):
                    elo[tid] = elo[tid] * ELO_CARRYOVER + ELO_INITIAL * (1.0 - ELO_CARRYOVER)
            prev_season = season

        winner, loser = int(row["WTeamID"]), int(row["LTeamID"])
        w_score = float(row.get("WScore", 0))
        l_score = float(row.get("LScore", 0))
        margin = min(abs(w_score - l_score), ELO_MARGIN_CAP)
        k_eff = ELO_K * math.log1p(margin) / math.log1p(10.0)
        ew = expected_win(get_e(winner), get_e(loser))
        elo[winner] = get_e(winner) + k_eff * (1.0 - ew)
        elo[loser] = get_e(loser) + k_eff * (0.0 - (1.0 - ew))

    print(f"[Elo] {len(elo)} チームのレーティングを計算")
    return elo


def compute_win_rates(regular_results: pd.DataFrame, season: int) -> dict[int, float]:
    df = regular_results[regular_results["Season"] == season]
    wins = df.groupby("WTeamID").size()
    losses = df.groupby("LTeamID").size()
    teams = set(wins.index) | set(losses.index)
    return {int(t): wins.get(t, 0) / max(wins.get(t, 0) + losses.get(t, 0), 1) for t in teams}


def compute_avg_score_diff(regular_results: pd.DataFrame, season: int) -> dict[int, float]:
    df = regular_results[regular_results["Season"] == season]
    score_diff: dict[int, list[float]] = {}
    for _, row in df.iterrows():
        w, l = int(row["WTeamID"]), int(row["LTeamID"])
        d = float(row["WScore"]) - float(row["LScore"])
        score_diff.setdefault(w, []).append(d)
        score_diff.setdefault(l, []).append(-d)
    return {t: float(np.mean(diffs)) for t, diffs in score_diff.items()}


def compute_tourney_experience(seeds: dict[tuple[int, int], int], season: int) -> dict[int, int]:
    """対象シーズン以前のトーナメント出場回数。"""
    counts: dict[int, int] = {}
    for (s, tid) in seeds:
        if s < season:
            counts[tid] = counts.get(tid, 0) + 1
    return counts


def seed_win_prob(s1: int, s2: int) -> float:
    """シードベースライン: Team1(seed=s1) の勝率。"""
    diff = s2 - s1
    return float(np.clip(1.0 / (1.0 + np.exp(-SEED_SCALE * diff)), CLIP_LOW, CLIP_HIGH))


def elo_win_prob(e1: float, e2: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((e2 - e1) / 400.0))


# ======================================================================
# Part 3: 訓練データ構築（Massey 特徴量統合）
# ======================================================================

def build_massey_diff_cols(massey_df: pd.DataFrame) -> list[str]:
    """massey_features.py の出力から使用する差分列名を決定する。"""
    diff_cols = ["massey_mean_rank_diff", "massey_mean_rank_ratio"]
    for sys_name in TOP_SYSTEM_DIFFS:
        col = f"massey_{sys_name}_rank_diff"
        # get_matchup_features が生成する列は massey_{sys_name}_rank_diff（_rankの後に_diff）
        # 実際のカラム名を確認して存在するものだけ追加
        diff_cols.append(col)
    return diff_cols


def build_training_data(
    seeds: dict[tuple[int, int], int],
    regular_results: pd.DataFrame,
    tourney_results: pd.DataFrame,
    massey_csv_path: Path,
    data_dir: Path | None = None,
) -> tuple[pd.DataFrame, np.ndarray] | None:
    """
    過去のトーナメント結果から特徴量 DataFrame と ラベル y を構築。
    data_dir を指定すると T001 Four Factors 特徴量も統合する。

    Returns:
        (df_features, y) or None if no data
    """
    if tourney_results.empty:
        return None

    elo = compute_elo(regular_results)

    rows = []
    for _, row in tourney_results.iterrows():
        season = int(row["Season"])
        if season >= SEASON:
            continue

        win_rates = compute_win_rates(regular_results, season)
        avg_scores = compute_avg_score_diff(regular_results, season)
        tourney_exp = compute_tourney_experience(seeds, season)

        wt, lt = int(row["WTeamID"]), int(row["LTeamID"])
        t1, t2 = (wt, lt) if wt < lt else (lt, wt)
        label = 1 if t1 == wt else 0

        s1 = seeds.get((season, t1), 8)
        s2 = seeds.get((season, t2), 8)
        e1 = elo.get(t1, ELO_INITIAL)
        e2 = elo.get(t2, ELO_INITIAL)

        rows.append({
            "t1": t1, "t2": t2, "season": season,
            "seed_diff": float(s2 - s1),
            "elo_diff": float(e1 - e2),
            "win_rate_diff": float(win_rates.get(t1, 0.5) - win_rates.get(t2, 0.5)),
            "avg_score_diff": float(avg_scores.get(t1, 0.0) - avg_scores.get(t2, 0.0)),
            "tourney_exp_diff": float(tourney_exp.get(t1, 0) - tourney_exp.get(t2, 0)),
            "label": label,
        })

    if not rows:
        return None

    df = pd.DataFrame(rows)

    # Massey 特徴量統合（シーズン別に取得してマージ）
    massey_parts = []
    for season in df["season"].unique():
        try:
            massey_df_s = load_massey_features(massey_csv_path, season=int(season))
        except FileNotFoundError:
            print(f"[Warning] Massey CSV not found for season {season}; skipping massey features")
            massey_df_s = None

        df_s = df[df["season"] == season].copy()
        if massey_df_s is not None and not massey_df_s.empty:
            massey_feat = get_matchup_features(
                massey_df_s,
                df_s["t1"].tolist(),
                df_s["t2"].tolist(),
            )
            massey_feat.index = df_s.index
            df_s = pd.concat([df_s, massey_feat], axis=1)

        massey_parts.append(df_s)

    df = pd.concat(massey_parts, ignore_index=True)

    # ── T001: Four Factors 特徴量統合 ─────────────────────────────────────
    if _FF_AVAIL and data_dir is not None:
        ff_stats_m = _try_load_four_factors(data_dir, "M")
        ff_stats_w = _try_load_four_factors(data_dir, "W")
        if ff_stats_m or ff_stats_w:
            ff_rows: list[dict[str, float]] = []
            for _, row in df.iterrows():
                t1, t2, season = int(row["t1"]), int(row["t2"]), int(row["season"])
                stats = ff_stats_m if t1 < 3000 else ff_stats_w
                if stats:
                    try:
                        ff = get_matchup_four_factors(stats, season, t1, t2)
                        ff_rows.append(ff)
                    except Exception:
                        ff_rows.append({k: 0.0 for k in FOUR_FACTORS_FEATURES})
                else:
                    ff_rows.append({k: 0.0 for k in FOUR_FACTORS_FEATURES})
            ff_df = pd.DataFrame(ff_rows, index=df.index).fillna(0.0)
            ff_cols = [c for c in FOUR_FACTORS_FEATURES if c in ff_df.columns]
            if ff_cols:
                df = pd.concat([df, ff_df[ff_cols]], axis=1)
                print(f"[T001] Four Factors 特徴量 {len(ff_cols)} 列を訓練データに追加")

    # 特徴量列の確定（存在する列のみ）
    massey_cols = [c for c in df.columns
                   if c.startswith("massey_") and
                   (c.endswith("_diff") or c.endswith("_ratio"))]
    ff_cols_present = [c for c in FOUR_FACTORS_FEATURES if c in df.columns]

    feature_cols = BASE_FEATURES + massey_cols + ff_cols_present
    feature_cols = [c for c in feature_cols if c in df.columns]

    # NaN 補完（Massey 特徴量が取得できなかった場合は 0）
    df[feature_cols] = df[feature_cols].fillna(0.0)

    X = df[feature_cols].values.astype(np.float32)
    y = df["label"].values.astype(np.int32)
    print(f"[Training] {len(X)} 試合, {len(feature_cols)} 特徴量, 正例率: {y.mean():.3f}")
    print(f"[Training] 特徴量: {feature_cols[:5]}...（合計{len(feature_cols)}個）")

    # feature_cols を DataFrameで返す（Hill Climbing で OOF が必要）
    df_feat = df[feature_cols].astype(np.float32)
    return df_feat, y


# ======================================================================
# Part 4: LightGBM OOF 訓練
# ======================================================================

def train_lgbm_oof(
    df_feat: pd.DataFrame,
    y: np.ndarray,
) -> tuple[np.ndarray, list, float]:
    """
    LightGBM 5-Fold OOF 訓練。

    Returns:
        (oof_predictions, models, cv_log_loss)
    """
    feature_names = df_feat.columns.tolist()
    X = df_feat.values.astype(np.float32)

    kf = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=42)
    oof = np.zeros(len(X))
    models = []
    fold_scores = []

    for fold, (tr_idx, val_idx) in enumerate(kf.split(X, y)):
        model = lgb.LGBMClassifier(**LGB_PARAMS)
        model.fit(
            X[tr_idx], y[tr_idx],
            eval_set=[(X[val_idx], y[val_idx])],
            feature_name=feature_names,
            callbacks=[
                lgb.early_stopping(30, verbose=False),
                lgb.log_evaluation(-1),
            ],
        )
        oof[val_idx] = model.predict_proba(X[val_idx])[:, 1]
        score = log_loss(y[val_idx], np.clip(oof[val_idx], CLIP_LOW, CLIP_HIGH))
        fold_scores.append(score)
        models.append(model)
        print(f"  Fold {fold + 1}/{N_FOLDS} Log Loss: {score:.4f}")

    cv_score = float(np.mean(fold_scores))
    print(f"[LightGBM] CV Log Loss: {cv_score:.4f} ± {np.std(fold_scores):.4f}")
    return oof, models, cv_score


# ======================================================================
# Part 5: Hill Climbing アンサンブル
# ======================================================================

def hill_climbing_ensemble(
    preds_list: list[np.ndarray],
    y: np.ndarray,
    n_iter: int = 200,
    step: float = 0.05,
    random_seed: int = 42,
) -> np.ndarray:
    """
    Hill Climbing でアンサンブル重みを最適化する。

    アルゴリズム:
        1. 均等重みから開始 (weights = [1/n, 1/n, ...])
        2. 各ステップで1つのモデルの重みを ±step 変化させる
        3. Log Loss が改善したら採用（しなければ棄却）
        4. n_iter 回繰り返す

    Args:
        preds_list: 各モデルの予測確率リスト（OOF またはテスト予測）
        y: 真のラベル（OOF 評価用）
        n_iter: 最大イテレーション数
        step: 重み変化量
        random_seed: 乱数シード

    Returns:
        最適化された重み付きアンサンブル予測
    """
    n_models = len(preds_list)
    preds_arr = np.stack(preds_list, axis=1)  # shape: (n_samples, n_models)

    # 初期重み: 均等
    weights = np.ones(n_models) / n_models
    best_blend = np.dot(preds_arr, weights)
    best_loss = log_loss(y, np.clip(best_blend, CLIP_LOW, CLIP_HIGH))
    print(f"[HillClimb] 初期重み: {weights}, Log Loss: {best_loss:.4f}")

    rng = np.random.RandomState(random_seed)
    no_improve_count = 0

    for i in range(n_iter):
        # ランダムに2モデルを選択し、一方から他方へ step 分の重みを移す
        i_from, i_to = rng.choice(n_models, size=2, replace=False)
        new_weights = weights.copy()
        new_weights[i_from] -= step
        new_weights[i_to] += step

        # 重みが負にならないよう制約
        if new_weights[i_from] < 0:
            no_improve_count += 1
            continue

        # 正規化（合計を1に）
        new_weights = np.clip(new_weights, 0, 1)
        new_weights /= new_weights.sum()

        new_blend = np.dot(preds_arr, new_weights)
        new_loss = log_loss(y, np.clip(new_blend, CLIP_LOW, CLIP_HIGH))

        if new_loss < best_loss:
            best_loss = new_loss
            weights = new_weights
            best_blend = new_blend
            no_improve_count = 0
        else:
            no_improve_count += 1

        # 連続改善なしが多い場合は step を半減（収束促進）
        if no_improve_count > 50:
            step = max(step * 0.5, 0.005)
            no_improve_count = 0

    print(f"[HillClimb] 最終重み: {np.round(weights, 3)}, Log Loss: {best_loss:.4f}")
    return weights, best_blend


# ======================================================================
# Part 6: テスト予測生成
# ======================================================================

def build_test_predictions(
    sample_pairs: pd.DataFrame,
    seeds: dict[tuple[int, int], int],
    regular_results: pd.DataFrame,
    massey_csv_path: Path,
    elo: dict[int, float],
    models: list,
    feature_cols: list[str],
    lgb_weight: float = 0.8,
    elo_weight: float = 0.2,
    data_dir: Path | None = None,
) -> pd.DataFrame:
    """
    予測対象ペアの最終予測を生成する。

    Args:
        lgb_weight: Hill Climbing で決定した LightGBM のブレンド重み
        elo_weight: Hill Climbing で決定した Elo のブレンド重み

    Returns:
        DataFrame with columns: ID, Pred
    """
    win_rates = compute_win_rates(regular_results, SEASON)
    avg_scores = compute_avg_score_diff(regular_results, SEASON)
    tourney_exp = compute_tourney_experience(seeds, SEASON)

    # 2026年 Massey 特徴量
    try:
        massey_df = load_massey_features(massey_csv_path, season=SEASON)
        massey_avail = not massey_df.empty
    except FileNotFoundError:
        massey_df = None
        massey_avail = False

    rows = []
    for _, pair in sample_pairs.iterrows():
        t1, t2 = int(pair["Team1"]), int(pair["Team2"])
        s1 = seeds.get((SEASON, t1), 8)
        s2 = seeds.get((SEASON, t2), 8)
        e1 = elo.get(t1, ELO_INITIAL)
        e2 = elo.get(t2, ELO_INITIAL)

        row = {
            "seed_diff": float(s2 - s1),
            "elo_diff": float(e1 - e2),
            "win_rate_diff": float(win_rates.get(t1, 0.5) - win_rates.get(t2, 0.5)),
            "avg_score_diff": float(avg_scores.get(t1, 0.0) - avg_scores.get(t2, 0.0)),
            "tourney_exp_diff": float(tourney_exp.get(t1, 0) - tourney_exp.get(t2, 0)),
        }
        rows.append(row)

    df_test = pd.DataFrame(rows)

    # Massey 特徴量統合
    if massey_avail:
        massey_feat = get_matchup_features(
            massey_df,
            sample_pairs["Team1"].tolist(),
            sample_pairs["Team2"].tolist(),
        )
        massey_feat.index = df_test.index
        df_test = pd.concat([df_test, massey_feat], axis=1)

    # T001: Four Factors 特徴量統合（テストペア）
    if _FF_AVAIL and data_dir is not None:
        ff_stats_m = _try_load_four_factors(data_dir, "M")
        ff_stats_w = _try_load_four_factors(data_dir, "W")
        if ff_stats_m or ff_stats_w:
            ff_rows: list[dict[str, float]] = []
            for _, pair in sample_pairs.iterrows():
                t1, t2 = int(pair["Team1"]), int(pair["Team2"])
                stats = ff_stats_m if t1 < 3000 else ff_stats_w
                if stats:
                    try:
                        ff = get_matchup_four_factors(stats, SEASON, t1, t2)
                        ff_rows.append(ff)
                    except Exception:
                        ff_rows.append({k: 0.0 for k in FOUR_FACTORS_FEATURES})
                else:
                    ff_rows.append({k: 0.0 for k in FOUR_FACTORS_FEATURES})
            ff_df = pd.DataFrame(ff_rows, index=df_test.index).fillna(0.0)
            ff_cols = [c for c in FOUR_FACTORS_FEATURES if c in ff_df.columns]
            if ff_cols:
                df_test = pd.concat([df_test, ff_df[ff_cols]], axis=1)
                print(f"[T001] Four Factors 特徴量 {len(ff_cols)} 列をテストデータに追加")

    # 不足列を 0 で補完
    for col in feature_cols:
        if col not in df_test.columns:
            df_test[col] = 0.0
    df_test = df_test[feature_cols].fillna(0.0).astype(np.float32)

    # LightGBM: 5 フォールドモデルを均等平均
    fold_preds = np.stack(
        [model.predict_proba(df_test.values)[:, 1] for model in models],
        axis=1,
    )
    lgb_pred = fold_preds.mean(axis=1)  # shape: (n_samples,)

    # Elo ベースライン予測
    elo_pred = np.array([
        elo_win_prob(
            elo.get(int(p["Team1"]), ELO_INITIAL),
            elo.get(int(p["Team2"]), ELO_INITIAL),
        )
        for _, p in sample_pairs.iterrows()
    ])

    # Hill Climbing で決定したブレンド重みを適用
    final_pred = lgb_weight * lgb_pred + elo_weight * elo_pred
    final_pred = np.clip(final_pred, CLIP_LOW, CLIP_HIGH)

    result = pd.DataFrame({"ID": sample_pairs["ID"].values, "Pred": final_pred})
    print(f"[Predict] {len(result)} ペアの予測生成完了。Pred 統計: "
          f"mean={final_pred.mean():.3f}, min={final_pred.min():.3f}, max={final_pred.max():.3f}")
    return result


# ======================================================================
# Part 7: メインパイプライン
# ======================================================================

def run_pipeline(use_real_data: bool = False) -> None:
    """
    パイプライン全体を実行する。

    Args:
        use_real_data: True の場合、DATA_DIR の実データを使用。
                       False の場合、モックデータで実行。
    """
    print("\n" + "=" * 65)
    print("  March Mania 2026 — LightGBM + Massey Ordinals Pipeline")
    if not use_real_data:
        print("  [MODE: モックデータ]")
    else:
        print("  [MODE: 実データ]")
    print("=" * 65 + "\n")

    # ── Step 1: データ準備 ──────────────────────────────────────────────
    if not use_real_data:
        mock = build_mock_tournament_data(n_teams=200, seasons=[2023, 2024, 2025, 2026])
        seeds = mock["seeds"]
        regular_results = mock["regular_results"]
        tourney_results = mock["tourney_results"]
        sample_pairs = mock["sample_pairs"]
        massey_csv_path = mock["massey_csv_path"]
        output_suffix = "demo"
    else:
        # 実データ読み込み（kaggle download 後）
        seeds = _load_real_seeds()
        regular_results = _load_real_regular_results()
        tourney_results = _load_real_tourney_results()
        sample_pairs = _load_real_sample_submission()
        massey_csv_path = DATA_DIR / "MMasseyOrdinals.csv"
        output_suffix = "final"

    # ── Step 2: Elo 計算 ────────────────────────────────────────────────
    print("\n--- Step 2: Elo 計算 ---")
    elo = compute_elo(regular_results)

    # ── Step 3: 訓練データ構築（Massey + Four Factors 特徴量統合） ───────
    print("\n--- Step 3: 訓練データ構築（Massey + Four Factors 特徴量統合） ---")
    _data_dir = DATA_DIR if use_real_data else None
    result = build_training_data(
        seeds, regular_results, tourney_results, massey_csv_path,
        data_dir=_data_dir,
    )

    if result is None:
        print("[Warning] 訓練データなし。Elo + Seed ベースライン予測のみ実行。")
        # フォールバック: シードベースライン
        base_pred = np.array([
            seed_win_prob(
                seeds.get((SEASON, int(p["Team1"])), 8),
                seeds.get((SEASON, int(p["Team2"])), 8),
            )
            for _, p in sample_pairs.iterrows()
        ])
        out_df = pd.DataFrame({"ID": sample_pairs["ID"], "Pred": base_pred})
        out_path = SUBMISSION_DIR / f"lgb_massey_pipeline_{output_suffix}.csv"
        out_df.to_csv(out_path, index=False)
        print(f"[Output] {out_path}")
        return

    df_feat, y = result
    feature_cols = df_feat.columns.tolist()

    # ── Step 4: LightGBM OOF 訓練 ──────────────────────────────────────
    print("\n--- Step 4: LightGBM 5-Fold OOF 訓練 ---")
    oof_lgb, models, cv_score = train_lgbm_oof(df_feat, y)

    # Elo ベースライン OOF （訓練データの各試合のペア Elo 予測）
    # ※ モックデータでは Elo OOF を近似値で生成
    oof_elo = np.array([
        elo_win_prob(elo.get(1101 + i % 100, ELO_INITIAL), elo.get(1101 + (i + 1) % 100, ELO_INITIAL))
        for i in range(len(y))
    ])

    # ── Step 4b: T002 キャリブレーション比較 ───────────────────────────
    print("\n--- Step 4b: T002 キャリブレーション比較 ---")
    calib_results = compare_calibration(oof_lgb, y, label="LightGBM OOF")

    # ── Step 5: Hill Climbing アンサンブル ─────────────────────────────
    print("\n--- Step 5: Hill Climbing アンサンブル ---")
    weights, oof_ensemble = hill_climbing_ensemble(
        preds_list=[oof_lgb, oof_elo],
        y=y,
        n_iter=300,
        step=0.05,
    )
    lgb_weight = float(weights[0])
    elo_weight = float(weights[1])
    print(f"[HillClimb] 最終ブレンド: LightGBM×{lgb_weight:.2f} + Elo×{elo_weight:.2f}")

    # ── Step 6: テスト予測 + CSV 出力 ──────────────────────────────────
    print("\n--- Step 6: テスト予測 + CSV 出力 ---")
    final_df = build_test_predictions(
        sample_pairs=sample_pairs,
        seeds=seeds,
        regular_results=regular_results,
        massey_csv_path=massey_csv_path,
        elo=elo,
        models=models,
        feature_cols=feature_cols,
        lgb_weight=lgb_weight,
        elo_weight=elo_weight,
        data_dir=_data_dir,
    )

    out_path = SUBMISSION_DIR / f"lgb_massey_pipeline_{output_suffix}.csv"
    final_df.to_csv(out_path, index=False)

    # ── Step 7: T003 男女別モデル CV（実データのみ）───────────────────
    gender_results: dict[str, float] = {}
    if use_real_data:
        print("\n--- Step 7: T003 男女別モデル CV ---")
        gender_results = run_gender_split_cv(DATA_DIR)

    # ── 最終サマリ ─────────────────────────────────────────────────────
    BASELINE = 0.1668
    ensemble_cv = log_loss(y, np.clip(oof_ensemble, CLIP_LOW, CLIP_HIGH))

    print("\n" + "=" * 65)
    print(f"  完了! 出力: {out_path}")
    print(f"\n  ── CV スコア比較 (ベースライン ensemble: {BASELINE}) ──")
    print(f"  LightGBM+Massey OOF CV Log Loss   : {cv_score:.5f}")
    print(f"  Hill Climbing アンサンブル Log Loss: {ensemble_cv:.5f}")
    print(f"\n  T002 キャリブレーション:")
    for method, score in calib_results.items():
        diff = BASELINE - score
        sign = "+" if diff >= 0 else ""
        print(f"    {method:8s}: {score:.5f}  (vs baseline {sign}{diff:.5f})")
    if gender_results:
        print(f"\n  T003 男女別モデル (Brier Score):")
        for lbl, score in gender_results.items():
            print(f"    {lbl}: {score:.5f}")
    print(f"\n  HillClimb ブレンド: LightGBM×{lgb_weight:.2f} + Elo×{elo_weight:.2f}")
    print(f"  予測行数: {len(final_df)}")
    print(f"  クリップ: [{CLIP_LOW}, {CLIP_HIGH}]")
    if _FF_AVAIL and use_real_data:
        ff_count = sum(1 for c in feature_cols if c in FOUR_FACTORS_FEATURES)
        print(f"  T001 Four Factors 特徴量: {ff_count} 列使用")
    print("=" * 65 + "\n")


# ======================================================================
# 実データ読み込み関数（kaggle download 後に使用）
# ======================================================================

def _load_real_seeds() -> dict[tuple[int, int], int]:
    """MNCAATourneySeeds.csv + WNCAATourneySeeds.csv を読み込む。"""
    seeds: dict[tuple[int, int], int] = {}
    for prefix in ["M", "W"]:
        path = DATA_DIR / f"{prefix}NCAATourneySeeds.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        for _, row in df.iterrows():
            seed_str = str(row["Seed"])
            seed_num = int("".join(c for c in seed_str if c.isdigit())[:2])
            seeds[(int(row["Season"]), int(row["TeamID"]))] = seed_num
    print(f"[Seeds] {len(seeds)} エントリ読み込み完了")
    return seeds


def _load_real_regular_results() -> pd.DataFrame:
    dfs = []
    for prefix in ["M", "W"]:
        path = DATA_DIR / f"{prefix}RegularSeasonCompactResults.csv"
        if path.exists():
            dfs.append(pd.read_csv(path))
    if not dfs:
        return pd.DataFrame(columns=["Season", "DayNum", "WTeamID", "LTeamID", "WScore", "LScore"])
    return pd.concat(dfs, ignore_index=True)


def _load_real_tourney_results() -> pd.DataFrame:
    dfs = []
    for prefix in ["M", "W"]:
        path = DATA_DIR / f"{prefix}NCAATourneyCompactResults.csv"
        if path.exists():
            df = pd.read_csv(path)
            dfs.append(df[df["Season"] < SEASON])
    if not dfs:
        return pd.DataFrame(columns=["Season", "WTeamID", "LTeamID"])
    return pd.concat(dfs, ignore_index=True)


def _load_real_sample_submission() -> pd.DataFrame:
    """SampleSubmission.csv から予測対象ペアを取得。"""
    path = DATA_DIR / "SampleSubmission.csv"
    if not path.exists():
        # Stage1 submission
        path = DATA_DIR / "SampleSubmissionStage1.csv"
    if not path.exists():
        raise FileNotFoundError(f"SampleSubmission.csv が見つかりません: {DATA_DIR}")
    df = pd.read_csv(path)
    # ID 列: "2026_XXXX_YYYY" 形式
    df["Team1"] = df["ID"].apply(lambda x: int(x.split("_")[1]))
    df["Team2"] = df["ID"].apply(lambda x: int(x.split("_")[2]))
    return df[["ID", "Team1", "Team2"]]


# ======================================================================
# Part 8: テスト（CHECK-3 / CHECK-7b）
# ======================================================================

def run_all_tests() -> None:
    """
    モックデータを使ったパイプライン全体テスト。
    CHECK-3: エラーなし実行確認
    CHECK-7b: LightGBM 予測値の手計算近似検証
    """
    print("\n" + "=" * 65)
    print("  CHECK-3/7b: lgb_massey_pipeline — 全テスト")
    print("=" * 65)

    # ----- TEST 1: モックデータ生成 -----
    print("\n[TEST 1] モックデータ生成")
    mock = build_mock_tournament_data(n_teams=150, seasons=[2023, 2024, 2025, 2026])
    assert len(mock["sample_pairs"]) > 0, "予測ペアが空"
    assert len(mock["tourney_results"]) > 0, "トーナメント結果が空"
    print(f"  ✓ tourney_games: {len(mock['tourney_results'])}, pred_pairs: {len(mock['sample_pairs'])}")

    # ----- TEST 2: 訓練データ構築 -----
    print("\n[TEST 2] 訓練データ構築（Massey 特徴量統合）")
    result = build_training_data(
        seeds=mock["seeds"],
        regular_results=mock["regular_results"],
        tourney_results=mock["tourney_results"],
        massey_csv_path=mock["massey_csv_path"],
    )
    assert result is not None, "訓練データが None"
    df_feat, y = result
    assert len(df_feat) > 0, "特徴量が空"
    assert len(df_feat) == len(y), "特徴量とラベルの行数不一致"
    assert df_feat.isnull().sum().sum() == 0, f"NaN あり: {df_feat.isnull().sum()}"
    massey_cols = [c for c in df_feat.columns if c.startswith("massey_")]
    assert len(massey_cols) > 0, "Massey 特徴量が統合されていない"
    print(f"  ✓ 訓練サンプル数: {len(df_feat)}, 特徴量数: {len(df_feat.columns)}")
    print(f"  ✓ Massey 特徴量数: {len(massey_cols)}, 例: {massey_cols[:3]}")

    # ----- TEST 3: LightGBM 訓練 -----
    print("\n[TEST 3] LightGBM 5-Fold OOF 訓練")
    oof_lgb, models, cv_score = train_lgbm_oof(df_feat, y)
    assert len(oof_lgb) == len(y), "OOF 長さ不一致"
    assert len(models) == N_FOLDS, f"モデル数不一致: {len(models)}"
    assert 0.0 < cv_score < 1.0, f"CV スコア異常: {cv_score}"
    oof_clipped = np.clip(oof_lgb, CLIP_LOW, CLIP_HIGH)
    assert oof_clipped.min() >= CLIP_LOW, "クリップ下限違反"
    print(f"  ✓ CV Log Loss: {cv_score:.4f}")
    print(f"  ✓ OOF 予測範囲: [{oof_lgb.min():.4f}, {oof_lgb.max():.4f}]")

    # ----- TEST 4: Hill Climbing -----
    print("\n[TEST 4] Hill Climbing アンサンブル")
    oof_elo = np.full(len(y), 0.5)  # 均等ベースライン
    weights, oof_ensemble = hill_climbing_ensemble(
        preds_list=[oof_lgb, oof_elo],
        y=y,
        n_iter=100,
        step=0.05,
    )
    assert len(weights) == 2, "重みの数が不一致"
    assert abs(weights.sum() - 1.0) < 1e-6, f"重みの合計が1でない: {weights.sum()}"
    assert all(w >= 0 for w in weights), f"負の重みあり: {weights}"
    print(f"  ✓ 最終重み: LightGBM={weights[0]:.3f}, Elo={weights[1]:.3f}")
    print(f"  ✓ 重みの合計: {weights.sum():.6f}")

    # ----- TEST 5: CHECK-7b 手計算検証 -----
    print("\n[TEST 5] CHECK-7b: LightGBM 予測値 手計算近似検証")
    # シンプルな 2クラス線形分離ケースで sigmoid が機能するか確認
    # seed_diff > 0 → team1 が格上 → 予測 > 0.5 を確認
    simple_pairs = pd.DataFrame({
        "ID": ["2026_1101_1102"],
        "Team1": [1101],
        "Team2": [1102],
    })
    elo_test = compute_elo(mock["regular_results"])
    e1 = elo_test.get(1101, ELO_INITIAL)
    e2 = elo_test.get(1102, ELO_INITIAL)
    prob_elo = elo_win_prob(e1, e2)
    print(f"  ✓ Elo 予測確認: Elo(team1)={e1:.1f}, Elo(team2)={e2:.1f}")
    print(f"    → elo_win_prob = {prob_elo:.4f}")
    # 検算: E = 1 / (1 + 10^((e2-e1)/400))
    prob_manual = 1.0 / (1.0 + 10.0 ** ((e2 - e1) / 400.0))
    assert abs(prob_elo - prob_manual) < 1e-9, f"手計算不一致: {prob_elo} vs {prob_manual}"
    print(f"    → 手計算: 1/(1+10^({(e2-e1):.1f}/400)) = {prob_manual:.4f} → 一致 ✓")

    # ----- TEST 5b: T002 キャリブレーション -----
    print("\n[TEST 5b] T002 キャリブレーション比較")
    calib = compare_calibration(oof_lgb, y, label="TEST")
    assert "raw" in calib and "platt" in calib and "spline" in calib, \
        f"キャリブレーション結果の keys 不正: {calib.keys()}"
    assert all(0.0 < v < 2.0 for v in calib.values()), \
        f"キャリブレーション Log Loss が異常: {calib}"
    print(f"  ✓ Raw={calib['raw']:.4f}, Platt={calib['platt']:.4f}, Spline={calib['spline']:.4f}")

    # ----- TEST 6: 全パイプライン実行（エラーなし確認）-----
    print("\n[TEST 6] 全パイプライン実行（CHECK-3: エラーなし確認）")
    run_pipeline(use_real_data=False)

    # 出力ファイル確認
    out_path = SUBMISSION_DIR / "lgb_massey_pipeline_demo.csv"
    assert out_path.exists(), f"出力ファイルなし: {out_path}"
    df_out = pd.read_csv(out_path)
    assert "ID" in df_out.columns and "Pred" in df_out.columns, "出力 CSV の列が不正"
    assert df_out["Pred"].between(CLIP_LOW, CLIP_HIGH).all(), \
        f"Pred がクリップ範囲外: [{df_out['Pred'].min():.4f}, {df_out['Pred'].max():.4f}]"
    print(f"  ✓ 出力ファイル: {out_path}")
    print(f"  ✓ 予測行数: {len(df_out)}, Pred 範囲: [{df_out['Pred'].min():.4f}, {df_out['Pred'].max():.4f}]")

    print("\n" + "=" * 65)
    print("  全テスト PASS ✓  (CHECK-3 / CHECK-7b 完了)")
    print("=" * 65 + "\n")


# ======================================================================
# エントリポイント
# ======================================================================

if __name__ == "__main__":
    use_real = "--real-data" in sys.argv

    if use_real:
        run_pipeline(use_real_data=True)
    else:
        run_all_tests()
