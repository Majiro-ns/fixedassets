"""
test_m2_law_agent.py
====================
disclosure-multiagent Phase 1-M2: 法令収集エージェント テスト

実行方法（実際のYAMLを使用・APIキー不要）:
    cd scripts/
    python3 test_m2_law_agent.py

テスト一覧:
    TEST 1: 実際のlaw_entries_human_capital.yamlを読み込んでLawContext生成
    TEST 2: 2025年度3月決算でHC_20260220_001（施行2026-02-20）が含まれることを確認
    TEST 3: 2024年度3月決算でHC_20260220_001が含まれないことを確認（期間外）
    TEST 4: CHECK-7b 法令参照期間の手計算検証
    TEST 5: 重要カテゴリ0件時の警告生成
    INTEGRATION: M3との統合確認
"""

import sys
import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch

# テスト対象モジュールをインポート
sys.path.insert(0, ".")
from m2_law_agent import (
    load_law_context,
    load_law_entries,
    get_applicable_entries,
    LAW_YAML_DIR,
    LAW_YAML_FILE,
    CRITICAL_CATEGORIES,
    _load_all_from_dir,
)
from m3_gap_analysis_agent import (
    LawEntry,
    calc_law_ref_period,
    _build_mock_report,
    analyze_gaps,
)

# 実際のYAMLファイルパス（TV-4: 実データ検証）
REAL_YAML_PATH = Path(__file__).parent.parent / "10_Research" / "law_entries_human_capital.yaml"


class TestLoadLawContext(unittest.TestCase):
    """TEST 1: 実際のlaw_entries_human_capital.yamlを読み込んでLawContext生成"""

    def test_load_real_yaml_returns_law_context(self):
        """実際のYAMLファイルを読み込んでLawContextが生成できる"""
        if not REAL_YAML_PATH.exists():
            self.skipTest(f"YAMLファイルが存在しません: {REAL_YAML_PATH}")

        ctx = load_law_context(2025, 3, yaml_path=REAL_YAML_PATH)

        # LawContextの構造確認
        self.assertEqual(ctx.fiscal_year, 2025)
        self.assertEqual(ctx.fiscal_month_end, 3)
        self.assertIsNotNone(ctx.law_yaml_as_of)
        self.assertIsInstance(ctx.applicable_entries, list)
        self.assertIsInstance(ctx.warnings, list)
        self.assertIsInstance(ctx.missing_categories, list)
        print(f"  [PASS] LawContext生成: applicable_entries={len(ctx.applicable_entries)}件, "
              f"law_yaml_as_of={ctx.law_yaml_as_of} ✓")

    def test_load_all_entries_count(self):
        """YAMLから全エントリ数を確認（TV-4: 実データ検証）"""
        if not REAL_YAML_PATH.exists():
            self.skipTest(f"YAMLファイルが存在しません: {REAL_YAML_PATH}")

        entries = load_law_entries(REAL_YAML_PATH)
        # law_entries_human_capital.yaml には7エントリが存在する（タスク仕様より）
        self.assertGreaterEqual(len(entries), 5, "最低5エントリ存在するはず")
        print(f"  [PASS] 全エントリ読み込み: {len(entries)}件 ✓")

    def test_law_yaml_as_of_format(self):
        """law_yaml_as_of が YYYY-MM-DD 形式である"""
        if not REAL_YAML_PATH.exists():
            self.skipTest(f"YAMLファイルが存在しません: {REAL_YAML_PATH}")

        ctx = load_law_context(2025, 3, yaml_path=REAL_YAML_PATH)
        # YYYY-MM-DD 形式チェック
        import re
        self.assertRegex(
            ctx.law_yaml_as_of,
            r"^\d{4}-\d{2}-\d{2}$",
            f"law_yaml_as_of={ctx.law_yaml_as_of} は YYYY-MM-DD 形式でない",
        )
        print(f"  [PASS] law_yaml_as_of形式: {ctx.law_yaml_as_of} ✓")


