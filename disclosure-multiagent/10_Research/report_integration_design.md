---
created: 2026-02-27
updated: 2026-02-27
type: design_document
tags: [disclosure-multiagent, M5, レポート統合, Streamlit, UI設計]
source: ashigaru4 subtask_063a6
phase: Phase 1-M5
---

# Phase 1-M5: レポート統合エージェント + Streamlit UI 設計書

> **作成**: 2026-02-27 / ashigaru4
> **対象フェーズ**: Phase 1-M5（レポート統合・UI）
> **参照**: 00_Requirements_Definition.md Section 6.2 / gap_analysis_design.md / matsu_take_ume_design.md

---

## M5-1: レポート統合エージェント設計書

### 1-1. 役割と位置づけ

```
[M1: PDF解析] → 構造化有報JSON
[M2: 法令収集] → 適用法令エントリJSON             ← law_yaml_as_of を伝搬
[M3: ギャップ分析] → ギャップ分析JSON
[M4: 松竹梅提案] → 提案文テキスト（gap_id別）

       ↓ 全て統合
【M5: レポート統合エージェント】
       ↓
Markdown レポート（最終成果物）
```

---

### 1-2. 入力インターフェース

#### 入力A: 構造化有報JSON（M1出力）

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class TableData:
    caption: str
    rows: list[list[str]]

@dataclass
class SectionData:
    section_id: str
    heading: str
    level: int
    text: str
    tables: list[TableData]
    parent_section_id: Optional[str]

@dataclass
class StructuredReport:
    document_id: str                  # EDINET書類管理番号等
    company_name: Optional[str]       # 未入力時は "分析対象企業"
    fiscal_year: int                  # 例: 2025
    fiscal_month_end: int             # 3, 6, 12
    sections: list[SectionData]
    extraction_library: str           # "PyMuPDF" 等
    extracted_at: str                 # ISO 8601
```

#### 入力B: 法令コンテキストJSON（M2出力）

```python
@dataclass
class LawEntry:
    id: str                           # "HC_20260220_001"
    title: str
    category: str
    change_type: str                  # "追加必須" / "修正推奨" / "参考"
    source: str                       # URL
    source_confirmed: bool            # False → 警告表示

@dataclass
class LawContext:
    fiscal_year: int
    fiscal_month_end: int
    law_yaml_as_of: str               # YAML更新日 "2026-02-27" — 必ずレポートに明示
    applicable_entries: list[LawEntry]
    missing_categories: list[str]
    warnings: list[str]
```

#### 入力C: ギャップ分析JSON（M3出力）— 主要フィールド

```python
@dataclass
class GapItem:
    gap_id: str                       # "GAP-001"
    section_id: str
    section_heading: str
    change_type: str
    has_gap: bool
    gap_description: Optional[str]
    disclosure_item: str
    reference_law_id: str
    reference_law_title: str
    reference_url: str
    source_confirmed: bool
    source_warning: Optional[str]     # source_confirmed=False 時のみ
    evidence_hint: str
    llm_reasoning: str
    confidence: str                   # "high" / "medium" / "low"

@dataclass
class GapAnalysisResult:
    document_id: str
    fiscal_year: int
    law_yaml_as_of: str               # M2から伝搬 — 必ずレポートに明示
    summary: dict                     # {"total_gaps": N, "by_change_type": {...}}
    gaps: list[GapItem]
    no_gap_items: list[dict]
    metadata: dict
```

#### 入力D: 松竹梅提案テキスト（M4出力）

```python
@dataclass
class ProposalItem:
    gap_id: str
    level: str                        # "松" / "竹" / "梅"
    text: str                         # 提案文本文
    char_count: int
    quality_status: str               # "pass" / "warn" / "fail"
    quality_warnings: list[str]
    attempts: int                     # 生成試行回数

@dataclass
class ProposalSet:
    document_id: str
    level: str                        # ユーザー選択水準
    proposals: list[ProposalItem]     # gap_id → proposal の対応
    generated_at: str
```

---

### 1-3. 出力: Markdownレポート構成

**Section 6.2（00_Requirements_Definition.md）に完全準拠**

```markdown
# 開示変更レポート — {company_name} 有価証券報告書

