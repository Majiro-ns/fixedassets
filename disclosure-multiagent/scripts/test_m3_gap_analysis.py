"""
test_m3_gap_analysis.py
=======================
disclosure-multiagent Phase 1-M3: ギャップ分析エージェント テスト

実行方法（APIキー不要）:
    python3 test_m3_gap_analysis.py

テスト一覧:
    TEST 1: GapItem・GapAnalysisResultのデータクラス構築（フィールド検証）
    TEST 2: change_typeのenum制約（"その他"が入ったらValueError）
    TEST 3: source_confirmed=Falseエントリの警告生成
    TEST 4: LLMレスポンスのJSONパース（モックAPIレスポンスを使用）
    TEST 5: CHECK-7b 法令参照期間の手計算（2025年度3月決算→2025/04/01〜2026/03/31）
"""

import json
import sys
import unittest
from unittest.mock import MagicMock, patch
from dataclasses import asdict

# テスト対象モジュールをインポート
sys.path.insert(0, ".")
from m3_gap_analysis_agent import (
    GapItem,
    GapAnalysisResult,
    GapSummary,
    GapMetadata,
    NoGapItem,
    LawEntry,
    LawContext,
    SectionData,
    TableData,
    StructuredReport,
    ChangeType,
    Confidence,
    attach_reference_url,
    calc_law_ref_period,
    analyze_gaps,
    judge_gap,
    result_to_dict,
    _build_mock_report,
    _build_mock_law_context,
    HUMAN_CAPITAL_KEYWORDS,
    SSBJ_KEYWORDS,
    ALL_RELEVANCE_KEYWORDS,
    is_relevant_section,
)


class TestDataclasses(unittest.TestCase):
    """TEST 1: GapItem・GapAnalysisResultのデータクラス構築（フィールド検証）"""

    def test_gap_item_construction(self):
        """GapItemが正しいフィールドで構築できる"""
        item = GapItem(
            gap_id="GAP-001",
            section_id="HC-001",
            section_heading="e. 人的資本経営に関する指標",
            change_type="追加必須",
            has_gap=True,
            gap_description="男性育児休業取得率の記載が見当たらない。",
            disclosure_item="男性育児休業取得率の開示（必須）",
            reference_law_id="HC_20230131_001",
            reference_law_title="企業内容等の開示に関する内閣府令改正",
            reference_url="https://www.fsa.go.jp/news/r4/sonota/20230131/20230131.html",
            source_confirmed=False,
            source_warning="⚠️ このURLは実アクセス未確認",
            evidence_hint="テキスト内に「育児休業」のキーワードなし。",
            confidence="high",
        )
        self.assertEqual(item.gap_id, "GAP-001")
        self.assertEqual(item.change_type, "追加必須")
        self.assertTrue(item.has_gap)
        self.assertFalse(item.source_confirmed)
        self.assertIsNotNone(item.source_warning)
        print("  [PASS] GapItem構築: gap_id/change_type/source_confirmed フィールド確認 ✓")

    def test_gap_analysis_result_construction(self):
        """GapAnalysisResultが正しく構築できる"""
        gap_item = GapItem(
            gap_id="GAP-001",
            section_id="HC-001",
            section_heading="人的資本",
            change_type="追加必須",
            has_gap=True,
            disclosure_item="人材育成方針の記載（必須）",
            reference_law_id="HC_20230131_001",
            reference_law_title="テスト法令",
            reference_url="https://example.com",
            source_confirmed=True,
            evidence_hint="記載なし",
        )
        no_gap = NoGapItem(
            disclosure_item="女性管理職比率（連結・単体）の開示（必須）",
            reference_law_id="HC_20230131_001",
            evidence_hint="テーブルで確認",
        )
        summary = GapSummary(
            total_gaps=1,
            by_change_type={"追加必須": 1, "修正推奨": 0, "参考": 0},
        )
        metadata = GapMetadata(
            llm_model="mock",
            sections_analyzed=2,
            entries_checked=1,
        )
        result = GapAnalysisResult(
            document_id="TEST-001",
            fiscal_year=2025,
            law_yaml_as_of="2026-02-27",
            summary=summary,
            gaps=[gap_item],
            no_gap_items=[no_gap],
            metadata=metadata,
        )
        self.assertEqual(result.document_id, "TEST-001")
        self.assertEqual(result.fiscal_year, 2025)
        self.assertEqual(result.law_yaml_as_of, "2026-02-27")
        self.assertEqual(result.summary.total_gaps, 1)
        self.assertEqual(len(result.gaps), 1)
        self.assertEqual(len(result.no_gap_items), 1)
        self.assertEqual(result.gap_analysis_version, "1.0")
        print("  [PASS] GapAnalysisResult構築: 全フィールド検証 ✓")

    def test_result_to_dict_serializable(self):
        """result_to_dict がJSON化できる"""
        report = _build_mock_report()
        law_context = _build_mock_law_context()
        result = analyze_gaps(report, law_context, use_mock=True)
        d = result_to_dict(result)
        # JSON化できること（例外が出ないこと）
        json_str = json.dumps(d, ensure_ascii=False)
        self.assertIn("document_id", d)
        self.assertIn("law_yaml_as_of", d)
        self.assertIn("gaps", d)
        self.assertIn("no_gap_items", d)
        print("  [PASS] result_to_dict: JSON化可能、必須フィールド存在 ✓")