class TestApplicableEntriesFilter(unittest.TestCase):
    """TEST 2/3: 年度フィルタリングの正確性"""

    def test_2025_fiscal_year_includes_hc_20260220_001(self):
        """
        TEST 2: 2025年度3月決算でHC_20260220_001（施行2026-02-20）が含まれる

        手計算:
          fiscal_year=2025, fiscal_month_end=3
          参照期間: 2025/04/01〜2026/03/31
          HC_20260220_001 effective_from=2026-02-20
          2025-04-01 <= 2026-02-20 <= 2026-03-31 → True ✓ (含まれる)
        """
        if not REAL_YAML_PATH.exists():
            self.skipTest(f"YAMLファイルが存在しません: {REAL_YAML_PATH}")

        ctx = load_law_context(2025, 3, yaml_path=REAL_YAML_PATH)
        entry_ids = [e.id for e in ctx.applicable_entries]

        self.assertIn(
            "HC_20260220_001",
            entry_ids,
            f"HC_20260220_001が2025年度のapplicable_entriesに含まれていない: {entry_ids}",
        )
        # 施行日が参照期間内であることを確認
        hc_entry = next(e for e in ctx.applicable_entries if e.id == "HC_20260220_001")
        self.assertEqual(hc_entry.effective_from, "2026-02-20")
        print(f"  [PASS] 2025年度にHC_20260220_001(2026-02-20)が含まれる ✓")
        print(f"         参照期間: 2025/04/01〜2026/03/31")
        print(f"         applicable_entries: {entry_ids}")

    def test_2024_fiscal_year_excludes_hc_20260220_001(self):
        """
        TEST 3: 2024年度3月決算でHC_20260220_001（施行2026-02-20）が含まれない

        手計算:
          fiscal_year=2024, fiscal_month_end=3
          参照期間: 2024/04/01〜2025/03/31
          HC_20260220_001 effective_from=2026-02-20
          2026-02-20 > 2025-03-31 → False (含まれない)
        """
        if not REAL_YAML_PATH.exists():
            self.skipTest(f"YAMLファイルが存在しません: {REAL_YAML_PATH}")

        ctx = load_law_context(2024, 3, yaml_path=REAL_YAML_PATH)
        entry_ids = [e.id for e in ctx.applicable_entries]

        self.assertNotIn(
            "HC_20260220_001",
            entry_ids,
            f"HC_20260220_001が2024年度のapplicable_entriesに誤って含まれている: {entry_ids}",
        )
        print(f"  [PASS] 2024年度にHC_20260220_001(2026-02-20)が含まれない ✓")
        print(f"         参照期間: 2024/04/01〜2025/03/31")
        print(f"         applicable_entries: {entry_ids}")

    def test_get_applicable_entries_date_boundary(self):
        """境界値テスト: 参照期間の開始日・終了日ちょうどのエントリ"""
        entries = [
            LawEntry(
                id="TEST_START",
                title="期間開始日のエントリ",
                category="金商法・開示府令",
                change_type="追加必須",
                disclosure_items=["テスト項目"],
                source="https://example.com",
                source_confirmed=True,
                effective_from="2025-04-01",  # 期間開始日ちょうど
            ),
            LawEntry(
                id="TEST_END",
                title="期間終了日のエントリ",
                category="金商法・開示府令",
                change_type="追加必須",
                disclosure_items=["テスト項目"],
                source="https://example.com",
                source_confirmed=True,
                effective_from="2026-03-31",  # 期間終了日ちょうど
            ),
            LawEntry(
                id="TEST_BEFORE",
                title="期間前のエントリ",
                category="金商法・開示府令",
                change_type="追加必須",
                disclosure_items=["テスト項目"],
                source="https://example.com",
                source_confirmed=True,
                effective_from="2025-03-31",  # 期間開始日の前日 → 含まれないはず
            ),
            LawEntry(
                id="TEST_AFTER",
                title="期間後のエントリ",
                category="金商法・開示府令",
                change_type="追加必須",
                disclosure_items=["テスト項目"],
                source="https://example.com",
                source_confirmed=True,
                effective_from="2026-04-01",  # 期間終了日の翌日 → 含まれないはず
            ),
        ]
        ref_period = ("2025/04/01", "2026/03/31")
        result = get_applicable_entries(entries, ref_period)
        result_ids = [e.id for e in result]

        self.assertIn("TEST_START", result_ids, "期間開始日ちょうどのエントリが含まれない")
        self.assertIn("TEST_END", result_ids, "期間終了日ちょうどのエントリが含まれない")
        self.assertNotIn("TEST_BEFORE", result_ids, "期間前のエントリが誤って含まれている")
        self.assertNotIn("TEST_AFTER", result_ids, "期間後のエントリが誤って含まれている")
        print(f"  [PASS] 境界値テスト: 開始日・終了日ちょうどのエントリを正しく処理 ✓")


