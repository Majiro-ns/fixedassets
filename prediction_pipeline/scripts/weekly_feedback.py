"""
scripts/weekly_feedback.py — 週次フィードバックレポート生成スクリプト

FeedbackAnalyzer（feedback_engine/analyzer.py）を呼び出し、
predictions_log.jsonl から週次成績を分析して Markdown レポートを出力する。

weekly_report.py との違い:
  - Tier別成績（S/A/B）分析
  - 逆指標・正指標の自動発見
  - 異常値検出と stdout アラート
  - AI フィルター改善推奨の出力

使用例:
    python scripts/weekly_feedback.py --start 20260217 --end 20260223 --sport keirin
    python scripts/weekly_feedback.py --start 20260217 --end 20260223 --sport both
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# feedback_engine を import できるようパスを通す（scripts/ の親 = pipeline_root）
PIPELINE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PIPELINE_ROOT))

try:
    import yaml as _yaml
    def _load_yaml(path: Path) -> dict:
        """YAML ファイルを読み込む（PyYAML 使用）。"""
        with open(path, encoding="utf-8") as f:
            return _yaml.safe_load(f) or {}
except ImportError:
    def _load_yaml(path: Path) -> dict:
        """PyYAML 未インストール時のフォールバック（空dictを返す）。"""
        return {}

from feedback_engine.analyzer import FeedbackAnalyzer


# ---- 定数 ------------------------------------------------------------------

ALERT_MIN_HIT_RATE      = 0.10   # 的中率10%未満でアラート
ALERT_VENUE_ROI_DELTA   = 0.50   # 場別ROI乖離50pt超でアラート


# ---- 設定読み込み ----------------------------------------------------------

def load_config(config_path: Path) -> dict:
    """
    config/settings.yaml を読み込む。

    Args:
        config_path: settings.yaml のパス

    Returns:
        設定辞書。ファイルが存在しない場合は空辞書。
    """
    if not config_path.exists():
        return {}
    return _load_yaml(config_path)


def resolve_log_path(config: dict) -> Path:
    """
    config から predictions_log.jsonl のパスを解決する。

    Args:
        config: settings.yaml の内容

    Returns:
        predictions_log.jsonl の絶対パス
    """
    log_dir = config.get("pipeline", {}).get("log_dir", "data/logs")
    return PIPELINE_ROOT / log_dir / "predictions_log.jsonl"


# ---- 日付変換 ---------------------------------------------------------------

def yyyymmdd_to_iso(s: str) -> str:
    """
    YYYYMMDD 形式を YYYY-MM-DD 形式に変換する。

    Args:
        s: YYYYMMDD 形式の日付文字列

    Returns:
        YYYY-MM-DD 形式の日付文字列
    """
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


# ---- アラート出力 -----------------------------------------------------------

def print_alerts(analysis: dict, sport: str) -> int:
    """
    分析結果から異常値アラートを stdout に出力する。

    アラート条件:
    - 週次的中率 < 10%
    - 場別 ROI 乖離 > 50%
    - 新規逆指標発見時

    Args:
        analysis: FeedbackAnalyzer.analyze_weekly() の返り値
        sport:    スポーツ名（表示用）

    Returns:
        発出したアラート数
    """
    alert_count = 0
    overall = analysis.get("overall", {})
    period = analysis.get("period", {})
    label = f"[{sport.upper()} {period.get('start','')}〜{period.get('end','')}]"

    # --- 1. 週次的中率チェック ---
    hit_rate = overall.get("hit_rate")
    if hit_rate is not None and hit_rate < ALERT_MIN_HIT_RATE:
        print(f"🚨 ALERT {label} 週次的中率 {hit_rate:.1%} が閾値 {ALERT_MIN_HIT_RATE:.0%} を下回っています")
        alert_count += 1

    # --- 2. 場別ROI乖離チェック（50%超） ---
    overall_roi = overall.get("roi")
    if overall_roi is not None:
        by_venue = analysis.get("by_venue", {})
        for venue, vstats in by_venue.items():
            venue_roi = vstats.get("roi")
            if venue_roi is None:
                continue
            delta = abs(venue_roi - overall_roi)
            if delta > ALERT_VENUE_ROI_DELTA:
                direction = "高い" if venue_roi > overall_roi else "低い"
                print(f"⚠️  ALERT {label} 場 [{venue}] ROI {venue_roi:.0%} が"
                      f"全体 {overall_roi:.0%} より {delta:.0%} {direction}")
                alert_count += 1

    # --- 3. 新規逆指標発見 ---
    reverse = analysis.get("new_reverse_indicators", [])
    for ind in reverse:
        print(f"🔴 ALERT {label} 逆指標発見: {ind['pattern']} "
              f"N={ind['n']} ROI={ind['roi']:.0%} "
              f"重要度={ind['significance']}")
        alert_count += 1

    return alert_count


# ---- Markdown レポート生成 --------------------------------------------------

def _tier_row(tier: str, stats: dict) -> str:
    """
    Tier 成績テーブルの1行を生成する。

    Args:
        tier:  "S" / "A" / "B"
        stats: _calc_tier_stats の1Tier分辞書

    Returns:
        Markdown テーブル行文字列
    """
    n       = stats.get("n", 0)
    hr      = stats.get("hit_rate")
    roi     = stats.get("roi")
    hr_str  = f"{hr:.1%}" if hr  is not None else "—"
    roi_str = f"{roi:.1%}" if roi is not None else "—"
    return f"| {tier}    | {n:>4} | {hr_str:>6}  | {roi_str:>6}  |"


def _format_single(analysis: dict, start_ymd: str, end_ymd: str, sport: str) -> str:
    """
    1スポーツ分の分析結果を Markdown に変換する。

    Args:
        analysis:  analyze_weekly() の返り値
        start_ymd: YYYYMMDD 形式の開始日
        end_ymd:   YYYYMMDD 形式の終了日
        sport:     スポーツ名

    Returns:
        Markdown 文字列
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    overall   = analysis.get("overall", {})
    by_tier   = analysis.get("by_tier", {})
    by_venue  = analysis.get("by_venue", {})
    anomalies = analysis.get("anomalies", [])
    reverse   = analysis.get("new_reverse_indicators", [])
    positive  = analysis.get("new_positive_indicators", [])
    bc        = analysis.get("tier_boundary_check", {})
    total     = analysis.get("total_predictions", 0)

    lines = []
    sport_label = {"keirin": "競輪", "kyotei": "競艇"}.get(sport, sport)

    lines.append(f"# 週次フィードバックレポート {start_ymd}〜{end_ymd} ({sport_label})")
    lines.append(f"生成日時: {generated_at}")
    lines.append("")

    # --- 全体成績 ---
    lines.append("## 全体成績")
    n       = overall.get("n",        total)
    hr      = overall.get("hit_rate")
    roi     = overall.get("roi")
    profit  = overall.get("profit")
    hr_str  = f"{hr:.1%}"  if hr     is not None else "—"
    roi_str = f"{roi:.1%}" if roi    is not None else "—"
    profit_str = f"{profit:+,}円" if profit is not None else "—"
    lines.append(f"- 予想件数: {n}件 / 的中率: {hr_str} / 回収率: {roi_str} / 損益: {profit_str}")
    lines.append("")

    # --- Tier別成績 ---
    lines.append("## Tier別成績")
    lines.append("")
    lines.append("| Tier | 件数 | 的中率  | 回収率  |")
    lines.append("|------|------|---------|---------|")
    for tier in ["S", "A", "B"]:
        ts = by_tier.get(tier, {"n": 0, "hit_rate": None, "roi": None})
        lines.append(_tier_row(tier, ts))
    lines.append("")

    # --- Tier境界チェック ---
    lines.append("## Tier境界チェック")
    s_mark = "✅" if bc.get("s_ok") else ("❌" if bc.get("s_ok") is False else "—")
    a_mark = "✅" if bc.get("a_ok") else ("❌" if bc.get("a_ok") is False else "—")
    b_mark = "✅" if bc.get("b_ok") else ("❌" if bc.get("b_ok") is False else "—")
    s_roi = f"{bc['s_roi']:.0%}" if bc.get("s_roi") is not None else "—"
    a_roi = f"{bc['a_roi']:.0%}" if bc.get("a_roi") is not None else "—"
    b_roi = f"{bc['b_roi']:.0%}" if bc.get("b_roi") is not None else "—"
    lines.append(f"- S (目標130%): {s_roi} {s_mark}")
    lines.append(f"- A (目標105%): {a_roi} {a_mark}")
    lines.append(f"- B (目標 95%): {b_roi} {b_mark}")
    lines.append(f"- **推奨**: {bc.get('recommendation', '—')}")
    lines.append("")

    # --- 場別成績 ---
    if by_venue:
        lines.append("## 場別成績")
        lines.append("")
        lines.append("| 場     | 件数 | 的中率  | 回収率  |")
        lines.append("|--------|------|---------|---------|")
        for venue, vstats in sorted(by_venue.items()):
            n_v   = vstats.get("n", 0)
            hr_v  = vstats.get("hit_rate")
            roi_v = vstats.get("roi")
            hr_vs  = f"{hr_v:.1%}"  if hr_v  is not None else "—"
            roi_vs = f"{roi_v:.1%}" if roi_v is not None else "—"
            warn   = " ⚠" if vstats.get("warning") else ""
            lines.append(f"| {venue:<6} | {n_v:>4} | {hr_vs:>6}  | {roi_vs:>6}  |{warn}")
        lines.append("")

    # --- 異常値検出 ---
    lines.append("## ⚠️ 異常値検出")
    lines.append("")
    if anomalies:
        for a in anomalies:
            sev_icon = "🚨" if a.get("severity") == "high" else "⚠️"
            lines.append(f"- {sev_icon} **{a['type']}**: {a['detail']}")
    else:
        lines.append("- なし")
    lines.append("")

    # --- 逆指標候補 ---
    lines.append("## 逆指標候補")
    lines.append("")
    if reverse:
        for ind in reverse:
            lines.append(f"- `{ind['pattern']}` N={ind['n']} ROI={ind['roi']:.0%} "
                         f"重要度={ind['significance']}")
    else:
        lines.append("- なし（N≥10 かつ ROI<50% のパターン未検出）")
    lines.append("")

    # --- 正指標候補 ---
    lines.append("## 正指標候補")
    lines.append("")
    if positive:
        for ind in positive:
            lines.append(f"- `{ind['pattern']}` N={ind['n']} ROI={ind['roi']:.0%} "
                         f"重要度={ind['significance']}")
    else:
        lines.append("- なし（N≥10 かつ ROI>130% のパターン未検出）")
    lines.append("")

    lines.append("---")
    lines.append("*生成: prediction_pipeline / weekly_feedback.py + feedback_engine/analyzer.py*")

    return "\n".join(lines)