> **但し書き・免責事項**
> 本レポートは参考情報です。実務の進め方や記載例を提示しますが、
> 最終判断は弁護士・公認会計士等の専門家にご依頼ください。
> 本システムの出力に基づく開示内容について、一切の責任を負いかねます。

---

- **分析対象**: {fiscal_year}年度有報（公開済み有報を入力とした次期版シミュレート）
- **法令参照期間**: {law_ref_start} 〜 {law_ref_end}
- **提案レベル**: {level}（{level_description}）
- **法令情報取得日**: {law_yaml_as_of}  ← ← 必須: 情報の鮮度を明示
- **レポート生成日時**: {generated_at}

{⚠️ source_confirmed: false エントリが含まれる場合のみ表示}
> ⚠️ **要確認**: 一部の法令URLは実アクセス未確認です（source_confirmed: false）。
> 参照前に以下のURLを直接確認してください: [{url_list}]

---

## 1. 変更箇所サマリ

| 変更種別 | 件数 |
|----------|------|
| 追加必須 | {追加必須件数} |
| 修正推奨 | {修正推奨件数} |
| 参考     | {参考件数} |
| **合計** | **{合計件数}** |

---

## 2. セクション別の変更提案

{ギャップ件数ぶんループ: change_typeでソート（追加必須→修正推奨→参考）}

### 2.{N}. {section_heading}

- **変更種別**: {change_type}
- **対象項目**: {disclosure_item}
- **根拠**: {reference_law_title}
  - 出典: [{reference_url}]({reference_url})
  {source_warningがある場合: > ⚠️ {source_warning}}
- **根拠ID**: {reference_law_id}
- **検出根拠**: {evidence_hint}

#### {level}レベルの提案文

> {proposal_text}

{has_gap=False の場合: > ✅ 対応済み: {evidence_hint}}

---

{ループ終わり}

## 3. 参照した法令・ガイダンス一覧

| ID | 名称 | 変更種別 | 出典 |
|----|------|----------|------|
{applicable_entries の一覧}

---

## 4. 免責事項（詳細）

本レポートは、入力された有価証券報告書（公開済み）と法令情報YAML（取得日: {law_yaml_as_of}）
を基に自動生成されたものです。

- 本システムは「参考情報の提供」を目的とし、開示内容の正確性を保証するものではありません
- 法令の解釈・適用については、公認会計士・弁護士等の専門家にご確認ください
- YAML情報の更新漏れにより、最新の法令改正が反映されていない場合があります
- 本レポートを利用した結果生じた損害について、開発者は責任を負いません
```

---

### 1-4. レポート生成ロジック

#### `law_ref_start` / `law_ref_end` の計算

```python
def calc_law_ref_period(fiscal_year: int, fiscal_month_end: int) -> tuple[str, str]:
    """
    法令参照期間を算出する。Phase 1 は3月決算のみ対応。

    Args:
        fiscal_year: 有報の会計年度（例: 2025）
        fiscal_month_end: 決算月（3, 6, 12）

    Returns:
        (start_date, end_date) in "YYYY/MM/DD" format

    Raises:
        NotImplementedError: 3月以外の決算月（Phase 2 で対応）
    """
    if fiscal_month_end == 3:
        # 3月決算: fiscal_year の 4/1 〜 翌年 3/31
        return f"{fiscal_year}/04/01", f"{fiscal_year + 1}/03/31"
    elif fiscal_month_end == 12:
        # 12月決算: fiscal_year の 1/1 〜 12/31（Phase 2）
        raise NotImplementedError("12月決算は Phase 2 で対応予定")
    elif fiscal_month_end == 6:
        # 6月決算: fiscal_year の 7/1 〜 翌年 6/30（Phase 2）
        raise NotImplementedError("6月決算は Phase 2 で対応予定")
    else:
        raise ValueError(f"未対応の決算月: {fiscal_month_end}")
```

#### `source_confirmed: false` 警告の表示判定

```python
def has_unconfirmed_sources(gap_results: list[GapItem]) -> list[str]:
    """
    source_confirmed: false のURLを収集する。
    ヘッダーの警告表示判定に使用する。
    """
    return [
        g.reference_url
        for g in gap_results
        if not g.source_confirmed and g.reference_url
    ]