class TestCalcLawRefPeriod(unittest.TestCase):
    """TEST 4: CHECK-7b 法令参照期間の手計算検証（TV-4: 実データで根拠確認）"""

    def test_2025_march_period(self):
        """
        CHECK-7b: 2025年度3月決算 → 2025/04/01〜2026/03/31

        手計算（m3の定義通り）:
          fiscal_year=2025, fiscal_month_end=3
          start = "2025" + "/04/01" = "2025/04/01"
          end = str(2025+1) + "/03/31" = "2026/03/31"

        根拠（TV-4）: m3_gap_analysis_agent.py calc_law_ref_period() の実装
        → HC_20260220_001(2026-02-20) が2025/04/01〜2026/03/31の範囲内 ✓
        """
        start, end = calc_law_ref_period(2025, 3)
        self.assertEqual(start, "2025/04/01", f"期待=2025/04/01, 実際={start}")
        self.assertEqual(end, "2026/03/31", f"期待=2026/03/31, 実際={end}")

        # HC_20260220_001の施行日が期間内であることを手計算で確認
        d_start = date.fromisoformat(start.replace("/", "-"))
        d_end = date.fromisoformat(end.replace("/", "-"))
        hc_date = date(2026, 2, 20)
        in_period = d_start <= hc_date <= d_end
        self.assertTrue(in_period)
        print(f"  [PASS] CHECK-7b 2025年度3月決算: {start}〜{end}")
        print(f"         HC_20260220_001(2026-02-20) in period: {in_period} ✓")

    def test_2024_march_period(self):
        """
        CHECK-7b: 2024年度3月決算 → 2024/04/01〜2025/03/31

        手計算:
          fiscal_year=2024, fiscal_month_end=3
          start = "2024" + "/04/01" = "2024/04/01"
          end = str(2024+1) + "/03/31" = "2025/03/31"

        根拠（TV-4）: HC_20260220_001(2026-02-20) は2025/03/31より後
        → 2024年度の参照期間外 → 含まれないことを確認
        """
        start, end = calc_law_ref_period(2024, 3)
        self.assertEqual(start, "2024/04/01", f"期待=2024/04/01, 実際={start}")
        self.assertEqual(end, "2025/03/31", f"期待=2025/03/31, 実際={end}")

        # HC_20260220_001が期間外であることを確認
        d_end = date.fromisoformat(end.replace("/", "-"))
        hc_date = date(2026, 2, 20)
        self.assertGreater(hc_date, d_end,
            f"HC_20260220_001(2026-02-20) <= {end} となっており期間内に誤判定される")
        print(f"  [PASS] CHECK-7b 2024年度3月決算: {start}〜{end}")
        print(f"         HC_20260220_001(2026-02-20) > {end}: True ✓ (期間外)")

    def test_hc_20230131_001_in_2022_fiscal_year(self):
        """
        HC_20230131_001（施行2023-01-31）が2022年度3月決算に含まれるか確認

        手計算:
          fiscal_year=2022, fiscal_month_end=3
          参照期間: 2022/04/01〜2023/03/31
          HC_20230131_001 effective_from=2023-01-31
          2022-04-01 <= 2023-01-31 <= 2023-03-31 → True (含まれる)
        """
        start, end = calc_law_ref_period(2022, 3)
        d_start = date.fromisoformat(start.replace("/", "-"))
        d_end = date.fromisoformat(end.replace("/", "-"))
        hc_date = date(2023, 1, 31)
        in_period = d_start <= hc_date <= d_end
        self.assertTrue(in_period)
        print(f"  [PASS] HC_20230131_001(2023-01-31) in 2022年度({start}〜{end}): True ✓")

    def test_tc_new1_march_backward_compat(self):
        """
        TC-NEW-1: 3月決算（M7.5拡張後も既存動作と同一）fiscal_year=2025 → 2025/04/01〜2026/03/31

        CHECK-7b 手計算:
            fiscal_month_end=3, fiscal_year=2025
            start: fiscal_year/04/01 = 2025/04/01
            end:   (fiscal_year+1)/03/31 = 2026/03/31
        根拠: m3_gap_analysis_agent.py calc_law_ref_period() 実装（改変禁止）
        """
        start, end = calc_law_ref_period(2025, 3)
        self.assertEqual(start, "2025/04/01", f"期待=2025/04/01, 実際={start}")
        self.assertEqual(end, "2026/03/31", f"期待=2026/03/31, 実際={end}")
        print(f"  [PASS] TC-NEW-1 3月決算(2025): {start}〜{end} ✓")

    def test_tc_new2_december_fiscal(self):
        """
        TC-NEW-2: 12月決算 fiscal_year=2025 → 2025/01/01〜2025/12/31

        CHECK-7b 手計算:
            fiscal_month_end=12, fiscal_year=2025
            start: fiscal_year/01/01 = 2025/01/01  (1月始まり)
            end:   fiscal_year/12/31 = 2025/12/31  (12月末)
        根拠: m3_gap_analysis_agent.py calc_law_ref_period() — fiscal_month_end==12 分岐
        対象企業例: 12月決算企業（自動車メーカー等）の有報対応
        """
        start, end = calc_law_ref_period(2025, 12)
        self.assertEqual(start, "2025/01/01", f"期待=2025/01/01, 実際={start}")
        self.assertEqual(end, "2025/12/31", f"期待=2025/12/31, 実際={end}")
        # 期間内の日付確認
        d_start = date.fromisoformat(start.replace("/", "-"))
        d_end   = date.fromisoformat(end.replace("/", "-"))
        self.assertLess(d_start, d_end)
        self.assertEqual((d_end - d_start).days, 364)  # 2025年は365日-1日
        print(f"  [PASS] TC-NEW-2 12月決算(2025): {start}〜{end} ✓")

    def test_tc_new3_june_fiscal(self):
        """
        TC-NEW-3: 6月決算 fiscal_year=2025 → 2025/07/01〜2026/06/30

        CHECK-7b 手計算:
            fiscal_month_end=6, fiscal_year=2025
            start_month = 6 + 1 = 7
            start: 2025/07/01
            end_day: 6月 → 30日
            end: (2025+1)/06/30 = 2026/06/30
        根拠: m3_gap_analysis_agent.py calc_law_ref_period() — 一般ケース分岐
        """
        start, end = calc_law_ref_period(2025, 6)
        self.assertEqual(start, "2025/07/01", f"期待=2025/07/01, 実際={start}")
        self.assertEqual(end, "2026/06/30", f"期待=2026/06/30, 実際={end}")
        print(f"  [PASS] TC-NEW-3 6月決算(2025): {start}〜{end} ✓")

    def test_tc_new4_september_fiscal(self):
        """
        TC-NEW-4: 9月決算 fiscal_year=2025 → 2025/10/01〜2026/09/30

        CHECK-7b 手計算:
            fiscal_month_end=9, fiscal_year=2025
            start_month = 9 + 1 = 10
            start: 2025/10/01
            end_day: 9月 → 30日
            end: (2025+1)/09/30 = 2026/09/30
        根拠: m3_gap_analysis_agent.py calc_law_ref_period() — 一般ケース分岐
        """
        start, end = calc_law_ref_period(2025, 9)
        self.assertEqual(start, "2025/10/01", f"期待=2025/10/01, 実際={start}")
        self.assertEqual(end, "2026/09/30", f"期待=2026/09/30, 実際={end}")
        print(f"  [PASS] TC-NEW-4 9月決算(2025): {start}〜{end} ✓")

    def test_tc_new5_january_fiscal_boundary(self):
        """
        TC-NEW-5: 1月決算（境界値）fiscal_year=2025 → 2025/02/01〜2026/01/31

        CHECK-7b 手計算:
            fiscal_month_end=1, fiscal_year=2025
            start_month = 1 + 1 = 2
            start: 2025/02/01
            end_day: 1月 → 31日
            end: (2025+1)/01/31 = 2026/01/31
        根拠: m3_gap_analysis_agent.py calc_law_ref_period() — 一般ケース分岐
        特記: 1月は期末月が最小値（2月〜1月の会計年度）の境界値
        """
        start, end = calc_law_ref_period(2025, 1)
        self.assertEqual(start, "2025/02/01", f"期待=2025/02/01, 実際={start}")
        self.assertEqual(end, "2026/01/31", f"期待=2026/01/31, 実際={end}")
        print(f"  [PASS] TC-NEW-5 1月決算(2025): {start}〜{end} ✓")


