"""
scripts/monthly_optimize.py — 月次フィルター最適化スクリプト

feedback_engine/analyzer.py で月次分析を実行し、
feedback_engine/optimizer.py でフィルター最適化案を生成・適用する。

設計書: true_ai_prediction_system_design.md セクション8「月次」準拠

使用例:
    # ドライラン（デフォルト）: 最適化案を確認するだけで適用しない
    python scripts/monthly_optimize.py

    # 競輪のみ、対象月を指定
    python scripts/monthly_optimize.py --sport keirin --month 2026-01

    # 実際に filters.yaml を更新する（殿の承認後に実行）
    python scripts/monthly_optimize.py --apply

    # 両競技、前月
    python scripts/monthly_optimize.py --sport both
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

# プロジェクトルートを sys.path に追加（scripts/ から実行された場合を想定）
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from feedback_engine.analyzer import FeedbackAnalyzer
from feedback_engine.optimizer import FilterOptimizer


# ──────────────────────────────────────────────
# 定数
# ──────────────────────────────────────────────

SETTINGS_PATH = _PROJECT_ROOT / "config" / "settings.yaml"
REPORTS_DIR   = _PROJECT_ROOT / "data" / "reports"
SPORTS        = ["keirin", "kyotei"]


# ──────────────────────────────────────────────
# 設定ロード
# ──────────────────────────────────────────────

def load_settings() -> dict:
    """
    config/settings.yaml を読み込んで返す。

    Returns:
        設定辞書。読み込み失敗時は空辞書を返す。
    """
    if not SETTINGS_PATH.exists():
        print(f"[WARN] settings.yaml が見つかりません: {SETTINGS_PATH}", file=sys.stderr)
        return {}
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_log_path(sport: str, settings: dict) -> str:
    """
    予想ログ（predictions_log.jsonl）のパスを返す。

    settings.yaml に log_path が定義されていればそれを使い、
    なければデフォルトパス（data/logs/{sport}_predictions_log.jsonl）を返す。

    Args:
        sport: "keirin" または "kyotei"
        settings: load_settings() の返り値

    Returns:
        ログファイルの絶対パス文字列
    """
    log_dir = _PROJECT_ROOT / settings.get("pipeline", {}).get("log_dir", "data/logs")
    return str(log_dir / f"{sport}_predictions_log.jsonl")


def get_config_dir(settings: dict) -> str:
    """
    config/ ディレクトリのパスを返す。

    Args:
        settings: load_settings() の返り値

    Returns:
        config/ の絶対パス文字列
    """
    config_subdir = settings.get("pipeline", {}).get("config_dir", "config")
    return str(_PROJECT_ROOT / config_subdir)


# ──────────────────────────────────────────────
# 分析結果フォーマット変換
# ──────────────────────────────────────────────

def _to_pct(roi_decimal) -> float | None:
    """
    ROI を小数表現（0.245）からパーセント表現（24.5）へ変換する。

    analyzer.py は小数（0.245 = 24.5%）で返すが、
    optimizer.py はパーセント値（24.5）を期待するため変換が必要。

    Args:
        roi_decimal: 小数形式の ROI。None の場合は None を返す。

    Returns:
        パーセント形式の ROI または None
    """
    if roi_decimal is None:
        return None
    return round(roi_decimal * 100.0, 2)


def adapt_analysis_for_optimizer(
    analysis: dict,
    sport: str,
    settings: dict,
) -> dict:
    """
    analyzer.py の出力を optimizer.py が期待するフォーマットへ変換する。

    主な変換内容:
      - ROI: 小数（0.245）→ パーセント（24.5）
      - by_keyword  → keyword_analysis（is_negative フラグを settings から付与）
      - by_venue    → by_venue（excluded フラグを settings から付与）
      - by_race_type → by_race_type（excluded フラグを付与）
      - tier_boundary_check: analyzer 形式 → optimizer 形式（"S"/"A"/"B" キー）

    Args:
        analysis:  analyzer.analyze_monthly() の返り値
        sport:     "keirin" または "kyotei"
        settings:  load_settings() の返り値

    Returns:
        optimizer.optimize() に渡せる形式の辞書
    """
    sport_filters: dict = settings.get("filters", {}).get(sport, {})
    excluded_venues: list = sport_filters.get("exclude_velodromes", [])
    negative_keywords: list = sport_filters.get("exclude_keywords", [])

    # --- by_venue: excluded フラグを付与 ---
    adapted_venue: dict[str, dict] = {}
    for venue, stats in analysis.get("by_venue", {}).items():
        adapted_venue[venue] = {
            "roi": _to_pct(stats.get("roi")),
            "n":   stats.get("n", 0),
            "excluded": venue in excluded_venues,
        }

    # --- keyword_analysis: is_negative フラグを付与 ---
    adapted_keywords: dict[str, dict] = {}
    for kw, stats in analysis.get("by_keyword", {}).items():
        adapted_keywords[kw] = {
            "roi":         _to_pct(stats.get("roi")),
            "n":           stats.get("n", 0),
            "is_negative": kw in negative_keywords,
        }

    # --- by_race_type: excluded フラグを付与 ---
    excluded_race_types: list = sport_filters.get("excluded_race_types", [])
    adapted_race_type: dict[str, dict] = {}
    for rt, stats in analysis.get("by_race_type", {}).items():
        adapted_race_type[rt] = {
            "roi":      _to_pct(stats.get("roi")),
            "n":        stats.get("n", 0),
            "excluded": rt in excluded_race_types,
        }

    # --- tier_boundary_check: analyzer 形式 → optimizer 形式 ---
    tbc = analysis.get("tier_boundary_check", {})
    adapted_tier: dict[str, dict] = {
        "S": {"actual_roi": _to_pct(tbc.get("s_roi"))},
        "A": {"actual_roi": _to_pct(tbc.get("a_roi"))},
        "B": {"actual_roi": _to_pct(tbc.get("b_roi"))},
    }

    return {
        "by_venue":           adapted_venue,
        "keyword_analysis":   adapted_keywords,
        "by_race_type":       adapted_race_type,
        "tier_boundary_check": adapted_tier,
        # 参考情報として残す（optimizer は使わないが report 生成に使用）
        "_overall":           analysis.get("overall", {}),
        "_by_tier":           analysis.get("by_tier", {}),
        "_new_reverse":       analysis.get("new_reverse_indicators", []),
        "_new_positive":      analysis.get("new_positive_indicators", []),
        "_anomalies":         analysis.get("anomalies", []),
        "_total_predictions": analysis.get("total_predictions", 0),
        "_period":            analysis.get("period", {}),
    }


# ──────────────────────────────────────────────
# Markdown レポート生成
# ──────────────────────────────────────────────

def build_report(
    sport: str,
    year_month: str,
    adapted: dict,
    optimize_result: dict,
    apply_result: dict,
    dry_run: bool,
) -> str:
    """
    月次最適化結果を Markdown 形式のレポートとして生成する。

    Args:
        sport:           "keirin" または "kyotei"
        year_month:      "YYYY-MM" 形式
        adapted:         adapt_analysis_for_optimizer() の返り値
        optimize_result: optimizer.optimize() の返り値
        apply_result:    optimizer.apply_changes() の返り値
        dry_run:         True の場合はドライラン表記を付与

    Returns:
        Markdown 文字列
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sport_ja = "競輪" if sport == "keirin" else "競艇"
    dry_label = "【DRY RUN】" if dry_run else "【適用済み】"

    lines: list[str] = []
    lines.append(f"# {sport_ja}月次フィルター最適化レポート {dry_label}")
    lines.append(f"")
    lines.append(f"- **対象月**: {year_month}")
    lines.append(f"- **生成日時**: {now_str}")
    lines.append(f"- **モード**: {'ドライラン（変更は未適用）' if dry_run else '本番適用（filters.yaml 更新済み）'}")
    lines.append(f"- **新バージョン**: {optimize_result['new_version']}")
    lines.append(f"")

    # ── 全体成績 ─────────────────────────────────
    overall = adapted.get("_overall", {})
    total_n = adapted.get("_total_predictions", 0)
    lines.append("## 1. 月次全体成績")
    lines.append("")
    if total_n == 0:
        lines.append("> データなし（教師データが蓄積されていません）")
    else:
        hit_rate = overall.get("hit_rate")
        roi      = overall.get("roi")
        profit   = overall.get("profit")
        lines.append(f"| 指標 | 値 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 予想件数 | {total_n}件 |")
        lines.append(f"| 的中率 | {hit_rate:.1%} |" if hit_rate is not None else "| 的中率 | N/A |")
        lines.append(f"| ROI | {roi:.0%} |"          if roi is not None      else "| ROI | N/A |")
        lines.append(f"| 収支 | {profit:+,}円 |"     if profit is not None   else "| 収支 | N/A |")
    lines.append("")

    # ── Tier別成績 ───────────────────────────────
    by_tier = adapted.get("_by_tier", {})
    lines.append("## 2. Tier別成績")
    lines.append("")
    lines.append("| Tier | N | 的中率 | ROI | 目標ROI | 判定 |")
    lines.append("|------|---|--------|-----|---------|------|")
    tier_targets_pct = {"S": "130%", "A": "105%", "B": "95%"}
    tier_targets_val = {"S": 1.30,   "A": 1.05,   "B": 0.95}
    for tier in ["S", "A", "B"]:
        ts = by_tier.get(tier, {})
        n  = ts.get("n", 0)
        hr = ts.get("hit_rate")
        roi = ts.get("roi")
        target = tier_targets_val[tier]
        if roi is None:
            ok = "─"
        else:
            ok = "✅" if roi >= target else "❌"
        hr_str  = f"{hr:.1%}"   if hr is not None  else "N/A"
        roi_str = f"{roi:.0%}"  if roi is not None else "N/A"
        lines.append(f"| {tier} | {n} | {hr_str} | {roi_str} | {tier_targets_pct[tier]} | {ok} |")
    lines.append("")

    # ── フィルター変更提案 ───────────────────────
    changes = optimize_result.get("changes", [])
    skipped = optimize_result.get("skipped", [])
    lines.append("## 3. フィルター変更提案")
    lines.append("")
    if not changes:
        lines.append("> 今月は変更提案なし（N閾値未達またはROI基準内）")
    else:
        lines.append("| # | 種別 | 対象 | 根拠 | 信頼度 |")
        lines.append("|---|------|------|------|--------|")
        for i, c in enumerate(changes, 1):
            type_ja = {
                "venue_add_exclude":       "除外場追加",
                "venue_remove_exclude":    "除外場解除",
                "keyword_add_negative":    "逆指標追加",
                "keyword_remove_negative": "逆指標解除",
                "race_type_add_exclude":   "種別除外追加",
                "race_type_remove_exclude":"種別除外解除",
            }.get(c["type"], c["type"])
            review = " ⚠️要確認" if c.get("requires_review") else ""
            lines.append(f"| {i} | {type_ja} | {c['target']} | {c['reason']}{review} | {c['confidence']} |")
    lines.append("")

    if skipped:
        lines.append("### 保留（優先度3件超過）")
        lines.append("")
        for s in skipped:
            lines.append(f"- `{s['type']}`: {s['target']}（{s['reason']}）")
        lines.append("")

    # ── Tier境界調整案 ───────────────────────────
    tier_adj = optimize_result.get("tier_adjustments", {})
    lines.append("## 4. Tier境界調整案")
    lines.append("")
    lines.append("| Tier | 実績ROI | 目標ROI | 判定 | 推奨アクション |")
    lines.append("|------|---------|---------|------|--------------|")
    for tier in ["S", "A", "B"]:
        adj = tier_adj.get(tier, {})
        actual = adj.get("actual_roi")
        target = adj.get("target_roi", 0)
        action = adj.get("action", "─")
        note   = adj.get("note", "")
        actual_str = f"{actual:.1f}%" if actual is not None else "N/A"
        action_ja  = {"maintain": "維持", "tighten": "条件強化", "demote": "降格検討",
                      "insufficient_data": "データ不足"}.get(action, action)
        lines.append(f"| {tier} | {actual_str} | {target:.0f}% | {action_ja} | {note} |")
    lines.append("")

    # ── 逆指標発見 ───────────────────────────────
    reverse = adapted.get("_new_reverse", [])
    lines.append("## 5. 新規逆指標発見")
    lines.append("")
    if not reverse:
        lines.append("> 今月は新規逆指標なし")
    else:
        lines.append("| パターン | N | ROI | 重要度 |")
        lines.append("|----------|---|-----|--------|")
        for ind in reverse:
            roi_pct = f"{ind['roi']:.0%}" if ind.get("roi") is not None else "N/A"
            lines.append(f"| {ind['pattern']} | {ind['n']} | {roi_pct} | {ind['significance']} |")
    lines.append("")

    # ── 正指標発見 ───────────────────────────────
    positive = adapted.get("_new_positive", [])
    lines.append("## 6. 新規正指標発見")
    lines.append("")
    if not positive:
        lines.append("> 今月は新規正指標なし")
    else:
        lines.append("| パターン | N | ROI | 重要度 |")
        lines.append("|----------|---|-----|--------|")
        for ind in positive:
            roi_pct = f"{ind['roi']:.0%}" if ind.get("roi") is not None else "N/A"
            lines.append(f"| {ind['pattern']} | {ind['n']} | {roi_pct} | {ind['significance']} |")
    lines.append("")

    # ── 異常値 ───────────────────────────────────
    anomalies = adapted.get("_anomalies", [])
    lines.append("## 7. 異常値検出")
    lines.append("")
    if not anomalies:
        lines.append("> 今月は異常値なし")
    else:
        for a in anomalies:
            sev_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(a["severity"], "⚪")
            lines.append(f"- {sev_emoji} **[{a['severity'].upper()}]** `{a['type']}`: {a['detail']}")
    lines.append("")

    # ── 適用結果 / 次のアクション ─────────────────
    lines.append("## 8. 適用結果 / 次のアクション")
    lines.append("")
    if dry_run:
        lines.append("このレポートはドライランです。変更は **未適用** です。")
        lines.append("")
        lines.append("### 承認後の適用手順")
        lines.append("```bash")
        lines.append(f"python scripts/monthly_optimize.py --sport {sport} --month {year_month} --apply")
        lines.append("```")
        if apply_result.get("backup_path") is None and changes:
            lines.append("")
            lines.append("> ⚠️ `--apply` 実行時は filters.yaml のバックアップが自動作成されます。")
    else:
        backup = apply_result.get("backup_path", "なし")
        lines.append(f"- **適用件数**: {len(apply_result.get('applied', []))}件")
        lines.append(f"- **バックアップ**: `{backup}`")
        lines.append(f"- **changelog**: {optimize_result['changelog']}")
        lines.append("")
        lines.append("> ロールバックが必要な場合はバックアップファイルを filters.yaml に上書きしてください。")
    lines.append("")

    lines.append("---")
    lines.append(f"*Generated by monthly_optimize.py / {now_str}*")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# 月次最適化メイン処理