```

#### Markdownレポート生成関数（骨格）

```python
def generate_report(
    structured_report: StructuredReport,
    law_context: LawContext,
    gap_analysis: GapAnalysisResult,
    proposal_set: ProposalSet,
) -> str:
    """
    全エージェントの出力をMarkdownレポートに統合する。

    Returns:
        str: 完全なMarkdownレポート
    """
    company = structured_report.company_name or "分析対象企業"
    law_ref_start, law_ref_end = calc_law_ref_period(
        gap_analysis.fiscal_year,
        structured_report.fiscal_month_end,
    )
    level = proposal_set.level
    level_desc = {"松": "充実開示向け", "竹": "スタンダード実務向け", "梅": "最小限対応向け"}[level]

    # 未確認URLの収集
    unconfirmed_urls = has_unconfirmed_sources(gap_analysis.gaps)

    # gap_id → proposal のマッピング
    proposal_map = {p.gap_id: p for p in proposal_set.proposals}

    # ギャップをchange_typeでソート
    sorted_gaps = sorted(
        [g for g in gap_analysis.gaps if g.has_gap],
        key=lambda g: {"追加必須": 0, "修正推奨": 1, "参考": 2}.get(g.change_type, 9),
    )

    lines = []

    # ── ヘッダー ──
    lines.append(f"# 開示変更レポート — {company} 有価証券報告書\n")
    lines.append("> **但し書き・免責事項**")
    lines.append("> 本レポートは参考情報です。最終判断は専門家にご確認ください。\n")
    lines.append(f"- **分析対象**: {gap_analysis.fiscal_year}年度有報（公開済み有報の次期版シミュレート）")
    lines.append(f"- **法令参照期間**: {law_ref_start} 〜 {law_ref_end}")
    lines.append(f"- **提案レベル**: {level}（{level_desc}）")
    lines.append(f"- **法令情報取得日**: {gap_analysis.law_yaml_as_of}")
    lines.append(f"- **レポート生成日時**: {proposal_set.generated_at}\n")

    if unconfirmed_urls:
        lines.append("> ⚠️ **要確認**: 一部の法令URLは実アクセス未確認です。参照前にご確認ください。")
        for url in set(unconfirmed_urls):
            lines.append(f">   - {url}")
        lines.append("")

    # ── サマリ ──
    lines.append("---\n")
    lines.append("## 1. 変更箇所サマリ\n")
    by_type = gap_analysis.summary.get("by_change_type", {})
    lines.append("| 変更種別 | 件数 |")
    lines.append("|----------|------|")
    for ct in ["追加必須", "修正推奨", "参考"]:
        lines.append(f"| {ct} | {by_type.get(ct, 0)} |")
    lines.append(f"| **合計** | **{gap_analysis.summary.get('total_gaps', 0)}** |\n")

    # ── セクション別詳細 ──
    lines.append("---\n")
    lines.append("## 2. セクション別の変更提案\n")
    for idx, gap in enumerate(sorted_gaps, start=1):
        proposal = proposal_map.get(gap.gap_id)
        lines.append(f"### 2.{idx}. {gap.section_heading}\n")
        lines.append(f"- **変更種別**: {gap.change_type}")
        lines.append(f"- **対象項目**: {gap.disclosure_item}")
        lines.append(f"- **根拠**: {gap.reference_law_title}")
        lines.append(f"  - 出典: [{gap.reference_url}]({gap.reference_url})")
        if gap.source_warning:
            lines.append(f"  > ⚠️ {gap.source_warning}")
        lines.append(f"- **根拠ID**: {gap.reference_law_id}")
        lines.append(f"- **検出根拠**: {gap.evidence_hint}\n")
        if proposal:
            lines.append(f"#### {level}レベルの提案文\n")
            lines.append(f"> {proposal.text}\n")
            if proposal.quality_warnings:
                for w in proposal.quality_warnings:
                    lines.append(f"> ⚠️ {w}")
        lines.append("---\n")

    # ── 法令一覧 ──
    lines.append("## 3. 参照した法令・ガイダンス一覧\n")
    lines.append("| ID | 名称 | 変更種別 | 出典 |")
    lines.append("|----|------|----------|------|")
    for entry in law_context.applicable_entries:
        confirmed = "" if entry.source_confirmed else " ⚠️未確認"
        lines.append(f"| {entry.id} | {entry.title} | {entry.change_type} | [{entry.source}]({entry.source}){confirmed} |")
    lines.append("")

    # ── 免責詳細 ──
    lines.append("## 4. 免責事項\n")
    lines.append(f"本レポートは、入力された有価証券報告書（公開済み）と法令情報YAML（取得日: {gap_analysis.law_yaml_as_of}）を基に自動生成されたものです。")
    lines.append("- 本システムは参考情報の提供を目的とし、開示内容の正確性を保証するものではありません")
    lines.append("- 法令の解釈・適用については、公認会計士・弁護士等の専門家にご確認ください")
    lines.append("- YAML情報の更新漏れにより、最新の法令改正が反映されていない場合があります\n")

    return "\n".join(lines)
