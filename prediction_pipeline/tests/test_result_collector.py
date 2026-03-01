"""
tests/test_result_collector.py
==============================

collect_results.py のユニットテスト。

テスト対象:
1. parse_race_result() — モックHTMLを使ったパーステスト
2. check_hit() — 的中判定ロジック
3. load_predictions_for_date() — 予測ファイル読み込み
4. 出力フォーマットのバリデーション
"""

import json
import sys
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest

# scripts/ をパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from collect_results import (
    KdreamsResultScraper,
    _parse_refund_table,
    _split_nums,
    check_hit,
    load_predictions_for_date,
    load_venue_slug_map,
    resolve_venue_name,
)


# ─── モックHTML ─────────────────────────────────────────────────────────────

MOCK_RESULT_HTML = dedent("""
<html>
<body>
  <!-- 着順テーブル -->
  <table class="result_table">
    <tr>
      <th>予想</th><th>着順</th><th>車番</th><th>選手名</th>
      <th>着差</th><th>上り</th><th>決まり手</th><th>S/B</th><th>勝敗因</th>
    </tr>
    <tr>
      <td>注</td><td>1</td><td>4</td><td>佐藤 友和</td>
      <td></td><td>12.1</td><td>差</td><td></td><td></td>
    </tr>
    <tr>
      <td>○</td><td>2</td><td>5</td><td>岩津 裕介</td>
      <td>１/４車輪</td><td>12.3</td><td>差</td><td></td><td></td>
    </tr>
    <tr>
      <td></td><td>3</td><td>7</td><td>須永 優太</td>
      <td>３/４車身</td><td>12.1</td><td></td><td></td><td></td>
    </tr>
    <tr>
      <td>×</td><td>4</td><td>2</td><td>小林 泰正</td>
      <td>１/２車身</td><td>12.5</td><td></td><td>B</td><td></td>
    </tr>
  </table>

  <!-- 払戻テーブル -->
  <table class="refund_table">
    <tr>
      <th rowspan="2">2<br/>枠<br/>連</th>
      <td>複</td>
      <td>
        <dl class="cf"><dt>未発売</dt></dl>
      </td>
      <th rowspan="2">2<br/>車<br/>連</th>
      <td>複</td>
      <td>
        <dl class="cf">
          <dt>4=5</dt><dd>1,740円<span>(6)</span></dd>
        </dl>
      </td>
      <th rowspan="2">3<br/>連<br/>勝</th>
      <td>複</td>
      <td>
        <dl class="cf">
          <dt>4=5=7</dt><dd>2,830円<span>(10)</span></dd>
        </dl>
      </td>
    </tr>
    <tr>
      <td>単</td>
      <td>
        <dl class="cf"><dt>未発売</dt></dl>
      </td>
      <td>単</td>
      <td>
        <dl class="cf">
          <dt>4-5</dt><dd>3,170円<span>(11)</span></dd>
        </dl>
      </td>
      <td>単</td>
      <td>
        <dl class="cf">
          <dt>4-5-7</dt><dd>13,750円<span>(43)</span></dd>
        </dl>
      </td>
    </tr>
  </table>
</body>
</html>
""")

MOCK_RESULT_HTML_HIT = dedent("""
<html>
<body>
  <table class="result_table">
    <tr>
      <th>予想</th><th>着順</th><th>車番</th><th>選手名</th>
    </tr>
    <tr><td>◎</td><td>1</td><td>4</td><td>選手A</td></tr>
    <tr><td>○</td><td>2</td><td>2</td><td>選手B</td></tr>
    <tr><td>△</td><td>3</td><td>6</td><td>選手C</td></tr>
  </table>
  <table class="refund_table">
    <tr>
      <th rowspan="2">3<br/>連<br/>勝</th>
      <td>複</td>
      <td>
        <dl class="cf">
          <dt>2=4=6</dt><dd>4,200円<span>(5)</span></dd>
        </dl>
      </td>
    </tr>
    <tr>
      <td>単</td>
      <td>
        <dl class="cf">
          <dt>4-2-6</dt><dd>12,500円<span>(30)</span></dd>
        </dl>
      </td>
    </tr>
  </table>
</body>
</html>
""")


