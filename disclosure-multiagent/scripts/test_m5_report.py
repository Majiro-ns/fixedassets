"""
test_m5_report.py
=================
disclosure-multiagent Phase 1-M5: レポート統合エージェント テストスイート

TEST 1: generate_report() の出力がMarkdown形式で必須セクション（6つ）を含む
TEST 2: law_yaml_as_of がヘッダーに含まれている
TEST 3: source_confirmed=False エントリが含まれる場合、警告バナーが2箇所に表示される
TEST 4: level="竹" 選択時に竹の提案文が含まれている
TEST 5: CHECK-7b 法令参照期間テキスト（2025年度3月決算 → "2025/04/01〜2026/03/31"）
TEST 6: pipeline_mock() がエラーなく実行され、Markdown出力が空でない
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

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
)
from m4_proposal_agent import (  # noqa: E402
    ProposalSet,
    Proposal,
    QualityCheckResult,
    GapItem as M4GapItem,
)
from m5_report_agent import generate_report, pipeline_mock, calc_law_ref_period  # noqa: E402

# ─────────────────────────────────────────────────────────
# テスト用定数
# ─────────────────────────────────────────────────────────

LAW_YAML_AS_OF = "2026-02-27"
GAP_ID = "GAP-001"
TEST_URL = "https://example.com/law/test"
TEST_URL_UNCONFIRMED = "https://example.com/law/unconfirmed"


# ─────────────────────────────────────────────────────────
# テスト用ヘルパー関数
# ─────────────────────────────────────────────────────────


def _make_structured_report(
    fiscal_year: int = 2025,
    fiscal_month_end: int = 3,
    company_name: str = "テスト株式会社",
) -> StructuredReport:
    return StructuredReport(
        document_id="TEST-DOC-001",
        company_name=company_name,
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
        sections=[
            SectionData(
                section_id="S-001",
                heading="人的資本に関する指標",
                level=3,
                text="テスト用テキスト",
            )
        ],
    )


def _make_law_context(
    fiscal_year: int = 2025,
    fiscal_month_end: int = 3,
    source_confirmed: bool = True,
) -> LawContext:
    url = TEST_URL if source_confirmed else TEST_URL_UNCONFIRMED
    return LawContext(
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
        law_yaml_as_of=LAW_YAML_AS_OF,
        applicable_entries=[
            LawEntry(
                id="HC_TEST_001",
                title="テスト法令（人的資本開示）",
                category="金商法",
                change_type="追加必須",
                disclosure_items=["テスト開示項目"],
                source=url,
                source_confirmed=source_confirmed,
            )
        ],
    )


def _make_quality(warnings: list[str] | None = None) -> QualityCheckResult:
    return QualityCheckResult(
        passed=True,
        should_regenerate=False,
        warnings=warnings or [],
    )


def _make_gap_item(
    gap_id: str = GAP_ID,
    source_confirmed: bool = True,
    change_type: str = "追加必須",
) -> M3GapItem:
    url = TEST_URL if source_confirmed else TEST_URL_UNCONFIRMED
    return M3GapItem(
        gap_id=gap_id,
        section_id="S-001",
        section_heading="人的資本に関する指標",
        change_type=change_type,
        has_gap=True,
        disclosure_item="テスト開示項目",
        reference_law_id="HC_TEST_001",
        reference_law_title="テスト法令（人的資本開示）",
        reference_url=url,
        source_confirmed=source_confirmed,
        source_warning=(
            "このURLは実アクセス未確認です" if not source_confirmed else None
        ),
        evidence_hint="テキスト内にキーワードが見当たらない",
    )


def _make_gap_analysis_result(
    fiscal_year: int = 2025,
    gaps: list[M3GapItem] | None = None,
    no_gap_items: list[NoGapItem] | None = None,
) -> GapAnalysisResult:
    if gaps is None:
        gaps = [_make_gap_item()]
    if no_gap_items is None:
        no_gap_items = []
    by_change_type: dict[str, int] = {}
    for g in gaps:
        by_change_type[g.change_type] = by_change_type.get(g.change_type, 0) + 1
    return GapAnalysisResult(
        document_id="TEST-DOC-001",
        fiscal_year=fiscal_year,
        law_yaml_as_of=LAW_YAML_AS_OF,
        summary=GapSummary(
            total_gaps=len(gaps),
            by_change_type=by_change_type,
        ),
        gaps=gaps,
        no_gap_items=no_gap_items,
        metadata=GapMetadata(
            llm_model="mock",
            sections_analyzed=1,
            entries_checked=1,
        ),
    )


def _make_proposal_set(
    gap_id: str = GAP_ID,
    take_text: str = (
        "竹レベルのテスト提案文。中期経営計画に沿った人材戦略の取組みを記載します。"
        "スタンダード実務向けの内容です。人材育成方針を明示し、育成プログラムを整備しています。"
    ),
    matsu_text: str = (
        "松レベルのテスト提案文。充実開示向けの詳細な記載例です。"
        "KPI・数値目標・ガバナンス体制を含む充実した内容を記載します。"
        "2030年ビジョンに掲げる事業成長率の達成に向け、事業戦略と連動した人材戦略を策定しています。"
    ),
    ume_text: str = "梅レベルのテスト提案文。最小限対応向けシンプル記載。",
) -> ProposalSet:
    return ProposalSet(
        gap_id=gap_id,
        disclosure_item="テスト開示項目",
        reference_law_id="HC_TEST_001",
        reference_url=TEST_URL,
        source_warning=None,
        matsu=Proposal(level="松", text=matsu_text, quality=_make_quality()),
        take=Proposal(level="竹", text=take_text, quality=_make_quality()),
        ume=Proposal(level="梅", text=ume_text, quality=_make_quality()),
    )


def _run_generate_report(
    fiscal_year: int = 2025,
    fiscal_month_end: int = 3,
    source_confirmed: bool = True,
    level: str = "竹",
    proposal_set: list[ProposalSet] | None = None,
    gaps: list[M3GapItem] | None = None,
) -> str:
    """generate_report() を共通設定で呼び出す"""
    report = _make_structured_report(
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
    )
    law = _make_law_context(
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
        source_confirmed=source_confirmed,
    )
    if gaps is None:
        gaps = [_make_gap_item(source_confirmed=source_confirmed)]
    gap_result = _make_gap_analysis_result(fiscal_year=fiscal_year, gaps=gaps)
    if proposal_set is None:
        proposal_set = [_make_proposal_set(gap_id=gaps[0].gap_id)]
    return generate_report(report, law, gap_result, proposal_set, level)


# ─────────────────────────────────────────────────────────
# TEST 1: 必須セクション6つを含む
# ─────────────────────────────────────────────────────────


class TestRequiredSections(unittest.TestCase):
    """TEST 1: generate_report() の出力がMarkdown形式で必須セクション（6つ）を含む"""

    def setUp(self) -> None:
        self.md = _run_generate_report()

    def test_is_markdown_starts_with_heading(self) -> None:
        """Markdown形式: # で始まる最上位見出しあり"""
        self.assertTrue(self.md.startswith("#"))

    def test_has_title_header(self) -> None:
        """タイトル: # 開示変更レポート"""
        self.assertIn("# 開示変更レポート", self.md)

    def test_has_disclaimer_header(self) -> None:
        """ヘッダー免責（但し書き・免責事項）"""
        self.assertIn("但し書き・免責事項", self.md)

    def test_has_section_1_summary(self) -> None:
        """Section 1: 変更箇所サマリ"""
        self.assertIn("## 1. 変更箇所サマリ", self.md)

    def test_has_section_2_gap_detail(self) -> None:
        """Section 2: セクション別の変更提案"""
        self.assertIn("## 2. セクション別の変更提案", self.md)

    def test_has_section_3_no_gap(self) -> None:
        """Section 3: 未変更項目"""
        self.assertIn("## 3. 未変更項目", self.md)

    def test_has_section_4_law_list(self) -> None:
        """Section 4: 参照した法令・ガイダンス一覧"""
        self.assertIn("## 4. 参照した法令・ガイダンス一覧", self.md)

    def test_has_section_5_disclaimer_detail(self) -> None:
        """Section 5: 免責事項"""
        self.assertIn("## 5. 免責事項", self.md)

    def test_returns_string(self) -> None:
        """str 型を返す"""
        self.assertIsInstance(self.md, str)

    def test_not_empty(self) -> None:
        """空文字列でない"""
        self.assertGreater(len(self.md), 0)