def format_report(analyses: dict, start_ymd: str, end_ymd: str) -> str:
    """
    全スポーツの分析結果をまとめた Markdown レポートを生成する。

    Args:
        analyses:  {sport: analysis_dict} の辞書
        start_ymd: YYYYMMDD 形式の開始日
        end_ymd:   YYYYMMDD 形式の終了日

    Returns:
        Markdown 文字列（複数スポーツの場合はセクション区切り）
    """
    sections = []
    for sport, analysis in analyses.items():
        sections.append(_format_single(analysis, start_ymd, end_ymd, sport))
    return "\n\n---\n\n".join(sections)


# ---- CLI -------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """
    コマンドライン引数を解析する。

    Returns:
        解析済み引数 Namespace
    """
    parser = argparse.ArgumentParser(
        description="週次フィードバックレポートを生成する（FeedbackAnalyzer 呼び出し）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python scripts/weekly_feedback.py --start 20260217 --end 20260223 --sport keirin
  python scripts/weekly_feedback.py --start 20260217 --end 20260223 --sport both
        """,
    )
    parser.add_argument("--start", required=True, help="集計開始日 (YYYYMMDD)")
    parser.add_argument("--end",   required=True, help="集計終了日 (YYYYMMDD)")
    parser.add_argument(
        "--sport",
        default="keirin",
        choices=["keirin", "kyotei", "both"],
        help="対象スポーツ (keirin / kyotei / both, デフォルト: keirin)",
    )
    parser.add_argument(
        "--config",
        default=str(PIPELINE_ROOT / "config" / "settings.yaml"),
        help="設定ファイルパス (デフォルト: config/settings.yaml)",
    )
    parser.add_argument(
        "--output",
        default=str(PIPELINE_ROOT / "data" / "reports"),
        help="レポート出力先ディレクトリ (デフォルト: data/reports)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="ファイルに保存せず標準出力に表示する",
    )
    return parser.parse_args()