class TestWarnings(unittest.TestCase):
    """TEST 5: 重要カテゴリ0件時の警告生成"""

    def test_missing_critical_category_warning(self):
        """
        重要カテゴリが0件の場合、warnings と missing_categories に記録される

        使用ダミーエントリ: 人的資本ガイダンスのみ → 金商法・開示府令とSSBJが0件
        """
        dummy_entries = [
            LawEntry(
                id="HC_DUMMY",
                title="ダミーガイダンス",
                category="人的資本ガイダンス",
                change_type="参考",
                disclosure_items=["ダミー項目"],
                source="https://example.com",
                source_confirmed=True,
                effective_from="2025-06-01",
            )
        ]
        ref_period = ("2025/04/01", "2026/03/31")

        # get_applicable_entries でフィルタ
        applicable = get_applicable_entries(dummy_entries, ref_period)

        # missing_categories を手動で計算
        from m2_law_agent import CRITICAL_CATEGORIES
        missing = [
            cat for cat in CRITICAL_CATEGORIES
            if not any(e.category == cat for e in applicable)
        ]

        self.assertIn("金商法・開示府令", missing)
        self.assertIn("SSBJ", missing)
        self.assertNotIn("人的資本ガイダンス", missing)
        print(f"  [PASS] missing_categories: {missing} ✓")

    def test_real_yaml_2025_no_ssbj_warning(self):
        """
        実際のlaw_entries_human_capital.yamlで2025年度3月決算を実行し
        warningsの内容を確認する（実データによるTV-4検証）
        """
        if not REAL_YAML_PATH.exists():
            self.skipTest(f"YAMLファイルが存在しません: {REAL_YAML_PATH}")

        ctx = load_law_context(2025, 3, yaml_path=REAL_YAML_PATH)
        print(f"  [INFO] 2025年度warnings: {ctx.warnings}")
        print(f"  [INFO] 2025年度missing_categories: {ctx.missing_categories}")
        # warningsは空でも0件警告でもよい（実YAMLの内容次第）
        self.assertIsInstance(ctx.warnings, list)
        self.assertIsInstance(ctx.missing_categories, list)
        print(f"  [PASS] warnings型確認 ✓")

    def test_file_not_found_raises(self):
        """存在しないYAMLファイルを指定するとFileNotFoundError"""
        with self.assertRaises(FileNotFoundError) as ctx:
            load_law_context(2025, 3, yaml_path=Path("/nonexistent/path.yaml"))
        # エラーメッセージにパス名が含まれること
        self.assertIn("nonexistent", str(ctx.exception))
        print(f"  [PASS] FileNotFoundError発生 '{str(ctx.exception)[:50]}...' ✓")


