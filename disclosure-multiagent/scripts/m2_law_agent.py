"""
m2_law_agent.py
===============
disclosure-multiagent Phase 1-M2: 法令収集エージェント

設計書: law_yaml_format_design.md (足軽3 subtask_063a3)
実装者: 足軽4 subtask_063a9
作成日: 2026-02-27

使用方法:
    # 実際のYAMLから2025年度3月決算向け法令コンテキスト取得
    python3 m2_law_agent.py

    # 別のYAMLディレクトリを使う場合
    LAW_YAML_DIR=/path/to/yamls python3 m2_law_agent.py
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import yaml

# M3のデータクラス・ユーティリティをimport（m3_gap_analysis_agent.py は改変しない）
from m3_gap_analysis_agent import (
    LawContext,
    LawEntry,
    calc_law_ref_period,
    is_entry_applicable,
)

# ─────────────────────────────────────────────────────────
# 定数（ハードコード禁止: 環境変数で上書き可能）
# ─────────────────────────────────────────────────────────

# デフォルトのYAMLディレクトリ（環境変数 LAW_YAML_DIR で上書き可能）
_DEFAULT_YAML_DIR = Path(__file__).parent.parent / "10_Research"
LAW_YAML_DIR: Path = Path(os.environ.get("LAW_YAML_DIR", str(_DEFAULT_YAML_DIR)))

# フォールバック: 直接ファイル指定（環境変数 LAW_YAML_FILE で上書き可能）
_DEFAULT_YAML_FILE = LAW_YAML_DIR / "law_entries_human_capital.yaml"
LAW_YAML_FILE: Path = Path(os.environ.get("LAW_YAML_FILE", str(_DEFAULT_YAML_FILE)))

# 重要カテゴリ（1件もエントリがない場合は警告）
CRITICAL_CATEGORIES = ["人的資本ガイダンス", "金商法・開示府令", "SSBJ"]


# ─────────────────────────────────────────────────────────
# YAMLファイル読み込み
# ─────────────────────────────────────────────────────────

def _extract_last_updated(yaml_path: Path) -> Optional[str]:
    """
    YAMLファイルの先頭コメントから `# Last Updated: YYYY-MM-DD` を抽出する。
    見つからない場合はファイルの更新日時を使用する。
    """
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i > 20:  # 先頭20行のみ確認
                    break
                m = re.match(r"#\s*Last Updated:\s*(\d{4}-\d{2}-\d{2})", line.strip())
                if m:
                    return m.group(1)
        # コメントが見つからない場合はファイル更新日時を使用
        mtime = os.path.getmtime(yaml_path)
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    except OSError:
        return datetime.now().strftime("%Y-%m-%d")


def load_law_entries(yaml_path: Path) -> list[LawEntry]:
    """
    指定したYAMLファイルからLawEntryのリストを読み込む。

    Args:
        yaml_path: 法令YAMLファイルのパス

    Returns:
        list[LawEntry]

    Raises:
        FileNotFoundError: YAMLファイルが存在しない場合
        ValueError: YAMLのパースエラーまたはスキーマ不正の場合
    """
    logger = logging.getLogger(__name__)

    if not yaml_path.exists():
        raise FileNotFoundError(
            f"法令YAMLファイルが見つかりません: {yaml_path}\n"
            f"環境変数 LAW_YAML_FILE でパスを指定できます。"
        )

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"YAMLパースエラー: {yaml_path}: {e}") from e

    if not isinstance(data, dict) or "entries" not in data:
        raise ValueError(
            f"YAMLフォーマット不正: 'entries' キーが見つかりません: {yaml_path}"
        )

    entries: list[LawEntry] = []
    for raw in data["entries"]:
        if not isinstance(raw, dict):
            logger.warning("スキップ: 不正なエントリ形式: %s", raw)
            continue

        # 必須フィールドチェック
        entry_id = raw.get("id", "UNKNOWN")
        if not raw.get("disclosure_items"):
            logger.debug("スキップ: %s (disclosure_items なし)", entry_id)

        entry = LawEntry(
            id=entry_id,
            title=raw.get("title", ""),
            category=raw.get("category", ""),
            change_type=raw.get("change_type", "参考"),
            disclosure_items=raw.get("disclosure_items") or [],
            source=raw.get("source", ""),
            source_confirmed=bool(raw.get("source_confirmed", False)),
            summary=raw.get("summary", ""),
            law_name=raw.get("law_name", ""),
            effective_from=str(raw["effective_from"]) if raw.get("effective_from") else None,
            target_companies=raw.get("target_companies", ""),
            notes=raw.get("notes", ""),
        )
        entries.append(entry)

    logger.info("法令エントリ読み込み完了: %d件 (%s)", len(entries), yaml_path.name)
    return entries


# ─────────────────────────────────────────────────────────
# フィルタリングロジック
# ─────────────────────────────────────────────────────────

def get_applicable_entries(
    entries: list[LawEntry],
    ref_period: tuple[str, str],
    categories: Optional[list[str]] = None,
) -> list[LawEntry]:
    """
    法令参照期間内のエントリをフィルタリングして返す（設計書 Section 4-3）。

    Args:
        entries: 全法令エントリ
        ref_period: (期間開始日文字列, 期間終了日文字列) in "YYYY/MM/DD" format
        categories: フィルタするカテゴリ（Noneの場合は全カテゴリ）

    Returns:
        期間内かつカテゴリ条件に一致するLawEntryのリスト
    """
    start_str, end_str = ref_period
    start = date.fromisoformat(start_str.replace("/", "-"))
    end = date.fromisoformat(end_str.replace("/", "-"))

    applicable: list[LawEntry] = []
    for entry in entries:
        if not entry.effective_from:
            # 施行日なし → 常に対象
            applicable.append(entry)
            continue

        try:
            eff = date.fromisoformat(entry.effective_from)
        except ValueError:
            logging.getLogger(__name__).warning(
                "日付パースエラー: entry=%s effective_from=%s",
                entry.id, entry.effective_from,
            )
            continue

        if start <= eff <= end:
            applicable.append(entry)

    # カテゴリフィルタ（指定がある場合のみ）
    if categories:
        applicable = [e for e in applicable if e.category in categories]

    return applicable


# ─────────────────────────────────────────────────────────
# メイン: 法令コンテキスト生成
# ─────────────────────────────────────────────────────────

def load_law_context(
    fiscal_year: int,
    fiscal_month_end: int = 3,
    yaml_path: Optional[Path] = None,
    categories: Optional[list[str]] = None,
) -> LawContext:
    """
    対象年度・決算月から法令コンテキスト（LawContext）を生成するメインAPI（設計書 Section 4-2）。

    処理フロー:
      1. YAMLファイル読み込み
      2. 法令参照期間を算出（calc_law_ref_period使用）
      3. 参照期間内エントリをフィルタ
      4. 重要カテゴリの網羅性チェック（警告生成）
      5. LawContextとして返す

    Args:
        fiscal_year: 対象事業年度（例: 2025 = 2025/04/01〜2026/03/31）
        fiscal_month_end: 決算月（デフォルト3月）
        yaml_path: 法令YAMLのパス（Noneの場合はLAW_YAML_FILE定数を使用）
        categories: フィルタカテゴリ（Noneの場合は全カテゴリ）

    Returns:
        LawContext（applicable_entries, law_yaml_as_of, warnings等を含む）

    Raises:
        FileNotFoundError: YAMLファイルが存在しない場合
        ValueError: YAMLパースエラーの場合
    """
    logger = logging.getLogger(__name__)

    target_yaml = yaml_path or LAW_YAML_FILE

    # STEP 1: YAMLファイル読み込み
    all_entries = load_law_entries(target_yaml)

    # STEP 2: 法令参照期間の算出（m3のcalc_law_ref_periodを使用）
    ref_start, ref_end = calc_law_ref_period(fiscal_year, fiscal_month_end)
    logger.info(
        "法令参照期間: fiscal_year=%d, fiscal_month_end=%d → %s〜%s",
        fiscal_year, fiscal_month_end, ref_start, ref_end,
    )

    # STEP 3: 日付フィルタ + カテゴリフィルタ
    applicable = get_applicable_entries(
        all_entries,
        ref_period=(ref_start, ref_end),
        categories=categories,
    )
    logger.info("適用エントリ: %d件 / 全%d件", len(applicable), len(all_entries))

    # STEP 4: 重要カテゴリの網羅性チェック
    warnings: list[str] = []
    missing_categories: list[str] = []
    for cat in CRITICAL_CATEGORIES:
        if not any(e.category == cat for e in applicable):
            missing_categories.append(cat)
            warnings.append(f"⚠️ 重要カテゴリのエントリが0件: {cat}")
            logger.warning("重要カテゴリが0件: %s", cat)

    # STEP 5: law_yaml_as_of の取得（YAMLコメントまたはファイル更新日時）
    law_yaml_as_of = _extract_last_updated(target_yaml)
    logger.info("law_yaml_as_of: %s", law_yaml_as_of)

    return LawContext(
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
        law_yaml_as_of=law_yaml_as_of,
        applicable_entries=applicable,
        missing_categories=missing_categories,
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────
# デモ実行
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    print("=== disclosure-multiagent M2: 法令収集エージェント デモ ===")
    print(f"YAMLファイル: {LAW_YAML_FILE}")
    print()

    for fy in [2025, 2024, 2022]:
        print(f"--- fiscal_year={fy}, fiscal_month_end=3 ---")
        try:
            ctx = load_law_context(fy, 3)
            print(f"  applicable_entries: {len(ctx.applicable_entries)}件")
            for e in ctx.applicable_entries:
                print(f"    [{e.id}] {e.title[:40]} ({e.change_type})")
            if ctx.warnings:
                for w in ctx.warnings:
                    print(f"  {w}")
            if ctx.missing_categories:
                print(f"  missing_categories: {ctx.missing_categories}")
            print(f"  law_yaml_as_of: {ctx.law_yaml_as_of}")
        except FileNotFoundError as e:
            print(f"  エラー: {e}")
        print()
