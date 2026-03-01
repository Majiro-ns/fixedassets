"""
test_m6_law_url_collector.py
============================
disclosure-multiagent Phase 2-M6: 法令URL自動収集スクリプト テスト

実行方法:
    cd scripts/
    python3 -m pytest test_m6_law_url_collector.py -v

テスト一覧:
    TestMatch (5件):
        TC-1: 完全一致 → confidence="high"
        TC-2: 部分一致1件 → confidence="medium"
        TC-3: 複数ヒット → confidence="low"（最近傍選択）
        TC-4: 一致なし → None
        TC-5: 被検索名が候補名を「含む」場合 → confidence="medium"

    TestGetLawList (3件):
        TC-6: _fetch 失敗（None返却）→ 空リスト
        TC-7: API エラーコード（Code != "0"）→ 空リスト
        TC-8: 正常 XML → list[dict] を返す（law_id/law_name）

    TestCollect (5件):
        TC-9:  source_confirmed:true エントリは unconfirmed に含まれない
        TC-10: source_confirmed:false + マッチあり → candidates に追加
        TC-11: source_confirmed:false + マッチなし → skipped に追加
        TC-12: 出力 JSON の metadata フィールドが正しい
        TC-13: candidates エントリのフォーマット（必須キー・URL形式）

CHECK-7b 手計算検算:
    [TC-1: 完全一致]
        laws = [{"law_id": "ID001", "law_name": "企業内容等の開示に関する内閣府令"}]
        _match("企業内容等の開示に関する内閣府令", laws)
        → law["law_name"] == law_name → confidence="high" ✓

    [TC-2: 部分一致1件]
        laws = [{"law_id": "ID001", "law_name": "企業内容等の開示に関する内閣府令"}]
        _match("開示に関する内閣府令", laws)  # 部分文字列
        → hits = [1件] → confidence="medium" ✓

    [TC-3: 複数ヒット・最近傍]
        laws = [{"law_name": "テスト法令短"}, {"law_name": "テスト法令長いもの"}]
        _match("テスト法令", laws)
        → hits = [2件]
        → |len("テスト法令短") - len("テスト法令")| = |6-5| = 1
        → |len("テスト法令長いもの") - len("テスト法令")| = |9-5| = 4
        → "テスト法令短" が最近傍 → confidence="low" ✓

    [TC-4: 一致なし]
        _match("存在しない法令名", [{"law_name": "全く別の法令"}])
        → 完全一致なし・部分一致なし → None ✓

    [TC-9: フィルタリング]
        fixture: TEST-001(false), TEST-002(true), TEST-003(false)
        unconfirmed = [TEST-001, TEST-003] → len=2、TEST-002 は除外 ✓

CHECK-9 テスト期待値の根拠:
    - m6_law_url_collector.py の _match() ロジック（行 63-74）から導出
    - confidence 定義: 完全一致=high / 部分一致1件=medium / 複数候補最近傍=low
    - collect() の unconfirmed フィルタ: `not e.get("source_confirmed", False)`
    - candidates 必須キー: entry_id / law_name / current_url / proposed_url /
                           egov_law_id / egov_law_name / confidence / source / note
"""

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# scripts/ ディレクトリから直接実行できるようパスを追加
sys.path.insert(0, str(Path(__file__).parent))

from m6_law_url_collector import _match, _get_law_list, collect


# ── テスト用定数 ──────────────────────────────────────────────────────────────

_FIXTURE_YAML = (
    Path(__file__).parent.parent / "tests" / "fixtures" / "test_laws.yaml"
)

# e-Gov API が返す最小 XML（正常系）
_MOCK_XML_OK = """\
<?xml version="1.0" encoding="UTF-8"?>
<DataRoot>
  <Result><Code>0</Code><Message/></Result>
  <ApplData>
    <LawNameListInfo>
      <LawId>ID001</LawId>
      <LawName>テスト法令A</LawName>
    </LawNameListInfo>
    <LawNameListInfo>
      <LawId>ID002</LawId>
      <LawName>テスト法令ロング版</LawName>
    </LawNameListInfo>
  </ApplData>
</DataRoot>"""

# e-Gov API が返すエラー XML（Code=1）
_MOCK_XML_ERROR = """\
<?xml version="1.0" encoding="UTF-8"?>
<DataRoot>
  <Result><Code>1</Code><Message>法令種別が誤っています。</Message></Result>
</DataRoot>"""


# ── TestMatch ────────────────────────────────────────────────────────────────