# ─────────────────────────────────────────────────────────
# TEST 2: law_yaml_as_of がヘッダーに含まれる
# ─────────────────────────────────────────────────────────


class TestLawYamlAsOf(unittest.TestCase):
    """TEST 2: law_yaml_as_of がヘッダーに含まれている"""

    def test_law_yaml_as_of_value_in_header(self) -> None:
        """法令情報取得日の値 (2026-02-27) がヘッダーセクションに含まれる"""
        md = _run_generate_report()
        # Section 1 より前がヘッダー
        header_part = md.split("## 1.")[0]
        self.assertIn(LAW_YAML_AS_OF, header_part,
                      f"'{LAW_YAML_AS_OF}' がヘッダーに見当たらない")

    def test_law_yaml_label_in_header(self) -> None:
        """「法令情報取得日」ラベルがヘッダーに含まれる"""
        md = _run_generate_report()
        header_part = md.split("## 1.")[0]
        self.assertIn("法令情報取得日", header_part)

    def test_law_yaml_as_of_in_disclaimer_detail(self) -> None:
        """law_yaml_as_of が免責事項詳細（Section 5）にも含まれる"""
        md = _run_generate_report()
        disclaimer_part = md.split("## 5.")[1] if "## 5." in md else ""
        self.assertIn(LAW_YAML_AS_OF, disclaimer_part)


