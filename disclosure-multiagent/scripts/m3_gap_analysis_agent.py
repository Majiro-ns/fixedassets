"""
m3_gap_analysis_agent.py
========================
disclosure-multiagent Phase 1-M3: ギャップ分析エージェント

設計書: gap_analysis_design.md (足軽3 subtask_063a4)
実装者: 足軽4 subtask_063a7
作成日: 2026-02-27

使用方法:
    # 本番（APIキーあり）
    ANTHROPIC_API_KEY=sk-ant-... python3 m3_gap_analysis_agent.py

    # モック（APIキーなし）
    USE_MOCK_LLM=true python3 m3_gap_analysis_agent.py
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Optional

# ─────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────

LLM_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 512
MAX_RETRIES = 3
RETRY_DELAY_SEC = 2.0
TEXT_CHUNK_MAX = 4000
TEXT_CHUNK_HEAD = 2000
TEXT_CHUNK_TAIL = 1000

# 人的資本関連セクション判定キーワード（設計書 Section 5-1）
HUMAN_CAPITAL_KEYWORDS = [
    "人的資本", "人材", "人材戦略", "人材育成", "従業員",
    "ダイバーシティ", "多様性", "育児休業", "育休",
    "サステナビリティ", "ESG", "社会",
    "給与", "賃金", "報酬",
]

# SSBJサステナビリティ開示基準関連セクション判定キーワード
SSBJ_KEYWORDS = [
    "SSBJ", "サステナビリティ開示", "気候変動", "気候関連",
    "GHG", "温室効果ガス", "Scope1", "Scope2", "Scope3",
    "スコープ1", "スコープ2", "スコープ3",
    "脱炭素", "カーボンニュートラル", "ネットゼロ",
    "移行計画", "移行リスク", "物理的リスク",
    "TCFD", "シナリオ分析", "排出量", "排出削減",
    "炭素", "カーボン", "再生可能エネルギー",
]

# 関連性判定に使用する全キーワード（人的資本 + SSBJ）
ALL_RELEVANCE_KEYWORDS = HUMAN_CAPITAL_KEYWORDS + SSBJ_KEYWORDS

# ─────────────────────────────────────────────────────────
# Enum / 定数クラス
# ─────────────────────────────────────────────────────────

class ChangeType(str, Enum):
    """change_type の許容値（設計書 hallucination対策: enum制約）"""
    ADD_MANDATORY = "追加必須"
    MODIFY_RECOMMENDED = "修正推奨"
    REFERENCE = "参考"


class Confidence(str, Enum):
    """LLM出力の確信度"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ERROR = "error"
    PARSE_ERROR = "parse_error"


# ─────────────────────────────────────────────────────────
# M1 入力: 構造化有報 データクラス
# ─────────────────────────────────────────────────────────

@dataclass
class TableData:
    """有報テーブル"""
    caption: str
    rows: list[list[str]]


@dataclass
class SectionData:
    """有報セクション（M1の出力単位）"""
    section_id: str
    heading: str
    text: str
    level: int = 3
    tables: list[TableData] = field(default_factory=list)
    parent_section_id: Optional[str] = None


@dataclass
class StructuredReport:
    """M1出力: 構造化有報JSON"""
    document_id: str
    company_name: str
    fiscal_year: int
    fiscal_month_end: int
    sections: list[SectionData]
    extraction_library: str = "PyMuPDF"
    extracted_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────────────────
# M2 入力: 法令コンテキスト データクラス
# ─────────────────────────────────────────────────────────

@dataclass
class LawEntry:
    """法令YAMLの1エントリ"""
    id: str
    title: str
    category: str
    change_type: str
    disclosure_items: list[str]
    source: str
    source_confirmed: bool
    summary: str = ""
    law_name: str = ""
    effective_from: Optional[str] = None
    target_companies: str = ""
    notes: str = ""


@dataclass
class LawContext:
    """M2出力: 適用法令コンテキスト"""
    fiscal_year: int
    fiscal_month_end: int
    law_yaml_as_of: str
    applicable_entries: list[LawEntry]
    missing_categories: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────
# M3 出力: ギャップ分析 データクラス
# ─────────────────────────────────────────────────────────