class TestMatch(unittest.TestCase):
    """_match() 関数のテスト（TC-1〜TC-5）"""

    def setUp(self):
        self.laws = [
            {"law_id": "ID001", "law_name": "テスト法令A"},
            {"law_id": "ID002", "law_name": "テスト法令A（施行令）"},
            {"law_id": "ID003", "law_name": "全く別の法令"},
        ]

    def test_tc1_exact_match_returns_high_confidence(self):
        """TC-1: 完全一致 → confidence="high"（_match ロジック行66-67）"""
        # CHECK-7b: "テスト法令A" == laws[0]["law_name"] → high
        result = _match("テスト法令A", self.laws)
        self.assertIsNotNone(result)
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["law_id"], "ID001")

    def test_tc2_partial_match_one_hit_returns_medium(self):
        """TC-2: 部分一致1件 → confidence="medium"（_match ロジック行69-70）"""
        # CHECK-7b: "全く別の法令" ←→ "全く別の法令（詳細版）" は部分一致1件
        laws = [{"law_id": "ID003", "law_name": "全く別の法令（詳細版）"}]
        result = _match("全く別の法令", laws)
        self.assertIsNotNone(result)
        self.assertEqual(result["confidence"], "medium")

    def test_tc3_multiple_hits_returns_low_with_nearest(self):
        """TC-3: 複数ヒット → confidence="low" + 最近傍を選択"""
        # CHECK-7b: "テスト法令A" に部分一致するのは ID001・ID002 の2件
        # |len("テスト法令A") - len("テスト法令A")| = 0 (ID001)
        # |len("テスト法令A") - len("テスト法令A（施行令）")| = 5 (ID002)
        # → ID001 が最近傍 → confidence="low"
        result = _match("テスト法令A", [
            {"law_id": "ID001", "law_name": "テスト法令A"},  # 完全一致は先に通るので別ケースにする
        ])
        # 完全一致が先にヒットするので複数ヒットケースは別データで確認
        laws_multi = [
            {"law_id": "ID001", "law_name": "テスト法令（短）"},
            {"law_id": "ID002", "law_name": "テスト法令（とても長い名前のもの）"},
        ]
        result = _match("テスト法令", laws_multi)
        self.assertIsNotNone(result)
        self.assertEqual(result["confidence"], "low")
        # "テスト法令（短）" の方が文字列長が "テスト法令" に近い
        self.assertEqual(result["law_id"], "ID001")

    def test_tc4_no_match_returns_none(self):
        """TC-4: 一致なし → None"""
        # CHECK-7b: "存在しない法令名" は laws にない → None
        result = _match("存在しない法令名", self.laws)
        self.assertIsNone(result)

    def test_tc5_query_contained_in_law_name_returns_medium(self):
        """TC-5: 被検索名が候補名の部分文字列 → confidence="medium"（1件）"""
        # CHECK-7b: "開示に関する内閣府令" は "企業内容等の開示に関する内閣府令" の部分文字列
        laws = [{"law_id": "ID010", "law_name": "企業内容等の開示に関する内閣府令"}]
        result = _match("開示に関する内閣府令", laws)
        self.assertIsNotNone(result)
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["law_id"], "ID010")


# ── TestGetLawList ───────────────────────────────────────────────────────────

class TestGetLawList(unittest.TestCase):
    """_get_law_list() のテスト（TC-6〜TC-8）"""

    @patch("m6_law_url_collector._fetch")
    def test_tc6_fetch_failure_returns_empty_list(self, mock_fetch):
        """TC-6: _fetch が None を返す（接続失敗等）→ 空リスト"""
        mock_fetch.return_value = None
        result = _get_law_list(2)
        self.assertEqual(result, [])
        mock_fetch.assert_called_once()

    @patch("m6_law_url_collector._fetch")
    def test_tc7_api_error_code_returns_empty_list(self, mock_fetch):
        """TC-7: API が Code=1（エラー）を返す → 空リスト"""
        mock_fetch.return_value = _MOCK_XML_ERROR
        result = _get_law_list(5)  # 無効カテゴリ
        self.assertEqual(result, [])

    @patch("m6_law_url_collector._fetch")
    def test_tc8_valid_xml_returns_law_list(self, mock_fetch):
        """TC-8: 正常 XML → list[dict] を返す（law_id・law_name キー）"""
        mock_fetch.return_value = _MOCK_XML_OK
        result = _get_law_list(2)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["law_id"], "ID001")
        self.assertEqual(result[0]["law_name"], "テスト法令A")
        self.assertEqual(result[1]["law_id"], "ID002")


# ── TestCollect ──────────────────────────────────────────────────────────────

