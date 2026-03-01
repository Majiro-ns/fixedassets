"""
m8_multiyear_agent.py
=====================
disclosure-multiagent Phase 2-M8: 複数年度比較エージェント（F-08）

設計書: 00_Requirements_Definition.md §3.2 F-08
実装者: 足軽3 subtask_074a3_disclosure_f08_multiyear
作成日: 2026-02-28

要件定義 F-08「複数年度の比較」:
    2年分・3年分の有報を比較し、トレンドや変更履歴を可視化する機能。

使用方法:
    from m8_multiyear_agent import YearlyReport, YearDiff, compare_years, detect_section_changes

制約:
    M1〜M5 モジュールの改変禁止（READ-ONLY参照のみ）
    m3_gap_analysis_agent.py の StructuredReport / SectionData をインポートして使用
"""

from __future__ import annotations

import difflib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# scriptsディレクトリをパスに追加（同一ディレクトリからのインポート）
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# M1〜M5 改変禁止: READ-ONLY インポートのみ
from m3_gap_analysis_agent import (  # noqa: E402
    StructuredReport,
    SectionData,
)


# ─────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────

# セクション本文の変化率閾値（これを超えると "changed" として検出）
# 根拠: 要件定義 §3.2 F-08「本文変化率 > 20% → changed として検出」
CHANGE_RATE_THRESHOLD: float = 0.20


# ─────────────────────────────────────────────────────────
# データクラス定義
# ─────────────────────────────────────────────────────────

@dataclass
class YearlyReport:
    """1年度分の有報データ（M1出力ラッパー）

    Attributes:
        fiscal_year:      会計年度（例: 2024）
        structured_report: M1出力の構造化有報（StructuredReport）
        elapsed_sec:      M1処理時間（秒）。省略可能
    """
    fiscal_year: int
    structured_report: StructuredReport
    elapsed_sec: float = 0.0


@dataclass
class YearDiff:
    """2年度間の差分結果

    Attributes:
        fiscal_year_from:  比較元年度（旧年度）
        fiscal_year_to:    比較先年度（新年度）
        added_sections:    新年度に追加されたセクション一覧
        removed_sections:  旧年度から削除されたセクション一覧
        changed_sections:  内容が変化したセクション（新年度版）一覧
                           変化率 > CHANGE_RATE_THRESHOLD で判定
        summary:           差分のテキストサマリー
    """
    fiscal_year_from: int
    fiscal_year_to: int
    added_sections: list[SectionData]
    removed_sections: list[SectionData]
    changed_sections: list[SectionData]
    summary: str


# ─────────────────────────────────────────────────────────
# 内部ユーティリティ
# ─────────────────────────────────────────────────────────

def _text_change_rate(old_text: str, new_text: str) -> float:
    """2つのテキストの変化率を計算する（0.0〜1.0）

    変化率 = 1.0 - 一致率（difflib.SequenceMatcher.ratio() を使用）

    手計算検証:
        old="abc", new="abc"   → ratio=1.0 → 変化率=0.0（変化なし）✓
        old="abc", new="xyz"   → ratio=0.0 → 変化率=1.0（全変化）✓
        old="abc", new="abcdef" → ratio=6/9=0.667 → 変化率=0.333 > 0.20 ✓

    Returns:
        float: 0.0（完全一致）〜1.0（完全不一致）
    """
    if not old_text and not new_text:
        return 0.0
    if not old_text or not new_text:
        return 1.0
    ratio = difflib.SequenceMatcher(None, old_text, new_text).ratio()
    return 1.0 - ratio


# ─────────────────────────────────────────────────────────
# メイン関数
# ─────────────────────────────────────────────────────────