@dataclass
class GapItem:
    """ギャップ分析の1件"""
    gap_id: str
    section_id: str
    section_heading: str
    change_type: str
    has_gap: Optional[bool]
    disclosure_item: str
    reference_law_id: str
    reference_law_title: str
    reference_url: str
    source_confirmed: bool
    evidence_hint: str
    llm_reasoning: Optional[str] = None
    gap_description: Optional[str] = None
    source_warning: Optional[str] = None
    confidence: str = Confidence.MEDIUM.value

    def __post_init__(self) -> None:
        """change_type の enum バリデーション（hallucination対策）"""
        valid = {ct.value for ct in ChangeType}
        if self.change_type not in valid:
            raise ValueError(
                f"change_type '{self.change_type}' は無効です。"
                f"有効値: {sorted(valid)}"
            )


@dataclass
class NoGapItem:
    """ギャップなし（充足済み）項目"""
    disclosure_item: str
    reference_law_id: str
    evidence_hint: str
    section_id: Optional[str] = None


@dataclass
class GapSummary:
    """ギャップ分析サマリー"""
    total_gaps: int
    by_change_type: dict[str, int]


@dataclass
class GapMetadata:
    """ギャップ分析メタデータ"""
    llm_model: str
    sections_analyzed: int
    entries_checked: int
    input_tokens_total: int = 0
    output_tokens_total: int = 0


@dataclass
class GapAnalysisResult:
    """M3出力: ギャップ分析JSON"""
    document_id: str
    fiscal_year: int
    law_yaml_as_of: str
    summary: GapSummary
    gaps: list[GapItem]
    no_gap_items: list[NoGapItem]
    metadata: GapMetadata
    gap_analysis_version: str = "1.0"
    analyzed_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────────────────
# プロンプト定義
# ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """あなたは日本の有価証券報告書の開示コンプライアンス専門家です。
以下の役割と制約に従って、有報テキストの法令要件充足状況を判定してください。

## 役割
有価証券報告書の特定のセクションテキストを読み、
指定された法令開示項目が記載されているかどうかを判定する。

## 制約（必ず守ること）
1. 判定は「提供された法令開示項目の要件のみ」に基づいて行う。
   YAMLエントリとして提供されていない法令・ガイドラインへの言及は禁止する。
2. 推測や一般的な「あるべき開示」の観点から余分な指摘を追加しない。
3. 出力は必ず指定のJSONフォーマットで返す。フォーマット外の文章を追加しない。
4. 有報テキストに明示的な記載がない場合は has_gap: true とする。
   「おそらく記載があるはず」という推測で has_gap: false としない。
5. 確信度（confidence）は "high"/"medium"/"low" のいずれかで答える。
   テキストに明確な記載あり → high
   類似の記載があるが完全ではない → medium
   テキストが断片的で判断しづらい → low

## 有報の構造について
様式第19号の主要セクション:
- 第二部第2「事業の状況」: 経営方針・サステナビリティ・人的資本・多様性
- 第二部第5「従業員の状況」: 従業員数・平均年齢・平均給与・女性管理職比率等
人的資本の開示は「事業の状況」と「従業員の状況」の両方に分散している場合がある。"""


def _build_user_prompt(
    section: SectionData,
    disclosure_item: str,
    law_entry: LawEntry,
) -> str:
    """ユーザープロンプトを構築する（設計書 Section 3-3）"""
    # テキストのチャンク処理（4000文字超の場合）
    text = section.text
    if len(text) > TEXT_CHUNK_MAX:
        text = text[:TEXT_CHUNK_HEAD] + "\n...[中略]...\n" + text[-TEXT_CHUNK_TAIL:]

    # テーブルをテキスト化
    table_text = ""
    for table in section.tables:
        rows_csv = "\n".join(",".join(row) for row in table.rows)
        table_text += f'\nテーブル「{table.caption}」:\n{rows_csv}\n'

    return f"""## 判定対象

### 有報セクション情報
- セクションID: {section.section_id}
- 見出し: {section.heading}
- テキスト:
\"\"\"{text}\"\"\"
{table_text}
### 確認すべき法令開示項目
- 項目: {disclosure_item}
- 法令根拠: {law_entry.title}
- 変更種別: {law_entry.change_type}（追加必須/修正推奨/参考のいずれか）