class TestChangeTypeEnum(unittest.TestCase):
    """TEST 2: change_typeのenum制約（"その他"が入ったらValueError）"""

    def test_valid_change_types(self):
        """有効なchange_typeは例外なく構築できる"""
        for ct in ["追加必須", "修正推奨", "参考"]:
            item = GapItem(
                gap_id="GAP-TEST",
                section_id="S-001",
                section_heading="テスト",
                change_type=ct,
                has_gap=True,
                disclosure_item="テスト項目",
                reference_law_id="TEST-001",
                reference_law_title="テスト法令",
                reference_url="https://example.com",
                source_confirmed=True,
                evidence_hint="テスト",
            )
            self.assertEqual(item.change_type, ct)
        print("  [PASS] valid change_types: 追加必須/修正推奨/参考 全て正常 ✓")

    def test_invalid_change_type_raises_value_error(self):
        """無効なchange_type("その他")はValueErrorを発生させる"""
        with self.assertRaises(ValueError) as ctx:
            GapItem(
                gap_id="GAP-TEST",
                section_id="S-001",
                section_heading="テスト",
                change_type="その他",  # 無効値
                has_gap=True,
                disclosure_item="テスト項目",
                reference_law_id="TEST-001",
                reference_law_title="テスト法令",
                reference_url="https://example.com",
                source_confirmed=True,
                evidence_hint="テスト",
            )
        self.assertIn("その他", str(ctx.exception))
        self.assertIn("無効", str(ctx.exception))
        print(f"  [PASS] 無効change_type: ValueError発生 '{ctx.exception}' ✓")

    def test_enum_class_values(self):
        """ChangeType enumが正しい値を持つ"""
        self.assertEqual(ChangeType.ADD_MANDATORY.value, "追加必須")
        self.assertEqual(ChangeType.MODIFY_RECOMMENDED.value, "修正推奨")
        self.assertEqual(ChangeType.REFERENCE.value, "参考")
        print("  [PASS] ChangeType enum値検証 ✓")