def main() -> int:
    """
    メインエントリーポイント。

    Returns:
        終了コード (0: 成功, 1: エラー)
    """
    args = parse_args()

    # --- 日付バリデーション ---
    try:
        start_dt = datetime.strptime(args.start, "%Y%m%d")
        end_dt   = datetime.strptime(args.end,   "%Y%m%d")
    except ValueError as exc:
        print(f"エラー: 日付形式が不正です（YYYYMMDD で指定してください）: {exc}", file=sys.stderr)
        return 1

    if start_dt > end_dt:
        print("エラー: 開始日が終了日より後になっています", file=sys.stderr)
        return 1

    # --- 設定読み込み ---
    config_path = Path(args.config)
    config = load_config(config_path)
    if not config_path.exists():
        print(f"警告: 設定ファイルが見つかりません ({config_path})。デフォルト設定を使用します",
              file=sys.stderr)

    # --- predictions_log.jsonl パス解決 ---
    log_path = resolve_log_path(config)
    if not log_path.exists():
        print(f"警告: predictions_log.jsonl が見つかりません ({log_path})。"
              "空のレポートを生成します", file=sys.stderr)

    print(f"[weekly_feedback] 集計期間: {args.start} 〜 {args.end}  スポーツ: {args.sport}")
    print(f"  ログパス: {log_path}")

    # --- YYYYMMDD → YYYY-MM-DD 変換 ---
    start_iso = yyyymmdd_to_iso(args.start)
    end_iso   = yyyymmdd_to_iso(args.end)

    # --- 分析実行 ---
    analyzer = FeedbackAnalyzer(str(log_path))
    sports_list = ["keirin", "kyotei"] if args.sport == "both" else [args.sport]

    analyses: dict[str, dict] = {}
    for sport in sports_list:
        print(f"  分析中: {sport} ...", end="", flush=True)
        analyses[sport] = analyzer.analyze_weekly(sport, start_iso, end_iso)
        n = analyses[sport].get("total_predictions", 0)
        print(f" {n}件")

    # --- アラート出力 ---
    total_alerts = 0
    for sport, analysis in analyses.items():
        total_alerts += print_alerts(analysis, sport)

    if total_alerts == 0:
        print("  ✅ 異常なし")

    # --- レポート生成 ---
    report_text = format_report(analyses, args.start, args.end)

    # --- 出力 ---
    if args.stdout:
        print("\n" + report_text)
    else:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename    = f"weekly_report_{args.end}.md"
        output_file = output_dir / filename

        output_file.write_text(report_text, encoding="utf-8")
        print(f"\n✅ レポート保存完了: {output_file}")

        # サマリー表示
        for sport, analysis in analyses.items():
            o = analysis.get("overall", {})
            hr  = o.get("hit_rate")
            roi = o.get("roi")
            n   = o.get("n", 0)
            hr_s  = f"{hr:.1%}"  if hr  is not None else "—"
            roi_s = f"{roi:.1%}" if roi is not None else "—"
            print(f"   [{sport}] 件数:{n}  的中率:{hr_s}  回収率:{roi_s}")

    return 0


# ---- __main__ テスト -------------------------------------------------------

if __name__ == "__main__":
    # 引数なしで起動した場合のみデモ引数を使用する
    if len(sys.argv) == 1:
        sys.argv = [
            "weekly_feedback.py",
            "--start", "20260217",
            "--end",   "20260223",
            "--sport", "keirin",
            "--stdout",
        ]
    sys.exit(main())
