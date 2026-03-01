"""
m5_report_agent.py
==================
disclosure-multiagent Phase 1-M5: レポート統合エージェント

設計書: report_integration_design.md (足軽4 subtask_063a6)
実装者: 足軽3 subtask_063a10
作成日: 2026-02-27

使用方法:
    python3 m5_report_agent.py

E2Eパイプライン確認:
    python3 -c "from m5_report_agent import pipeline_mock; print(pipeline_mock()[:1000])"

入力:
    structured_report: StructuredReport (M1出力)
    law_context:       LawContext        (M2出力)
    gap_result:        GapAnalysisResult (M3出力)
    proposal_set:      list[ProposalSet] (M4出力 — gap_id ごとの ProposalSet リスト)
    level:             str               ("松" / "竹" / "梅")

出力:
    str: 完全な Markdown レポート（設計書 Section 1-3 + 要件定義 Section 6.2 準拠）
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────────────────
# M3 インポート (StructuredReport / LawContext / GapAnalysisResult 等)
# ─────────────────────────────────────────────────────────

_scripts_dir = Path(__file__).parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from m3_gap_analysis_agent import (  # noqa: E402
    StructuredReport,
    LawContext,
    GapAnalysisResult,
    GapItem as M3GapItem,
    NoGapItem,
    GapSummary,
    GapMetadata,
    LawEntry,
    SectionData,
    TableData,
    calc_law_ref_period,
    analyze_gaps,
    _build_mock_report,
    _build_mock_law_context,
)

# ─────────────────────────────────────────────────────────
# M4 インポート (ProposalSet / GapItem / generate_proposals 等)
# ─────────────────────────────────────────────────────────

from m4_proposal_agent import (  # noqa: E402
    ProposalSet,
    Proposal,
    QualityCheckResult,
    GapItem as M4GapItem,
    generate_proposals,
)

# ─────────────────────────────────────────────────────────
# M8 インポート（F-08 複数年度比較。省略可能）
# ─────────────────────────────────────────────────────────

try:
    from m8_multiyear_agent import YearDiff  # noqa: E402
except ImportError:
    YearDiff = None  # type: ignore[assignment,misc]

# ─────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────

LEVEL_DESCRIPTIONS: dict[str, str] = {
    "松": "充実開示向け",
    "竹": "スタンダード実務向け",
    "梅": "最小限対応向け",
}

CHANGE_TYPE_ORDER: dict[str, int] = {
    "追加必須": 0,
    "修正推奨": 1,
    "参考": 2,
}

# ─────────────────────────────────────────────────────────
# 内部ユーティリティ
# ─────────────────────────────────────────────────────────


def _collect_unconfirmed_urls(gaps: list[M3GapItem]) -> list[str]:
    """source_confirmed=False の gap から reference_url を収集する（重複除去前）"""
    return [
        g.reference_url
        for g in gaps
        if not g.source_confirmed and g.reference_url
    ]


def _sort_gaps(gaps: list[M3GapItem]) -> list[M3GapItem]:
    """change_type でソート: 追加必須 → 修正推奨 → 参考"""
    return sorted(gaps, key=lambda g: CHANGE_TYPE_ORDER.get(g.change_type, 9))


def _build_disclaimer_header() -> str:
    """ヘッダー免責文言を生成する（設計書 Section 1-3 準拠）"""
    return (
        "> **但し書き・免責事項**\n"
        "> 本レポートは参考情報です。実務の進め方や記載例を提示しますが、\n"
        "> 最終判断は弁護士・公認会計士等の専門家にご依頼ください。\n"
        "> 本システムの出力に基づく開示内容について、一切の責任を負いかねます。"
    )


def _build_disclaimer_detail(law_yaml_as_of: str) -> str:
    """詳細免責文言を生成する（law_yaml_as_of は動的に埋め込む。ハードコード禁止）"""
    items = [
        f"本レポートは、入力された有価証券報告書（公開済み）と"
        f"法令情報YAML（取得日: {law_yaml_as_of}）を基に自動生成されたものです。",
        "",
        "- 本システムは「参考情報の提供」を目的とし、"
        "開示内容の正確性を保証するものではありません",
        "- 法令の解釈・適用については、公認会計士・弁護士等の専門家にご確認ください",
        "- YAML情報の更新漏れにより、最新の法令改正が反映されていない場合があります",
        "- 本レポートを利用した結果生じた損害について、開発者は責任を負いません",
    ]
    return "\n".join(items)


# ─────────────────────────────────────────────────────────
# メイン関数: generate_report
# ─────────────────────────────────────────────────────────


def generate_report(
    structured_report: StructuredReport,
    law_context: LawContext,
    gap_result: GapAnalysisResult,
    proposal_set: "list[ProposalSet]",
    level: str,
    year_diff: "Optional[YearDiff]" = None,
) -> str:
    """
    全エージェントの出力をMarkdownレポートに統合する。

    Args:
        structured_report: M1出力（企業名・会計年度・決算月 等）
        law_context:        M2出力（適用法令エントリ・law_yaml_as_of）
        gap_result:         M3出力（ギャップ分析結果）
        proposal_set:       M4出力（gap_id 別 ProposalSet のリスト）
        level:              提案レベル ("松" / "竹" / "梅")
        year_diff:          M8出力（複数年度比較結果。省略可能）
                            指定時は Section 6「複数年度比較」を出力する

    Returns:
        str: 完全な Markdown レポート（設計書 Section 1-3 + 要件定義 Section 6.2 準拠）
    """
    company = structured_report.company_name or "分析対象企業"
    law_ref_start, law_ref_end = calc_law_ref_period(
        gap_result.fiscal_year,
        structured_report.fiscal_month_end,
    )
    level_desc = LEVEL_DESCRIPTIONS.get(level, level)
    law_yaml_as_of = gap_result.law_yaml_as_of or "取得日不明（確認推奨）"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # has_gap=True のギャップのみ対象
    has_gap_items = [g for g in gap_result.gaps if g.has_gap]

    # source_confirmed=False URL の収集（ヘッダー警告バナー用）
    unconfirmed_urls = sorted(set(_collect_unconfirmed_urls(has_gap_items)))

    # change_type でソート（追加必須→修正推奨→参考）
    sorted_gaps = _sort_gaps(has_gap_items)

    # gap_id → ProposalSet マッピング
    proposal_map: dict[str, ProposalSet] = {ps.gap_id: ps for ps in proposal_set}

    lines: list[str] = []

    # ─── ヘッダー ─────────────────────────────────────────────
    lines.append(f"# 開示変更レポート — {company} 有価証券報告書")
    lines.append("")
    lines.append(_build_disclaimer_header())
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"- **分析対象**: {gap_result.fiscal_year}年度有報"
        f"（公開済み有報を入力とした次期版シミュレート）"
    )
    lines.append(f"- **法令参照期間**: {law_ref_start} 〜 {law_ref_end}")
    lines.append(f"- **提案レベル**: {level}（{level_desc}）")
    lines.append(f"- **法令情報取得日**: {law_yaml_as_of}")
    lines.append(f"- **レポート生成日時**: {generated_at}")
    lines.append("")

    # source_confirmed=False 警告バナー（ヘッダー — 1箇所目）
    if unconfirmed_urls:
        lines.append(
            "> ⚠️ **要確認**: 一部の法令URLは実アクセス未確認です"
            "（source_confirmed: false）。"
        )
        lines.append("> 参照前に以下のURLを直接確認してください:")
        for url in unconfirmed_urls:
            lines.append(f">   - {url}")
        lines.append("")

    # ─── Section 1: 変更箇所サマリ ───────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## 1. 変更箇所サマリ")
    lines.append("")
    by_type = gap_result.summary.by_change_type
    total = gap_result.summary.total_gaps
    lines.append("| 変更種別 | 件数 |")
    lines.append("|----------|------|")
    for ct in ["追加必須", "修正推奨", "参考"]:
        lines.append(f"| {ct} | {by_type.get(ct, 0)} |")
    lines.append(f"| **合計** | **{total}** |")
    lines.append("")

    # ─── Section 2: セクション別の変更提案 ─────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## 2. セクション別の変更提案")
    lines.append("")

    for idx, gap in enumerate(sorted_gaps, start=1):
        ps = proposal_map.get(gap.gap_id)
        lines.append(f"### 2.{idx}. {gap.section_heading}")
        lines.append("")
        lines.append(f"- **変更種別**: {gap.change_type}")
        lines.append(f"- **対象項目**: {gap.disclosure_item}")
        lines.append(f"- **根拠**: {gap.reference_law_title}")
        lines.append(f"  - 出典: [{gap.reference_url}]({gap.reference_url})")

        # source_confirmed=False 警告（ギャップ詳細内 — 2箇所目）
        if not gap.source_confirmed:
            warning_text = (
                gap.source_warning
                if gap.source_warning
                else "このURLは実アクセス未確認です。参照前に確認してください。"
            )
            lines.append(f"  > ⚠️ {warning_text}")

        lines.append(f"- **根拠ID**: {gap.reference_law_id}")
        if gap.evidence_hint:
            lines.append(f"- **検出根拠**: {gap.evidence_hint}")
        lines.append("")

        if ps:
            proposal = ps.get_proposal(level)
            lines.append(f"#### {level}レベルの提案文")
            lines.append("")
            lines.append(f"> {proposal.text}")
            lines.append("")
            if proposal.quality.warnings:
                for w in proposal.quality.warnings:
                    lines.append(f"> ⚠️ {w}")
                lines.append("")

        lines.append("---")
        lines.append("")

    # ─── Section 3: 未変更項目（has_gap=False） ─────────────────
    lines.append("## 3. 未変更項目（対応済み）")
    lines.append("")
    if gap_result.no_gap_items:
        for item in gap_result.no_gap_items:
            hint = getattr(item, "evidence_hint", "") or ""
            lines.append(f"- ✅ **{item.disclosure_item}** ({item.reference_law_id})")
            if hint:
                lines.append(f"  - {hint}")
    else:
        lines.append("（未変更項目なし）")
    lines.append("")

    # ─── Section 4: 参照した法令・ガイダンス一覧 ─────────────────
    lines.append("---")
    lines.append("")
    lines.append("## 4. 参照した法令・ガイダンス一覧")
    lines.append("")
    lines.append("| ID | 名称 | 変更種別 | 出典 |")
    lines.append("|----|------|----------|------|")
    for entry in law_context.applicable_entries:
        confirmed_mark = "" if entry.source_confirmed else " ⚠️未確認"
        lines.append(
            f"| {entry.id} | {entry.title} | {entry.change_type}"
            f" | [{entry.source}]({entry.source}){confirmed_mark} |"
        )
    lines.append("")

    # ─── Section 5: 免責事項（詳細） ─────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## 5. 免責事項")
    lines.append("")
    lines.append(_build_disclaimer_detail(law_yaml_as_of))
    lines.append("")

    # ─── Section 6: 複数年度比較（M8出力・省略可能） ───────────────
    if year_diff is not None:
        lines.append("---")
        lines.append("")
        lines.append(
            f"## 6. 複数年度比較"
            f"（{year_diff.fiscal_year_from}年度 → {year_diff.fiscal_year_to}年度）"
        )
        lines.append("")
        lines.append(f"> **比較サマリ**: {year_diff.summary}")
        lines.append("")

        # 追加セクション
        lines.append(
            f"### 6.1 追加セクション（{year_diff.fiscal_year_to}年度 新規）"
            f" — {len(year_diff.added_sections)}件"
        )
        lines.append("")
        if year_diff.added_sections:
            for sec in year_diff.added_sections:
                lines.append(f"- ➕ **{sec.heading}**")
                if sec.text:
                    preview = sec.text[:120].replace("\n", " ")
                    lines.append(f"  > {preview}{'...' if len(sec.text) > 120 else ''}")
        else:
            lines.append("（追加セクションなし）")
        lines.append("")

        # 削除セクション
        lines.append(
            f"### 6.2 削除セクション（{year_diff.fiscal_year_from}年度 から削除）"
            f" — {len(year_diff.removed_sections)}件"
        )
        lines.append("")
        if year_diff.removed_sections:
            for sec in year_diff.removed_sections:
                lines.append(f"- ➖ **{sec.heading}**")
                if sec.text:
                    preview = sec.text[:120].replace("\n", " ")
                    lines.append(f"  > {preview}{'...' if len(sec.text) > 120 else ''}")
        else:
            lines.append("（削除セクションなし）")
        lines.append("")

        # 変更セクション
        lines.append(
            f"### 6.3 変更セクション（本文変化率 > 20%）"
            f" — {len(year_diff.changed_sections)}件"
        )
        lines.append("")
        if year_diff.changed_sections:
            for sec in year_diff.changed_sections:
                lines.append(f"- ✏️ **{sec.heading}**（{year_diff.fiscal_year_to}年度版）")
                if sec.text:
                    preview = sec.text[:120].replace("\n", " ")
                    lines.append(f"  > {preview}{'...' if len(sec.text) > 120 else ''}")
        else:
            lines.append("（内容変更セクションなし）")
        lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# M3GapItem → M4GapItem 変換
# ─────────────────────────────────────────────────────────


def _m3_gap_to_m4_gap(gap: M3GapItem) -> M4GapItem:
    """
    M3のGapItemをM4のGapItemに変換する。

    M3とM4はほぼ同じフィールドを持つが、has_gap の型が異なる
    （M3: Optional[bool]、M4: bool）ため変換が必要。
    """
    return M4GapItem(
        gap_id=gap.gap_id,
        section_id=gap.section_id,
        section_heading=gap.section_heading,
        change_type=gap.change_type,
        has_gap=bool(gap.has_gap),
        disclosure_item=gap.disclosure_item,
        reference_law_id=gap.reference_law_id,
        reference_law_title=gap.reference_law_title,
        reference_url=gap.reference_url,
        source_confirmed=gap.source_confirmed,
        source_warning=gap.source_warning,
        gap_description=getattr(gap, "gap_description", None),
        evidence_hint=getattr(gap, "evidence_hint", None),
        law_summary=None,
    )


# ─────────────────────────────────────────────────────────
# E2Eパイプライン確認用モック関数
# ─────────────────────────────────────────────────────────


def pipeline_mock(
    company_name: str = "サンプル株式会社",
    fiscal_year: int = 2025,
    level: str = "竹",
) -> str:
    """
    E2Eパイプライン確認用モック関数。
    M3/M4のモック関数を使用してフルパイプライン（M1〜M5）を検証する。

    Args:
        company_name: 企業名（モックデータに上書き）
        fiscal_year:  対象年度（3月決算想定）
        level:        提案レベル ("松" / "竹" / "梅")

    Returns:
        str: 完全な Markdown レポート

    Notes:
        ANTHROPIC_API_KEY 未設定時は自動的にモックモードで動作する。
        USE_MOCK_LLM=true を設定すると明示的にモックモードを強制できる。
    """
    # Step 1: モックデータ構築（M3の _build_mock_* 使用）
    structured_report = _build_mock_report()
    structured_report.company_name = company_name
    structured_report.fiscal_year = fiscal_year

    law_context = _build_mock_law_context()
    law_context.fiscal_year = fiscal_year

    # Step 2: M3 ギャップ分析（モックモード: use_mock=True）
    gap_result = analyze_gaps(structured_report, law_context, use_mock=True)

    # Step 3: M4 松竹梅提案生成（has_gap=True のギャップのみ）
    # M3のGapItemをM4のGapItemに変換して渡す
    # ANTHROPIC_API_KEY なし → M4内部で自動的にモックモード動作
    proposals: list[ProposalSet] = []
    for gap in gap_result.gaps:
        if gap.has_gap:
            m4_gap = _m3_gap_to_m4_gap(gap)
            ps = generate_proposals(m4_gap)
            proposals.append(ps)

    # Step 4: M5 レポート統合
    return generate_report(
        structured_report=structured_report,
        law_context=law_context,
        gap_result=gap_result,
        proposal_set=proposals,
        level=level,
    )


if __name__ == "__main__":
    print("=== disclosure-multiagent M5: レポート統合エージェント デモ ===")
    print()
    report_md = pipeline_mock()
    # 先頭3000文字のみ表示
    print(report_md[:3000])
    print("...")
    print(f"\n[全体: {len(report_md)}文字]")