```

---

## M5-2: Streamlit UI 設計書

### 2-1. 画面フロー

```
[アップロード画面]
     │ ① PDFドラッグ&ドロップ（必須）
     │ ② 対象年度選択（プルダウン、必須）
     │ ③ 松竹梅選択（ラジオボタン、必須）
     │ ④ 企業名入力（テキスト、任意）
     │ ⑤ 免責同意チェック（必須）
     │ ⑥ [分析開始] ボタン
     ↓
[処理中画面]
     │ プログレスバー: PDF解析 → 法令取得 → ギャップ分析 → 提案生成
     │ ステップ別進捗テキスト表示
     │ キャンセルボタン（処理中断）
     ↓
[結果表示画面]
     │ ① ギャップサマリー（必須対応N件 / 推奨対応N件 / 参考N件）
     │ ② セクション別の変更提案（アコーディオン形式）
     │ ③ [Markdownダウンロード] ボタン
     ↓
[再実行] → アップロード画面に戻る
```

---

### 2-2. Streamlit 実装スケルトン（M5-2）

```python
"""
disclosure-multiagent — Streamlit UI スケルトン
Phase 1-M5-2 設計書（実装時に詳細化する）

## 実行方法
    streamlit run app.py

## 依存関係（予定）
    pip install streamlit anthropic pdfplumber pyyaml
"""
import streamlit as st
from datetime import datetime
from pathlib import Path

# ── ページ設定 ──
st.set_page_config(
    page_title="開示変更レポート生成",
    page_icon="📋",
    layout="wide",
)

# ── セッション状態の初期化 ──
if "processing" not in st.session_state:
    st.session_state.processing = False
if "result_md" not in st.session_state:
    st.session_state.result_md = None
if "step" not in st.session_state:
    st.session_state.step = "upload"  # "upload" / "processing" / "result"


def run_pipeline(
    pdf_bytes: bytes,
    fiscal_year: int,
    level: str,
    company_name: str,
    progress_bar,
    status_text,
) -> str:
    """
    M1〜M5の処理パイプライン（スケルトン）

    実装フェーズで各エージェントの呼び出しを追記する。
    """
    # STEP 1: PDF解析（M1）
    status_text.text("📄 PDF解析中...")
    progress_bar.progress(10)
    # structured_report = pdf_agent.parse(pdf_bytes)
    # ↑ 実装フェーズで置換
    structured_report = {"company_name": company_name, "fiscal_year": fiscal_year}

    # STEP 2: 法令取得（M2）
    status_text.text("📚 法令情報を読み込み中...")
    progress_bar.progress(35)
    # law_context = law_agent.collect(fiscal_year, fiscal_month_end=3)
    law_context = {"law_yaml_as_of": datetime.now().strftime("%Y-%m-%d")}

    # STEP 3: ギャップ分析（M3）
    status_text.text("🔍 ギャップ分析中...")
    progress_bar.progress(60)
    # gap_result = gap_agent.analyze(structured_report, law_context)
    gap_result = {"summary": {"total_gaps": 0, "by_change_type": {}}, "gaps": []}

    # STEP 4: 松竹梅提案生成（M4）
    status_text.text(f"✍️ {level}レベルの提案文を生成中...")
    progress_bar.progress(85)
    # proposal_set = proposal_agent.generate(gap_result, level)
    proposal_set = {"proposals": []}

    # STEP 5: レポート統合（M5）
    status_text.text("📋 レポートを生成中...")
    progress_bar.progress(95)
    # report_md = generate_report(structured_report, law_context, gap_result, proposal_set)
    report_md = f"# 開示変更レポート\n法令情報取得日: {law_context['law_yaml_as_of']}\n"

    progress_bar.progress(100)
    status_text.text("✅ 完了！")
    return report_md