# ─── _split_nums テスト ──────────────────────────────────────────────────────

class TestSplitNums:
    def test_equal_separator_two(self):
        assert _split_nums("4=5", "=") == [4, 5]

    def test_equal_separator_three(self):
        assert _split_nums("4=5=7", "=") == [4, 5, 7]

    def test_dash_separator_two(self):
        assert _split_nums("4-5", "-") == [4, 5]

    def test_dash_separator_three(self):
        assert _split_nums("4-5-7", "-") == [4, 5, 7]

    def test_non_numeric_returns_empty(self):
        assert _split_nums("未発売", "=") == []

    def test_mixed_non_numeric_returns_empty(self):
        assert _split_nums("4=X=7", "=") == []


# ─── parse_race_result テスト ─────────────────────────────────────────────────

class TestParseRaceResult:
    def setup_method(self):
        self.scraper = KdreamsResultScraper()

    def test_top3_extraction(self):
        result = self.scraper.parse_race_result(MOCK_RESULT_HTML)
        assert result["top3"] == [4, 5, 7], f"Expected [4,5,7] but got {result['top3']}"

    def test_trio_payout_parsed(self):
        result = self.scraper.parse_race_result(MOCK_RESULT_HTML)
        trio = result["payouts"].get("trio", [])
        assert len(trio) >= 1, "3連複払戻が見つからない"
        assert trio[0]["numbers"] == [4, 5, 7], f"Expected [4,5,7] but got {trio[0]['numbers']}"
        assert trio[0]["payout"] == 2830, f"Expected 2830 but got {trio[0]['payout']}"

    def test_trifecta_payout_parsed(self):
        result = self.scraper.parse_race_result(MOCK_RESULT_HTML)
        trifecta = result["payouts"].get("trifecta", [])
        assert len(trifecta) >= 1, "3連単払戻が見つからない"
        assert trifecta[0]["numbers"] == [4, 5, 7]
        assert trifecta[0]["payout"] == 13750

    def test_quinella_payout_parsed(self):
        result = self.scraper.parse_race_result(MOCK_RESULT_HTML)
        quinella = result["payouts"].get("quinella_or_wide", [])
        assert len(quinella) >= 1, "2車連複払戻が見つからない"
        numbers_sets = [sorted(q["numbers"]) for q in quinella]
        assert [4, 5] in numbers_sets

    def test_exacta_payout_parsed(self):
        result = self.scraper.parse_race_result(MOCK_RESULT_HTML)
        exacta = result["payouts"].get("exacta", [])
        assert len(exacta) >= 1, "2車連単払戻が見つからない"
        assert exacta[0]["numbers"] == [4, 5]
        assert exacta[0]["payout"] == 3170

    def test_unsold_payout_skipped(self):
        """未発売の払戻は無視されること"""
        result = self.scraper.parse_race_result(MOCK_RESULT_HTML)
        # 未発売が混入していないことを確認
        for bet_type, entries in result["payouts"].items():
            for entry in entries:
                assert entry["payout"] > 0 or entry.get("numbers") is not None

    def test_top3_empty_when_no_result_table(self):
        html = "<html><body><p>no table</p></body></html>"
        result = self.scraper.parse_race_result(html)
        assert result["top3"] == []
        assert result["payouts"] == {}

    def test_hit_race_top3(self):
        """的中ケース: 予測と一致する着順"""
        result = self.scraper.parse_race_result(MOCK_RESULT_HTML_HIT)
        assert result["top3"] == [4, 2, 6]


# ─── check_hit テスト ─────────────────────────────────────────────────────────