class TestSourceConfirmedWarning(unittest.TestCase):
    """TEST 3: source_confirmed=Falseエントリの警告生成"""

    def test_source_confirmed_false_gets_warning(self):
        """source_confirmed=Falseの法令エントリには警告が付与される"""
        entry_unconfirmed = LawEntry(
            id="HC_20230131_001",
            title="テスト法令（未確認URL）",
            category="金商法・開示府令",
            change_type="追加必須",
            disclosure_items=["テスト項目"],
            source="https://www.fsa.go.jp/test/unconfirmed.html",
            source_confirmed=False,
        )
        gap_result = {
            "has_gap": True,
            "gap_description": "テストギャップ",
            "evidence_hint": "テスト証拠",
            "confidence": "medium",
        }
        result = attach_reference_url(gap_result, entry_unconfirmed)

        self.assertFalse(result["source_confirmed"])
        self.assertIsNotNone(result["source_warning"])
        self.assertIn("⚠️", result["source_warning"])
        self.assertIn("source_confirmed: false", result["source_warning"])
        print(f"  [PASS] source_confirmed=False: 警告フィールド付与 '{result['source_warning'][:30]}...' ✓")

    def test_source_confirmed_true_no_warning(self):
        """source_confirmed=Trueの場合は警告フィールドがNone"""
        entry_confirmed = LawEntry(
            id="HC_20260220_001",
            title="テスト法令（確認済みURL）",
            category="金商法・開示府令",
            change_type="追加必須",
            disclosure_items=["テスト項目"],
            source="https://sustainablejapan.jp/2026/02/23/fsa-ssbj-4/122214",
            source_confirmed=True,
        )
        gap_result = {
            "has_gap": True,
            "gap_description": "テスト",
            "evidence_hint": "テスト",
            "confidence": "high",
        }
        result = attach_reference_url(gap_result, entry_confirmed)

        self.assertTrue(result["source_confirmed"])
        self.assertIsNone(result["source_warning"])
        print("  [PASS] source_confirmed=True: source_warning=None ✓")

    def test_mock_pipeline_unconfirmed_warning_propagated(self):
        """モックパイプラインでsource_confirmed=Falseの警告がGapItemに伝搬する"""
        report = _build_mock_report()
        law_context = _build_mock_law_context()
        result = analyze_gaps(report, law_context, use_mock=True)

        # HC_20230131_001 (source_confirmed=False) 由来のギャップを検索
        unconfirmed_gaps = [
            g for g in result.gaps
            if g.reference_law_id == "HC_20230131_001" and g.has_gap is True
        ]
        if unconfirmed_gaps:
            for g in unconfirmed_gaps:
                self.assertFalse(g.source_confirmed)
                self.assertIsNotNone(g.source_warning)
                self.assertIn("⚠️", g.source_warning)
            print(f"  [PASS] パイプライン警告伝搬: {len(unconfirmed_gaps)}件のギャップに警告付与 ✓")
        else:
            print("  [INFO] HC_20230131_001由来のギャップなし（モックデータで全項目充足）")