def validate_inputs(pdf_file, fiscal_year, level, agreed) -> list[str]:
    """入力バリデーション。エラーメッセージのリストを返す。"""
    errors = []
    if pdf_file is None:
        errors.append("PDFファイルを選択してください")
    elif not pdf_file.name.lower().endswith(".pdf"):
        errors.append("PDFファイル（.pdf）のみ対応しています")
    elif pdf_file.size > 50 * 1024 * 1024:  # 50MB上限
        errors.append(f"ファイルサイズが上限（50MB）を超えています（{pdf_file.size // 1024 // 1024} MB）")
    if fiscal_year is None:
        errors.append("対象年度を選択してください")
    if not level:
        errors.append("開示レベル（松/竹/梅）を選択してください")
    if not agreed:
        errors.append("免責事項に同意してください")
    return errors


# ── アップロード画面 ──
def render_upload():
    st.title("📋 開示変更レポート生成")
    st.caption("有価証券報告書（公開済み）を入力すると、次期有報に必要な変更箇所を松竹梅で提案します")

    with st.form("upload_form"):
        # ① PDFアップロード
        pdf_file = st.file_uploader(
            "有価証券報告書PDF（公開済みのみ）",
            type=["pdf"],
            help="EDINETで取得した公開済み有報PDFをアップロードしてください"
        )

        col1, col2 = st.columns(2)
        with col1:
            # ② 対象年度
            current_year = datetime.now().year
            fiscal_year = st.selectbox(
                "対象年度（必須）",
                options=list(range(current_year - 1, current_year - 4, -1)),
                format_func=lambda y: f"{y}年度（{y}年4月〜{y+1}年3月）",
            )
        with col2:
            # ③ 松竹梅
            level = st.radio(
                "開示レベル（必須）",
                options=["竹（スタンダード実務向け）", "梅（最小限対応向け）", "松（充実開示向け）"],
                help="竹: 必須項目を過不足なく満たす実務的な記載\n"
                     "梅: 法令義務の最小限を満たす簡潔な記載\n"
                     "松: KPI・数値目標・ガバナンス体制を含む充実した記載",
            )

        # ④ 企業名（任意）
        company_name = st.text_input(
            "企業名（任意）",
            placeholder="例: ○○株式会社（未入力時は「分析対象企業」と表示）",
        )

        # ⑤ 免責同意
        agreed = st.checkbox(
            "**免責事項に同意します**: 本レポートは参考情報です。最終判断は専門家にご確認ください。",
        )

        # ⑥ 送信ボタン（処理中はグレーアウト）
        submitted = st.form_submit_button(
            "分析開始",
            disabled=st.session_state.processing,
            type="primary",
        )

    if submitted:
        # 入力バリデーション
        level_key = level.split("（")[0]  # "竹" / "梅" / "松"
        errors = validate_inputs(pdf_file, fiscal_year, level_key, agreed)
        if errors:
            for e in errors:
                st.error(e)
            return

        # 処理開始
        st.session_state.processing = True
        st.session_state.step = "processing"
        st.session_state._pending = {
            "pdf_bytes": pdf_file.read(),
            "fiscal_year": fiscal_year,
            "level": level_key,
            "company_name": company_name or "分析対象企業",
        }
        st.rerun()


# ── 処理中画面 ──
def render_processing():
    st.title("⏳ 分析中...")
    params = st.session_state._pending

    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        result_md = run_pipeline(
            pdf_bytes=params["pdf_bytes"],
            fiscal_year=params["fiscal_year"],
            level=params["level"],
            company_name=params["company_name"],
            progress_bar=progress_bar,
            status_text=status_text,
        )
        st.session_state.result_md = result_md
        st.session_state.step = "result"
    except TimeoutError:
        st.error("処理がタイムアウトしました。ファイルサイズを確認して再度お試しください。")
        st.session_state.step = "upload"
    except Exception as e:
        st.error(f"処理中にエラーが発生しました: {e}")
        st.session_state.step = "upload"
    finally:
        st.session_state.processing = False

    st.rerun()


