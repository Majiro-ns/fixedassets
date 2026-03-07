"""
test_m1_pdf_agent.py
====================
disclosure-multiagent Phase 1-M1: PDF解析エージェント テスト

実装者: 足軽4 subtask_063a11
作成日: 2026-02-27

テスト仕様（subtask_063a11 要件定義より）:
  TEST 1: StructuredReport の構築と dict 変換
  TEST 2: セクション分割ロジック（モックテキストで検証）
           - 「第一部 企業情報」で分割できる
           - 「1【サステナビリティに関する考え方及び取組】」で分割できる
  TEST 3: 人的資本セクションのフィルタ（JINJI_SECTION_KEYWORDS含むセクションが抽出される）
  TEST 4: CHECK-7b JINJI_SECTION_KEYWORDS確認（12件・手計算）
  TEST 5: エラーハンドリング（存在しないファイルパス → FileNotFoundError）

実PDFなしで全テスト動作（モックテキスト使用）。
"""

import sys
import os
import unittest
from pathlib import Path

# scriptsディレクトリをパスに追加
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from m1_pdf_agent import (
    JINJI_SECTION_KEYWORDS,
    HEADING_PATTERNS,
    SHOSHU_SECTION_KEYWORDS,
    SHOSHU_HEADING_PATTERNS,
    MAX_SECTION_CHARS,
    split_sections_from_text,
    get_human_capital_sections,
    get_shoshu_sections,
    report_to_dict,
    _is_heading_line,
    _infer_heading_level,
    _is_heading_line_for_doc_type,
)
from m3_gap_analysis_agent import (
    StructuredReport,
    SectionData,
    TableData,
)


# ═══════════════════════════════════════════════════════════════
# TEST 1: StructuredReport の構築と dict 変換
# ═══════════════════════════════════════════════════════════════

class TestStructuredReportBuilding(unittest.TestCase):
    """TEST 1: StructuredReport の構築と dict 変換"""

    def test_structured_report_construction(self):
        """StructuredReport を正しく構築できる"""
        sections = [
            SectionData(
                section_id="SEC-001",
                heading="第一部 企業情報",
                text="企業情報のテキスト",
                level=1,
            ),
            SectionData(
                section_id="SEC-002",
                heading="1【事業の概要】",
                text="事業概要のテキスト",
                level=2,
            ),
        ]
        report = StructuredReport(
            document_id="TEST_ABC123",
            company_name="テスト株式会社",
            fiscal_year=2025,
            fiscal_month_end=3,
            sections=sections,
        )
        self.assertEqual(report.document_id, "TEST_ABC123")
        self.assertEqual(report.company_name, "テスト株式会社")
        self.assertEqual(report.fiscal_year, 2025)
        self.assertEqual(report.fiscal_month_end, 3)
        self.assertEqual(len(report.sections), 2)
        self.assertEqual(report.sections[0].section_id, "SEC-001")
        self.assertEqual(report.sections[1].heading, "1【事業の概要】")

    def test_report_to_dict_structure(self):
        """report_to_dict が JSON 化可能な dict を返す"""
        table = TableData(
            caption="従業員数",
            rows=[["項目", "人数"], ["正社員", "1000"]],
        )
        section = SectionData(
            section_id="SEC-001",
            heading="第一部 企業情報",
            text="テキスト内容",
            level=1,
            tables=[table],
        )
        report = StructuredReport(
            document_id="DOC_001",
            company_name="サンプル株式会社",
            fiscal_year=2025,
            fiscal_month_end=3,
            sections=[section],
        )
        d = report_to_dict(report)

        # トップレベルキー確認
        self.assertIn("document_id", d)
        self.assertIn("company_name", d)
        self.assertIn("fiscal_year", d)
        self.assertIn("fiscal_month_end", d)
        self.assertIn("sections", d)
        self.assertIn("extraction_library", d)
        self.assertIn("extracted_at", d)

        # セクション内容確認
        self.assertEqual(len(d["sections"]), 1)
        sec_d = d["sections"][0]
        self.assertEqual(sec_d["section_id"], "SEC-001")
        self.assertEqual(sec_d["heading"], "第一部 企業情報")
        self.assertEqual(sec_d["level"], 1)
        self.assertIn("text", sec_d)
        self.assertIn("text_length", sec_d)
        self.assertIn("tables", sec_d)
        self.assertEqual(sec_d["tables"][0]["caption"], "従業員数")
        self.assertEqual(sec_d["tables"][0]["rows_count"], 2)

    def test_section_data_defaults(self):
        """SectionData のデフォルト値が正しい"""
        s = SectionData(
            section_id="SEC-001",
            heading="テスト",
            text="本文",
        )
        self.assertEqual(s.level, 3)  # デフォルトlevel=3
        self.assertEqual(s.tables, [])
        self.assertIsNone(s.parent_section_id)