class TestJsonParseMock(unittest.TestCase):
    """TEST 4: LLMレスポンスのJSONパース（モックAPIレスポンスを使用）"""

    def test_valid_json_response_parsed(self):
        """有効なJSONレスポンスが正しくパースされる"""
        mock_response_text = json.dumps({
            "has_gap": True,
            "gap_description": "男性育児休業取得率の記載が見当たらない。",
            "evidence_hint": "テキスト内に「育児休業」のキーワードなし。",
            "confidence": "high",
        }, ensure_ascii=False)

        # anthropicクライアントをモック化
        mock_client = MagicMock()
        mock_content = MagicMock()
        mock_content.text = mock_response_text
        mock_usage = MagicMock()
        mock_usage.input_tokens = 1500
        mock_usage.output_tokens = 80
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_response.usage = mock_usage
        mock_client.messages.create.return_value = mock_response

        section = SectionData(
            section_id="HC-001",
            heading="e. 人的資本経営",
            text="当社では人材育成を推進しています。",
        )
        law_entry = LawEntry(
            id="HC_20230131_001",
            title="テスト法令",
            category="金商法・開示府令",
            change_type="追加必須",
            disclosure_items=["男性育児休業取得率の開示（必須）"],
            source="https://example.com",
            source_confirmed=False,
        )

        result, in_tok, out_tok = judge_gap(
            section=section,
            disclosure_item="男性育児休業取得率の開示（必須）",
            law_entry=law_entry,
            client=mock_client,
            use_mock=False,
        )

        self.assertTrue(result["has_gap"])
        self.assertEqual(result["confidence"], "high")
        self.assertIsNotNone(result["gap_description"])
        self.assertEqual(in_tok, 1500)
        self.assertEqual(out_tok, 80)
        print("  [PASS] 有効JSONレスポンスのパース: has_gap/confidence/tokens 正常 ✓")

    def test_invalid_json_response_parse_error(self):
        """無効なJSONレスポンスはparse_errorとして記録される"""
        mock_client = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "申し訳ありませんが、判定できません。"  # JSONでない
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 20
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_response.usage = mock_usage
        mock_client.messages.create.return_value = mock_response

        section = SectionData(
            section_id="HC-001",
            heading="テスト",
            text="テスト",
        )
        law_entry = LawEntry(
            id="TEST-001",
            title="テスト",
            category="テスト",
            change_type="追加必須",
            disclosure_items=["テスト"],
            source="https://example.com",
            source_confirmed=True,
        )

        result, _, _ = judge_gap(
            section=section,
            disclosure_item="テスト",
            law_entry=law_entry,
            client=mock_client,
            use_mock=False,
        )

        self.assertIsNone(result["has_gap"])
        self.assertEqual(result["confidence"], Confidence.PARSE_ERROR.value)
        print("  [PASS] 無効JSONレスポンス: confidence=parse_error, has_gap=None ✓")

    def test_code_block_json_response_parsed(self):
        """```json ... ``` 形式のレスポンスもパースできる"""
        mock_client = MagicMock()
        mock_content = MagicMock()
        mock_content.text = '```json\n{"has_gap": false, "gap_description": null, "evidence_hint": "記載あり", "confidence": "medium"}\n```'
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 30
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        mock_response.usage = mock_usage
        mock_client.messages.create.return_value = mock_response

        section = SectionData(section_id="S-001", heading="テスト", text="テスト")
        law_entry = LawEntry(
            id="TEST-001", title="テスト", category="テスト",
            change_type="追加必須", disclosure_items=["テスト"],
            source="https://example.com", source_confirmed=True,
        )

        result, _, _ = judge_gap(
            section=section,
            disclosure_item="テスト",
            law_entry=law_entry,
            client=mock_client,
            use_mock=False,
        )

        self.assertFalse(result["has_gap"])
        self.assertIsNone(result["gap_description"])
        print("  [PASS] コードブロックJSON: has_gap=false 正常パース ✓")


class TestCalcLawRefPeriod(unittest.TestCase):
    """TEST 5: CHECK-7b 法令参照期間の手計算検証"""

    def test_march_fiscal_year_2025(self):
        """
        CHECK-7b: 2025年度3月決算 → 2025/04/01〜2026/03/31

        手計算:
          fiscal_year=2025, fiscal_month_end=3
          start = 2025 + "/04/01" = "2025/04/01"
          end = (2025+1) + "/03/31" = "2026/03/31"
        """
        start, end = calc_law_ref_period(2025, 3)
        # 手計算の期待値
        expected_start = "2025/04/01"
        expected_end = "2026/03/31"
        self.assertEqual(start, expected_start,
            f"期間開始: 期待={expected_start}, 実際={start}")
        self.assertEqual(end, expected_end,
            f"期間終了: 期待={expected_end}, 実際={end}")
        print(f"  [PASS] CHECK-7b 2025年度3月決算: {start}〜{end} ✓")

    def test_hc_20260220_001_in_period(self):
        """
        HC_20260220_001（施行日2026-02-20）が2025年度3月決算の期間内であることを確認

        手計算:
          法令参照期間: 2025/04/01〜2026/03/31
          施行日: 2026-02-20
          2025-04-01 <= 2026-02-20 <= 2026-03-31 → True ✓
        """
        from datetime import date as dt
        start_str, end_str = calc_law_ref_period(2025, 3)
        start = dt.fromisoformat(start_str.replace("/", "-"))
        end = dt.fromisoformat(end_str.replace("/", "-"))
        effective_date = dt(2026, 2, 20)

        in_period = start <= effective_date <= end

        self.assertTrue(in_period,
            f"HC_20260220_001(2026-02-20) は {start_str}〜{end_str} の範囲外")
        print(f"  [PASS] HC_20260220_001(2026-02-20) in {start_str}〜{end_str}: True ✓")

    def test_december_fiscal_year(self):
        """12月決算の法令参照期間"""
        start, end = calc_law_ref_period(2025, 12)
        self.assertEqual(start, "2025/01/01")
        self.assertEqual(end, "2025/12/31")
        print(f"  [PASS] 2025年度12月決算: {start}〜{end} ✓")

    def test_gap_err_001_empty_sections(self):
        """TEST 5 追加: GAP_ERR_001 空sectionsでValueError"""
        empty_report = StructuredReport(
            document_id="EMPTY",
            company_name="空テスト",
            fiscal_year=2025,
            fiscal_month_end=3,
            sections=[],
        )
        law_context = _build_mock_law_context()
        with self.assertRaises(ValueError) as ctx:
            analyze_gaps(empty_report, law_context, use_mock=True)
        self.assertIn("GAP_ERR_001", str(ctx.exception))
        print(f"  [PASS] GAP_ERR_001: 空sections → ValueError発生 ✓")


