"""
週次集計レポート生成スクリプト

data/predictions/ と data/results/ を照合し、
指定期間の的中率・回収率を計算して Markdown レポートを出力する。

使用例:
    python scripts/weekly_report.py --start 20260217 --end 20260223
    python scripts/weekly_report.py --start 20260217 --end 20260223 --output data/reports/
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# ─── データクラス ──────────────────────────────────────────────────

@dataclass
class PredictionRecord:
    """1件の予想レコード。"""
    date: str
    venue_name: str
    race_no: int
    prediction_text: str
    recommended_numbers: list[int]
    cost_points: int = 300  # 購入コスト（ポイント）
    model: str = "unknown"


@dataclass
class ResultRecord:
    """1件のレース結果レコード。"""
    date: str
    venue_name: str
    race_no: int
    winning_numbers: list[int]
    odds: float


@dataclass
class MatchResult:
    """予想と結果の照合結果。"""
    prediction: PredictionRecord
    result: ResultRecord
    is_hit: bool
    payout: float  # 払戻額（ポイント）


@dataclass
class WeeklyStats:
    """週次集計統計。"""
    period_start: str
    period_end: str
    total_predictions: int = 0
    total_hits: int = 0
    total_cost: int = 0
    total_payout: float = 0.0
    matches: list[MatchResult] = field(default_factory=list)
    unmatched_predictions: list[PredictionRecord] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        """的中率 (0.0 〜 1.0)。予想件数がゼロの場合は 0.0。"""
        if self.total_predictions == 0:
            return 0.0
        return self.total_hits / self.total_predictions

    @property
    def recovery_rate(self) -> float:
        """回収率 (払戻合計 / コスト合計)。コストがゼロの場合は 0.0。"""
        if self.total_cost == 0:
            return 0.0
        return self.total_payout / self.total_cost


# ─── ファイル読み込み ──────────────────────────────────────────────

def load_predictions(predictions_dir: str, start_date: str, end_date: str) -> list[PredictionRecord]:
    """指定期間の予想ファイルをロードする。

    Args:
        predictions_dir: 予想ファイルのディレクトリ
        start_date: 開始日 YYYYMMDD
        end_date: 終了日 YYYYMMDD

    Returns:
        PredictionRecord のリスト
    """
    records: list[PredictionRecord] = []
    pred_path = Path(predictions_dir)

    if not pred_path.exists():
        return records

    for filepath in sorted(pred_path.glob("prediction_*.json")):
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            date = data.get("date", "")
            if not (start_date <= date <= end_date):
                continue

            # 複数予想が1ファイルに入っている場合
            items = data.get("predictions", [data])
            for item in items:
                records.append(
                    PredictionRecord(
                        date=item.get("date", date),
                        venue_name=item.get("venue_name", "不明"),
                        race_no=int(item.get("race_no", 0)),
                        prediction_text=item.get("prediction_text", ""),
                        recommended_numbers=item.get("recommended_numbers", []),
                        cost_points=item.get("cost_points", 300),
                        model=item.get("model", "unknown"),
                    )
                )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            print(f"  警告: {filepath.name} の読み込みをスキップ: {exc}", file=sys.stderr)

    return records


def load_results(results_dir: str, start_date: str, end_date: str) -> list[ResultRecord]:
    """指定期間のレース結果ファイルをロードする。

    Args:
        results_dir: 結果ファイルのディレクトリ
        start_date: 開始日 YYYYMMDD
        end_date: 終了日 YYYYMMDD

    Returns:
        ResultRecord のリスト
    """
    records: list[ResultRecord] = []
    results_path = Path(results_dir)

    if not results_path.exists():
        return records

    for filepath in sorted(results_path.glob("results_*.json")):
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            # 単一会場形式
            if "results" in data:
                date = data.get("date", "")
                venue_name = data.get("venue_name", "不明")
                if start_date <= date <= end_date:
                    for item in data["results"]:
                        records.append(
                            ResultRecord(
                                date=date,
                                venue_name=venue_name,
                                race_no=int(item.get("race_no", 0)),
                                winning_numbers=item.get("winning_numbers", []),
                                odds=float(item.get("odds", 0.0)),
                            )
                        )

            # 全会場まとめ形式
            elif "venues" in data:
                for venue_data in data["venues"]:
                    date = venue_data.get("date", "")
                    venue_name = venue_data.get("venue_name", "不明")
                    if start_date <= date <= end_date:
                        for item in venue_data.get("results", []):
                            records.append(
                                ResultRecord(
                                    date=date,
                                    venue_name=venue_name,
                                    race_no=int(item.get("race_no", 0)),
                                    winning_numbers=item.get("winning_numbers", []),
                                    odds=float(item.get("odds", 0.0)),
                                )
                            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            print(f"  警告: {filepath.name} の読み込みをスキップ: {exc}", file=sys.stderr)

    return records


# ─── 照合ロジック ──────────────────────────────────────────────────

def match_predictions_with_results(
    predictions: list[PredictionRecord],
    results: list[ResultRecord],
) -> WeeklyStats:
    """予想リストと結果リストを照合して WeeklyStats を生成する。

    Args:
        predictions: 予想レコードのリスト
        results: 結果レコードのリスト

    Returns:
        照合結果を含む WeeklyStats
    """
    # 結果を (date, venue_name, race_no) でインデックス化
    results_index: dict[tuple[str, str, int], ResultRecord] = {
        (r.date, r.venue_name, r.race_no): r for r in results
    }

    stats = WeeklyStats(period_start="", period_end="")
    dates = [p.date for p in predictions]
    if dates:
        stats.period_start = min(dates)
        stats.period_end = max(dates)

    for pred in predictions:
        key = (pred.date, pred.venue_name, pred.race_no)
        result = results_index.get(key)

        if result is None:
            stats.unmatched_predictions.append(pred)
            continue

        # 的中判定: predicted_numbers に winning_numbers の先頭が含まれるか
        winning_set = set(result.winning_numbers)
        predicted_set = set(pred.recommended_numbers)
        is_hit = bool(winning_set & predicted_set)

        payout = pred.cost_points * result.odds if is_hit else 0.0

        match = MatchResult(
            prediction=pred,
            result=result,
            is_hit=is_hit,
            payout=payout,
        )
        stats.matches.append(match)
        stats.total_predictions += 1
        stats.total_cost += pred.cost_points
        stats.total_payout += payout
        if is_hit:
            stats.total_hits += 1

    return stats


# ─── レポート生成 ──────────────────────────────────────────────────

def generate_report(stats: WeeklyStats) -> str:
    """WeeklyStats から Markdown レポートを生成する。

    Args:
        stats: 週次集計統計

    Returns:
        Markdown 形式のレポート文字列
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []

    lines.append("# 週次予想集計レポート")
    lines.append(f"集計期間: {stats.period_start} 〜 {stats.period_end}")
    lines.append(f"生成日時: {generated_at}")
    lines.append("")

    # サマリー
    lines.append("## サマリー")
    lines.append("")
    lines.append("| 項目 | 値 |")
    lines.append("|------|-----|")
    lines.append(f"| 予想件数 | {stats.total_predictions} 件 |")
    lines.append(f"| 的中件数 | {stats.total_hits} 件 |")
    lines.append(f"| **的中率** | **{stats.hit_rate:.1%}** |")
    lines.append(f"| 投資コスト | {stats.total_cost:,} pt |")
    lines.append(f"| 払戻合計 | {stats.total_payout:,.0f} pt |")
    lines.append(f"| **回収率** | **{stats.recovery_rate:.1%}** |")
    lines.append(f"| 未照合予想 | {len(stats.unmatched_predictions)} 件 |")
    lines.append("")

    # 評価
    lines.append("## 評価")
    lines.append("")
    if stats.recovery_rate >= 1.20:
        lines.append("🟢 **優秀**: 回収率 120%超。予想精度が高い。")
    elif stats.recovery_rate >= 1.00:
        lines.append("🟡 **プラス**: 回収率 100%超。黒字継続。")
    elif stats.recovery_rate >= 0.80:
        lines.append("🟠 **要改善**: 回収率 80〜100%。戦略の見直しを検討。")
    else:
        lines.append("🔴 **要対策**: 回収率 80%未満。予想ロジックの根本的な見直しが必要。")
    lines.append("")

    # 詳細: 的中レース
    hits = [m for m in stats.matches if m.is_hit]
    if hits:
        lines.append("## 的中レース一覧")
        lines.append("")
        lines.append("| 日付 | 会場 | レース | 的中番号 | オッズ | 払戻 |")
        lines.append("|------|------|--------|---------|------|------|")
        for m in sorted(hits, key=lambda x: (x.prediction.date, x.prediction.venue_name)):
            winning = " - ".join(str(n) for n in m.result.winning_numbers)
            lines.append(
                f"| {m.prediction.date} | {m.prediction.venue_name} "
                f"| {m.prediction.race_no}R | {winning} "
                f"| {m.result.odds:.1f} 倍 | {m.payout:,.0f} pt |"
            )
        lines.append("")

    # 詳細: 外れレース
    misses = [m for m in stats.matches if not m.is_hit]
    if misses:
        lines.append("## 外れレース一覧")
        lines.append("")
        lines.append("| 日付 | 会場 | レース | 予想番号 | 実際の結果 |")
        lines.append("|------|------|--------|---------|---------|")
        for m in sorted(misses, key=lambda x: (x.prediction.date, x.prediction.venue_name)):
            predicted = " - ".join(str(n) for n in m.prediction.recommended_numbers)
            actual = " - ".join(str(n) for n in m.result.winning_numbers)
            lines.append(
                f"| {m.prediction.date} | {m.prediction.venue_name} "
                f"| {m.prediction.race_no}R | {predicted} | {actual} |"
            )
        lines.append("")

    # 未照合予想（結果が取得できなかったもの）
    if stats.unmatched_predictions:
        lines.append("## 未照合予想（結果データなし）")
        lines.append("")
        for pred in stats.unmatched_predictions:
            lines.append(
                f"- {pred.date} / {pred.venue_name} {pred.race_no}R "
                f"（推奨番号: {pred.recommended_numbers}）"
            )
        lines.append("")

    lines.append("---")
    lines.append("*生成: prediction_pipeline / weekly_report.py*")

    return "\n".join(lines)