# ─────────────────────────────────────────────────────────
# TEST 3: source_confirmed=False 警告バナーが2箇所に表示
# ─────────────────────────────────────────────────────────


class TestSourceUnconfirmedWarning(unittest.TestCase):
    """TEST 3: source_confirmed=False の場合、警告バナーが2箇所に表示される"""

    def test_warning_banner_in_header(self) -> None:
        """ヘッダーに ⚠️ 要確認 バナーが表示される"""
        md = _run_generate_report(source_confirmed=False)
        header_part = md.split("## 1.")[0]
        self.assertIn("⚠️", header_part,
                      "ヘッダーに⚠️バナーがない")
        self.assertIn("要確認", header_part,
                      "ヘッダーに「要確認」がない")

    def test_warning_in_gap_detail(self) -> None:
        """ギャップ詳細（Section 2）内に ⚠️ 警告が表示される"""
        md = _run_generate_report(source_confirmed=False)
        section2_marker = "## 2. セクション別の変更提案"
        section3_marker = "## 3. 未変更項目"
        self.assertIn(section2_marker, md, "Section 2 が見当たらない")
        # Section 2〜3 の間を抽出
        start = md.index(section2_marker) + len(section2_marker)
        end = md.index(section3_marker) if section3_marker in md else len(md)
        gap_detail_part = md[start:end]
        self.assertIn("⚠️", gap_detail_part,
                      "ギャップ詳細に⚠️警告がない")

    def test_warning_count_at_least_two(self) -> None:
        """⚠️ が2箇所以上（ヘッダー1 + ギャップ詳細1）に出現する"""
        md = _run_generate_report(source_confirmed=False)
        count = md.count("⚠️")
        self.assertGreaterEqual(count, 2,
                                f"⚠️ の出現回数が {count} 件（2件以上必要）")

    def test_no_warning_when_all_confirmed(self) -> None:
        """source_confirmed=True の場合はヘッダーに「要確認」バナーなし"""
        md = _run_generate_report(source_confirmed=True)
        header_part = md.split("## 1.")[0]
        self.assertNotIn("要確認", header_part,
                         "確認済みなのにヘッダーに警告バナーが表示された")

    def test_unconfirmed_url_listed_in_header_banner(self) -> None:
        """未確認URLがヘッダーバナー内にリスト表示される"""
        md = _run_generate_report(source_confirmed=False)
        header_part = md.split("## 1.")[0]
        self.assertIn(TEST_URL_UNCONFIRMED, header_part,
                      "未確認URLがヘッダーバナーに表示されていない")


# ─────────────────────────────────────────────────────────
# TEST 4: level="竹" 選択時に竹の提案文が含まれる
# ─────────────────────────────────────────────────────────