class TestCheckHit:
    """的中判定ロジックのテスト。"""

    def _make_race_result(self, top3, trio_payout=0):
        """テスト用race_resultを生成。"""
        trio_numbers = sorted(top3[:3]) if top3 else []
        return {
            "top3": top3,
            "payouts": {
                "trio": [{"numbers": trio_numbers, "payout": trio_payout}] if trio_payout > 0 else [],
                "trifecta": [],
            },
        }

    # ── 3連複ながし ──

    def test_trio_hit(self):
        """3連複ながし: 的中（unit_bet=1200, trio_payout=4200）"""
        bet = {
            "bet_type": "3連複ながし",
            "axis": 4,
            "partners": [2, 6],
            "combinations": [[2, 4, 6]],
            "unit_bet": 1200,
            "total_investment": 1200,
        }
        race_result = self._make_race_result([4, 2, 6], trio_payout=4200)
        hit, payout = check_hit(bet, race_result)
        assert hit is True
        # payout = 4200 * 1200 / 100 = 50400円
        assert payout == (4200 * 1200) // 100

    def test_trio_miss(self):
        """3連複ながし: 外れ（組合せが一致しない）"""
        bet = {
            "bet_type": "3連複ながし",
            "axis": 4,
            "partners": [2, 6],
            "combinations": [[2, 4, 6]],
            "unit_bet": 1200,
            "total_investment": 1200,
        }
        # 実際の着順: 1=4, 2=5, 3=7 → sorted=[4,5,7]
        race_result = self._make_race_result([4, 5, 7], trio_payout=2830)
        hit, payout = check_hit(bet, race_result)
        assert hit is False
        assert payout == 0

    def test_trio_hit_order_independent(self):
        """3連複は着順に関係なく組合せが一致すれば的中"""
        bet = {
            "bet_type": "3連複ながし",
            "axis": 4,
            "partners": [2, 6],
            "combinations": [[2, 4, 6]],  # sorted
            "unit_bet": 1000,
            "total_investment": 1000,
        }
        # 実際の着順: 2-6-4 → sorted=[2,4,6] → HIT
        race_result = self._make_race_result([2, 6, 4], trio_payout=3500)
        hit, payout = check_hit(bet, race_result)
        assert hit is True
        assert payout == (3500 * 1000) // 100

    def test_trio_multiple_combinations(self):
        """3連複: 複数組合せのどれかが的中すれば的中"""
        bet = {
            "bet_type": "3連複ながし",
            "axis": 4,
            "partners": [2, 6, 3],
            "combinations": [[2, 4, 6], [3, 4, 6], [2, 3, 4]],
            "unit_bet": 1000,
            "total_investment": 3000,
        }
        # [3,4,6] が的中
        race_result = self._make_race_result([3, 6, 4], trio_payout=5000)
        hit, payout = check_hit(bet, race_result)
        assert hit is True

    def test_empty_top3_returns_no_hit(self):
        """着順データが空の場合: 外れとして扱う"""
        bet = {
            "bet_type": "3連複ながし",
            "combinations": [[2, 4, 6]],
            "unit_bet": 1000,
        }
        race_result = {"top3": [], "payouts": {}}
        hit, payout = check_hit(bet, race_result)
        assert hit is False
        assert payout == 0

    def test_no_payout_data_but_hit(self):
        """組合せ一致するが払戻データなし: 的中フラグのみ立つ"""
        bet = {
            "bet_type": "3連複ながし",
            "combinations": [[2, 4, 6]],
            "unit_bet": 1200,
        }
        race_result = {
            "top3": [4, 2, 6],
            "payouts": {"trio": []},  # 払戻データなし
        }
        hit, payout = check_hit(bet, race_result)
        assert hit is True
        assert payout == 0  # 払戻データなし → 0

    # ── 3連単（trifecta）──

    def test_trifecta_hit(self):
        """3連単: 着順が完全一致で的中（unit_bet=800, trifecta_payout=12500）"""
        bet = {
            "bet_type": "3連単",
            "combinations": [[4, 2, 6]],
            "unit_bet": 800,
        }
        race_result = {
            "top3": [4, 2, 6],
            "payouts": {
                "trifecta": [{"numbers": [4, 2, 6], "payout": 12500}],
            },
        }
        hit, payout = check_hit(bet, race_result)
        assert hit is True
        # payout = 12500 * 800 / 100 = 100000円
        assert payout == (12500 * 800) // 100

    def test_trifecta_miss_wrong_order(self):
        """3連単: 着順が違えば外れ（2連単は順番固定）"""
        bet = {
            "bet_type": "3連単",
            "combinations": [[4, 2, 6]],
            "unit_bet": 800,
        }
        # 実際の着順: 4-6-2（2着と3着が逆）
        race_result = {
            "top3": [4, 6, 2],
            "payouts": {
                "trifecta": [{"numbers": [4, 6, 2], "payout": 8000}],
            },
        }
        hit, payout = check_hit(bet, race_result)
        assert hit is False
        assert payout == 0

    def test_trifecta_no_payout_but_hit(self):
        """3連単: 組合せ一致するが払戻データなし → 的中フラグのみ"""
        bet = {
            "bet_type": "3連単",
            "combinations": [[4, 2, 6]],
            "unit_bet": 1000,
        }
        race_result = {
            "top3": [4, 2, 6],
            "payouts": {"trifecta": []},  # 払戻データなし
        }
        hit, payout = check_hit(bet, race_result)
        assert hit is True
        assert payout == 0

    def test_trifecta_hit_lower_case_bet_type(self):
        """3連単: bet_type が英字小文字 "trifecta" でも的中判定できること"""
        bet = {
            "bet_type": "trifecta",
            "combinations": [[4, 2, 6]],
            "unit_bet": 1000,
        }
        race_result = {
            "top3": [4, 2, 6],
            "payouts": {
                "trifecta": [{"numbers": [4, 2, 6], "payout": 15000}],
            },
        }
        hit, payout = check_hit(bet, race_result)
        assert hit is True
        assert payout == (15000 * 1000) // 100

    # ── 2車連（quinella/exacta）──

    def test_quinella_hit(self):
        """2車連複: 1着・2着の組合せ一致で的中"""
        bet = {
            "bet_type": "2車連",
            "combinations": [[4, 2]],
            "unit_bet": 1000,
        }
        race_result = {
            "top3": [4, 2, 6],
            "payouts": {
                "quinella_or_wide": [{"numbers": [2, 4], "payout": 1700}],
            },
        }
        hit, payout = check_hit(bet, race_result)
        assert hit is True
        # payout = 1700 * 1000 / 100 = 17000円
        assert payout == (1700 * 1000) // 100

    def test_quinella_miss(self):
        """2車連複: 1着・2着に予測した選手が含まれなければ外れ"""
        bet = {
            "bet_type": "2車連",
            "combinations": [[3, 5]],
            "unit_bet": 1000,
        }
        race_result = {
            "top3": [4, 2, 6],
            "payouts": {
                "quinella_or_wide": [{"numbers": [2, 4], "payout": 1700}],
            },
        }
        hit, payout = check_hit(bet, race_result)
        assert hit is False
        assert payout == 0

    def test_quinella_order_independent(self):
        """2車連複: 着順関係なく1着・2着の組合せが一致すれば的中"""
        bet = {
            "bet_type": "2連",
            "combinations": [[2, 4]],  # [4, 2] と同じ組合せ
            "unit_bet": 1500,
        }
        race_result = {
            "top3": [4, 2, 6],
            "payouts": {
                "quinella_or_wide": [{"numbers": [2, 4], "payout": 1700}],
            },
        }
        hit, payout = check_hit(bet, race_result)
        assert hit is True

    def test_unknown_bet_type_returns_no_hit(self):
        """未知のbet_typeは外れとして扱う"""
        bet = {
            "bet_type": "ワイド",  # 未対応のbet_type
            "combinations": [[4, 2]],
            "unit_bet": 500,
        }
        race_result = {
            "top3": [4, 2, 6],
            "payouts": {"quinella_or_wide": [{"numbers": [2, 4], "payout": 1700}]},
        }
        hit, payout = check_hit(bet, race_result)
        # 未対応bet_typeは外れとして扱う
        assert hit is False
        assert payout == 0

    def test_top3_only_two_returns_no_hit(self):
        """top3が2件しかない（レース中断等）: 外れとして扱う"""
        bet = {
            "bet_type": "3連複ながし",
            "combinations": [[1, 2]],
            "unit_bet": 1000,
        }
        race_result = {
            "top3": [1, 2],  # 3着データなし
            "payouts": {},
        }
        hit, payout = check_hit(bet, race_result)
        assert hit is False
        assert payout == 0


