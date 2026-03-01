"""
run_e2e.py
==========
disclosure-multiagent Phase 1-M5-3: E2Eパイプライン実行スクリプト

実装者: 足軽4 subtask_063a13
作成日: 2026-02-27

使用方法:
    # USE_MOCK_LLM=true（実APIキー不要）で実行
    cd scripts/
    USE_MOCK_LLM=true python3 run_e2e.py \\
        "../10_Research/samples/company_a.pdf" \\
        --company-name "サンプル社A" \\
        --fiscal-year 2025 \\
        --level 竹

    # 出力ファイルを明示指定
    USE_MOCK_LLM=true python3 run_e2e.py \\
        "/path/to/yuho.pdf" \\
        --output "/path/to/report.md"

パイプライン:
    M1(PDF解析) → M2(法令取得) → M3(ギャップ分析) → M4(提案生成) → M5(レポート統合)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# scriptsディレクトリをパスに追加（相対import対応）
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# ─────────────────────────────────────────────────────────
# 各エージェントのインポート（改変禁止: importのみ）
# ─────────────────────────────────────────────────────────

from m1_pdf_agent import extract_report  # noqa: E402
from m2_law_agent import load_law_context  # noqa: E402
from m3_gap_analysis_agent import (  # noqa: E402
    analyze_gaps,
    GapItem as M3GapItem,
)
from m4_proposal_agent import (  # noqa: E402
    generate_proposals,
    GapItem as M4GapItem,
    ProposalSet,
)
from m5_report_agent import generate_report, _m3_gap_to_m4_gap  # noqa: E402

# デフォルト出力ディレクトリ
_DEFAULT_REPORTS_DIR = _SCRIPTS_DIR / "reports"


# ─────────────────────────────────────────────────────────
# E2Eパイプライン関数
# ─────────────────────────────────────────────────────────

def run_pipeline(
    pdf_path: str,
    company_name: str = "",
    fiscal_year: int = 2025,
    fiscal_month_end: int = 3,
    level: str = "竹",
) -> str:
    """
    M1→M2→M3→M4→M5 のE2Eパイプラインを実行してMarkdownレポートを返す。

    Args:
        pdf_path:          PDFファイルパス（ハードコード禁止: 引数で受け取る）
        company_name:      企業名（省略時はM1が自動推定）
        fiscal_year:       対象事業年度（例: 2025）
        fiscal_month_end:  決算月（デフォルト: 3月）
        level:             提案レベル（"松" / "竹" / "梅"）

    Returns:
        str: Markdown形式のレポート

    Raises:
        FileNotFoundError: PDFファイルが存在しない場合
    """
    logger = logging.getLogger(__name__)

    # ── STEP 1: M1 PDF解析 ──────────────────────────────
    logger.info("[M1] PDF解析開始: %s", pdf_path)
    structured_report = extract_report(
        pdf_path=pdf_path,
        company_name=company_name,
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
    )
    company_display = structured_report.company_name or company_name or "分析対象企業"
    logger.info(
        "[M1] PDF解析完了: 会社=%s, セクション数=%d",
        company_display,
        len(structured_report.sections),
    )

    # ── STEP 2: M2 法令取得 ──────────────────────────────
    logger.info("[M2] 法令コンテキスト取得: fiscal_year=%d, month=%d", fiscal_year, fiscal_month_end)
    law_context = load_law_context(
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
    )
    logger.info(
        "[M2] 法令取得完了: 適用エントリ=%d件, as_of=%s",
        len(law_context.applicable_entries),
        law_context.law_yaml_as_of,
    )
    if law_context.warnings:
        for w in law_context.warnings:
            logger.warning("[M2] %s", w)

    # ── STEP 3: M3 ギャップ分析（USE_MOCK_LLM環境変数で制御）──────────
    _use_mock = os.environ.get("USE_MOCK_LLM", "").lower() in ("true", "1")
    logger.info("[M3] ギャップ分析開始（use_mock=%s）", _use_mock)
    gap_result = analyze_gaps(
        report=structured_report,
        law_context=law_context,
        use_mock=_use_mock,
    )
    has_gap_count = sum(1 for g in gap_result.gaps if g.has_gap)
    logger.info(
        "[M3] ギャップ分析完了: total_gaps=%d, has_gap=%d件",
        gap_result.summary.total_gaps,
        has_gap_count,
    )

    # ── STEP 4: M4 提案生成（USE_MOCK_LLM対応）──────────
    logger.info("[M4] 提案生成開始（has_gap=%d件）", has_gap_count)
    proposals: list[ProposalSet] = []
    for gap in gap_result.gaps:
        if gap.has_gap:
            m4_gap = _m3_gap_to_m4_gap(gap)
            ps = generate_proposals(m4_gap)
            proposals.append(ps)
    logger.info("[M4] 提案生成完了: %d件", len(proposals))

    # ── STEP 5: M5 レポート統合 ──────────────────────────
    logger.info("[M5] レポート生成開始: level=%s", level)
    report_md = generate_report(
        structured_report=structured_report,
        law_context=law_context,
        gap_result=gap_result,
        proposal_set=proposals,
        level=level,
    )
    logger.info("[M5] レポート生成完了: %d文字", len(report_md))

    return report_md


def run_batch(
    pdf_paths: list[str],
    company_names: list[str] | None = None,
    fiscal_year: int = 2025,
    fiscal_month_end: int = 3,
    level: str = "竹",
) -> list[dict]:
    """
    複数PDFの一括処理（バッチモード）。
    1社でエラーが発生しても他社の処理を続行する。

    Args:
        pdf_paths:      PDFパスのリスト
        company_names:  企業名リスト（省略時は空文字・pdf_pathsと同順）
        fiscal_year:    対象事業年度
        fiscal_month_end: 決算月
        level:          提案レベル（"松" / "竹" / "梅"）

    Returns:
        各社の処理結果 dict のリスト:
            pdf_path    : 入力PDFパス
            company_name: 企業名
            status      : "ok" | "error"
            report_md   : 生成されたMarkdownレポート（エラー時は空文字）
            elapsed_sec : 処理時間（秒）
            error       : エラーメッセージ（成功時はNone）
    """
    logger = logging.getLogger(__name__)
    results: list[dict] = []

    for i, pdf_path in enumerate(pdf_paths):
        company = (company_names[i] if company_names and i < len(company_names) else "")
        logger.info("[BATCH] (%d/%d) 処理開始: %s", i + 1, len(pdf_paths), pdf_path)
        start = time.monotonic()

        try:
            report_md = run_pipeline(
                pdf_path=pdf_path,
                company_name=company,
                fiscal_year=fiscal_year,
                fiscal_month_end=fiscal_month_end,
                level=level,
            )
            elapsed = round(time.monotonic() - start, 3)
            logger.info("[BATCH] (%d/%d) 完了: elapsed=%.3f秒", i + 1, len(pdf_paths), elapsed)
            results.append({
                "pdf_path": str(pdf_path),
                "company_name": company,
                "status": "ok",
                "report_md": report_md,
                "elapsed_sec": elapsed,
                "error": None,
            })
        except Exception as exc:
            elapsed = round(time.monotonic() - start, 3)
            logger.error(
                "[BATCH] (%d/%d) エラー（続行）: %s → %s",
                i + 1, len(pdf_paths), pdf_path, exc,
            )
            results.append({
                "pdf_path": str(pdf_path),
                "company_name": company,
                "status": "error",
                "report_md": "",
                "elapsed_sec": elapsed,
                "error": str(exc),
            })

    ok_count = sum(1 for r in results if r["status"] == "ok")
    logger.info("[BATCH] 全処理完了: %d/%d成功", ok_count, len(results))
    return results


def save_report(
    report_md: str,
    output_path: str,
) -> Path:
    """
    Markdownレポートをファイルに保存する。
    出力ディレクトリが存在しない場合は自動作成する。

    Args:
        report_md:   Markdown文字列
        output_path: 保存先パス

    Returns:
        保存したファイルの Path
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report_md)
    return out