class TestProposalLevelSelection(unittest.TestCase):
    """TEST 4: level 選択時に該当レベルの提案文が含まれている"""

    TAKE_TEXT = (
        "竹レベル専用識別テキスト。中期経営計画に基づく人材戦略の具体的内容を記載します。"
        "OJTと集合研修を組み合わせた体系的なプログラムを整備しています。"
    )
    MATSU_TEXT = (
        "松レベル専用識別テキスト。充実開示向けKPI・数値目標・ガバナンス体制を含む。"
        "デジタル専門人材を2028年度末までに現状比2倍に拡充する計画です。"
    )
    UME_TEXT = "梅レベル専用識別テキスト。最小限対応向けの簡潔な記載例。"

    def setUp(self) -> None:
        self.gap = _make_gap_item()
        self.ps = _make_proposal_set(
            take_text=self.TAKE_TEXT,
            matsu_text=self.MATSU_TEXT,
            ume_text=self.UME_TEXT,
        )
        self.report = _make_structured_report()
        self.law = _make_law_context()
        self.gap_result = _make_gap_analysis_result(gaps=[self.gap])

    def _run(self, level: str) -> str:
        return generate_report(
            self.report, self.law, self.gap_result, [self.ps], level
        )

    def test_take_text_in_take_level_report(self) -> None:
        """level=竹 のとき竹専用テキストが含まれる"""
        md = self._run("竹")
        self.assertIn(self.TAKE_TEXT, md)

    def test_take_level_heading_in_take_report(self) -> None:
        """level=竹 のとき「竹レベルの提案文」見出しが含まれる"""
        md = self._run("竹")
        self.assertIn("竹レベルの提案文", md)

    def test_matsu_text_in_matsu_level_report(self) -> None:
        """level=松 のとき松専用テキストが含まれる"""
        md = self._run("松")
        self.assertIn(self.MATSU_TEXT, md)

    def test_matsu_level_heading_in_matsu_report(self) -> None:
        """level=松 のとき「松レベルの提案文」見出しが含まれる"""
        md = self._run("松")
        self.assertIn("松レベルの提案文", md)

    def test_ume_text_in_ume_level_report(self) -> None:
        """level=梅 のとき梅専用テキストが含まれる"""
        md = self._run("梅")
        self.assertIn(self.UME_TEXT, md)

    def test_ume_level_heading_in_ume_report(self) -> None:
        """level=梅 のとき「梅レベルの提案文」見出しが含まれる"""
        md = self._run("梅")
        self.assertIn("梅レベルの提案文", md)


# ─────────────────────────────────────────────────────────
# TEST 5: CHECK-7b 法令参照期間テキスト
# ─────────────────────────────────────────────────────────


class TestLawRefPeriod(unittest.TestCase):
    """TEST 5: CHECK-7b 2025年度3月決算 → "2025/04/01 〜 2026/03/31" がヘッダーに含まれる"""

    def test_calc_law_ref_period_start(self) -> None:
        """CHECK-7b 手計算: 2025年度3月決算 開始日 = 2025/04/01"""
        start, _ = calc_law_ref_period(2025, 3)
        self.assertEqual(start, "2025/04/01",
                         f"開始日の手計算結果: 2025/04/01 ≠ {start}")

    def test_calc_law_ref_period_end(self) -> None:
        """CHECK-7b 手計算: 2025年度3月決算 終了日 = 2026/03/31"""
        _, end = calc_law_ref_period(2025, 3)
        self.assertEqual(end, "2026/03/31",
                         f"終了日の手計算結果: 2026/03/31 ≠ {end}")

    def test_law_ref_start_in_header(self) -> None:
        """開始日 2025/04/01 がレポートヘッダーに含まれる"""
        md = _run_generate_report(fiscal_year=2025, fiscal_month_end=3)
        header_part = md.split("## 1.")[0]
        self.assertIn("2025/04/01", header_part,
                      "開始日 2025/04/01 がヘッダーにない")

    def test_law_ref_end_in_header(self) -> None:
        """終了日 2026/03/31 がレポートヘッダーに含まれる"""
        md = _run_generate_report(fiscal_year=2025, fiscal_month_end=3)
        header_part = md.split("## 1.")[0]
        self.assertIn("2026/03/31", header_part,
                      "終了日 2026/03/31 がヘッダーにない")

    def test_law_ref_period_full_string_in_report(self) -> None:
        """「2025/04/01 〜 2026/03/31」が連続してレポートに含まれる"""
        md = _run_generate_report(fiscal_year=2025, fiscal_month_end=3)
        self.assertIn("2025/04/01 〜 2026/03/31", md,
                      "「2025/04/01 〜 2026/03/31」が連続して含まれない")

    def test_law_ref_period_label_in_header(self) -> None:
        """「法令参照期間」ラベルがヘッダーに含まれる"""
        md = _run_generate_report(fiscal_year=2025, fiscal_month_end=3)
        header_part = md.split("## 1.")[0]
        self.assertIn("法令参照期間", header_part)


# ─────────────────────────────────────────────────────────
# TEST 6: pipeline_mock() E2Eパイプライン
# ─────────────────────────────────────────────────────────