## 出力フォーマット（JSONのみ返すこと）
{{
  "has_gap": true または false,
  "gap_description": "ギャップがある場合の説明（日本語・1〜2文）。ない場合はnull",
  "evidence_hint": "判定の根拠となるテキストの引用や観察（日本語・1文）",
  "confidence": "high" または "medium" または "low"
}}"""


# ─────────────────────────────────────────────────────────
# モックLLMレスポンス（テスト用）
# ─────────────────────────────────────────────────────────

def _mock_judge_response(disclosure_item: str, section: SectionData) -> dict:
    """
    APIキー不要のモックレスポンス。
    disclosure_itemのキーワードがsectionのtextに含まれるかで has_gap を決定する。
    """
    keywords = disclosure_item.split("（")[0].replace("の記載", "").replace("の開示", "")
    has_gap = keywords not in section.text and not any(
        kw in section.text for kw in keywords.split()
    )
    if has_gap:
        return {
            "has_gap": True,
            "gap_description": f"「{keywords}」に関する記載が見当たらない。",
            "evidence_hint": f"テキスト内に「{keywords[:8]}」のキーワードなし。",
            "confidence": "medium",
        }
    else:
        return {
            "has_gap": False,
            "gap_description": None,
            "evidence_hint": f"テキスト内に関連する記載を確認。",
            "confidence": "medium",
        }


# ─────────────────────────────────────────────────────────
# LLM判定コア関数
# ─────────────────────────────────────────────────────────

def judge_gap(
    section: SectionData,
    disclosure_item: str,
    law_entry: LawEntry,
    client,
    use_mock: bool = False,
) -> tuple[dict, int, int]:
    """
    1つの disclosure_item × section ペアのギャップを判定する。

    Args:
        section: 分析対象セクション
        disclosure_item: 確認する開示項目
        law_entry: 根拠法令エントリ
        client: anthropic.Anthropic() インスタンス（モック時はNone）
        use_mock: True の場合はモックレスポンスを返す

    Returns:
        (判定結果dict, 入力トークン数, 出力トークン数)

    Raises:
        なし（エラーは結果dictに記録し継続）
    """
    logger = logging.getLogger(__name__)

    if use_mock:
        result = _mock_judge_response(disclosure_item, section)
        return result, 0, 0

    user_prompt = _build_user_prompt(section, disclosure_item, law_entry)

    # リトライロジック（設計書 GAP_ERR_003）
    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=LLM_MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

            raw_text = response.content[0].text.strip()
            # JSONブロックを抽出（```json ... ``` の場合も対応）
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                raw_text = "\n".join(
                    l for l in lines if not l.startswith("```")
                )

            result = json.loads(raw_text)

            # confidence バリデーション
            valid_conf = {c.value for c in Confidence
                         if c not in (Confidence.ERROR, Confidence.PARSE_ERROR)}
            if result.get("confidence") not in valid_conf:
                result["confidence"] = Confidence.LOW.value

            return result, input_tokens, output_tokens

        except json.JSONDecodeError as e:
            logger.warning(
                "GAP_ERR_004: JSONパースエラー (試行%d/%d): %s",
                attempt, MAX_RETRIES, e,
            )
            return {
                "has_gap": None,
                "gap_description": None,
                "evidence_hint": "LLM出力のJSONパースに失敗",
                "confidence": Confidence.PARSE_ERROR.value,
                "llm_raw_output": response.content[0].text if 'response' in dir() else "",
            }, 0, 0

        except Exception as e:
            last_error = e
            logger.warning(
                "GAP_ERR_003: API呼び出しエラー (試行%d/%d): %s",
                attempt, MAX_RETRIES, e,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SEC)

    # 全リトライ失敗
    logger.error("GAP_ERR_003: %d回リトライ後も失敗: %s", MAX_RETRIES, last_error)
    return {
        "has_gap": None,
        "gap_description": None,
        "evidence_hint": f"APIエラー（{MAX_RETRIES}回リトライ失敗）",
        "confidence": Confidence.ERROR.value,
    }, 0, 0


# ─────────────────────────────────────────────────────────
# 根拠URL付与
# ─────────────────────────────────────────────────────────

def attach_reference_url(gap_result: dict, law_entry: LawEntry) -> dict:
    """
    ギャップ判定結果に法令根拠URLを付与する（設計書 Section 4-2）。
    source_confirmed: false の場合は警告を追加。
    """
    gap_result["reference_law_id"] = law_entry.id
    gap_result["reference_law_title"] = law_entry.title
    gap_result["reference_url"] = law_entry.source
    gap_result["source_confirmed"] = law_entry.source_confirmed

    if not law_entry.source_confirmed:
        gap_result["source_warning"] = (
            "⚠️ このURLは実アクセス未確認（source_confirmed: false）。"
            "参照前にURLの有効性を確認することを推奨します。"
        )
    else:
        gap_result["source_warning"] = None

    return gap_result


# ─────────────────────────────────────────────────────────
# セクション関連性フィルタ
# ─────────────────────────────────────────────────────────

def is_relevant_section(section: SectionData) -> bool:
    """セクションが人的資本またはSSBJ関連かどうかを判定する（設計書 Section 5-1）"""
    heading_lower = section.heading
    text_lower = section.text[:200]  # 先頭200文字で判定
    combined = heading_lower + text_lower
    return any(kw in combined for kw in ALL_RELEVANCE_KEYWORDS)


# ─────────────────────────────────────────────────────────
# 法令参照期間計算
# ─────────────────────────────────────────────────────────

def calc_law_ref_period(fiscal_year: int, fiscal_month_end: int) -> tuple[str, str]:
    """
    事業年度から法令参照期間（start, end）を算出する。

    Args:
        fiscal_year: 事業年度（例: 2025 = 2025年度）
        fiscal_month_end: 決算月（例: 3 = 3月決算）

    Returns:
        (期間開始日文字列, 期間終了日文字列) in "YYYY/MM/DD" format

    Example:
        >>> calc_law_ref_period(2025, 3)
        ('2025/04/01', '2026/03/31')
    """
    if fiscal_month_end == 3:
        # 3月決算: 当年4月1日〜翌年3月31日
        start = f"{fiscal_year}/04/01"
        end = f"{fiscal_year + 1}/03/31"
    elif fiscal_month_end == 12:
        # 12月決算: 当年1月1日〜当年12月31日
        start = f"{fiscal_year}/01/01"
        end = f"{fiscal_year}/12/31"
    else:
        # 一般: 前年(fiscal_month_end+1)月〜当年fiscal_month_end月
        start_month = fiscal_month_end + 1
        start_year = fiscal_year if fiscal_month_end < 12 else fiscal_year
        if fiscal_month_end == 12:
            start = f"{fiscal_year}/01/01"
            end = f"{fiscal_year}/12/31"
        else:
            start = f"{fiscal_year}/{start_month:02d}/01"
            # 翌月1日の前日 = 当月末
            if fiscal_month_end == 2:
                end_day = 28
            elif fiscal_month_end in (4, 6, 9, 11):
                end_day = 30
            else:
                end_day = 31
            end = f"{fiscal_year + 1}/{fiscal_month_end:02d}/{end_day:02d}"
    return start, end


def is_entry_applicable(
    entry: LawEntry,
    fiscal_year: int,
    fiscal_month_end: int,
) -> bool:
    """
    法令エントリが指定事業年度に適用されるかを判定する。
    effective_from が法令参照期間内であれば適用。
    """
    if not entry.effective_from:
        return True  # 施行日不明は常に対象

    start_str, end_str = calc_law_ref_period(fiscal_year, fiscal_month_end)
    # YYYY/MM/DD を date に変換
    start = date.fromisoformat(start_str.replace("/", "-"))
    end = date.fromisoformat(end_str.replace("/", "-"))
    eff = date.fromisoformat(entry.effective_from)

    return start <= eff <= end


# ─────────────────────────────────────────────────────────
# メイン: ギャップ分析
# ─────────────────────────────────────────────────────────

def analyze_gaps(
    report: StructuredReport,
    law_context: LawContext,
    use_mock: Optional[bool] = None,
) -> GapAnalysisResult:
    """
    ギャップ分析のメインエントリポイント（設計書 Section 2-3）。

    Args:
        report: M1出力の構造化有報
        law_context: M2出力の適用法令コンテキスト
        use_mock: True=モック / False=本番API / None=環境変数USE_MOCK_LLMで決定

    Returns:
        GapAnalysisResult

    Raises:
        ValueError: report.sections が空の場合（GAP_ERR_001）
    """
    logger = logging.getLogger(__name__)

    # 環境変数でモック切替
    if use_mock is None:
        use_mock = os.environ.get("USE_MOCK_LLM", "").lower() in ("true", "1", "yes")

    # ── STEP 1: 入力検証 ──
    if not report.sections:
        raise ValueError(
            "GAP_ERR_001: 有報テキストの抽出に失敗しました。"
            "M1エージェントの出力を確認してください。"
        )
    if not law_context.applicable_entries:
        logger.warning(
            "GAP_ERR_002: ⚠️ 適用法令エントリが0件です。"
            "対象年度・決算月の設定を確認してください。"
        )

    # ── クライアント初期化 ──
    client = None
    if not use_mock:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("ANTHROPIC_API_KEY 未設定。USE_MOCK_LLM=true に切替します。")
            use_mock = True
        else:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)

    # ── STEP 2: 関連セクション抽出 ──
    relevant_sections = [s for s in report.sections if is_relevant_section(s)]
    if not relevant_sections:
        # 関連セクションなし → 全セクションを対象
        logger.warning("人的資本関連セクションが見つかりません。全セクションを対象にします。")
        relevant_sections = report.sections

    logger.info(
        "document_id=%s fiscal_year=%s 対象セクション=%d件 法令エントリ=%d件",
        report.document_id, report.fiscal_year,
        len(relevant_sections), len(law_context.applicable_entries),
    )

    # ── STEP 3: エントリ×セクション のマトリクス判定 ──
    gaps: list[GapItem] = []
    no_gap_items: list[NoGapItem] = []
    gap_counter = 0
    total_input_tokens = 0
    total_output_tokens = 0

    for entry in law_context.applicable_entries:
        # disclosure_items が空のエントリはスキップ（GAP_ERR_005）
        if not entry.disclosure_items:
            logger.info("スキップ: %s (disclosure_items なし)", entry.id)
            continue

        for disclosure_item in entry.disclosure_items:
            # 各 disclosure_item × 関連セクション の組み合わせで判定
            item_has_gap = True  # 少なくとも1セクションでOKなら no_gap
            best_result: Optional[dict] = None
            best_section: Optional[SectionData] = None

            for section in relevant_sections:
                result, in_tok, out_tok = judge_gap(
                    section=section,
                    disclosure_item=disclosure_item,
                    law_entry=entry,
                    client=client,
                    use_mock=use_mock,
                )
                total_input_tokens += in_tok
                total_output_tokens += out_tok

                # コスト見積もりログ（設計書 Section 2: コスト見積もり）
                if in_tok > 0:
                    logger.debug(
                        "  API: %s × %s | in=%d out=%d tok",
                        entry.id[:20], section.section_id, in_tok, out_tok,
                    )

                if result.get("has_gap") is False:
                    # 充足確認 → このセクションで OK
                    item_has_gap = False
                    best_result = result
                    best_section = section
                    break  # 1セクションでOKなら以降のセクションを確認しない
                elif best_result is None or result.get("has_gap") is True:
                    # ギャップあり or 先頭セクション → 候補として保持
                    best_result = result
                    best_section = section

            # 根拠URL付与
            if best_result:
                best_result = attach_reference_url(best_result, entry)

            if item_has_gap:
                gap_counter += 1
                gap_id = f"GAP-{gap_counter:03d}"

                gap_item = GapItem(
                    gap_id=gap_id,
                    section_id=best_section.section_id if best_section else "N/A",
                    section_heading=best_section.heading if best_section else "N/A",
                    change_type=entry.change_type,
                    has_gap=best_result.get("has_gap"),
                    gap_description=best_result.get("gap_description"),
                    disclosure_item=disclosure_item,
                    reference_law_id=best_result.get("reference_law_id", entry.id),
                    reference_law_title=best_result.get("reference_law_title", entry.title),
                    reference_url=best_result.get("reference_url", entry.source),
                    source_confirmed=best_result.get("source_confirmed", entry.source_confirmed),
                    source_warning=best_result.get("source_warning"),
                    evidence_hint=best_result.get("evidence_hint", ""),
                    llm_reasoning=best_result.get("gap_description"),
                    confidence=best_result.get("confidence", Confidence.MEDIUM.value),
                )
                gaps.append(gap_item)
            else:
                no_gap_items.append(NoGapItem(
                    disclosure_item=disclosure_item,
                    reference_law_id=entry.id,
                    evidence_hint=best_result.get("evidence_hint", "") if best_result else "",
                    section_id=best_section.section_id if best_section else None,
                ))

    # ── STEP 5: 出力JSON生成 ──
    by_change_type: dict[str, int] = {ct.value: 0 for ct in ChangeType}
    for gap in gaps:
        if gap.has_gap is True:
            by_change_type[gap.change_type] = by_change_type.get(gap.change_type, 0) + 1

    real_gaps = [g for g in gaps if g.has_gap is True]
    summary = GapSummary(
        total_gaps=len(real_gaps),
        by_change_type=by_change_type,
    )

    metadata = GapMetadata(
        llm_model=LLM_MODEL if not use_mock else "mock",
        sections_analyzed=len(relevant_sections),
        entries_checked=len(law_context.applicable_entries),
        input_tokens_total=total_input_tokens,
        output_tokens_total=total_output_tokens,
    )

    logger.info(
        "ギャップ分析完了: total_gaps=%d, 入力%d tok, 出力%d tok",
        len(real_gaps), total_input_tokens, total_output_tokens,
    )

    return GapAnalysisResult(
        document_id=report.document_id,
        fiscal_year=report.fiscal_year,
        law_yaml_as_of=law_context.law_yaml_as_of,
        summary=summary,
        gaps=gaps,
        no_gap_items=no_gap_items,
        metadata=metadata,
    )


# ─────────────────────────────────────────────────────────
# 出力: GapAnalysisResult → dict（JSON化用）
# ─────────────────────────────────────────────────────────

def result_to_dict(result: GapAnalysisResult) -> dict:
    """GapAnalysisResult を JSON化可能な dict に変換する"""
    return {
        "document_id": result.document_id,
        "fiscal_year": result.fiscal_year,
        "gap_analysis_version": result.gap_analysis_version,
        "analyzed_at": result.analyzed_at,
        "law_yaml_as_of": result.law_yaml_as_of,
        "summary": {
            "total_gaps": result.summary.total_gaps,
            "by_change_type": result.summary.by_change_type,
        },
        "gaps": [
            {
                "gap_id": g.gap_id,
                "section_id": g.section_id,
                "section_heading": g.section_heading,
                "change_type": g.change_type,
                "has_gap": g.has_gap,
                "gap_description": g.gap_description,
                "disclosure_item": g.disclosure_item,
                "reference_law_id": g.reference_law_id,
                "reference_law_title": g.reference_law_title,
                "reference_url": g.reference_url,
                "source_confirmed": g.source_confirmed,
                "source_warning": g.source_warning,
                "evidence_hint": g.evidence_hint,
                "llm_reasoning": g.llm_reasoning,
                "confidence": g.confidence,
            }
            for g in result.gaps
        ],
        "no_gap_items": [
            {
                "disclosure_item": n.disclosure_item,
                "reference_law_id": n.reference_law_id,
                "evidence_hint": n.evidence_hint,
                "section_id": n.section_id,
            }
            for n in result.no_gap_items
        ],
        "metadata": {
            "llm_model": result.metadata.llm_model,
            "sections_analyzed": result.metadata.sections_analyzed,
            "entries_checked": result.metadata.entries_checked,
            "input_tokens_total": result.metadata.input_tokens_total,
            "output_tokens_total": result.metadata.output_tokens_total,
        },
    }


# ─────────────────────────────────────────────────────────
# デモ実行（モックデータ）
# ─────────────────────────────────────────────────────────

def _build_mock_report() -> StructuredReport:
    """モックの構造化有報を構築する（law_entries_human_capital.yaml の内容を考慮）"""
    return StructuredReport(
        document_id="S100VHUZ_MOCK",
        company_name="サンプル株式会社",
        fiscal_year=2025,
        fiscal_month_end=3,
        sections=[
            SectionData(
                section_id="HC-001",
                heading="e. 人的資本経営に関する指標",
                level=3,
                text=(
                    "当社は人材の確保・育成・定着を重要課題と位置づけており、"
                    "人材育成方針として「全社員の継続的スキルアップ」を掲げています。"
                    "女性管理職比率は連結14.1%（単体13.2%）です。"
                    "男女間賃金格差は94.3%（対男性）です。"
                ),
                tables=[
                    TableData(
                        caption="人的資本関連指標",
                        rows=[
                            ["指標", "2023年度", "2024年度"],
                            ["女性管理職比率", "12.3%", "14.1%"],
                            ["男女賃金格差", "93.1%", "94.3%"],
                        ],
                    )
                ],
            ),
            SectionData(
                section_id="DIV-001",
                heading="f. 多様性に関する指標",
                level=3,
                text=(
                    "当社は多様性・公平性・包摂性（DEI）を経営の重要課題と位置づけています。"
                    "社内環境整備方針として、フレックスタイム制度・テレワーク制度を整備しています。"
                    "男性育児休業取得率は42.3%（2024年度実績）です。"
                ),
                tables=[],
            ),
            SectionData(
                section_id="EMP-001",
                heading="従業員の状況",
                level=2,
                text=(
                    "従業員数は連結2,450名（単体1,820名）です。"
                    "平均年齢は38.2歳、平均年間給与は7,250千円です。"
                    "前事業年度の平均年間給与は6,980千円でした。"
                    # 注: 対前年増減率や給与決定方針の記載なし（ギャップとして検出されるべき）
                ),
                tables=[],
            ),
        ],
    )


def _build_mock_law_context() -> LawContext:
    """モックの法令コンテキストを構築する（HC_20260220_001 と HC_20230131_001）"""
    return LawContext(
        fiscal_year=2025,
        fiscal_month_end=3,
        law_yaml_as_of="2026-02-27",
        applicable_entries=[
            LawEntry(
                id="HC_20230131_001",
                title="企業内容等の開示に関する内閣府令改正（人的資本・多様性開示の義務化）",
                category="金商法・開示府令",
                change_type="追加必須",
                disclosure_items=[
                    "人材育成方針の記載（必須）",
                    "社内環境整備方針の記載（必須）",
                    "女性管理職比率（連結・単体）の開示（必須）",
                    "男性育児休業取得率の開示（必須）",
                    "男女間賃金格差の開示（必須）",
                ],
                source="https://www.fsa.go.jp/news/r4/sonota/20230131/20230131.html",
                source_confirmed=False,
                effective_from="2023-01-31",
            ),
            LawEntry(
                id="HC_20260220_001",
                title="企業内容等の開示に関する内閣府令改正（人的資本開示拡充・給与開示）",
                category="金商法・開示府令",
                change_type="追加必須",
                disclosure_items=[
                    "企業戦略と関連付けた人材戦略の記載（必須）",
                    "従業員給与等の決定に関する方針の記載（必須）",
                    "平均年間給与の対前事業年度増減率の記載（必須）",
                ],
                source="https://sustainablejapan.jp/2026/02/23/fsa-ssbj-4/122214",
                source_confirmed=True,
                effective_from="2026-02-20",
            ),
        ],
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    print("=== disclosure-multiagent M3: ギャップ分析エージェント デモ ===")
    print("USE_MOCK_LLM=true でモックモード実行")
    print()

    report = _build_mock_report()
    law_context = _build_mock_law_context()

    result = analyze_gaps(report, law_context, use_mock=True)
    output = result_to_dict(result)

    print(json.dumps(output, ensure_ascii=False, indent=2))
    print()
    print(f"total_gaps: {result.summary.total_gaps}")
    print(f"by_change_type: {result.summary.by_change_type}")
    print(f"sections_analyzed: {result.metadata.sections_analyzed}")