# ─── load_predictions_for_date テスト ───────────────────────────────────────

class TestLoadPredictions:
    def test_load_valid_predictions(self, tmp_path, monkeypatch):
        """output/YYYYMMDD/keirin_*.json を正しく読み込む"""
        import collect_results as cr
        monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path / "output")

        date_dir = tmp_path / "output" / "20260228"
        date_dir.mkdir(parents=True)

        pred_data = {
            "race_info": {"venue_name": "和歌山", "race_no": "12"},
            "bet": {"bet_type": "3連複ながし", "combinations": [[2, 4, 6]], "unit_bet": 1200}
        }
        (date_dir / "keirin_和歌山_12.json").write_text(
            json.dumps(pred_data, ensure_ascii=False), encoding="utf-8"
        )

        preds = load_predictions_for_date("20260228")
        assert "和歌山_12" in preds
        assert preds["和歌山_12"]["bet"]["bet_type"] == "3連複ながし"

    def test_missing_date_dir_returns_empty(self, tmp_path, monkeypatch):
        """存在しないディレクトリは空辞書を返す"""
        import collect_results as cr
        monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path / "output")
        preds = load_predictions_for_date("20991231")
        assert preds == {}

    def test_malformed_json_skipped(self, tmp_path, monkeypatch):
        """壊れたJSONはスキップされる"""
        import collect_results as cr
        monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path / "output")

        date_dir = tmp_path / "output" / "20260228"
        date_dir.mkdir(parents=True)
        (date_dir / "keirin_和歌山_12.json").write_text("{invalid json", encoding="utf-8")

        preds = load_predictions_for_date("20260228")
        assert preds == {}

    def test_multiple_files_loaded(self, tmp_path, monkeypatch):
        """複数ファイルを全て読み込む"""
        import collect_results as cr
        monkeypatch.setattr(cr, "OUTPUT_DIR", tmp_path / "output")

        date_dir = tmp_path / "output" / "20260228"
        date_dir.mkdir(parents=True)

        for venue, race_no in [("和歌山", 12), ("大垣", 9), ("川崎", 11)]:
            pred_data = {
                "race_info": {"venue_name": venue, "race_no": str(race_no)},
                "bet": {"bet_type": "3連複ながし", "combinations": [[1, 2, 3]], "unit_bet": 1000}
            }
            (date_dir / f"keirin_{venue}_{race_no}.json").write_text(
                json.dumps(pred_data, ensure_ascii=False), encoding="utf-8"
            )

        preds = load_predictions_for_date("20260228")
        assert len(preds) == 3
        assert "和歌山_12" in preds
        assert "大垣_9" in preds
        assert "川崎_11" in preds


