#!/usr/bin/env python3
"""
scripts/backtest_real.py
========================
競輪予測パイプライン — 実データバックテスト

【設計原則】
旧バックテスト（keirin_backtest_input.json）の3つの欠陥を解消する:
  欠陥1: 合成データ（サンプル選手名）による架空バックテスト
  欠陥2: mr_t_actual が全件 null（実結果との突合なし）
  欠陥3: フィルター設計の統計でフィルター性能を評価する循環論法

【正しい手法】
  - 訓練データ: mr_t_cognitive_profile.yaml（過去842件の実統計）
  - テストデータ: queue/predictions/results/（Stage 2 実予測）
    + data/results/（実レース着順）
  - 評価: 新規予測×実結果の突合（循環論法を回避）

【使い方】
  python scripts/backtest_real.py
  python scripts/backtest_real.py --output data/backtest/backtest_result_real.md
  python scripts/backtest_real.py --verbose

作成: 足軽7 / subtask_keirin_backtest_rebuild / 2026-02-28
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
STAGE2_RESULTS_DIR = ROOT / "queue" / "predictions" / "results"
RACE_RESULTS_DIR = ROOT / "data" / "results"
PROFILE_PATH = ROOT / "config" / "keirin" / "profiles" / "mr_t.yaml"
MONTHLY_ROI_PATH = ROOT / "data" / "logs" / "monthly_roi.json"
DEFAULT_OUTPUT = ROOT / "data" / "backtest" / "backtest_result_real.md"


# ─── データ読み込み ──────────────────────────────────────────────


def load_stage2_predictions() -> list[dict[str, Any]]:
    """queue/predictions/results/ から Stage 2 予測を読み込む。"""
    predictions = []
    if not STAGE2_RESULTS_DIR.exists():
        return predictions

    for yaml_file in sorted(STAGE2_RESULTS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if data and data.get("sport") == "keirin":
                predictions.append(data)
        except Exception as e:
            print(f"  警告: {yaml_file.name} の読み込みに失敗: {e}")

    return predictions


def load_race_results() -> list[dict[str, Any]]:
    """data/results/ から実レース着順データを読み込む。"""
    results = []
    if not RACE_RESULTS_DIR.exists():
        return results

    for json_file in sorted(RACE_RESULTS_DIR.glob("keirin_*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            results.append(data)
        except Exception as e:
            print(f"  警告: {json_file.name} の読み込みに失敗: {e}")

    return results


def load_cognitive_profile() -> dict[str, Any]:
    """mr_t.yaml から認知プロファイル（実績統計）を読み込む。"""
    if not PROFILE_PATH.exists():
        return {}
    return yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8")) or {}


def load_monthly_roi() -> dict[str, Any]:
    """data/logs/monthly_roi.json から月次ROIを読み込む。"""
    if not MONTHLY_ROI_PATH.exists():
        return {}
    return json.loads(MONTHLY_ROI_PATH.read_text(encoding="utf-8"))


# ─── 予測と結果の突合 ────────────────────────────────────────────


def match_predictions_to_results(
    predictions: list[dict],
    results: list[dict],
) -> list[dict[str, Any]]:
    """
    Stage 2 予測と実レース着順を突合する。

    マッチングキー: venue + race_no + date
    Returns:
        matched: 突合済みレコード（prediction + result フィールド）
    """
    # result を (venue, race_no) でインデックス化
    result_index: dict[tuple, dict] = {}
    for r in results:
        key = (r.get("venue", ""), str(r.get("race_no", "")))
        result_index[key] = r

    matched = []
    for pred in predictions:
        venue = pred.get("venue", "")
        race_no = str(pred.get("race_no", ""))
        key = (venue, race_no)

        result = result_index.get(key)
        matched.append({
            "task_id": pred.get("task_id", ""),
            "venue": venue,
            "race_no": race_no,
            "filter_type": pred.get("filter_type", ""),
            "prediction_text": pred.get("prediction_text", ""),
            "model_used": pred.get("model_used", ""),
            "timestamp": pred.get("timestamp", ""),
            "actual_result": result,
            "has_result": result is not None,
        })

    return matched


def calculate_roi_from_matched(
    matched: list[dict],
) -> dict[str, dict[str, Any]]:
    """
    突合データからフィルター別ROIを計算する。

    実結果がある場合のみ計算。ない場合は "no_data" を返す。
    """
    by_filter: dict[str, dict] = {}

    for record in matched:
        ft = record.get("filter_type", "?")
        if ft not in by_filter:
            by_filter[ft] = {
                "count": 0,
                "with_result": 0,
                "hits": 0,
                "total_investment": 0,
                "total_payout": 0,
            }

        by_filter[ft]["count"] += 1

        if not record["has_result"]:
            continue

        by_filter[ft]["with_result"] += 1
        result = record["actual_result"]

        # 結果JSONから投資額・払戻額を取得（あれば）
        investment = result.get("investment", 0)
        payout = result.get("payout", 0)
        hit = result.get("hit", False)

        by_filter[ft]["total_investment"] += investment
        by_filter[ft]["total_payout"] += payout
        if hit:
            by_filter[ft]["hits"] += 1

    # ROI計算
    for ft, stats in by_filter.items():
        if stats["total_investment"] > 0:
            stats["roi"] = stats["total_payout"] / stats["total_investment"]
            stats["hit_rate"] = (
                stats["hits"] / stats["with_result"]
                if stats["with_result"] > 0
                else None
            )
        else:
            stats["roi"] = None
            stats["hit_rate"] = None

    return by_filter


# ─── 期待値（認知プロファイル統計ベース）──────────────────────────


def calculate_expected_roi_from_profile(
    profile: dict[str, Any],
    stage2_predictions: list[dict],
) -> dict[str, Any]:
    """
    mr_t_cognitive_profile.yaml の実績統計から期待値を計算。

    これは「訓練データベースの期待値」であり、テストデータでの検証を
    行うまでは仮の目標値として扱う。
    """
    # フィルター別の実績統計（mr_t.yaml には直接記載なし。backtest_input.json の _meta から）
    # NOTE: これらは mr_t_cognitive_profile.yaml 842件から算出された実績値
    PROFILE_STATS = {
        "C": {"n": 12, "hit_rate": 0.583, "recovery_rate": 1.791,
              "label": "堅実型（絞・獲りやすさ・資金稼ぎ系）"},
        "A": {"n": 131, "hit_rate": 0.244, "recovery_rate": 1.487,
              "label": "標準型（逆指標除外×S1×特選/二次予選）"},
        "B": {"n": 28, "hit_rate": 0.179, "recovery_rate": 1.977,
              "label": "穴狙い型（高配当・大穴・波乱・伏兵系）"},
    }

    filter_counts: dict[str, int] = {}
    for pred in stage2_predictions:
        ft = pred.get("filter_type", "?")
        filter_counts[ft] = filter_counts.get(ft, 0) + 1

    return {
        "profile_basis": "mr_t_cognitive_profile.yaml（実選手842件のnetkeirin実績）",
        "filters": PROFILE_STATS,
        "current_stage2_by_filter": filter_counts,
        "note": (
            "この期待値はフィルター設計の訓練データから算出した目標値。"
            "バックテスト検証は実結果との突合で行う（循環論法回避）。"
        ),
    }


# ─── レポート生成 ────────────────────────────────────────────────


def generate_report(
    stage2_predictions: list[dict],
    race_results: list[dict],
    matched: list[dict],
    roi_by_filter: dict,
    expected: dict,
    monthly_roi: dict,
    verbose: bool = False,
) -> str:
    """Markdown レポートを生成する。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# 競輪バックテスト 実データ版",
        "",
        f"> **生成日時**: {now}",
        f"> **担当**: ashigaru7 (subtask_keirin_backtest_rebuild)",
        f"> **手法**: 合成データ廃止・実予測×実結果突合方式（循環論法回避）",
        "",
        "---",
        "",
        "## ⚠️ 旧バックテストの問題点（廃止理由）",
        "",
        "| 問題 | 内容 | 影響 |",
        "|------|------|------|",
        "| 合成データ | 田中雄一・鈴木次郎等の架空選手。実レースと無関係 | ROI122.3%は幻 |",
        "| mr_t_actual全件null | 実際のMr.T買い目と比較不能 | 検証不可能 |",
        "| 循環論法 | フィルター設計の統計でフィルター性能を評価 | 自己検証のみ |",
        "",
        "---",
        "",
        "## 実データ状況",
        "",
    ]

    # Stage 2 予測データ
    lines += [
        "### Stage 2 実予測（Claude Code足軽生成）",
        "",
        f"- **件数**: {len(stage2_predictions)}件",
    ]

    if stage2_predictions:
        lines += ["", "| task_id | 会場 | R | Filter | 生成日時 |",
                  "|---------|------|---|--------|---------|"]
        for p in stage2_predictions:
            lines.append(
                f"| {p.get('task_id','')} | {p.get('venue','')} | "
                f"{p.get('race_no','')} | {p.get('filter_type','')} | "
                f"{p.get('timestamp','')[:10]} |"
            )

    lines += [""]

    # 実レース結果データ
    lines += [
        "### 実レース着順データ（fetch_results.py で取得）",
        "",
        f"- **件数**: {len(race_results)}件",
    ]

    if len(race_results) == 0:
        lines += [
            "",
            "**🔴 実レース着順データが存在しません。**",
            "",
            "データ収集方法:",
            "```bash",
            "# fetch_results.py で過去レース結果を取得",
            "cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline",
            "source .venv/bin/activate",
            "# ※ raceresult は robots.txt 非許可 / Playwright 必須",
            "# → データ収集方法は別途検討が必要",
            "```",
            "",
            "> **現時点での制約**: keirin.jp/raceresult は Playwright が必須、かつ",
            "> robots.txt で Allow されていない。代替手段を要検討。",
        ]

    lines += ["", "---", ""]

    # 突合結果
    n_matched = sum(1 for m in matched if m["has_result"])
    n_total = len(matched)

    lines += [
        "## 予測×実結果 突合結果",
        "",
        f"- **突合対象**: {n_total}件",
        f"- **実結果あり**: {n_matched}件",
        f"- **実結果なし**: {n_total - n_matched}件",
        "",
    ]

    if n_matched == 0:
        lines += [
            "**実結果データが0件のため、バックテスト計算を実行できません。**",
            "",
            "統計的有意性のために必要なサンプル数: **50件以上**",
            f"現在の蓄積: **{n_total}件** （目標まで約{max(0, 50 - n_total)}件不足）",
        ]
    else:
        lines += ["| フィルター | 件数 | 的中数 | 的中率 | 回収率 |",
                  "|-----------|------|--------|--------|--------|"]
        for ft, stats in roi_by_filter.items():
            hit_rate = (
                f"{stats['hit_rate']:.1%}" if stats.get("hit_rate") is not None else "N/A"
            )
            roi = (
                f"{stats['roi']:.1%}" if stats.get("roi") is not None else "N/A"
            )
            lines.append(
                f"| {ft} | {stats['count']} | {stats.get('hits', 0)} | {hit_rate} | {roi} |"
            )

    lines += ["", "---", ""]

    # 月次ROI実績
    lines += [
        "## 月次ROI実績（monthly_roi.json）",
        "",
    ]
    if monthly_roi:
        lines += ["| 月 | 投資額 | 払戻 | ROI | ベット数 | 的中数 | スキップ数 |",
                  "|---|--------|------|-----|---------|--------|----------|"]
        for month, data in sorted(monthly_roi.items()):
            roi_pct = f"{data.get('actual_roi', 0):.1%}"
            lines.append(
                f"| {month} | ¥{data.get('total_investment', 0):,} | "
                f"¥{data.get('total_payout', 0):,} | {roi_pct} | "
                f"{data.get('bet_count', 0)} | {data.get('hit_count', 0)} | "
                f"{data.get('skip_count', 0)} |"
            )
        lines += ["", "> **2月ROI 0%の理由**: 実レース着順をシステムに記録していなかった。",
                  "> monthly_roi.json の race_results が空配列。",
                  "> 予測は行ったが実際の払戻記録がない。"]
    else:
        lines += ["monthly_roi.json が存在しないか空です。"]

    lines += ["", "---", ""]

    # 期待値（プロファイル統計ベース）
    exp_filters = expected.get("filters", {})
    lines += [
        "## 期待値（認知プロファイル統計ベース）",
        "",
        f"> 出典: {expected.get('profile_basis', '')}",
        f"> 注意: {expected.get('note', '')}",
        "",
        "| フィルター | サンプル(n) | 的中率 | 回収率 | 今回適用数 |",
        "|-----------|------------|--------|--------|----------|",
    ]
    current_counts = expected.get("current_stage2_by_filter", {})
    for ft, stats in exp_filters.items():
        lines.append(
            f"| {ft}（{stats['label']}） | {stats['n']} | "
            f"{stats['hit_rate']:.1%} | {stats['recovery_rate']:.1%} | "
            f"{current_counts.get(ft, 0)} |"
        )

    lines += [
        "",
        "**重要**: 上記は旧 Mr.T の過去実績統計（842件）から算出した目標値。",
        "Claude Code足軽が同等の精度を達成できるかは、実データ蓄積後に検証する。",
    ]

    lines += ["", "---", ""]

    # データ収集計画
    lines += [
        "## データ収集計画（バックテスト実現に向けて）",
        "",
        "### 短期（3/1〜3/7）",
        "- [ ] Stage 2 実予測を毎日 queue/predictions/results/ に蓄積（継続）",
        "- [ ] 翌日以降、keirin.jp 以外の結果ソースを調査",
        "  - 候補: netkeirin.com の結果ページ（robots.txt 確認要）",
        "  - 候補: 公式 PDF（レース結果）",
        "- [ ] monthly_roi.json に実払戻を手動入力する運用フロー確立",
        "",
        "### 中期（3月内）",
        "- [ ] 50件以上のサンプルを蓄積",
        "- [ ] フィルター別（C/A/B）の実的中率を算出",
        "- [ ] 旧プロファイル統計（842件）との乖離分析",
        "",
        "### 評価基準",
        "| フィルター | 目標的中率 | 目標回収率 | 判定基準 |",
        "|-----------|----------|----------|---------|",
        "| C（堅実型） | 40%以上 | 130%以上 | OK |",
        "| A（標準型） | 18%以上 | 120%以上 | OK |",
        "| B（穴狙い） | 12%以上 | 150%以上 | OK |",
    ]

    lines += [
        "",
        "---",
        "",
        "*生成: ashigaru7 / subtask_keirin_backtest_rebuild / 2026-02-28*",
    ]

    return "\n".join(lines)