# ═══════════════════════════════════════════════════════════════
# TEST 2: セクション分割ロジック（モックテキストで検証）
# ═══════════════════════════════════════════════════════════════

class TestSectionSplitting(unittest.TestCase):
    """TEST 2: セクション分割ロジック（モックテキストで検証）"""

    def test_split_by_daichi_heading(self):
        """「第一部 企業情報」で分割できる（HEADING_PATTERNS パターン1）"""
        mock_text = """第一部 企業情報
企業情報に関する記述がここに入る。

第二部 提出会社の保証会社等の情報
保証会社等の情報がここに入る。
"""
        sections = split_sections_from_text(mock_text)
        self.assertGreaterEqual(len(sections), 2)

        headings = [s.heading for s in sections]
        self.assertTrue(
            any("第一部" in h for h in headings),
            f"「第一部」が見出しとして検出されていない。検出された見出し: {headings}"
        )
        self.assertTrue(
            any("第二部" in h for h in headings),
            f"「第二部」が見出しとして検出されていない。検出された見出し: {headings}"
        )

    def test_split_by_number_kakko_heading(self):
        """「1【サステナビリティに関する考え方及び取組】」で分割できる（パターン3）"""
        mock_text = """第一部 企業情報
企業情報のイントロ

1【事業の概要】
事業概要の内容

2【サステナビリティに関する考え方及び取組】
サステナビリティの取組内容。
人的資本への投資を強化します。
"""
        sections = split_sections_from_text(mock_text)
        headings = [s.heading for s in sections]

        self.assertTrue(
            any("サステナビリティ" in h for h in headings),
            f"「サステナビリティ」見出しが未検出。検出された見出し: {headings}"
        )
        self.assertTrue(
            any("1【事業の概要】" in h or "事業の概要" in h for h in headings),
            f"「1【事業の概要】」見出しが未検出。検出された見出し: {headings}"
        )

    def test_section_body_text_is_captured(self):
        """セクション本文が正しく切り取られる"""
        mock_text = """第一部 企業情報
この部には企業情報の詳細が記載される。

1【事業の概要】
事業の概要として、当社は製造業を営む。
"""
        sections = split_sections_from_text(mock_text)
        # 「第一部 企業情報」の本文に「企業情報の詳細」が含まれるか
        sec1 = next((s for s in sections if "第一部" in s.heading), None)
        self.assertIsNotNone(sec1, "「第一部」セクションが見つからない")
        self.assertIn("企業情報の詳細", sec1.text)

    def test_no_heading_text_becomes_single_section(self):
        """見出しパターンが1件も検出されない場合は全文を1セクションとして返す"""
        mock_text = "これは見出しのないテキストです。\n改行のある普通のテキスト。\n"
        sections = split_sections_from_text(mock_text)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].section_id, "SEC-001")
        self.assertEqual(sections[0].heading, "（見出し未検出）")
        self.assertIn("見出しのないテキスト", sections[0].text)

    def test_is_heading_line_daichi(self):
        """_is_heading_line が「第一部」を見出しと認識する"""
        self.assertTrue(_is_heading_line("第一部 企業情報"))
        self.assertTrue(_is_heading_line("第二部 提出会社の保証会社等の情報"))

    def test_is_heading_line_number_kakko(self):
        """_is_heading_line が「1【...】」を見出しと認識する"""
        self.assertTrue(_is_heading_line("1【事業の概要】"))
        self.assertTrue(_is_heading_line("2【サステナビリティに関する考え方及び取組】"))

    def test_is_heading_line_negative(self):
        """_is_heading_line が通常テキストを見出しとして誤認識しない"""
        self.assertFalse(_is_heading_line("当社は人材育成を重視しています。"))
        self.assertFalse(_is_heading_line(""))
        self.assertFalse(_is_heading_line("   "))

    def test_heading_level_inference(self):
        """見出しレベルが正しく推定される"""
        self.assertEqual(_infer_heading_level("第一部 企業情報"), 1)
        self.assertEqual(_infer_heading_level("第２部 提出会社の情報"), 1)
        self.assertEqual(_infer_heading_level("1【事業の概要】"), 2)
        self.assertEqual(_infer_heading_level("【表紙】"), 2)

    def test_max_section_chars_truncation(self):
        """max_section_chars を超える本文はトランケートされる"""
        long_body = "A" * 10000
        mock_text = f"第一部 企業情報\n{long_body}\n"
        sections = split_sections_from_text(mock_text, max_section_chars=100)
        self.assertEqual(len(sections[0].text), 100)

    def test_full_mock_yuho_text(self):
        """有報の典型的なモックテキスト全体でセクション分割が動く（CHECK-8）"""
        mock_yuho = """表紙
提出書類: 有価証券報告書
会社名: テスト株式会社
事業年度: 2025年3月期

第一部 企業情報
1【事業の概要】
当社は情報サービス業を営んでいます。

2【沿革】
2000年 設立

3【事業の内容】
ソフトウェア開発及び保守

4【関係会社の状況】
子会社1社

5【従業員の状況】
2025年3月31日現在、従業員数は500名です。

6【サステナビリティに関する考え方及び取組】
（1）ガバナンス
当社のサステナビリティガバナンスについて記載します。

（2）人的資本
人材育成方針として、以下を定めています。
エンゲージメント向上を最優先課題とします。

第二部 提出会社の保証会社等の情報
該当なし
"""
        sections = split_sections_from_text(mock_yuho)
        # 最低5セクション以上
        self.assertGreaterEqual(
            len(sections), 5,
            f"セクション数が想定より少ない: {len(sections)}件"
        )
        headings = [s.heading for s in sections]
        # 重要見出しが検出されていること
        self.assertTrue(any("第一部" in h for h in headings))
        self.assertTrue(any("従業員の状況" in h for h in headings) or
                        any("従業員" in s.text for s in sections))