# ──────────────────────────────────────────────

def run_monthly_optimize(
    sport: str,
    year_month: str,
    dry_run: bool,
    settings: dict,
    verbose: bool = True,
) -> dict:
    """
    1競技分の月次フィルター最適化を実行する。

    Args:
        sport:       "keirin" または "kyotei"
        year_month:  "YYYY-MM" 形式
        dry_run:     True なら変更を実際には適用しない
        settings:    load_settings() の返り値
        verbose:     True なら進捗を標準出力に表示

    Returns:
        {
            "sport": str,
            "year_month": str,
            "optimize_result": dict,
            "apply_result": dict,
            "report_path": str,
        }
    """
    if verbose:
        sport_ja = "競輪" if sport == "keirin" else "競艇"
        print(f"\n{'='*60}")
        print(f"{sport_ja} ({sport}) 月次最適化: {year_month}")
        print(f"モード: {'DRY RUN' if dry_run else '本番適用'}")
        print(f"{'='*60}")

    log_path    = get_log_path(sport, settings)
    config_dir  = get_config_dir(settings)

    # ── Step 1: 月次分析 ─────────────────────────
    if verbose:
        print(f"[1/4] 月次分析実行: {log_path}")
    analyzer = FeedbackAnalyzer(log_path)
    analysis = analyzer.analyze_monthly(sport, year_month)
    if verbose:
        total = analysis.get("total_predictions", 0)
        print(f"      予想件数: {total}件")
        if total == 0:
            print("      ※ データなし。フィルター変更提案は生成されません。")

    # ── Step 2: フォーマット変換 ─────────────────
    adapted = adapt_analysis_for_optimizer(analysis, sport, settings)

    # ── Step 3: 最適化案生成 ─────────────────────
    if verbose:
        print(f"[2/4] フィルター最適化案生成...")
    optimizer = FilterOptimizer(config_dir=config_dir)
    optimize_result = optimizer.optimize(sport, adapted)
    n_changes = len(optimize_result.get("changes", []))
    if verbose:
        print(f"      変更提案: {n_changes}件  新バージョン: {optimize_result['new_version']}")

    # ── Step 4: 変更適用（dry_run 制御） ─────────
    if verbose:
        print(f"[3/4] フィルター{'プレビュー' if dry_run else '適用'}...")
    apply_result = optimizer.apply_changes(sport, optimize_result, dry_run=dry_run)

    # ── Step 5: Markdown レポート生成 ────────────
    if verbose:
        print(f"[4/4] レポート生成...")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    today_str   = datetime.now().strftime("%Y%m%d")
    report_name = f"monthly_optimize_{today_str}_{sport}.md"
    report_path = REPORTS_DIR / report_name

    report_md = build_report(sport, year_month, adapted, optimize_result, apply_result, dry_run)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    if verbose:
        print(f"      レポート出力: {report_path}")

    return {
        "sport":           sport,
        "year_month":      year_month,
        "optimize_result": optimize_result,
        "apply_result":    apply_result,
        "report_path":     str(report_path),
    }