class TestSSBJKeywords(unittest.TestCase):
    """TEST 6: SSBJ関連キーワードとis_relevant_section()の動作検証"""

    def test_ssbj_keywords_defined(self):
        """SSBJ_KEYWORDS定数が定義されており、必須キーワードを含む"""
        required = ["SSBJ", "GHG", "温室効果ガス", "気候変動", "Scope1", "Scope2", "Scope3"]
        for kw in required:
            self.assertIn(kw, SSBJ_KEYWORDS, f"SSBJ_KEYWORDS に '{kw}' が含まれていない")
        print(f"  [PASS] SSBJ_KEYWORDS: {len(SSBJ_KEYWORDS)}件定義済み（必須7件含む）✓")

    def test_all_relevance_keywords_contains_both(self):
        """ALL_RELEVANCE_KEYWORDS が人的資本キーワードとSSBJキーワードを両方含む"""
        for kw in HUMAN_CAPITAL_KEYWORDS:
            self.assertIn(kw, ALL_RELEVANCE_KEYWORDS, f"人的資本キーワード '{kw}' が欠落")
        for kw in SSBJ_KEYWORDS:
            self.assertIn(kw, ALL_RELEVANCE_KEYWORDS, f"SSBJキーワード '{kw}' が欠落")
        print(f"  [PASS] ALL_RELEVANCE_KEYWORDS: {len(ALL_RELEVANCE_KEYWORDS)}件（HC+SSBJ両方含む）✓")

    def test_is_relevant_section_detects_ssbj_heading(self):
        """SSBJ関連キーワードを含むセクション見出しが関連ありと判定される"""
        section = SectionData(
            section_id="SSBJ-001",
            heading="GHG排出量とScope1・Scope2の開示",
            text="当社のGHG排出量に関する開示です。",
        )
        self.assertTrue(is_relevant_section(section),
                        "GHG/Scope1/Scope2を含むセクションが関連ありと判定されるべき")
        print("  [PASS] is_relevant_section: GHG/Scope1見出しセクション → True ✓")

    def test_is_relevant_section_detects_climate_heading(self):
        """気候変動関連見出しが関連ありと判定される"""
        section = SectionData(
            section_id="CLIM-001",
            heading="気候変動リスク・機会の開示",
            text="移行リスクと物理的リスクについて記載します。",
        )
        self.assertTrue(is_relevant_section(section),
                        "気候変動を含む見出しが関連ありと判定されるべき")
        print("  [PASS] is_relevant_section: 気候変動見出し → True ✓")

    def test_is_relevant_section_detects_ssbj_in_text(self):
        """本文先頭200文字にSSBJキーワードがある場合も関連ありと判定"""
        section = SectionData(
            section_id="ENV-001",
            heading="環境情報",
            text="SSBJ基準に従い、温室効果ガスの排出量を開示します。" + "a" * 200,
        )
        self.assertTrue(is_relevant_section(section),
                        "本文にSSBJキーワードがある場合も関連ありと判定されるべき")
        print("  [PASS] is_relevant_section: 本文SSBJキーワード → True ✓")

    def test_is_relevant_section_still_detects_human_capital(self):
        """既存の人的資本キーワードも引き続き関連ありと判定される（後退なし）"""
        section = SectionData(
            section_id="HC-001",
            heading="e. 人的資本経営に関する指標",
            text="当社は人材育成を推進しています。",
        )
        self.assertTrue(is_relevant_section(section),
                        "人的資本セクションが引き続き関連ありと判定されるべき")
        print("  [PASS] is_relevant_section: 人的資本キーワード後退なし → True ✓")

    def test_ssbj_law_entry_in_period(self):
        """
        CHECK-7b: SSBJ基準（施行2025-04-01）が2025年度3月決算の期間内であることを確認

        手計算:
          法令参照期間: 2025/04/01〜2026/03/31
          施行日: 2025-04-01
          2025-04-01 <= 2025-04-01 <= 2026-03-31 → True ✓
        """
        from datetime import date as dt
        start_str, end_str = calc_law_ref_period(2025, 3)
        start = dt.fromisoformat(start_str.replace("/", "-"))
        end = dt.fromisoformat(end_str.replace("/", "-"))
        ssbj_effective = dt(2025, 4, 1)  # sb-2025-001 effective_from

        in_period = start <= ssbj_effective <= end
        self.assertTrue(in_period,
            f"SSBJ基準(2025-04-01) は {start_str}〜{end_str} の範囲内のはず")
        print(f"  [PASS] CHECK-7b SSBJ sb-2025-001(2025-04-01) in {start_str}〜{end_str}: True ✓")