# ═══════════════════════════════════════════════════════════════
# TEST 3: 人的資本セクションのフィルタ
# ═══════════════════════════════════════════════════════════════

class TestGetHumanCapitalSections(unittest.TestCase):
    """TEST 3: 人的資本セクションのフィルタ（JINJI_SECTION_KEYWORDS含むセクションが抽出される）"""

    def _make_report(self, sections: list[SectionData]) -> StructuredReport:
        return StructuredReport(
            document_id="TEST_FILTER",
            company_name="テスト株式会社",
            fiscal_year=2025,
            fiscal_month_end=3,
            sections=sections,
        )

    def test_keyword_in_heading_is_detected(self):
        """JINJI_SECTION_KEYWORDS のキーワードが見出しにあるセクションが抽出される"""
        sections = [
            SectionData(section_id="SEC-001", heading="第一部 企業情報", text="一般情報"),
            SectionData(section_id="SEC-002", heading="人的資本", text="人的資本の詳細"),
            SectionData(section_id="SEC-003", heading="財務情報", text="財務データ"),
        ]
        report = self._make_report(sections)
        result = get_human_capital_sections(report)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].section_id, "SEC-002")

    def test_keyword_in_body_text_is_detected(self):
        """JINJI_SECTION_KEYWORDS のキーワードが本文先頭200字にあるセクションが抽出される"""
        sections = [
            SectionData(
                section_id="SEC-001",
                heading="サステナビリティ関連取組",
                text="人材育成方針として、当社は以下を定めています。",
            ),
            SectionData(
                section_id="SEC-002",
                heading="財務状況",
                text="売上高は1000億円です。",
            ),
        ]
        report = self._make_report(sections)
        result = get_human_capital_sections(report)
        # SEC-001: 見出しに「サステナビリティ」→ 抽出
        # SEC-001: 本文に「人材育成」→ 抽出
        # → SEC-001 が抽出される
        self.assertGreaterEqual(len(result), 1)
        sec_ids = [s.section_id for s in result]
        self.assertIn("SEC-001", sec_ids)
        self.assertNotIn("SEC-002", sec_ids)

    def test_multiple_keywords_match(self):
        """複数キーワードにマッチするセクションも重複なく返る"""
        sections = [
            SectionData(
                section_id="SEC-001",
                heading="従業員の状況",
                text="エンゲージメント指標、ダイバーシティ推進について。",
            ),
        ]
        report = self._make_report(sections)
        result = get_human_capital_sections(report)
        self.assertEqual(len(result), 1)  # 重複なし

    def test_no_keyword_sections_excluded(self):
        """JINJI_SECTION_KEYWORDS に無関係なセクションは除外される"""
        sections = [
            SectionData(section_id="SEC-001", heading="事業の概要", text="製造業を営む。"),
            SectionData(section_id="SEC-002", heading="財務諸表", text="貸借対照表の詳細。"),
            SectionData(section_id="SEC-003", heading="リスク管理", text="主要リスク要因。"),
        ]
        report = self._make_report(sections)
        result = get_human_capital_sections(report)
        self.assertEqual(len(result), 0)

    def test_empty_report_returns_empty(self):
        """セクションがゼロの report では空リストが返る"""
        report = self._make_report([])
        result = get_human_capital_sections(report)
        self.assertEqual(result, [])

    def test_all_keywords_covered(self):
        """JINJI_SECTION_KEYWORDS の全12キーワードがそれぞれ検出される"""
        # CHECK-7b の前提確認: 12件ある各キーワードが get_human_capital_sections で検出されること
        for kw in JINJI_SECTION_KEYWORDS:
            section = SectionData(
                section_id="SEC-001",
                heading=f"{kw}に関する方針",
                text="詳細情報",
            )
            report = self._make_report([section])
            result = get_human_capital_sections(report)
            self.assertEqual(
                len(result), 1,
                f"キーワード「{kw}」を含む見出しが検出されなかった"
            )

    def test_body_only_200chars_checked(self):
        """本文チェックは先頭200文字のみ（200文字より後のキーワードは検出対象外）"""
        # 先頭200文字を「A」で埋め、201文字目以降に「人的資本」を置く
        padding = "A" * 200
        long_text = padding + "人的資本という単語がここにある"
        section = SectionData(
            section_id="SEC-001",
            heading="財務情報",  # 見出しにはキーワードなし
            text=long_text,
        )
        report = self._make_report([section])
        result = get_human_capital_sections(report)
        # 200文字以降は見ないため、このセクションは検出されない
        self.assertEqual(len(result), 0)


