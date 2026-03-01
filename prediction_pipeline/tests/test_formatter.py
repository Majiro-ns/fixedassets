"""
tests/test_formatter.py
=======================

src/formatter.py の単体テスト。

テスト対象関数:
  - format_prediction()       標準JSON形式変換
  - format_batch()            バッチまとめ
  - save_prediction()         JSONファイル保存
  - to_text_summary()         テキストサマリー変換
  - batch_to_text_summary()   バッチテキストサマリー
  - _extract_axis_partners()  予想テキストから軸・相手を抽出
  - _format_partners()        相手番号リストを文字列変換
  - _get_filter_headline()    フィルタータイプ別ヘッドライン
  - format_json()             JSON文字列変換
  - format_markdown()         Markdown変換
  - format_netkeirin_style()  netkeirin風テキスト生成

テスト期待値根拠（CHECK-9）:
  - format_prediction()のフィールド定義は src/formatter.py:52-73 の return 辞書に準拠
  - _extract_axis_partners()のパターンは src/formatter.py:237-265 の正規表現に準拠
  - _get_filter_headline()の返り値は src/formatter.py:285-289 の headlines 辞書に準拠
  - save_prediction()のエンコーディングは src/formatter.py:127 の ensure_ascii=False に準拠
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from formatter import (
    _extract_axis_partners,
    _format_partners,
    _get_filter_headline,
    batch_to_text_summary,
    format_batch,
    format_json,
    format_markdown,
    format_netkeirin_style,
    format_prediction,
    save_prediction,
    to_text_summary,
)


# ─────────────────────────────────────────────────────────────────────────────
# フィクスチャ
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_race_info():
    return {
        "sport": "keirin",
        "venue_name": "川崎",
        "race_no": 9,
        "grade": "S1",
        "stage": "準決勝",
        "start_time": "15:30",
        "entries": [
            {"car_no": 1, "name": "山田太郎", "grade": "S1"},
            {"car_no": 2, "name": "鈴木一郎", "grade": "S1"},
        ],
    }


@pytest.fixture
def sample_profile():
    return {
        "predictor_name": "Mr.T（競輪眼）",
        "profile_id": "mr_t_634",
    }


@pytest.fixture
def sample_bet():
    return {
        "bet_type": "3連複ながし",
        "num_bets": 3,
        "total_investment": 3600,
        "unit_bet": 1200,
    }


@pytest.fixture
def sample_prediction_text():
    return "軸: 1番（山田）\n相手: 2番、3番、5番\nコメント: ライン先頭が絞れる一戦。"


# ─────────────────────────────────────────────────────────────────────────────
# format_prediction()
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatPrediction:
    def test_all_fields_present(self, sample_race_info, sample_profile, sample_bet, sample_prediction_text):
        """全引数指定時、返り値に timestamp/date/sport/race_info/predictor/prediction/bet が揃う。
        根拠: formatter.py:52-73 の return 辞書定義"""
        result = format_prediction(
            sample_race_info,
            sample_prediction_text,
            bet_result=sample_bet,
            profile=sample_profile,
            model_used="claude-haiku-4-5-20251001",
        )
        assert "timestamp" in result
        assert result["sport"] == "keirin"
        assert result["race_info"]["venue_name"] == "川崎"
        assert result["race_info"]["race_no"] == 9
        assert result["race_info"]["grade"] == "S1"
        assert result["race_info"]["stage"] == "準決勝"
        assert result["predictor"]["name"] == "Mr.T（競輪眼）"
        assert result["predictor"]["model"] == "claude-haiku-4-5-20251001"
        assert result["prediction"]["text"] == sample_prediction_text
        assert result["prediction"]["entries"] == sample_race_info["entries"]
        assert result["bet"] == sample_bet

    def test_optional_profile_none(self, sample_race_info, sample_prediction_text):
        """profile=None の場合、predictor.name='unknown', profile_id='' になる。
        根拠: formatter.py:64-65 の (profile or {}).get() フォールバック"""
        result = format_prediction(sample_race_info, sample_prediction_text)
        assert result["predictor"]["name"] == "unknown"
        assert result["predictor"]["profile_id"] == ""

    def test_optional_model_none(self, sample_race_info, sample_prediction_text):
        """model_used=None の場合、predictor.model='unknown' になる。
        根拠: formatter.py:66 の model_used or 'unknown'"""
        result = format_prediction(sample_race_info, sample_prediction_text)
        assert result["predictor"]["model"] == "unknown"

    def test_optional_bet_none(self, sample_race_info, sample_prediction_text):
        """bet_result=None の場合、bet={} になる（空辞書）。
        根拠: formatter.py:72 の bet_result or {}"""
        result = format_prediction(sample_race_info, sample_prediction_text)
        assert result["bet"] == {}

    def test_empty_race_info(self, sample_prediction_text):
        """race_info が空辞書の場合、各フィールドは空文字列になる。
        根拠: formatter.py:57-61 の .get(key, '') デフォルト値"""
        result = format_prediction({}, sample_prediction_text)
        assert result["sport"] == "keirin"  # デフォルト値
        assert result["race_info"]["venue_name"] == ""
        assert result["race_info"]["race_no"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# format_batch()
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatBatch:
    def test_batch_structure(self, sample_race_info, sample_prediction_text):
        """format_batch は batch_id/generated_at/total_races/meta/predictions を返す。
        根拠: formatter.py:91-97 の return 辞書定義"""
        pred = format_prediction(sample_race_info, sample_prediction_text)
        batch = format_batch([pred], meta={"sport": "keirin", "date": "20260302"})
        assert "batch_id" in batch
        assert "generated_at" in batch
        assert batch["total_races"] == 1
        assert batch["meta"]["sport"] == "keirin"
        assert len(batch["predictions"]) == 1

    def test_batch_meta_optional(self, sample_race_info, sample_prediction_text):
        """meta=None の場合、meta={} になる。
        根拠: formatter.py:95 の meta or {}"""
        pred = format_prediction(sample_race_info, sample_prediction_text)
        batch = format_batch([pred])
        assert batch["meta"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# save_prediction()
# ─────────────────────────────────────────────────────────────────────────────

class TestSavePrediction:
    def test_save_creates_file(self, tmp_path, sample_race_info, sample_prediction_text):
        """save_prediction() は指定ディレクトリにJSONファイルを作成する。
        根拠: formatter.py:116-129 のファイル保存ロジック"""
        pred = format_prediction(sample_race_info, sample_prediction_text)
        saved_path = save_prediction(pred, output_dir=str(tmp_path))
        assert Path(saved_path).exists()

    def test_save_japanese_encoding(self, tmp_path, sample_race_info, sample_prediction_text):
        """保存したJSONが日本語を文字化けせずに読み込める。
        根拠: formatter.py:127 の ensure_ascii=False + utf-8 encoding"""
        pred = format_prediction(sample_race_info, sample_prediction_text)
        saved_path = save_prediction(pred, output_dir=str(tmp_path))
        with open(saved_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["race_info"]["venue_name"] == "川崎"

    def test_save_custom_filename(self, tmp_path, sample_race_info, sample_prediction_text):
        """filename 指定時、指定したファイル名で保存される。
        根拠: formatter.py:124 の file_path = output_path / filename"""
        pred = format_prediction(sample_race_info, sample_prediction_text)
        saved_path = save_prediction(pred, output_dir=str(tmp_path), filename="test_output.json")
        assert Path(saved_path).name == "test_output.json"
        assert Path(saved_path).exists()


# ─────────────────────────────────────────────────────────────────────────────
# to_text_summary()
# ─────────────────────────────────────────────────────────────────────────────

class TestToTextSummary:
    def test_bet_info_included(self, sample_race_info, sample_prediction_text, sample_bet):
        """bet_type が 'skip' 以外の場合、賭け式・点数・合計が含まれる。
        根拠: formatter.py:159-163 の bet セクション"""
        pred = format_prediction(sample_race_info, sample_prediction_text, bet_result=sample_bet)
        summary = to_text_summary(pred)
        assert "川崎" in summary
        assert "3連複ながし" in summary
        assert "3点" in summary

    def test_skip_bet_shown(self, sample_race_info, sample_prediction_text):
        """bet_type='skip' の場合、見送り理由が表示される。
        根拠: formatter.py:165-166 の skip 分岐"""
        skip_bet = {"bet_type": "skip", "reason": "F10フィルター不通過"}
        pred = format_prediction(sample_race_info, sample_prediction_text, bet_result=skip_bet)
        summary = to_text_summary(pred)
        assert "[見送り]" in summary
        assert "F10フィルター不通過" in summary


# ─────────────────────────────────────────────────────────────────────────────
# _extract_axis_partners()
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractAxisPartners:
    def test_axis_colon_pattern(self):
        """「軸: 3番」形式から軸番号を抽出できる。
        根拠: formatter.py:238 の axis_patterns[0]"""
        axis, partners = _extract_axis_partners("軸: 3番 山田。相手: 1番、2番、5番。")
        assert axis == 3
        assert 1 in partners
        assert 2 in partners

    def test_axis_maru_pattern(self):
        """「◎3番」形式から軸番号を抽出できる。
        根拠: formatter.py:239 の axis_patterns[1]"""
        axis, _ = _extract_axis_partners("◎3番 鈴木。△1番、4番。")
        assert axis == 3

    def test_axis_honmei_pattern(self):
        """「本命: 5番」形式から軸番号を抽出できる。
        根拠: formatter.py:240 の axis_patterns[2]"""
        axis, _ = _extract_axis_partners("本命: 5番が中心。")
        assert axis == 5

    def test_no_axis_text_returns_none(self):
        """軸・本命パターンが含まれないテキストは axis=None, partners=[] を返す。
        根拠: formatter.py:233-234 の初期値 None, []"""
        axis, partners = _extract_axis_partners("今日は様子見。")
        assert axis is None
        assert partners == []

    def test_empty_string(self):
        """空文字列入力で axis=None, partners=[] を返す（クラッシュしない）。
        根拠: formatter.py の正規表現はマッチなしで None/[] を返す"""
        axis, partners = _extract_axis_partners("")
        assert axis is None
        assert partners == []

    def test_partners_exclude_axis(self):
        """相手リストに軸番号が含まれても除外される。
        根拠: formatter.py:262 の int(n) != axis フィルタリング"""
        axis, partners = _extract_axis_partners("軸: 3番。相手: 3番、1番、4番。")
        assert axis == 3
        assert 3 not in partners
        assert 1 in partners


# ─────────────────────────────────────────────────────────────────────────────
# _format_partners()
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatPartners:
    def test_normal_list(self):
        """[1, 2, 3] → '1、2、3' に変換される。
        根拠: formatter.py:307 の '、'.join(str(p) for p in partners)"""
        result = _format_partners([1, 2, 3])
        assert result == "1、2、3"

    def test_empty_list_returns_yokinin(self):
        """空リストの場合 '要確認' を返す。
        根拠: formatter.py:305-306 の if not partners: return '要確認'"""
        result = _format_partners([])
        assert result == "要確認"


# ─────────────────────────────────────────────────────────────────────────────
# _get_filter_headline()
# ─────────────────────────────────────────────────────────────────────────────

class TestGetFilterHeadline:
    def test_known_filter_types(self):
        """A/B/C それぞれが想定のヘッドラインを返す。
        根拠: formatter.py:285-289 の headlines 辞書"""
        assert _get_filter_headline("C") == "獲りやすさ抜群！点数絞って攻める！"
        assert _get_filter_headline("B") == "高配当狙える！妙味ある一戦！"
        assert _get_filter_headline("A") == "波乱の可能性あり！中穴ゾーンで攻める！"

    def test_unknown_filter_type_returns_default(self):
        """未定義のフィルタータイプは汎用ヘッドラインを返す。
        根拠: formatter.py:290 の headlines.get(filter_type, ...) デフォルト値"""
        result = _get_filter_headline("Z")
        assert "注目" in result or "勝負" in result


# ─────────────────────────────────────────────────────────────────────────────
# format_json()
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatJson:
    def test_returns_valid_json(self, sample_prediction_text, sample_bet):
        """format_json() は有効なJSON文字列を返す。
        根拠: formatter.py:354 の json.dumps(output, ...)"""
        race_data = {"venue_name": "平塚", "race_no": 7, "grade": "S1"}
        metadata = {"sport": "keirin", "filter_type": "C"}
        json_str = format_json(sample_prediction_text, sample_bet, race_data, metadata)
        parsed = json.loads(json_str)
        assert parsed["meta"]["sport"] == "keirin"
        assert parsed["meta"]["filter_type"] == "C"
        assert parsed["race"]["venue_name"] == "平塚"

    def test_japanese_not_escaped(self, sample_prediction_text, sample_bet):
        """日本語文字がエスケープされずにそのまま出力される（ensure_ascii=False）。
        根拠: formatter.py:354 の ensure_ascii=False"""
        race_data = {"venue_name": "川崎", "race_no": 9, "grade": "S1"}
        json_str = format_json(sample_prediction_text, sample_bet, race_data)
        assert "川崎" in json_str
        assert r"\u5ddd\u5d0e" not in json_str  # エスケープされていないこと


# ─────────────────────────────────────────────────────────────────────────────
# format_markdown()
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatMarkdown:
    def test_contains_venue_and_grade(self, sample_prediction_text, sample_bet):
        """Markdown 出力に会場名・グレード・フィルタータイプが含まれる。
        根拠: formatter.py:388-390 のヘッダー行"""
        race_data = {"venue_name": "立川", "race_no": 11, "grade": "S1"}
        metadata = {"filter_type": "A"}
        md = format_markdown(sample_prediction_text, sample_bet, race_data, metadata)
        assert "立川" in md
        assert "S1" in md
        assert "フィルタータイプ" in md

    def test_kelly_allocation_section(self, sample_prediction_text):
        """allocation_plan キーがある場合、Kelly配分セクションが含まれる。
        根拠: formatter.py:426-437 の allocation_plan 分岐"""
        kelly_bet = {
            "bet_type": "3連複ながし",
            "num_bets": 3,
            "total_investment": 3600,
            "unit_bet": 1200,
            "allocation_plan": {"filter_C": "¥2,000", "filter_A": "¥1,600"},
        }
        race_data = {"venue_name": "川崎", "race_no": 9, "grade": "S1"}
        metadata = {"filter_type": "C"}
        md = format_markdown(sample_prediction_text, kelly_bet, race_data, metadata)
        assert "Kelly最適配分" in md
        assert "filter_C" in md


# ─────────────────────────────────────────────────────────────────────────────
# format_netkeirin_style()
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatNetkeirinStyle:
    def test_filter_type_headline_embedded(self, sample_prediction_text):
        """filter_type=C の場合、'獲りやすさ' を含むヘッドラインが出力に含まれる。
        根拠: formatter.py:466-467 の _get_filter_headline() 呼び出し"""
        race_data = {"venue_name": "熊本", "race_no": 2}
        output = format_netkeirin_style(sample_prediction_text, race_data, filter_type="C")
        assert "獲りやすさ" in output
        assert "熊本" in output

    def test_long_text_truncated_to_200(self):
        """200文字を超える予想テキストは200文字+省略記号に要約される。
        根拠: formatter.py:471-473 の prediction[:200] + '…'"""
        long_text = "あ" * 250
        race_data = {"venue_name": "川崎", "race_no": 9}
        output = format_netkeirin_style(long_text, race_data, filter_type="A")
        assert "…" in output
        # 要約部分が200文字+省略記号になっていること
        lines = output.split("\n")
        summary_line = next((l for l in lines if "あ" in l), "")
        assert len(summary_line) <= 202  # 200文字 + "…" = 201文字 + マージン

    def test_no_axis_shows_yokinin(self):
        """軸番号が抽出できない場合、'要確認' が表示される。
        根拠: formatter.py:475 の axis_display = '要確認' フォールバック"""
        race_data = {"venue_name": "防府", "race_no": 7}
        output = format_netkeirin_style("展開次第で難しい一戦。", race_data, filter_type="B")
        assert "要確認" in output


# ─────────────────────────────────────────────────────────────────────────────
# batch_to_text_summary()
# ─────────────────────────────────────────────────────────────────────────────

class TestBatchToTextSummary:
    def test_total_investment_calculated(self, sample_race_info, sample_prediction_text, sample_bet):
        """bet_type != skip の場合、本日合計投資額が集計される。
        根拠: formatter.py:201-207 の total_investment 計算"""
        pred = format_prediction(sample_race_info, sample_prediction_text, bet_result=sample_bet)
        batch = format_batch([pred, pred])  # 2件 × ¥3,600 = ¥7,200
        summary = batch_to_text_summary(batch)
        assert "7,200" in summary or "7200" in summary