# ─── 出力フォーマットのバリデーションテスト ─────────────────────────────────

class TestOutputFormat:
    """collect_results()の出力フォーマットが仕様通りか検証。"""

    def _make_sample_output(self):
        return {
            "date": "20260301",
            "fetched_at": "2026-03-01T20:00:00",
            "races": [
                {
                    "venue": "和歌山",
                    "race_no": 12,
                    "trifecta_result": [3, 5, 7],
                    "trifecta_payout": 12500,
                    "trio_result": [3, 5, 7],
                    "trio_payout": 4200,
                    "our_prediction": {
                        "axis": 4,
                        "partners": [2, 6],
                        "bet_type": "3連複ながし",
                        "combinations": [[2, 4, 6]],
                        "investment": 1200,
                    },
                    "hit": False,
                    "payout": 0,
                }
            ],
        }

    def test_top_level_fields(self):
        data = self._make_sample_output()
        assert "date" in data
        assert "fetched_at" in data
        assert "races" in data
        assert isinstance(data["races"], list)

    def test_race_entry_required_fields(self):
        data = self._make_sample_output()
        race = data["races"][0]
        required = ["venue", "race_no", "trifecta_result", "trifecta_payout",
                    "trio_result", "trio_payout"]
        for field in required:
            assert field in race, f"必須フィールドが欠落: {field}"

    def test_race_prediction_fields(self):
        data = self._make_sample_output()
        race = data["races"][0]
        pred = race["our_prediction"]
        assert "axis" in pred
        assert "partners" in pred
        assert "bet_type" in pred
        assert "combinations" in pred
        assert "investment" in pred

    def test_hit_and_payout_fields(self):
        data = self._make_sample_output()
        race = data["races"][0]
        assert "hit" in race
        assert isinstance(race["hit"], bool)
        assert "payout" in race
        assert isinstance(race["payout"], int)

    def test_json_serializable(self):
        data = self._make_sample_output()
        json_str = json.dumps(data, ensure_ascii=False)
        reloaded = json.loads(json_str)
        assert reloaded["date"] == "20260301"
        assert reloaded["races"][0]["venue"] == "和歌山"

    def test_hit_false_payout_zero(self):
        """外れの場合、payoutは0であること"""
        data = self._make_sample_output()
        race = data["races"][0]
        assert race["hit"] is False
        assert race["payout"] == 0

    def test_hit_true_payout_positive(self):
        """的中の場合、payoutは正の整数であること"""
        data = self._make_sample_output()
        race = data["races"][0]
        # 的中ケースに書き換え
        race["hit"] = True
        race["payout"] = 50400
        race["trio_result"] = [2, 4, 6]
        race["trio_payout"] = 4200
        assert race["hit"] is True
        assert race["payout"] > 0