# ═══════════════════════════════════════════════════════════════
# TEST 4: CHECK-7b JINJI_SECTION_KEYWORDS 手計算確認
# ═══════════════════════════════════════════════════════════════

class TestJinjiSectionKeywordsManualCheck(unittest.TestCase):
    """
    TEST 4: CHECK-7b JINJI_SECTION_KEYWORDS の手計算確認

    【手計算プロセス】
    pdf_poc_extract.py の JINJI_SECTION_KEYWORDS を目視で数えた結果:

    1. "人的資本"          ← 確認 ✓
    2. "人材戦略"          ← 確認 ✓
    3. "人材の確保"        ← 確認 ✓
    4. "人材育成"          ← 確認 ✓
    5. "人材確保"          ← 確認 ✓
    6. "従業員の状況"      ← 確認 ✓
    7. "エンゲージメント"  ← 確認 ✓
    8. "ダイバーシティ"    ← 確認 ✓
    9. "女性活躍"          ← 確認 ✓
    10. "育成方針"          ← 確認 ✓
    11. "人材の多様性"      ← 確認 ✓
    12. "サステナビリティ"  ← 確認 ✓

    合計: 12件
    """

    # CHECK-7b: タスク仕様で明示的に確認を求められた3キーワード
    def test_keyword_jinnteki_shihon_exists(self):
        """「人的資本」が JINJI_SECTION_KEYWORDS に含まれる（CHECK-7b）"""
        self.assertIn("人的資本", JINJI_SECTION_KEYWORDS)

    def test_keyword_jinzai_senryaku_exists(self):
        """「人材戦略」が JINJI_SECTION_KEYWORDS に含まれる（CHECK-7b）"""
        self.assertIn("人材戦略", JINJI_SECTION_KEYWORDS)

    def test_keyword_juugyoin_exists(self):
        """「従業員の状況」が JINJI_SECTION_KEYWORDS に含まれる（CHECK-7b）"""
        self.assertIn("従業員の状況", JINJI_SECTION_KEYWORDS)

    def test_total_keyword_count_is_12(self):
        """
        JINJI_SECTION_KEYWORDS の総数が手計算と一致: 12件

        手計算結果（pdf_poc_extract.py と m1_pdf_agent.py の比較）:
          直接記載グループ (5件): 人的資本, 人材戦略, 人材の確保, 人材育成, 人材確保
          代替キーワードグループ (7件): 従業員の状況, エンゲージメント, ダイバーシティ,
                                        女性活躍, 育成方針, 人材の多様性, サステナビリティ
          合計: 5 + 7 = 12件
        """
        expected_count = 12
        actual_count = len(JINJI_SECTION_KEYWORDS)
        self.assertEqual(
            actual_count,
            expected_count,
            f"JINJI_SECTION_KEYWORDS の件数が想定と異なる: 実測={actual_count}件, 期待={expected_count}件\n"
            f"実際のリスト: {JINJI_SECTION_KEYWORDS}"
        )

    def test_all_expected_keywords_present(self):
        """手計算で確認した全12キーワードが存在する"""
        # pdf_poc_extract.py を目視確認した全キーワード
        expected_keywords = [
            "人的資本",
            "人材戦略",
            "人材の確保",
            "人材育成",
            "人材確保",
            "従業員の状況",
            "エンゲージメント",
            "ダイバーシティ",
            "女性活躍",
            "育成方針",
            "人材の多様性",
            "サステナビリティ",
        ]
        for kw in expected_keywords:
            self.assertIn(
                kw,
                JINJI_SECTION_KEYWORDS,
                f"キーワード「{kw}」が JINJI_SECTION_KEYWORDS に見つからない"
            )

    def test_no_unexpected_keywords(self):
        """想定外のキーワードが紛れ込んでいない（pdf_poc_extract.py との完全一致確認）"""
        expected_keywords = set([
            "人的資本", "人材戦略", "人材の確保", "人材育成", "人材確保",
            "従業員の状況", "エンゲージメント", "ダイバーシティ", "女性活躍",
            "育成方針", "人材の多様性", "サステナビリティ",
        ])
        actual_keywords = set(JINJI_SECTION_KEYWORDS)
        extra = actual_keywords - expected_keywords
        self.assertEqual(
            extra,
            set(),
            f"想定外のキーワードが含まれている: {extra}"
        )

    def test_heading_patterns_count_is_8(self):
        """HEADING_PATTERNS のパターン数が 8 件"""
        self.assertEqual(
            len(HEADING_PATTERNS),
            8,
            f"HEADING_PATTERNS の件数が想定と異なる: {len(HEADING_PATTERNS)}件"
        )