# ──────────────────────────────────────────────
# CLI エントリポイント
# ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """
    コマンドライン引数をパースして返す。

    Returns:
        パース済みの Namespace オブジェクト
    """
    parser = argparse.ArgumentParser(
        description="月次フィルター最適化スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python scripts/monthly_optimize.py                    # 両競技、前月、ドライラン
  python scripts/monthly_optimize.py --sport keirin     # 競輪のみ
  python scripts/monthly_optimize.py --month 2026-01   # 対象月を指定
  python scripts/monthly_optimize.py --apply            # 実際に適用（殿承認後）
        """,
    )
    parser.add_argument(
        "--sport",
        choices=["keirin", "kyotei", "both"],
        default="both",
        help="対象競技 (デフォルト: both)",
    )
    parser.add_argument(
        "--month",
        default=None,
        help="対象月 YYYY-MM 形式 (省略時: 前月)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="フィルターを実際に更新する（省略時はドライラン）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="ドライラン（--apply なしのデフォルト動作と同じ）",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="進捗表示を抑制する",
    )
    return parser.parse_args()


def resolve_year_month(month_arg: str | None) -> str:
    """
    --month 引数を解釈して "YYYY-MM" 文字列を返す。

    Args:
        month_arg: CLI の --month 引数値。None の場合は前月を使用。

    Returns:
        "YYYY-MM" 形式の文字列

    Raises:
        ValueError: 形式が不正な場合
    """
    if month_arg is not None:
        # 形式バリデーション
        try:
            datetime.strptime(month_arg, "%Y-%m")
        except ValueError:
            raise ValueError(f"--month は YYYY-MM 形式で指定してください: {month_arg!r}")
        return month_arg

    # 前月を計算
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}-12"
    return f"{today.year}-{today.month - 1:02d}"