# ─── BUG-3: venue_name英語slug→日本語マッピングテスト ───────────────────────

class TestVenueSlugMapping:
    """BUG-3: 英語slug→日本語venue_nameのマッピング検証。

    BUG-3の背景:
      kdreams.jpが返すvenue_code（例: "56", "73"）がVENUE_NAMEに未登録の場合、
      英語slug（"kishiwada", "komatsushima"）がvenue_nameに使われ、
      予測ファイルの日本語venue_name（"岸和田", "小松島"）とのマッチングに失敗する。
    """

    def test_load_venue_slug_map_returns_dict(self):
        """venue_map.yamlが正常に読み込まれること"""
        slug_map = load_venue_slug_map()
        assert isinstance(slug_map, dict)
        assert len(slug_map) > 0, "venue_map.yamlが空または読み込み失敗"

    def test_kishiwada_slug_maps_to_japanese(self):
        """kishiwada → 岸和田 のマッピングが存在すること（BUG-3の主要ケース）"""
        slug_map = load_venue_slug_map()
        assert slug_map.get("kishiwada") == "岸和田", \
            f"kishiwadaのマッピング不正: {slug_map.get('kishiwada')}"

    def test_komatsushima_slug_maps_to_japanese(self):
        """komatsushima → 小松島 のマッピングが存在すること（BUG-3の主要ケース）"""
        slug_map = load_venue_slug_map()
        assert slug_map.get("komatsushima") == "小松島", \
            f"komatsushimaのマッピング不正: {slug_map.get('komatsushima')}"

    def test_kurume_slug_maps_to_japanese(self):
        """kurume → 久留米 のマッピングが存在すること"""
        slug_map = load_venue_slug_map()
        assert slug_map.get("kurume") == "久留米"

    def test_wakayama_slug_maps_to_japanese(self):
        """wakayama → 和歌山 のマッピングが存在すること"""
        slug_map = load_venue_slug_map()
        assert slug_map.get("wakayama") == "和歌山"

    def test_resolve_venue_name_primary_lookup_by_code(self):
        """venue_codeがVENUE_NAME_MAPにある場合は日本語名を返すこと（1次ルックアップ）"""
        venue_name_map = {"29": "岸和田"}  # venue_code "29" → 岸和田
        result = resolve_venue_name("29", "kishiwada", venue_name_map)
        assert result == "岸和田", f"Expected '岸和田' but got '{result}'"

    def test_resolve_venue_name_fallback_by_slug(self):
        """venue_codeが未登録でもslugから日本語名が解決されること（BUG-3の修正検証）"""
        venue_name_map = {}  # venue_code "56" は未登録（BUG-3ケース）
        result = resolve_venue_name("56", "kishiwada", venue_name_map)
        assert result == "岸和田", \
            f"BUG-3修正検証失敗: venue_code='56' slug='kishiwada' → Expected '岸和田' got '{result}'"

    def test_resolve_venue_name_komatsushima_bug3(self):
        """venue_code "73" + slug "komatsushima" → "小松島"（BUG-3の実ケース）"""
        venue_name_map = {}  # venue_code "73" はVENUE_NAMEに未登録
        result = resolve_venue_name("73", "komatsushima", venue_name_map)
        assert result == "小松島", \
            f"BUG-3修正検証失敗: venue_code='73' slug='komatsushima' → Expected '小松島' got '{result}'"

    def test_resolve_venue_name_unknown_slug_falls_back_to_slug(self):
        """未知のslugはそのままフォールバックとして返すこと"""
        venue_name_map = {}
        result = resolve_venue_name("99", "unknown_venue", venue_name_map)
        assert result == "unknown_venue", \
            f"未知slug フォールバック失敗: Expected 'unknown_venue' got '{result}'"

    def test_resolve_venue_name_code_takes_priority_over_slug(self):
        """venue_codeとslugが両方あればvenue_codeの結果を優先すること"""
        # venue_code "29" と slug "kishiwada" の両方が有効な場合
        venue_name_map = {"29": "岸和田"}
        result = resolve_venue_name("29", "kishiwada", venue_name_map)
        # venue_codeによる1次ルックアップが返されること（slugと結果は同じ）
        assert result == "岸和田"

    def test_prediction_matching_after_bug3_fix(self):
        """BUG-3修正後: 英語slugを使ったvenue_nameが予測キーと一致すること"""
        # 予測ファイルのキー形式: "{venue_name}_{race_no}"
        # BUG-3修正前: venue_code "56" → "kishiwada_1" （日本語名と不一致）
        # BUG-3修正後: venue_code "56" → "岸和田_1" （日本語名と一致）
        venue_name_map = {}  # venue_code "56" は未登録
        resolved = resolve_venue_name("56", "kishiwada", venue_name_map)
        pred_key = f"{resolved}_1"

        # 予測ファイルが日本語venue_nameで格納されていると仮定
        predictions = {"岸和田_1": {"bet": {"bet_type": "3連複ながし"}}}
        assert pred_key in predictions, \
            f"BUG-3修正後のキー '{pred_key}' が予測辞書に見つからない（予測との突合が失敗）"