# ═══════════════════════════════════════════════════════════════
# TEST 5: エラーハンドリング
# ═══════════════════════════════════════════════════════════════

class TestErrorHandling(unittest.TestCase):
    """TEST 5: エラーハンドリング（FileNotFoundError）"""

    def test_nonexistent_pdf_raises_file_not_found(self):
        """存在しないPDFパスを渡すと FileNotFoundError が発生する"""
        from m1_pdf_agent import extract_report

        nonexistent_path = "/tmp/nonexistent_yuho_test_abc123.pdf"
        # ファイルが実際に存在しないことを確認
        self.assertFalse(Path(nonexistent_path).exists())

        with self.assertRaises(FileNotFoundError) as ctx:
            extract_report(nonexistent_path)

        # エラーメッセージにパスが含まれる
        self.assertIn("nonexistent", str(ctx.exception))

    def test_file_not_found_error_message_contains_path(self):
        """FileNotFoundError のメッセージに問題のパスが含まれる"""
        from m1_pdf_agent import extract_report

        bad_path = "/tmp/test_bad_path_xyz987.pdf"
        self.assertFalse(Path(bad_path).exists())

        with self.assertRaises(FileNotFoundError) as ctx:
            extract_report(bad_path)

        # エラーメッセージがパスを含む
        err_msg = str(ctx.exception)
        self.assertTrue(
            "test_bad_path_xyz987" in err_msg or "tmp" in err_msg,
            f"エラーメッセージにパス情報がない: {err_msg}"
        )


# ═══════════════════════════════════════════════════════════════
# TEST 6: extract_tables フラグ（FINDING-001対応）
# ═══════════════════════════════════════════════════════════════