# ── 結果表示画面 ──
def render_result():
    st.title("✅ レポート生成完了")
    result_md = st.session_state.result_md

    # ダウンロードボタン
    st.download_button(
        label="📥 Markdownをダウンロード",
        data=result_md,
        file_name=f"disclosure_report_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
        mime="text/markdown",
    )

    # プレビュー表示
    st.divider()
    st.markdown(result_md)

    if st.button("🔄 別のファイルを分析"):
        st.session_state.step = "upload"
        st.session_state.result_md = None
        st.rerun()


# ── メインルーティング ──
step = st.session_state.step
if step == "upload":
    render_upload()
elif step == "processing":
    render_processing()
elif step == "result":
    render_result()
```

---

### 2-3. エラーハンドリング設計

| エラー種別 | 検出タイミング | 表示方法 | 復旧 |
|-----------|--------------|---------|------|
| ファイル形式エラー | フォーム送信時 | `st.error()` | 再アップロード |
| ファイルサイズ超過（>50MB） | フォーム送信時 | `st.error()` | 再アップロード |
| 必須項目未入力 | フォーム送信時 | `st.error()` | 入力 |
| PDF解析失敗 | 処理中 M1 | `st.error()` + ステップ表示 | アップロード画面に戻る |
| LLM API エラー | 処理中 M3/M4 | `st.error()` + エラー詳細 | 再試行 or アップロード画面 |
| APIキー未設定 | 起動時 | `st.error()` + 設定案内 | 環境変数設定 |
| タイムアウト | 処理中 | `st.error()` + 案内 | アップロード画面に戻る |
| 二重実行 | ボタンクリック | ボタングレーアウト（`disabled=True`） | 処理完了まで待機 |

---

## M5-3: エンドツーエンド処理フロー

### 3-1. 擬似コード（1社分の完全フロー）

```python
# ─── 完全な処理パイプライン ───
def run_full_pipeline(
    pdf_path: Path,
    fiscal_year: int,
    fiscal_month_end: int,
    level: str,
    company_name: str | None = None,
) -> str:
    """
    M1〜M5を連鎖実行し、Markdownレポートを返す。

    型定義はM5-1で定義したdataclassを使用。
    """

    # ─── M1: PDF解析エージェント ───
    # 入力: PDF ファイルパス
    # 出力: StructuredReport
    pdf_bytes = pdf_path.read_bytes()
    structured_report: StructuredReport = pdf_agent.parse(pdf_bytes)
    # 所要時間目安: 30〜120秒（PyMuPDF: 30秒 / Document AI: 120秒）

    # ─── M2: 法令収集エージェント ───
    # 入力: 対象年度・決算月
    # 出力: LawContext（law_yaml_as_of を含む）
    law_context: LawContext = law_agent.collect(
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
    )
    # 所要時間目安: 1〜5秒（YAML読み込みのみ）

    # ─── M3: ギャップ分析エージェント ───
    # 入力: StructuredReport + LawContext
    # 出力: GapAnalysisResult（law_yaml_as_of を伝搬）
    gap_analysis: GapAnalysisResult = gap_agent.analyze(
        structured_report=structured_report,
        law_context=law_context,
    )
    # 所要時間目安: 20〜120秒
    #   Haiku: 1ペア約2秒 × (5項目 × 3セクション) = 30秒
    #   Sonnet: 1ペア約5秒 × 15 = 75秒（大企業・多セクションの場合）

    # ─── M4: 松竹梅提案エージェント ───
    # 入力: GapAnalysisResult（has_gap=True のみ）+ level
    # 出力: ProposalSet（gap_id別の提案文）
    proposal_set: ProposalSet = proposal_agent.generate(
        gap_analysis=gap_analysis,
        level=level,
    )
    # 所要時間目安: 10〜60秒
    #   Haiku: 1ギャップ約3秒 × 5件 = 15秒（再生成なし）
    #   再生成発生時: +3秒/件 × 2回 = 最大+30秒

    # ─── M5: レポート統合エージェント ───
    # 入力: 全エージェントの出力
    # 出力: Markdown文字列
    report_md: str = generate_report(
        structured_report=structured_report,
        law_context=law_context,
        gap_analysis=gap_analysis,
        proposal_set=proposal_set,
    )
    # 所要時間目安: 1〜5秒（テンプレート結合のみ）

    return report_md