class TestM3Integration(unittest.TestCase):
    """M3との統合確認テスト（タスク仕様 Section 4）"""

    def test_m2_to_m3_pipeline(self):
        """
        M2→M3パイプラインのE2Eテスト

        law_context = load_law_context(2025, 3)
        report = _build_mock_report()
        result = analyze_gaps(report, law_context, use_mock=True)
        assert result is not None
        """
        if not REAL_YAML_PATH.exists():
            self.skipTest(f"YAMLファイルが存在しません: {REAL_YAML_PATH}")

        # M2: 法令コンテキスト取得
        law_ctx = load_law_context(2025, 3, yaml_path=REAL_YAML_PATH)
        self.assertGreater(len(law_ctx.applicable_entries), 0,
                           "2025年度の適用エントリが0件")

        # M3: ギャップ分析
        report = _build_mock_report()
        result = analyze_gaps(report, law_ctx, use_mock=True)

        # 結果確認
        self.assertIsNotNone(result)
        self.assertEqual(result.document_id, "S100VHUZ_MOCK")
        self.assertEqual(result.fiscal_year, 2025)
        # law_yaml_as_ofがM2からM3に正しく伝搬されること
        self.assertEqual(result.law_yaml_as_of, law_ctx.law_yaml_as_of)
        self.assertIsInstance(result.gaps, list)
        self.assertIsInstance(result.no_gap_items, list)

        print(f"  [PASS] M2→M3パイプライン:")
        print(f"         M2 applicable_entries: {len(law_ctx.applicable_entries)}件")
        print(f"         M3 total_gaps: {result.summary.total_gaps}")
        print(f"         law_yaml_as_of伝搬: {law_ctx.law_yaml_as_of} → {result.law_yaml_as_of} ✓")

    def test_law_yaml_as_of_propagation(self):
        """law_yaml_as_ofがM2からM3に正しく伝搬される"""
        if not REAL_YAML_PATH.exists():
            self.skipTest(f"YAMLファイルが存在しません: {REAL_YAML_PATH}")

        law_ctx = load_law_context(2025, 3, yaml_path=REAL_YAML_PATH)
        report = _build_mock_report()
        result = analyze_gaps(report, law_ctx, use_mock=True)

        self.assertEqual(
            result.law_yaml_as_of,
            law_ctx.law_yaml_as_of,
            "law_yaml_as_ofがM3結果に正しく伝搬されていない",
        )
        print(f"  [PASS] law_yaml_as_of伝搬: '{law_ctx.law_yaml_as_of}' ✓")