class TestExtractTablesFlag(unittest.TestCase):
    """
    TEST 6: extract_tables フラグ（FINDING-001対応）

    subtask_074a3z: M1テーブル抽出オプション化
    FINDING-001: find_tables() が処理時間の97%を占める問題の対応テスト

    手計算検証（CHECK-7b）:
      TC-1 (extract_tables=True デフォルト):
        pages=[1ページ] → _extract_tables_from_page が1回呼ばれる
        call_count > 0 → True ✓

      TC-2 (extract_tables=False):
        pages=[1ページ] → if extract_tables else [] の分岐で _extract_tables_from_page をスキップ
        call_count == 0 → True ✓
        sections は生成される（テキスト抽出は行われる）→ isinstance(result, StructuredReport) ✓

      TC-3 (後方互換):
        extract_report('/nonexistent.pdf') → FileNotFoundError
        extract_report('/nonexistent.pdf', extract_tables=True) → FileNotFoundError
        extract_report('/nonexistent.pdf', extract_tables=False) → FileNotFoundError
        いずれも同じ動作（ファイル存在チェックはextract_tables引数より先に実行）✓
    """

    def _build_fitz_mocks(self):
        """テスト用の fitz モジュール + ドキュメント + ページのモックを生成する"""
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_page.get_text.return_value = (
            "第一部 企業情報\n人材戦略について記載します。\n"
        )

        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))

        mock_fitz = MagicMock()
        mock_fitz.open.return_value = mock_doc

        return mock_fitz, mock_doc, mock_page

    def test_tc1_extract_tables_true_calls_extract_function(self):
        """
        TC-1: extract_tables=True（デフォルト）→ _extract_tables_from_page が呼ばれること

        手計算:
            pages = [1ページ]
            extract_tables=True → ループ内で _extract_tables_from_page(page) が実行される
            call_count >= 1 ✓
        根拠: FINDING-001対応: デフォルト動作が従来と同一であることを確認（後方互換の機能面）
        """
        from unittest.mock import MagicMock, patch, patch as mock_patch

        mock_fitz, mock_doc, mock_page = self._build_fitz_mocks()

        import m1_pdf_agent
        from m1_pdf_agent import extract_report

        with patch.dict(sys.modules, {'fitz': mock_fitz}), \
             patch('m1_pdf_agent._check_fitz', return_value=True), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('m1_pdf_agent._extract_tables_from_page', return_value=[]) as mock_ext:
            # extract_tables=True（デフォルト）で呼び出し
            extract_report('/dummy/test_tc1.pdf', extract_tables=True)
            # _extract_tables_from_page が1回以上呼ばれていること
            self.assertGreater(
                mock_ext.call_count, 0,
                "_extract_tables_from_page が呼ばれていない（extract_tables=True のはず）"
            )

    def test_tc2_extract_tables_false_skips_extract_function(self):
        """
        TC-2: extract_tables=False → _extract_tables_from_page が呼ばれないこと

        手計算:
            pages = [1ページ]
            extract_tables=False → `_extract_tables_from_page(page) if extract_tables else []`
            → else [] が選ばれ _extract_tables_from_page は実行されない
            call_count == 0 ✓
            セクションは生成される（page.get_text() によるテキスト抽出は行われる）
        根拠: FINDING-001対応: テーブル抽出スキップで処理時間を大幅短縮（11.5秒→~0.5秒）
        """
        from unittest.mock import MagicMock, patch

        mock_fitz, mock_doc, mock_page = self._build_fitz_mocks()

        import m1_pdf_agent
        from m1_pdf_agent import extract_report
        from m3_gap_analysis_agent import StructuredReport as SR

        with patch.dict(sys.modules, {'fitz': mock_fitz}), \
             patch('m1_pdf_agent._check_fitz', return_value=True), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('m1_pdf_agent._extract_tables_from_page', return_value=[]) as mock_ext:
            # extract_tables=False で呼び出し
            result = extract_report('/dummy/test_tc2.pdf', extract_tables=False)
            # _extract_tables_from_page が一度も呼ばれていないこと
            mock_ext.assert_not_called()
            # セクションは生成されていること（テキスト抽出は正常実行）
            self.assertIsInstance(result, SR,
                                  "extract_tables=False でも StructuredReport が返るべき")

    def test_tc3_backward_compat_extract_tables_optional(self):
        """
        TC-3: 後方互換 — extract_tables 引数なしで extract_report が呼び出せること

        手計算:
            extract_report('/nonexistent.pdf') → FileNotFoundError（ファイルチェックが先行）
            extract_report('/nonexistent.pdf', extract_tables=True) → 同上
            extract_report('/nonexistent.pdf', extract_tables=False) → 同上
            いずれも同じ動作 → extract_tables はオプション引数 ✓

        根拠: 既存の m1_precision_check.py / run_e2e.py 等の呼び出しが壊れないことを確認
             （CONCERN-002: M1モジュール改変禁止を遵守 → 後方互換必須）
        """
        from m1_pdf_agent import extract_report

        dummy = '/tmp/nonexistent_backward_compat_test_abc.pdf'
        self.assertFalse(Path(dummy).exists(), "テスト用ダミーファイルが存在してはいけない")

        # 引数なし（デフォルト extract_tables=True）→ FileNotFoundError
        with self.assertRaises(FileNotFoundError,
                               msg="extract_tables引数なしでも FileNotFoundError が出るべき"):
            extract_report(dummy)

        # extract_tables=True 明示 → FileNotFoundError
        with self.assertRaises(FileNotFoundError,
                               msg="extract_tables=True でも FileNotFoundError が出るべき"):
            extract_report(dummy, extract_tables=True)

        # extract_tables=False → FileNotFoundError（ファイルチェックは先行実行）
        with self.assertRaises(FileNotFoundError,
                               msg="extract_tables=False でも FileNotFoundError が出るべき"):
            extract_report(dummy, extract_tables=False)


# ═══════════════════════════════════════════════════════════════
# TEST 7: 招集通知（shoshu）対応テスト
# ═══════════════════════════════════════════════════════════════