```

---

### 3-2. 型定義サマリ（M1〜M5 インターフェース一覧）

| モジュール | 主要な入出力型 | 備考 |
|-----------|-------------|------|
| M1 (pdf_agent) | `bytes → StructuredReport` | PyMuPDF / Document AI |
| M2 (law_agent) | `(int, int) → LawContext` | YAML読み込み。law_yaml_as_of を返す |
| M3 (gap_agent) | `(StructuredReport, LawContext) → GapAnalysisResult` | LLM (Haiku) 使用 |
| M4 (proposal_agent) | `(GapAnalysisResult, str) → ProposalSet` | LLM (Haiku) 使用 |
| M5 (generate_report) | `(StructuredReport, LawContext, GapAnalysisResult, ProposalSet) → str` | テンプレート処理のみ |

---

### 3-3. 処理時間の見積もり

| ステップ | 最小 | 最大 | 代表値 | 備考 |
|---------|------|------|--------|------|
| M1: PDF解析 | 10秒 | 120秒 | 45秒 | PyMuPDF: 10〜30秒 / Document AI: 60〜120秒 |
| M2: 法令収集 | 1秒 | 5秒 | 2秒 | YAML読み込み（Phase 1）|
| M3: ギャップ分析 | 10秒 | 180秒 | 60秒 | Haiku × (法令項目数 × セクション数) |
| M4: 提案生成 | 5秒 | 90秒 | 20秒 | Haiku × ギャップ件数（再生成考慮）|
| M5: レポート統合 | 1秒 | 5秒 | 2秒 | テンプレート処理のみ |
| **合計** | **27秒** | **400秒** | **129秒** | |

> **設計方針**: 00_Requirements_Definition.md 5.2 に「処理時間の厳格な上限は設けない」と定義。
> Streamlit の進捗表示（4ステップ）でユーザーの待機ストレスを軽減する。
> 400秒超（約7分）の場合はタイムアウト警告を表示し、ファイルサイズ・設定の見直しを案内する。

---

### 3-4. データフロー確認（law_yaml_as_of の伝搬）

```
M2 (law_agent) → LawContext.law_yaml_as_of = "2026-02-27"
       ↓
M3 (gap_agent) → GapAnalysisResult.law_yaml_as_of = "2026-02-27"  ← M2から伝搬
       ↓
M5 (generate_report) → レポートヘッダーに明示:
  "法令情報取得日: 2026-02-27"

※ 伝搬漏れ防止: gap_agent は law_context.law_yaml_as_of を
  必ず GapAnalysisResult にコピーすること（M3設計書 gap_analysis_design.md 参照）
```

---

## 設計上の注意点・実装時の確認事項

### law_yaml_as_of の必須表示

- **レポートヘッダーに必ず表示する**（情報の鮮度の透明性確保）
- M2 → M3 → M5 の伝搬を実装時に確認すること
- `law_yaml_as_of` が欠損している場合はレポートに「取得日不明（確認推奨）」と表示

### source_confirmed: false の扱い

- M3のギャップ分析JSONにすでに `source_warning` フィールドが設計済み（gap_analysis_design.md参照）
- M5のレポート生成時に `source_warning` を読み取り、該当箇所にインライン表示
- ヘッダーにも「一部URL未確認」の警告バナーを表示

### Phase 2 以降の拡張ポイント

| 項目 | Phase 1 | Phase 2 |
|------|---------|---------|
| 決算期 | 3月のみ | 12月・6月を追加 |
| 出力形式 | Markdown | PDF / HTML / Word |
| 企業名抽出 | 手動入力 | PDF表紙から自動抽出 |
| エクスポート | ファイルダウンロードのみ | クリップボードコピー・共有URL |

---

## 関連ドキュメント

- `gap_analysis_design.md` — M3設計書（入力C: GapAnalysisResult の元定義）
- `matsu_take_ume_design.md` — M4設計書（入力D: ProposalSet の元定義・文字数チェック）
- `law_yaml_format_design.md` — M2設計書（LawContext.law_yaml_as_of の元定義）
- `00_Requirements_Definition.md` Section 6.2 — 出力レポート構成の要件定義
- `22_MVP_Development_Checklist.md` — M5-1〜M5-3 チェックリスト

---

*作成: ashigaru4 / subtask_063a6 / 2026-02-27*