def detect_section_changes(
    old: StructuredReport,
    new: StructuredReport,
) -> dict[str, list[SectionData]]:
    """2つのStructuredReport間のセクション差分を検出する

    アルゴリズム:
        1. 旧年度・新年度のセクションを heading でインデックス化
        2. 追加 = 新年度のみに存在する heading のセクション
        3. 削除 = 旧年度のみに存在する heading のセクション
        4. 変更 = 両年度に存在し、本文変化率 > CHANGE_RATE_THRESHOLD のセクション

    手計算検証:
        old.sections = [A, B, C], new.sections = [A, B, D]
        追加: {D}, 削除: {C}, 共通: {A, B}
        A・B の本文が同一 → changed=[] → added=[D], removed=[C], changed=[] ✓

    Args:
        old: 旧年度の構造化有報（M1出力）
        new: 新年度の構造化有報（M1出力）

    Returns:
        dict: {'added': list[SectionData], 'removed': list[SectionData], 'changed': list[SectionData]}
              changed は新年度版のSectionDataを格納
    """
    # heading でインデックス化（同一見出しが複数ある場合は最初のものを使用）
    old_by_heading: dict[str, SectionData] = {}
    for sec in old.sections:
        if sec.heading not in old_by_heading:
            old_by_heading[sec.heading] = sec

    new_by_heading: dict[str, SectionData] = {}
    for sec in new.sections:
        if sec.heading not in new_by_heading:
            new_by_heading[sec.heading] = sec

    old_headings = set(old_by_heading.keys())
    new_headings = set(new_by_heading.keys())

    # 追加: 新年度のみに存在
    added_headings = new_headings - old_headings
    added = [new_by_heading[h] for h in sorted(added_headings)]

    # 削除: 旧年度のみに存在
    removed_headings = old_headings - new_headings
    removed = [old_by_heading[h] for h in sorted(removed_headings)]

    # 変更: 両年度に存在し、本文変化率 > CHANGE_RATE_THRESHOLD
    common_headings = old_headings & new_headings
    changed = []
    for heading in sorted(common_headings):
        old_sec = old_by_heading[heading]
        new_sec = new_by_heading[heading]
        rate = _text_change_rate(old_sec.text, new_sec.text)
        if rate > CHANGE_RATE_THRESHOLD:
            changed.append(new_sec)

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def compare_years(reports: list[YearlyReport]) -> YearDiff:
    """複数年度のレポートを比較し、最新2年度間の差分を返す

    入力が2件の場合は直接比較する。3件以上の場合は最新2年度（年度昇順の末尾2件）を比較する。

    手計算検証:
        reports = [2023年度, 2024年度]
        → fiscal_year_from=2023, fiscal_year_to=2024 の YearDiff を返す ✓

        reports = [2020年度, 2021年度, 2022年度]
        → fiscal_year_from=2021, fiscal_year_to=2022 の YearDiff を返す ✓

    Args:
        reports: YearlyReport のリスト（年度順不同可）。最低2件必要。

    Returns:
        YearDiff: 最新2年度間の差分結果

    Raises:
        ValueError: reports が2件未満の場合
    """
    if len(reports) < 2:
        raise ValueError(
            f"compare_years には最低2件の YearlyReport が必要です（受取: {len(reports)}件）"
        )

    # 会計年度で昇順ソートし、最新2年度を取得
    sorted_reports = sorted(reports, key=lambda r: r.fiscal_year)
    old_report = sorted_reports[-2]
    new_report = sorted_reports[-1]

    changes = detect_section_changes(
        old_report.structured_report,
        new_report.structured_report,
    )

    # サマリー生成
    summary_parts: list[str] = []
    if changes["added"]:
        summary_parts.append(f"追加: {len(changes['added'])}件")
    if changes["removed"]:
        summary_parts.append(f"削除: {len(changes['removed'])}件")
    if changes["changed"]:
        summary_parts.append(f"変更: {len(changes['changed'])}件")
    if not summary_parts:
        summary_parts = ["差分なし"]

    summary = (
        f"{old_report.fiscal_year}年度 → {new_report.fiscal_year}年度: "
        + ", ".join(summary_parts)
    )

    return YearDiff(
        fiscal_year_from=old_report.fiscal_year,
        fiscal_year_to=new_report.fiscal_year,
        added_sections=changes["added"],
        removed_sections=changes["removed"],
        changed_sections=changes["changed"],
        summary=summary,
    )