class TestPipelineMock(unittest.TestCase):
    """TEST 6: pipeline_mock() がエラーなく実行され、Markdown出力が空でない"""

    def test_pipeline_mock_returns_string(self) -> None:
        """pipeline_mock() が str を返す"""
        result = pipeline_mock()
        self.assertIsInstance(result, str)

    def test_pipeline_mock_not_empty(self) -> None:
        """pipeline_mock() の出力が空でない"""
        result = pipeline_mock()
        self.assertGreater(len(result), 0)

    def test_pipeline_mock_is_markdown(self) -> None:
        """pipeline_mock() の出力が Markdown 形式（# 見出しあり）"""
        result = pipeline_mock()
        self.assertIn("# 開示変更レポート", result)

    def test_pipeline_mock_company_name_reflected(self) -> None:
        """pipeline_mock(company_name=...) が企業名をレポートに反映する"""
        company = "テスト商事株式会社"
        result = pipeline_mock(company_name=company)
        self.assertIn(company, result)

    def test_pipeline_mock_level_reflected(self) -> None:
        """pipeline_mock(level=梅) が梅レベルをレポートに反映する"""
        result = pipeline_mock(level="梅")
        self.assertIn("梅", result)

    def test_pipeline_mock_section_2_exists(self) -> None:
        """pipeline_mock() の出力に Section 2（変更提案）が含まれる"""
        result = pipeline_mock()
        self.assertIn("## 2. セクション別の変更提案", result)

    def test_pipeline_mock_e2e_law_ref_period(self) -> None:
        """pipeline_mock(fiscal_year=2025) の出力に 2025/04/01 が含まれる"""
        result = pipeline_mock(fiscal_year=2025)
        self.assertIn("2025/04/01", result)


# ─────────────────────────────────────────────────────────
# TEST 7: M5×M8 統合テスト — generate_report(year_diff=...) による Section 6
# ─────────────────────────────────────────────────────────

from m8_multiyear_agent import YearDiff  # noqa: E402
from m3_gap_analysis_agent import SectionData  # noqa: E402 (already imported above)


def _make_section_data(heading: str, text: str) -> SectionData:
    """テスト用 SectionData を生成"""
    return SectionData(section_id=f"SEC-{heading[:6]}", heading=heading, text=text)


def _make_year_diff(
    year_from: int = 2024,
    year_to: int = 2025,
    added: list[SectionData] | None = None,
    removed: list[SectionData] | None = None,
    changed: list[SectionData] | None = None,
) -> YearDiff:
    """テスト用 YearDiff を生成"""
    added = added or []
    removed = removed or []
    changed = changed or []
    parts = []
    if added:
        parts.append(f"追加: {len(added)}件")
    if removed:
        parts.append(f"削除: {len(removed)}件")
    if changed:
        parts.append(f"変更: {len(changed)}件")
    if not parts:
        parts = ["差分なし"]
    summary = f"{year_from}年度 → {year_to}年度: " + ", ".join(parts)
    return YearDiff(
        fiscal_year_from=year_from,
        fiscal_year_to=year_to,
        added_sections=added,
        removed_sections=removed,
        changed_sections=changed,
        summary=summary,
    )