class TestCollect(unittest.TestCase):
    """collect() 関数のテスト（TC-9〜TC-13）"""

    # e-Gov API モック: _fetch が呼ばれたら _MOCK_XML_OK を返す
    # TEST-001(law_name="テスト法令A") は ID001 と完全一致 → high
    # TEST-003(law_name="テスト法令C（一致なし）") は一致なし → skipped

    def _run_collect_with_mock(self, yaml_path: Path) -> dict:
        """_fetch をモックして collect() を実行する共通ヘルパー"""
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "output.json"
            with patch("m6_law_url_collector._fetch") as mock_fetch:
                mock_fetch.return_value = _MOCK_XML_OK
                result = collect(yaml_path, output_path)
            return result

    def test_tc9_source_confirmed_true_excluded_from_unconfirmed(self):
        """TC-9: source_confirmed:true エントリは処理対象外"""
        if not _FIXTURE_YAML.exists():
            self.skipTest(f"fixture not found: {_FIXTURE_YAML}")
        result = self._run_collect_with_mock(_FIXTURE_YAML)
        # metadata.unconfirmed_count は TEST-001 と TEST-003 の 2 件
        self.assertEqual(result["metadata"]["unconfirmed_count"], 2)
        # TEST-002（source_confirmed:true）は candidates にも skipped にも含まれない
        all_ids = (
            [c["entry_id"] for c in result["candidates"]]
            + [s["entry_id"] for s in result["skipped"]]
        )
        self.assertNotIn("TEST-002", all_ids)

    def test_tc10_match_found_produces_candidate(self):
        """TC-10: source_confirmed:false + マッチあり → candidates に追加"""
        if not _FIXTURE_YAML.exists():
            self.skipTest(f"fixture not found: {_FIXTURE_YAML}")
        result = self._run_collect_with_mock(_FIXTURE_YAML)
        # TEST-001 ("テスト法令A") は完全一致 → candidates
        candidate_ids = [c["entry_id"] for c in result["candidates"]]
        self.assertIn("TEST-001", candidate_ids)

    def test_tc11_no_match_produces_skipped(self):
        """TC-11: source_confirmed:false + マッチなし → skipped に追加"""
        if not _FIXTURE_YAML.exists():
            self.skipTest(f"fixture not found: {_FIXTURE_YAML}")
        result = self._run_collect_with_mock(_FIXTURE_YAML)
        # TEST-003 ("テスト法令C（一致なし）") はモック XML に一致なし → skipped
        skipped_ids = [s["entry_id"] for s in result["skipped"]]
        self.assertIn("TEST-003", skipped_ids)

    def test_tc12_metadata_fields_present(self):
        """TC-12: 出力 JSON の metadata が必須フィールドを持つ"""
        if not _FIXTURE_YAML.exists():
            self.skipTest(f"fixture not found: {_FIXTURE_YAML}")
        result = self._run_collect_with_mock(_FIXTURE_YAML)
        meta = result["metadata"]
        required_keys = {
            "yaml_path", "total_entries", "unconfirmed_count",
            "candidates_found", "skipped_count", "egov_api_status",
        }
        for key in required_keys:
            self.assertIn(key, meta, f"metadata に '{key}' がない")
        # 数値整合性: total = unconfirmed + confirmed
        # fixture: TEST-001(false) + TEST-002(true) + TEST-003(false) = 3
        self.assertEqual(meta["total_entries"], 3)
        self.assertEqual(meta["unconfirmed_count"], 2)

    def test_tc13_candidate_entry_format(self):
        """TC-13: candidates エントリが必須キーと正しい URL 形式を持つ"""
        if not _FIXTURE_YAML.exists():
            self.skipTest(f"fixture not found: {_FIXTURE_YAML}")
        result = self._run_collect_with_mock(_FIXTURE_YAML)
        # TEST-001 が candidates に存在するはず
        candidates = [c for c in result["candidates"] if c["entry_id"] == "TEST-001"]
        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        required_keys = {
            "entry_id", "law_name", "current_url", "proposed_url",
            "egov_law_id", "egov_law_name", "confidence", "source", "note",
        }
        for key in required_keys:
            self.assertIn(key, c, f"candidate に '{key}' がない")
        # proposed_url は e-Gov の URL 形式
        self.assertTrue(
            c["proposed_url"].startswith("https://laws.e-gov.go.jp/law/"),
            f"proposed_url が期待形式でない: {c['proposed_url']}",
        )
        # confidence は high（完全一致）
        self.assertEqual(c["confidence"], "high")


if __name__ == "__main__":
    unittest.main(verbosity=2)