class TestShoshuDocType(unittest.TestCase):
    """
    TEST 7: 招集通知（shoshu）書類種別対応テスト

    D-Shoshu-01 で追加した以下の機能を検証する:
      - SHOSHU_SECTION_KEYWORDS（12件）
      - SHOSHU_HEADING_PATTERNS（8件）
      - _is_heading_line_for_doc_type(line, doc_type)
      - split_sections_from_text(text, doc_type="shoshu")
      - get_shoshu_sections(report)

    手計算検証（CHECK-7b 相当）:
      SHOSHU_SECTION_KEYWORDS:
        1. "議案"               6. "株主提案"
        2. "取締役選任"         7. "報告事項"
        3. "役員報酬"           8. "決議事項"
        4. "定款変更"           9. "議決権"
        5. "監査役選任"        10. "社外取締役"
                               11. "スキルマトリックス"
                               12. "コーポレートガバナンス"
      合計: 12件

      SHOSHU_HEADING_PATTERNS:
        1. ^第[0-9]+号議案           (第1号議案 取締役選任の件)
        2. ^【[^】]*議案[^】]*】   (【取締役選任の件】)
        3. ^報告事項
        4. ^決議事項
        5. ^株主提案
        6. ^[（(][0-9]+[）)] <漢字>  (（1）取締役選任の件)
        7. ^[0-9]+. <漢字>{2,}      (1. 取締役の選任について)
        8. ^【[^】]+】$            (汎用パターン)
      合計: 8件
    """

    def _make_report(self, sections: list) -> StructuredReport:
        return StructuredReport(
            document_id="TEST_SHOSHU",
            company_name="テスト株式会社",
            fiscal_year=2025,
            fiscal_month_end=3,
            sections=sections,
        )

    # ── 7-1: _is_heading_line_for_doc_type ──────────────────

    def test_shoshu_heading_gian_detected(self):
        """「第N号議案」が shoshu 見出しとして認識される"""
        self.assertTrue(_is_heading_line_for_doc_type("第1号議案 取締役選任の件", "shoshu"))
        self.assertTrue(_is_heading_line_for_doc_type("第2号議案 役員報酬改定の件", "shoshu"))
        self.assertTrue(_is_heading_line_for_doc_type("第10号議案 定款変更の件", "shoshu"))

    def test_shoshu_heading_hokokujiko_detected(self):
        """「報告事項」「決議事項」「株主提案」が shoshu 見出しとして認識される"""
        self.assertTrue(_is_heading_line_for_doc_type("報告事項", "shoshu"))
        self.assertTrue(_is_heading_line_for_doc_type("決議事項", "shoshu"))
        self.assertTrue(_is_heading_line_for_doc_type("株主提案", "shoshu"))

    def test_yuho_heading_not_detected_as_shoshu(self):
        """有報専用パターン「第一部」「N【...】」は shoshu 見出しとして認識されない"""
        self.assertFalse(_is_heading_line_for_doc_type("第一部 企業情報", "shoshu"))
        self.assertFalse(_is_heading_line_for_doc_type("1【事業の概要】", "shoshu"))
        self.assertFalse(_is_heading_line_for_doc_type("第２【企業の概況】", "shoshu"))

    def test_default_doc_type_is_yuho(self):
        """_is_heading_line_for_doc_type のデフォルトは yuho（有報パターン）を使う"""
        self.assertTrue(_is_heading_line_for_doc_type("第一部 企業情報"))
        self.assertTrue(_is_heading_line_for_doc_type("1【事業の概要】"))
        # shoshu専用パターンはデフォルト(yuho)では検出されない
        self.assertFalse(_is_heading_line_for_doc_type("第1号議案 取締役選任の件"))

    # ── 7-2: split_sections_from_text with doc_type="shoshu" ──

    def test_split_shoshu_text_detects_gian(self):
        """招集通知テキストを doc_type='shoshu' で分割すると「第N号議案」が見出しになる"""
        mock_shoshu = """報告事項
第190期事業報告の内容。

決議事項
第1号議案 取締役選任の件
候補者情報がここに入る。

第2号議案 役員報酬改定の件
報酬体系の変更内容。
"""
        sections = split_sections_from_text(mock_shoshu, doc_type="shoshu")
        headings = [s.heading for s in sections]

        self.assertTrue(
            any("報告事項" in h for h in headings),
            f"「報告事項」が見出し未検出: {headings}"
        )
        self.assertTrue(
            any("第1号議案" in h for h in headings),
            f"「第1号議案」が見出し未検出: {headings}"
        )
        self.assertTrue(
            any("第2号議案" in h for h in headings),
            f"「第2号議案」が見出し未検出: {headings}"
        )

    def test_split_shoshu_default_yuho_backward_compat(self):
        """doc_type 引数なし（デフォルト）は有報分割と同一結果（後方互換）"""
        mock_yuho = "第一部 企業情報\n企業情報\n\n第二部 保証会社情報\n情報\n"
        sections_default = split_sections_from_text(mock_yuho)
        sections_yuho = split_sections_from_text(mock_yuho, doc_type="yuho")
        self.assertEqual(
            [s.heading for s in sections_default],
            [s.heading for s in sections_yuho],
            "デフォルト引数と doc_type='yuho' の結果が異なる（後方互換違反）"
        )

    def test_shoshu_text_not_split_with_yuho_pattern(self):
        """招集通知テキストは doc_type='yuho' では「第N号議案」が見出し未検出（パターン非一致）"""
        mock_shoshu = "第1号議案 取締役選任の件\n候補者情報\n"
        sections_yuho = split_sections_from_text(mock_shoshu, doc_type="yuho")
        headings = [s.heading for s in sections_yuho]
        # 有報パターンでは「第1号議案」にマッチしない → 見出し未検出 → 1セクション
        self.assertTrue(
            not any("第1号議案" in h for h in headings),
            f"有報パターンが招集通知見出しを誤検出: {headings}"
        )

    # ── 7-3: get_shoshu_sections ────────────────────────────

    def test_get_shoshu_sections_keyword_in_heading(self):
        """SHOSHU_SECTION_KEYWORDS が見出しにあるセクションが抽出される"""
        sections = [
            SectionData(section_id="SEC-001", heading="第1号議案 取締役選任の件", text="候補者情報"),
            SectionData(section_id="SEC-002", heading="財務諸表", text="財務データ"),
            SectionData(section_id="SEC-003", heading="役員報酬改定議案", text="報酬詳細"),
        ]
        report = self._make_report(sections)
        result = get_shoshu_sections(report)
        sec_ids = [s.section_id for s in result]

        self.assertIn("SEC-001", sec_ids)
        self.assertIn("SEC-003", sec_ids)
        self.assertNotIn("SEC-002", sec_ids)

    def test_get_shoshu_sections_keyword_in_body(self):
        """SHOSHU_SECTION_KEYWORDS が本文先頭200字にあるセクションが抽出される"""
        sections = [
            SectionData(
                section_id="SEC-001",
                heading="ご通知",
                text="議案として取締役選任を上程いたします。",
            ),
        ]
        report = self._make_report(sections)
        result = get_shoshu_sections(report)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].section_id, "SEC-001")

    def test_get_shoshu_sections_empty_report(self):
        """セクションなしの report では空リスト"""
        report = self._make_report([])
        result = get_shoshu_sections(report)
        self.assertEqual(result, [])

    def test_get_shoshu_sections_no_keyword_excluded(self):
        """SHOSHU_SECTION_KEYWORDS に無関係なセクションは除外される"""
        sections = [
            SectionData(section_id="SEC-001", heading="サステナビリティ報告", text="環境データ"),
            SectionData(section_id="SEC-002", heading="人的資本", text="人材育成方針"),
        ]
        report = self._make_report(sections)
        result = get_shoshu_sections(report)
        # 「サステナビリティ」「人的資本」は SHOSHU_SECTION_KEYWORDS にない
        self.assertEqual(len(result), 0)

    def test_all_shoshu_keywords_detectable(self):
        """SHOSHU_SECTION_KEYWORDS の全キーワードが get_shoshu_sections で検出される（手計算確認）"""
        for kw in SHOSHU_SECTION_KEYWORDS:
            section = SectionData(
                section_id="SEC-001",
                heading=f"{kw}に関する事項",
                text="詳細情報",
            )
            report = self._make_report([section])
            result = get_shoshu_sections(report)
            self.assertEqual(
                len(result), 1,
                f"キーワード「{kw}」を含む見出しが get_shoshu_sections で未検出"
            )

    # ── 7-4: 定数の手計算確認 ──────────────────────────────

    def test_shoshu_keywords_count_is_12(self):
        """
        SHOSHU_SECTION_KEYWORDS のキーワード数が 12 件（手計算確認）

        手計算:
          1.議案 2.取締役選任 3.役員報酬 4.定款変更 5.監査役選任
          6.株主提案 7.報告事項 8.決議事項 9.議決権 10.社外取締役
          11.スキルマトリックス 12.コーポレートガバナンス
          合計: 12件
        """
        self.assertEqual(
            len(SHOSHU_SECTION_KEYWORDS),
            12,
            f"SHOSHU_SECTION_KEYWORDS の件数が想定と異なる: 実測={len(SHOSHU_SECTION_KEYWORDS)}件"
        )

    def test_shoshu_heading_patterns_count_is_8(self):
        """SHOSHU_HEADING_PATTERNS のパターン数が 8 件（手計算確認）"""
        self.assertEqual(
            len(SHOSHU_HEADING_PATTERNS),
            8,
            f"SHOSHU_HEADING_PATTERNS の件数が想定と異なる: {len(SHOSHU_HEADING_PATTERNS)}件"
        )

    def test_shoshu_keywords_all_expected_present(self):
        """手計算で確認した全12キーワードが存在する"""
        expected = [
            "議案", "取締役選任", "役員報酬", "定款変更", "監査役選任",
            "株主提案", "報告事項", "決議事項", "議決権", "社外取締役",
            "スキルマトリックス", "コーポレートガバナンス",
        ]
        for kw in expected:
            self.assertIn(
                kw,
                SHOSHU_SECTION_KEYWORDS,
                f"キーワード「{kw}」が SHOSHU_SECTION_KEYWORDS に見つからない"
            )


# ═══════════════════════════════════════════════════════════════
# メイン実行
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("disclosure-multiagent M1 PDF解析エージェント テスト")
    print("実PDFなしで動作（モックテキスト使用）")
    print("=" * 60)
    print()
    print("【CHECK-7b 手計算確認】")
    print(f"  JINJI_SECTION_KEYWORDS: {len(JINJI_SECTION_KEYWORDS)}件")
    for i, kw in enumerate(JINJI_SECTION_KEYWORDS, 1):
        print(f"    {i:2d}. {kw}")
    print()
    print(f"  HEADING_PATTERNS: {len(HEADING_PATTERNS)}件")
    print()

    unittest.main(verbosity=2)