class TestM5M8Integration(unittest.TestCase):
    """TEST 7: M5×M8 統合テスト（generate_report の year_diff パラメータ）

    CHECK-7b 手計算:
        year_diff = YearDiff(2024→2025, added=[ESG戦略], removed=[経営方針], changed=[人材戦略])
        Section 6 ヘッダー: "## 6. 複数年度比較（2024年度 → 2025年度）"
        6.1 追加: "➕ ESG戦略" が含まれる
        6.2 削除: "➖ 経営方針" が含まれる
        6.3 変更: "✏️ 人材戦略" が含まれる ✓
    """

    def setUp(self) -> None:
        self.report = _make_structured_report()
        self.law = _make_law_context()
        self.gap_item = _make_gap_item()
        self.gap_result = _make_gap_analysis_result(gaps=[self.gap_item])
        self.proposals = [_make_proposal_set(gap_id=self.gap_item.gap_id)]

        # 各種テスト用セクション
        self.added_sec = _make_section_data("ESG戦略", "ESGへの取り組みを記載する。")
        self.removed_sec = _make_section_data("経営方針", "経営の基本方針を記載する。")
        self.changed_sec = _make_section_data("人材戦略", "大幅に刷新した人材戦略を記載する。")

        # 標準的な year_diff（追加1件・削除1件・変更1件）
        self.year_diff_full = _make_year_diff(
            year_from=2024,
            year_to=2025,
            added=[self.added_sec],
            removed=[self.removed_sec],
            changed=[self.changed_sec],
        )
        # 差分なし
        self.year_diff_empty = _make_year_diff(2023, 2024)

    def _run(self, year_diff: "YearDiff | None") -> str:
        return generate_report(
            self.report, self.law, self.gap_result, self.proposals, "竹",
            year_diff=year_diff,
        )

    def test_section6_present_when_year_diff_provided(self) -> None:
        """year_diff 指定時に Section 6「複数年度比較」が出力される

        手計算: year_diff=YearDiff(2024→2025, ...) → "## 6. 複数年度比較" 含む ✓
        """
        md = self._run(self.year_diff_full)
        self.assertIn("## 6. 複数年度比較", md,
                      "year_diff 指定時に Section 6 が含まれない")

    def test_section6_absent_when_no_year_diff(self) -> None:
        """year_diff=None（デフォルト）時に Section 6 が出力されない

        手計算: year_diff=None → "## 6." はレポートに含まれない ✓
        """
        md = self._run(None)
        self.assertNotIn("## 6. 複数年度比較", md,
                         "year_diff=None なのに Section 6 が含まれる")

    def test_section6_year_range_in_header(self) -> None:
        """Section 6 ヘッダーに year_from → year_to の年度範囲が含まれる

        手計算: fiscal_year_from=2024, fiscal_year_to=2025
        → "2024年度 → 2025年度" が Section 6 見出しに含まれる ✓
        """
        md = self._run(self.year_diff_full)
        self.assertIn("2024年度", md, "2024年度 が Section 6 に含まれない")
        self.assertIn("2025年度", md, "2025年度 が Section 6 に含まれない")

    def test_section6_summary_present(self) -> None:
        """Section 6 に year_diff.summary が含まれる"""
        md = self._run(self.year_diff_full)
        self.assertIn(self.year_diff_full.summary, md,
                      f"summary '{self.year_diff_full.summary}' が Section 6 に含まれない")

    def test_section6_added_section_listed(self) -> None:
        """Section 6.1 に追加セクション名（➕マーカー付き）が含まれる

        手計算: added=[ESG戦略] → "➕ **ESG戦略**" が Section 6.1 に含まれる ✓
        """
        md = self._run(self.year_diff_full)
        self.assertIn("➕", md, "➕マーカーが Section 6 に含まれない")
        self.assertIn("ESG戦略", md, "追加セクション 'ESG戦略' が Section 6 に含まれない")

    def test_section6_removed_section_listed(self) -> None:
        """Section 6.2 に削除セクション名（➖マーカー付き）が含まれる

        手計算: removed=[経営方針] → "➖ **経営方針**" が Section 6.2 に含まれる ✓
        """
        md = self._run(self.year_diff_full)
        self.assertIn("➖", md, "➖マーカーが Section 6 に含まれない")
        self.assertIn("経営方針", md, "削除セクション '経営方針' が Section 6 に含まれない")

    def test_section6_changed_section_listed(self) -> None:
        """Section 6.3 に変更セクション名（✏️マーカー付き）が含まれる

        手計算: changed=[人材戦略] → "✏️ **人材戦略**" が Section 6.3 に含まれる ✓
        """
        md = self._run(self.year_diff_full)
        self.assertIn("✏️", md, "✏️マーカーが Section 6 に含まれない")
        self.assertIn("人材戦略", md, "変更セクション '人材戦略' が Section 6 に含まれない")

    def test_section6_no_diff_shows_none_message(self) -> None:
        """差分なし（added/removed/changed 全空）のとき「なし」メッセージが表示される"""
        md = self._run(self.year_diff_empty)
        self.assertIn("## 6. 複数年度比較", md, "Section 6 が含まれない")
        self.assertIn("なし", md,
                      "差分なし時に「なし」メッセージが含まれない")

    def test_existing_sections_1_to_5_intact_with_year_diff(self) -> None:
        """year_diff 指定時も Section 1〜5 が正常に出力される（回帰テスト）

        手計算: year_diff あり → Section 1〜5 はそのまま、Section 6 が追加 ✓
        """
        md = self._run(self.year_diff_full)
        for section_header in [
            "## 1. 変更箇所サマリ",
            "## 2. セクション別の変更提案",
            "## 3. 未変更項目",
            "## 4. 参照した法令・ガイダンス一覧",
            "## 5. 免責事項",
        ]:
            self.assertIn(section_header, md,
                          f"year_diff あり時に '{section_header}' が欠落している")


if __name__ == "__main__":
    unittest.main(verbosity=2)