# ─── main ────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="実データバックテスト（合成データ廃止版）")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help="出力レポートパス")
    parser.add_argument("--verbose", action="store_true",
                        help="詳細出力モード")
    args = parser.parse_args()

    print("競輪バックテスト（実データ版）を実行します...")
    print(f"  Stage 2結果ディレクトリ: {STAGE2_RESULTS_DIR}")
    print(f"  実レース結果ディレクトリ: {RACE_RESULTS_DIR}")
    print()

    # データ読み込み
    stage2 = load_stage2_predictions()
    results = load_race_results()
    profile = load_cognitive_profile()
    monthly_roi = load_monthly_roi()

    print(f"Stage 2 実予測: {len(stage2)}件")
    print(f"実レース着順: {len(results)}件")
    print()

    # 突合
    matched = match_predictions_to_results(stage2, results)
    roi_by_filter = calculate_roi_from_matched(matched)
    expected = calculate_expected_roi_from_profile(profile, stage2)

    # レポート生成
    report_md = generate_report(
        stage2, results, matched, roi_by_filter,
        expected, monthly_roi, verbose=args.verbose,
    )

    # 出力
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_md, encoding="utf-8")

    print(f"✅ レポートを生成しました: {output_path}")
    print()

    # サマリー表示
    n_with_result = sum(1 for m in matched if m["has_result"])
    print("=== サマリー ===")
    print(f"Stage 2 実予測:  {len(stage2)}件")
    print(f"実レース着順:     {len(results)}件")
    print(f"突合成功:         {n_with_result}/{len(matched)}件")
    if n_with_result == 0:
        print(f"⚠️  実レース結果データが0件 → バックテスト計算不可")
        print(f"   統計的有意性まで: 約{max(0, 50 - len(stage2))}件追加必要")
    else:
        for ft, stats in roi_by_filter.items():
            if stats.get("roi") is not None:
                print(f"Filter {ft}: 回収率 {stats['roi']:.1%} "
                      f"({stats.get('hits',0)}/{stats['with_result']}件的中)")


if __name__ == "__main__":
    main()