def run_all_tests():
    """全テストを実行し、結果を表示する"""
    print("=" * 60)
    print("disclosure-multiagent M3: ギャップ分析エージェント テスト")
    print("=" * 60)
    print()

    test_classes = [
        ("TEST 1: データクラス構築", TestDataclasses),
        ("TEST 2: change_type enum制約", TestChangeTypeEnum),
        ("TEST 3: source_confirmed警告生成", TestSourceConfirmedWarning),
        ("TEST 4: JSONパース（モック）", TestJsonParseMock),
        ("TEST 5: CHECK-7b 法令参照期間", TestCalcLawRefPeriod),
        ("TEST 6: SSBJキーワード・is_relevant_section", TestSSBJKeywords),
    ]

    total_pass = 0
    total_fail = 0
    total_error = 0

    for test_name, test_class in test_classes:
        print(f"\n--- {test_name} ---")
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(test_class)
        runner = unittest.TextTestRunner(verbosity=0, stream=open(os.devnull, "w"))
        import os
        result = runner.run(suite)

        # 手動で結果カウント
        if result.failures:
            for test, tb in result.failures:
                print(f"  [FAIL] {test}: {tb.splitlines()[-1]}")
                total_fail += 1
        if result.errors:
            for test, tb in result.errors:
                print(f"  [ERROR] {test}: {tb.splitlines()[-1]}")
                total_error += 1

        passed = result.testsRun - len(result.failures) - len(result.errors)
        total_pass += passed

    print()
    print("=" * 60)
    print(f"テスト結果: PASS={total_pass}, FAIL={total_fail}, ERROR={total_error}")
    if total_fail == 0 and total_error == 0:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 60)
    return total_fail == 0 and total_error == 0


if __name__ == "__main__":
    import os
    # unittest の標準出力を使用
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestDataclasses,
        TestChangeTypeEnum,
        TestSourceConfirmedWarning,
        TestJsonParseMock,
        TestCalcLawRefPeriod,
        TestSSBJKeywords,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    print("=== disclosure-multiagent M3 テスト実行 ===")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