class TestLawsDirectoryLoading(unittest.TestCase):
    """
    TEST 6: laws/ ディレクトリ全体読み込みテスト（D-LAW-DIR-fix 追加）

    laws/human_capital_2024.yaml / ssbj_2025.yaml / shareholder_notice_2025.yaml
    が全件 m2 に読み込まれることを確認する。
    """

    def test_law_yaml_dir_points_to_laws(self):
        """LAW_YAML_DIR が laws/ を指していること（10_Research/ ではない）"""
        self.assertTrue(
            LAW_YAML_DIR.name == "laws" or str(LAW_YAML_DIR).endswith("/laws"),
            f"LAW_YAML_DIR が laws/ を指していません: {LAW_YAML_DIR}"
        )

    def test_laws_dir_has_three_yamls(self):
        """laws/ 配下に3件のYAMLが存在すること"""
        yaml_files = list(LAW_YAML_DIR.glob("*.yaml"))
        self.assertEqual(
            len(yaml_files), 3,
            f"laws/*.yaml が3件ではありません: {[f.name for f in yaml_files]}"
        )

    def test_load_all_from_dir_returns_all_entries(self):
        """_load_all_from_dir() が laws/ 配下の全YAMLを結合して返すこと"""
        if not LAW_YAML_DIR.exists():
            self.skipTest(f"laws/ ディレクトリが存在しません: {LAW_YAML_DIR}")
        all_entries, _ = _load_all_from_dir(LAW_YAML_DIR)
        # 3ファイル結合（human_capital + ssbj + shareholder_notice）で40件超を期待
        self.assertGreater(len(all_entries), 40,
                           f"laws/ 全YAML結合エントリ数が少なすぎます: {len(all_entries)}件")

    def test_load_all_from_dir_includes_ssbj(self):
        """ssbj_2025.yaml のエントリが読み込まれること"""
        if not LAW_YAML_DIR.exists():
            self.skipTest(f"laws/ ディレクトリが存在しません: {LAW_YAML_DIR}")
        all_entries, _ = _load_all_from_dir(LAW_YAML_DIR)
        # ssbj_2025.yaml のIDは "sb-" プレフィックス（例: sb-2025-001）
        ssbj_entries = [e for e in all_entries if e.id.startswith("sb-")]
        self.assertGreater(len(ssbj_entries), 0,
                           "ssbj_2025.yaml のエントリが0件（sb- プレフィックスのIDが見つからない）")

    def test_load_all_from_dir_includes_human_capital(self):
        """human_capital_2024.yaml のエントリが読み込まれること"""
        if not LAW_YAML_DIR.exists():
            self.skipTest(f"laws/ ディレクトリが存在しません: {LAW_YAML_DIR}")
        all_entries, _ = _load_all_from_dir(LAW_YAML_DIR)
        hc_entries = [e for e in all_entries if e.id.startswith("hc-")]
        self.assertGreater(len(hc_entries), 0,
                           "human_capital_2024.yaml のエントリが0件（hc- プレフィックスのIDが見つからない）")

    def test_load_all_from_dir_includes_shareholder_notice(self):
        """shareholder_notice_2025.yaml のエントリが読み込まれること"""
        if not LAW_YAML_DIR.exists():
            self.skipTest(f"laws/ ディレクトリが存在しません: {LAW_YAML_DIR}")
        all_entries, _ = _load_all_from_dir(LAW_YAML_DIR)
        gm_entries = [e for e in all_entries if e.id.startswith("gm-") or e.id.startswith("gc-")]
        self.assertGreater(len(gm_entries), 0,
                           "shareholder_notice_2025.yaml のエントリが0件（gm-/gc- プレフィックスのIDが見つからない）")

    def test_default_load_law_context_reads_all_yamls(self):
        """yaml_path=None のデフォルト呼び出しが laws/ 全体を読み込むこと（エラーなし確認）"""
        if not LAW_YAML_DIR.exists():
            self.skipTest(f"laws/ ディレクトリが存在しません: {LAW_YAML_DIR}")
        # デフォルト呼び出しでエラーが起きないこと（FileNotFoundError等）を確認
        ctx = load_law_context(2025, 3)
        self.assertIsNotNone(ctx)
        # 注: applicable_entries は日付フィルタ（effective_from が参照期間内）で絞られる
        # laws/ 配下の全エントリがフィルタ前に読まれていることを別テストで確認済み
        all_entries, _ = _load_all_from_dir(LAW_YAML_DIR)
        self.assertGreater(len(all_entries), 40,
                           f"デフォルト呼び出しの全エントリ（フィルタ前）が少なすぎます: {len(all_entries)}件")


if __name__ == "__main__":
    import os
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestLoadLawContext,
        TestApplicableEntriesFilter,
        TestCalcLawRefPeriod,
        TestWarnings,
        TestM3Integration,
        TestLawsDirectoryLoading,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    print("=== disclosure-multiagent M2 テスト実行 ===")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
