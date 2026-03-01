"""
m1_precision_check.py
=====================
disclosure-multiagent M1 PDF精度検証スクリプト（10社・cmd_073対応）

実行方法:
    cd scripts/
    USE_MOCK_LLM=true python3 m1_precision_check.py

出力:
    コンソール: 10社の検証結果サマリー
    ../10_Research/m1_precision_report.md: Markdownレポート

注意: M1〜M5 モジュールは改変しない（READ-ONLY呼び出しのみ）
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from datetime import datetime

# scripts/ をパスに追加
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from m1_pdf_agent import extract_report, get_human_capital_sections
from pdf_poc_extract import is_fund_report

# PDFディレクトリ
_SAMPLES_DIR = _SCRIPTS_DIR.parent / "10_Research" / "samples"
_REPORT_PATH = _SCRIPTS_DIR.parent / "10_Research" / "m1_precision_report.md"

# PoC実績値（PDF_PoC_Result.md より: v2.1修正版）
_BASELINE: dict[str, dict] = {
    "company_a.pdf": {"sections": 18, "is_fund": False},
    "company_b.pdf": {"sections": 8,  "is_fund": False},
    "company_c.pdf": {"sections": 0,  "is_fund": True},
    "company_d.pdf": {"sections": 24, "is_fund": False},
    "company_e.pdf": {"sections": 22, "is_fund": False},
    "company_f.pdf": {"sections": 14, "is_fund": False},
    "company_g.pdf": {"sections": 41, "is_fund": False},
    "company_h.pdf": {"sections": 34, "is_fund": False},
    "company_i.pdf": {"sections": 61, "is_fund": False},
    "company_j.pdf": {"sections": 25, "is_fund": False},
}
_BASELINE_AVG_TIME = 0.828  # 秒（PDF_PoC_Result.md 実績）


def run_precision_check() -> dict:
    """10社PDFを順次処理し精度指標を収集する"""
    pdf_files = sorted(_SAMPLES_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"ERROR: PDFが見つかりません: {_SAMPLES_DIR}", file=sys.stderr)
        sys.exit(1)

    results = []
    errors = []

    print(f"=== M1精度検証開始: {len(pdf_files)}社 ===")
    print(f"PDFディレクトリ: {_SAMPLES_DIR}")
    print()

    for pdf_path in pdf_files:
        name = pdf_path.name
        print(f"処理中: {name} ...", end=" ", flush=True)

        t0 = time.perf_counter()
        try:
            # M1 extract_report（セクション分割）
            report = extract_report(str(pdf_path), fiscal_year=2025)
            elapsed = time.perf_counter() - t0

            # 人的資本セクション抽出
            hc_sections = get_human_capital_sections(report)

            # ファンド型判定（pdf_poc_extract の is_fund_report を使用）
            # full_text は extract_report 内部で処理済みのためセクションテキストを結合
            combined_text = "\n".join(s.text for s in report.sections)
            # ファンド判定は冒頭テキストで行う（is_fund_report は head=4000文字）
            # company_c: 基準価額・受益者 → is_fund=True が期待値
            is_fund = is_fund_report(combined_text)

            total_sections = len(report.sections)
            hc_count = len(hc_sections)
            baseline = _BASELINE.get(name, {})
            baseline_sections = baseline.get("sections", -1)
            baseline_fund = baseline.get("is_fund", None)

            # 差分（基準値との乖離）
            section_diff = total_sections - baseline_sections if baseline_sections >= 0 else None
            fund_match = (is_fund == baseline_fund) if baseline_fund is not None else None

            row = {
                "name": name,
                "total_sections": total_sections,
                "hc_sections": hc_count,
                "is_fund": is_fund,
                "elapsed": elapsed,
                "error": None,
                "baseline_sections": baseline_sections,
                "section_diff": section_diff,
                "fund_match": fund_match,
                "company_name": report.company_name,
            }
            results.append(row)
            status = "✓ファンド" if is_fund else f"✓ sec={total_sections} hc={hc_count}"
            print(f"{elapsed:.3f}s  {status}")

        except Exception as e:
            elapsed = time.perf_counter() - t0
            errors.append({"name": name, "error": str(e), "elapsed": elapsed})
            results.append({
                "name": name,
                "total_sections": -1,
                "hc_sections": -1,
                "is_fund": None,
                "elapsed": elapsed,
                "error": str(e),
                "baseline_sections": _BASELINE.get(name, {}).get("sections", -1),
                "section_diff": None,
                "fund_match": None,
                "company_name": "",
            })
            print(f"ERROR: {e}")

    print()
    return {"results": results, "errors": errors}


def compute_metrics(data: dict) -> dict:
    """検証指標を集計する"""
    results = data["results"]
    errors = data["errors"]

    total = len(results)
    error_count = len(errors)
    ok_results = [r for r in results if r["error"] is None]

    # 処理時間
    times = [r["elapsed"] for r in ok_results]
    avg_time = sum(times) / len(times) if times else 0
    max_time = max(times) if times else 0
    min_time = min(times) if times else 0

    # ファンド型判定
    fund_expected_only_c = all(
        r["fund_match"] for r in ok_results if r["fund_match"] is not None
    )
    company_c_result = next((r for r in results if r["name"] == "company_c.pdf"), None)
    c_is_fund = company_c_result["is_fund"] if company_c_result else None

    # 非ファンド9社で誤検知なし
    non_fund_false_positives = [
        r["name"] for r in ok_results
        if r["is_fund"] and r["name"] != "company_c.pdf"
    ]

    # 人的資本セクション抽出率（非ファンド事業会社）
    business_results = [r for r in ok_results if not r["is_fund"]]
    hc_detected = [r for r in business_results if r["hc_sections"] > 0]
    hc_rate = len(hc_detected) / len(business_results) if business_results else 0

    # セクション数の基準値との乖離
    section_diffs = [
        abs(r["section_diff"]) for r in ok_results
        if r["section_diff"] is not None and not r["is_fund"]
    ]
    avg_section_diff = sum(section_diffs) / len(section_diffs) if section_diffs else 0

    return {
        "total": total,
        "error_count": error_count,
        "avg_time": avg_time,
        "max_time": max_time,
        "min_time": min_time,
        "baseline_avg_time": _BASELINE_AVG_TIME,
        "time_ratio": avg_time / _BASELINE_AVG_TIME if _BASELINE_AVG_TIME > 0 else 0,
        "c_is_fund": c_is_fund,
        "fund_expected_only_c": fund_expected_only_c,
        "non_fund_false_positives": non_fund_false_positives,
        "hc_rate": hc_rate,
        "hc_detected_count": len(hc_detected),
        "business_count": len(business_results),
        "avg_section_diff": avg_section_diff,
    }


def print_summary(data: dict, metrics: dict) -> None:
    """コンソールにサマリーを出力"""
    results = data["results"]
    print("=" * 70)
    print("【M1精度検証サマリー】")
    print("=" * 70)

    # C1: エラー件数
    err_mark = "✅" if metrics["error_count"] == 0 else "❌"
    print(f"{err_mark} C1 エラー件数: {metrics['error_count']}/{metrics['total']}社")

    # C2: 人的資本抽出率
    hc_mark = "✅" if metrics["hc_rate"] >= 0.8 else "❌"
    print(f"{hc_mark} C2 人的資本抽出率: {metrics['hc_detected_count']}/{metrics['business_count']}社"
          f" ({metrics['hc_rate']:.1%}) [期待: ≥80%]")

    # C3: ファンド型判定
    fund_mark = "✅" if metrics["c_is_fund"] and not metrics["non_fund_false_positives"] else "❌"
    fp_str = f" | 誤検知: {metrics['non_fund_false_positives']}" if metrics["non_fund_false_positives"] else ""
    print(f"{fund_mark} C3 ファンド型判定: company_c={metrics['c_is_fund']}{fp_str}")

    # C4: 処理時間
    time_mark = "✅" if metrics["avg_time"] <= 2.0 else "❌"
    ratio_str = f" (PoC比 {metrics['time_ratio']:.2f}x)"
    print(f"{time_mark} C4 平均処理時間: {metrics['avg_time']:.3f}秒/社"
          f"{ratio_str} [期待: ≤2.0秒]")
    print(f"     最速: {metrics['min_time']:.3f}秒 / 最遅: {metrics['max_time']:.3f}秒")
    print()

    print("【社別詳細】")
    print(f"{'ファイル':<15} {'企業名':<20} {'sec数':>5} {'基準':>5} {'差':>4} {'HC':>4} {'ファンド':>7} {'時間':>6}")
    print("-" * 75)
    for r in results:
        if r["error"]:
            print(f"{r['name']:<15} ERROR: {r['error'][:40]}")
            continue
        name_s = r["name"].replace(".pdf", "")
        co_name = r["company_name"][:18] if r["company_name"] else "—"
        diff_s = f"{r['section_diff']:+d}" if r["section_diff"] is not None else "—"
        fund_s = "✓" if r["is_fund"] else "—"
        print(f"{name_s:<15} {co_name:<20} {r['total_sections']:>5} "
              f"{r['baseline_sections']:>5} {diff_s:>4} {r['hc_sections']:>4} "
              f"{fund_s:>7} {r['elapsed']:>5.3f}s")


def write_markdown_report(data: dict, metrics: dict) -> None:
    """10_Research/m1_precision_report.md に結果を書き出す"""
    results = data["results"]
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    c1_ok = metrics["error_count"] == 0
    c2_ok = metrics["hc_rate"] >= 0.8
    c3_ok = metrics["c_is_fund"] and not metrics["non_fund_false_positives"]
    c4_ok = metrics["avg_time"] <= 2.0

    def ck(ok: bool) -> str:
        return "✅" if ok else "❌"

    lines = [
        "# M1 PDF精度検証レポート（10社）",
        "",
        f"> 実施日: {now}",
        f"> 実施者: 足軽3号（subtask_073a3_disclosure_m1_precision）",
        f"> 使用モード: USE_MOCK_LLM=true（実PDF・M1実処理）",
        "",
        "---",
        "",
        "## 完了条件チェック",
        "",
        f"| 条件 | 結果 | 詳細 |",
        f"|------|------|------|",
        f"| C1: エラーなし | {ck(c1_ok)} | {metrics['error_count']}/{metrics['total']}社エラー |",
        f"| C2: 人的資本抽出率≥80% | {ck(c2_ok)} | {metrics['hc_detected_count']}/{metrics['business_count']}社 ({metrics['hc_rate']:.1%}) |",
        f"| C3: ファンド型判定 company_c のみ | {ck(c3_ok)} | company_c is_fund={metrics['c_is_fund']} 誤検知={metrics['non_fund_false_positives'] or 'なし'} |",
        f"| C4: 平均処理時間≤2.0秒 | {ck(c4_ok)} | {metrics['avg_time']:.3f}秒/社（PoC比{metrics['time_ratio']:.2f}x） |",
        "",
        "---",
        "",
        "## 社別詳細結果",
        "",
        "| ファイル | 企業名 | セクション数 | PoC基準 | 差分 | 人的資本sec | ファンド型 | 処理時間(秒) |",
        "|----------|--------|------------|---------|------|------------|----------|------------|",
    ]

    for r in results:
        if r["error"]:
            lines.append(f"| {r['name']} | ERROR | — | {r['baseline_sections']} | — | — | — | {r['elapsed']:.3f} |")
            continue
        diff_s = f"{r['section_diff']:+d}" if r["section_diff"] is not None else "—"
        fund_s = "✓（ファンド）" if r["is_fund"] else "—"
        fm_s = "✅" if r["fund_match"] else ("❌" if r["fund_match"] is False else "—")
        lines.append(
            f"| {r['name'].replace('.pdf','')} "
            f"| {r['company_name'][:20] or '—'} "
            f"| {r['total_sections']} "
            f"| {r['baseline_sections']} "
            f"| {diff_s} "
            f"| {r['hc_sections']} "
            f"| {fund_s} {fm_s} "
            f"| {r['elapsed']:.3f} |"
        )

    lines += [
        "",
        "---",
        "",
        "## 処理時間サマリー",
        "",
        f"| 指標 | 今回 | PoC実績 | 比率 |",
        f"|------|------|--------|------|",
        f"| 平均時間（全10社） | {metrics['avg_time']:.3f}秒 | {metrics['baseline_avg_time']:.3f}秒 | {metrics['time_ratio']:.2f}x |",
        f"| 最速 | {metrics['min_time']:.3f}秒 | — | — |",
        f"| 最遅 | {metrics['max_time']:.3f}秒 | — | — |",
        "",
        "---",
        "",
        "## ファンド型判定詳細",
        "",
        f"- company_c is_fund: **{metrics['c_is_fund']}**（期待値: True）",
        f"- 誤検知（非ファンドなのに is_fund=True）: **{metrics['non_fund_false_positives'] or 'なし'}**",
        f"- 判定一致率: {'全社一致' if metrics['fund_expected_only_c'] else '不一致あり'}",
        "",
        "---",
        "",
        "## 人的資本セクション抽出詳細",
        "",
        f"- 事業会社（非ファンド）: {metrics['business_count']}社",
        f"- 人的資本sec≥1件: {metrics['hc_detected_count']}社 ({metrics['hc_rate']:.1%})",
        f"- セクション数の平均乖離（PoC比）: {metrics['avg_section_diff']:.1f}件",
        "",
        "---",
        "",
        "*本レポートは m1_precision_check.py により自動生成*",
    ]

    _REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"レポート保存: {_REPORT_PATH}")


if __name__ == "__main__":
    data = run_precision_check()
    metrics = compute_metrics(data)
    print_summary(data, metrics)
    write_markdown_report(data, metrics)
    print()
    # 全完了条件チェック
    all_ok = (
        metrics["error_count"] == 0
        and metrics["hc_rate"] >= 0.8
        and metrics["c_is_fund"]
        and not metrics["non_fund_false_positives"]
        and metrics["avg_time"] <= 2.0
    )
    print(f"{'✅ 全完了条件クリア' if all_ok else '⚠️  一部条件未達'}")
    sys.exit(0 if all_ok else 1)