# ─────────────────────────────────────────────────────────
# CLI エントリポイント
# ─────────────────────────────────────────────────────────

def _build_default_output_path(
    pdf_path: str,
    company_name: str,
    fiscal_year: int,
) -> Path:
    """デフォルト出力パスを生成する（ハードコードなし）"""
    pdf_stem = Path(pdf_path).stem
    company_slug = company_name.replace("　", "_").replace(" ", "_")[:20] if company_name else pdf_stem
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{company_slug}_{fiscal_year}_{ts}.md"
    return _DEFAULT_REPORTS_DIR / filename


def main() -> int:
    """コマンドラインエントリポイント"""
    parser = argparse.ArgumentParser(
        description="disclosure-multiagent E2Eパイプライン実行スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例（単一PDF）:
  USE_MOCK_LLM=true python3 run_e2e.py ../10_Research/samples/company_a.pdf \\
      --company-name "サンプル社A" --fiscal-year 2025 --level 竹

例（バッチ処理）:
  USE_MOCK_LLM=true python3 run_e2e.py --batch \\
      ../10_Research/samples/company_a.pdf \\
      ../10_Research/samples/company_b.pdf \\
      --output-json batch_result.json
        """,
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        default="",
        help="解析するPDFファイルのパス（--batch 使用時は省略可）",
    )
    parser.add_argument(
        "--batch",
        nargs="+",
        metavar="PDF",
        default=None,
        help="複数PDFを一括処理（スペース区切りで複数指定）",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="バッチ処理結果をJSONファイルに保存するパス",
    )
    parser.add_argument(
        "--company-name",
        default="",
        help="企業名（省略時はPDFから自動推定）",
    )
    parser.add_argument(
        "--fiscal-year",
        type=int,
        default=2025,
        help="対象事業年度 (デフォルト: 2025)",
    )
    parser.add_argument(
        "--fiscal-month-end",
        type=int,
        default=3,
        help="決算月 (デフォルト: 3)",
    )
    parser.add_argument(
        "--level",
        choices=["松", "竹", "梅"],
        default="竹",
        help="提案レベル (デフォルト: 竹)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="出力ファイルパス（省略時は reports/report_{company}_{year}_{ts}.md）",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="標準出力にMarkdownを表示（ファイル保存と併用可）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="ログレベル (デフォルト: INFO)",
    )

    args = parser.parse_args()

    # ロギング設定
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    # USE_MOCK_LLM の確認（警告のみ: 未設定でもM4は自動モックになる）
    if os.environ.get("USE_MOCK_LLM", "").lower() != "true":
        logger.warning(
            "USE_MOCK_LLM が設定されていません。"
            "実LLM（ANTHROPIC_API_KEY）が使用されます。"
            "モックで実行するには: USE_MOCK_LLM=true python3 run_e2e.py ..."
        )

    # ─── バッチモード ─────────────────────────────────────────
    if args.batch:
        batch_results = run_batch(
            pdf_paths=args.batch,
            fiscal_year=args.fiscal_year,
            fiscal_month_end=args.fiscal_month_end,
            level=args.level,
        )

        ok_count = sum(1 for r in batch_results if r["status"] == "ok")
        err_count = len(batch_results) - ok_count
        print(f"\n✓ バッチ処理完了: {ok_count}件成功 / {err_count}件エラー", file=sys.stderr)

        # 成功分のレポートを保存
        for r in batch_results:
            if r["status"] == "ok":
                out = _build_default_output_path(r["pdf_path"], r["company_name"], args.fiscal_year)
                saved = save_report(r["report_md"], str(out))
                logger.info("レポート保存: %s (%.3f秒)", saved, r["elapsed_sec"])
                print(f"  → {saved} ({r['elapsed_sec']:.3f}秒)", file=sys.stderr)
            else:
                logger.warning("スキップ（エラー）: %s → %s", r["pdf_path"], r["error"])
                print(f"  ✗ {r['pdf_path']}: {r['error']}", file=sys.stderr)

        # JSON出力
        if args.output_json:
            json_out = Path(args.output_json)
            json_out.parent.mkdir(parents=True, exist_ok=True)
            # report_md はJSONに含めると大きくなるため文字数のみ記録
            summary = [
                {k: (len(v) if k == "report_md" else v) if k == "report_md" else v
                 for k, v in r.items()}
                for r in batch_results
            ]
            with open(json_out, "w", encoding="utf-8") as f:
                json.dump(
                    {"total": len(batch_results), "ok": ok_count, "error": err_count, "results": summary},
                    f, ensure_ascii=False, indent=2,
                )
            logger.info("JSON出力保存: %s", json_out)
            print(f"  → JSON: {json_out}", file=sys.stderr)

        return 0 if err_count == 0 else 4

    # ─── 単一PDFモード ────────────────────────────────────────
    if not args.pdf_path:
        parser.error("pdf_path か --batch のいずれかを指定してください")

    try:
        report_md = run_pipeline(
            pdf_path=args.pdf_path,
            company_name=args.company_name,
            fiscal_year=args.fiscal_year,
            fiscal_month_end=args.fiscal_month_end,
            level=args.level,
        )
    except FileNotFoundError as e:
        logger.error("PDFファイルが見つかりません: %s", e)
        return 1
    except RuntimeError as e:
        logger.error("パイプライン実行エラー: %s", e)
        return 2
    except Exception as e:
        logger.error("予期しないエラー: %s", e, exc_info=True)
        return 3

    # 標準出力
    if args.stdout:
        print(report_md)

    # ファイル保存
    output_path = args.output or str(
        _build_default_output_path(args.pdf_path, args.company_name, args.fiscal_year)
    )
    saved = save_report(report_md, output_path)
    logger.info("レポート保存完了: %s", saved)
    print(f"\n✓ レポート生成完了: {saved}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