def main() -> int:
    """
    月次フィルター最適化スクリプトのエントリポイント。

    Returns:
        終了コード（0: 成功、1: エラー）
    """
    args = parse_args()
    verbose = not args.quiet

    # dry_run: --apply が指定されなければ True
    dry_run = not args.apply

    try:
        year_month = resolve_year_month(args.month)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    settings = load_settings()
    sports_to_run = SPORTS if args.sport == "both" else [args.sport]

    if verbose:
        print(f"月次フィルター最適化を開始します")
        print(f"対象月: {year_month}  競技: {', '.join(sports_to_run)}  "
              f"モード: {'DRY RUN' if dry_run else '本番適用'}")

    results = []
    for sport in sports_to_run:
        try:
            result = run_monthly_optimize(
                sport=sport,
                year_month=year_month,
                dry_run=dry_run,
                settings=settings,
                verbose=verbose,
            )
            results.append(result)
        except Exception as e:
            print(f"[ERROR] {sport} の最適化中にエラーが発生しました: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    if verbose:
        print(f"\n{'='*60}")
        print("完了サマリ")
        print(f"{'='*60}")
        for r in results:
            sport_ja = "競輪" if r["sport"] == "keirin" else "競艇"
            n = len(r["optimize_result"].get("changes", []))
            print(f"  {sport_ja}: 変更提案 {n}件  レポート → {r['report_path']}")
        if dry_run:
            print(f"\n  ※ ドライランです。実際の適用は --apply フラグで実行してください。")

    return 0


# ──────────────────────────────────────────────
# __main__ テストブロック
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import tempfile

    print("=" * 60)
    print("monthly_optimize.py テスト実行")
    print("=" * 60)

    # --- モックログを一時ファイルに書き出す ---
    _MOCK_RECORDS = [
        {"sport": "keirin", "date": "2026-01-10", "venue": "立川", "tier": "S",
         "filter_type": "A",
         "result": {"hit": True,  "payout": 1800, "roi": 1.80},
         "features": {"race_type": "特選", "day_of_week": "土"},
         "cre_keywords_matched": ["先行有利"]},
        {"sport": "keirin", "date": "2026-01-12", "venue": "玉野", "tier": "A",
         "filter_type": "B",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"race_type": "一般", "day_of_week": "月"},
         "cre_keywords_matched": ["自信"]},
        {"sport": "keirin", "date": "2026-01-15", "venue": "立川", "tier": "S",
         "filter_type": "A",
         "result": {"hit": True,  "payout": 2200, "roi": 2.20},
         "features": {"race_type": "特選", "day_of_week": "水"},
         "cre_keywords_matched": ["先行有利", "連携実績"]},
        {"sport": "keirin", "date": "2026-01-20", "venue": "松戸", "tier": "B",
         "filter_type": "C",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"race_type": "一般", "day_of_week": "火"},
         "cre_keywords_matched": []},
        {"sport": "keirin", "date": "2026-01-25", "venue": "立川", "tier": "S",
         "filter_type": "A",
         "result": {"hit": True,  "payout": 1500, "roi": 1.50},
         "features": {"race_type": "二次予選", "day_of_week": "日"},
         "cre_keywords_matched": ["先行有利"]},
        # kyotei レコード
        {"sport": "kyotei", "date": "2026-01-10", "venue": "住之江", "tier": "S",
         "filter_type": "A",
         "result": {"hit": True,  "payout": 1600, "roi": 1.60},
         "features": {"race_type": "SG", "day_of_week": "土"},
         "cre_keywords_matched": ["イン逃げ"]},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        # 一時的なプロジェクト構造を構築
        tmp = Path(tmpdir)
        (tmp / "data" / "logs").mkdir(parents=True)
        (tmp / "data" / "reports").mkdir(parents=True)
        (tmp / "data" / "feedback").mkdir(parents=True)
        (tmp / "config" / "keirin").mkdir(parents=True)
        (tmp / "config" / "kyotei").mkdir(parents=True)

        # モックログを書き出す
        for sport_name in ["keirin", "kyotei"]:
            log_file = tmp / "data" / "logs" / f"{sport_name}_predictions_log.jsonl"
            with open(log_file, "w", encoding="utf-8") as lf:
                for rec in _MOCK_RECORDS:
                    if rec["sport"] == sport_name:
                        lf.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # モック filters.yaml を配置
        keirin_filters = {
            "version": "v1.0.0",
            "min_s1_count": 3,
            "preferred_venues": ["熊本", "立川"],
            "excluded_venues": ["玉野", "名古屋"],
        }
        kyotei_filters = {
            "version": "v1.0.0",
            "filters": {"grade_strategy": {}},
        }
        with open(tmp / "config" / "keirin" / "filters.yaml", "w", encoding="utf-8") as ff:
            yaml.dump(keirin_filters, ff, allow_unicode=True)
        with open(tmp / "config" / "kyotei" / "filters.yaml", "w", encoding="utf-8") as ff:
            yaml.dump(kyotei_filters, ff, allow_unicode=True)

        # モック settings.yaml
        mock_settings = {
            "pipeline": {"config_dir": "config", "log_dir": "data/logs"},
            "filters": {
                "keirin": {
                    "exclude_velodromes": ["玉野", "名古屋"],
                    "exclude_keywords":   ["自信", "見えた"],
                },
                "kyotei": {
                    "exclude_velodromes": [],
                    "exclude_keywords":   [],
                },
            },
        }

        # run_monthly_optimize を直接呼び出す（一時ディレクトリ内で実行）
        # テスト用に REPORTS_DIR を一時差し替え（モジュールレベルなので global 宣言不要）
        _orig_reports_dir = REPORTS_DIR
        REPORTS_DIR = tmp / "data" / "reports"

        result = run_monthly_optimize(
            sport="keirin",
            year_month="2026-01",
            dry_run=True,
            settings={
                "pipeline": {
                    "config_dir": str(tmp / "config"),
                    "log_dir": str(tmp / "data" / "logs"),
                },
                "filters": mock_settings["filters"],
            },
            verbose=True,
        )

        # レポートが生成されたか確認
        report_path = Path(result["report_path"])
        assert report_path.exists(), f"レポートが生成されませんでした: {report_path}"
        report_lines = report_path.read_text(encoding="utf-8").splitlines()
        assert len(report_lines) > 10, "レポートの行数が少なすぎます"
        print(f"\nレポート生成確認: OK ({len(report_lines)}行)")
        print(f"  先頭3行: {report_lines[:3]}")

        # optimize_result の構造確認
        opt = result["optimize_result"]
        assert "changes"         in opt, "changes キーがありません"
        assert "tier_adjustments" in opt, "tier_adjustments キーがありません"
        assert "new_version"     in opt, "new_version キーがありません"
        print(f"optimize_result 構造確認: OK")
        print(f"  変更提案: {len(opt['changes'])}件")
        print(f"  新バージョン: {opt['new_version']}")

        # apply_result の構造確認
        apl = result["apply_result"]
        assert apl["dry_run"] is True, "dry_run フラグが True であるべきです"
        print(f"apply_result 構造確認: OK (dry_run={apl['dry_run']})")

        REPORTS_DIR = _orig_reports_dir

    print()
    print("=" * 60)
    print("全テスト PASS")
    print("=" * 60)

    sys.exit(0)