# ─── CLI エントリーポイント ───────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="週次予想集計レポートを生成する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  python scripts/weekly_report.py --start 20260217 --end 20260223
  python scripts/weekly_report.py --start 20260217 --end 20260223 --output data/reports/
        """,
    )
    parser.add_argument(
        "--start",
        required=True,
        help="集計開始日 (YYYYMMDD)",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="集計終了日 (YYYYMMDD)",
    )
    parser.add_argument(
        "--predictions-dir",
        default="data/predictions",
        help="予想ファイルのディレクトリ (デフォルト: data/predictions)",
    )
    parser.add_argument(
        "--results-dir",
        default="data/results",
        help="結果ファイルのディレクトリ (デフォルト: data/results)",
    )
    parser.add_argument(
        "--output",
        default="data/reports",
        help="レポート出力先ディレクトリ (デフォルト: data/reports)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="ファイルに保存せず標準出力に表示する",
    )
    return parser.parse_args()


def main() -> int:
    """メインエントリーポイント。

    Returns:
        終了コード (0: 成功, 1: エラー)
    """
    args = parse_args()

    # 日付バリデーション
    try:
        start_dt = datetime.strptime(args.start, "%Y%m%d")
        end_dt = datetime.strptime(args.end, "%Y%m%d")
    except ValueError as exc:
        print(f"エラー: 日付の形式が不正です（YYYYMMDD 形式で指定してください）: {exc}", file=sys.stderr)
        return 1

    if start_dt > end_dt:
        print("エラー: 開始日が終了日より後になっています", file=sys.stderr)
        return 1

    print(f"[weekly_report] 集計期間: {args.start} 〜 {args.end}")

    # データ読み込み
    print(f"  予想データ読み込み: {args.predictions_dir}")
    predictions = load_predictions(args.predictions_dir, args.start, args.end)
    print(f"    → {len(predictions)} 件")

    print(f"  結果データ読み込み: {args.results_dir}")
    results = load_results(args.results_dir, args.start, args.end)
    print(f"    → {len(results)} 件")

    if not predictions and not results:
        print("警告: 対象期間のデータが見つかりません", file=sys.stderr)

    # 照合・集計
    stats = match_predictions_with_results(predictions, results)
    stats.period_start = args.start
    stats.period_end = args.end

    # レポート生成
    report_text = generate_report(stats)

    # 出力
    if args.stdout:
        print("\n" + report_text)
    else:
        output_path = Path(args.output)
        output_path.mkdir(parents=True, exist_ok=True)
        filename = f"weekly_report_{args.start}_{args.end}.md"
        filepath = output_path / filename

        with open(filepath, mode="w", encoding="utf-8") as f:
            f.write(report_text)

        print(f"\n✅ レポート保存完了: {filepath}")
        print(f"   的中率: {stats.hit_rate:.1%} ({stats.total_hits}/{stats.total_predictions} 件)")
        print(f"   回収率: {stats.recovery_rate:.1%} ({stats.total_payout:,.0f}pt / {stats.total_cost:,}pt)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
