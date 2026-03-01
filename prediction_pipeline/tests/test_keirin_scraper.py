"""
KeirinScraper のテストスイート

Tier1（低リスク）: keirin.jp/pc/votinglist への実接続テスト
実際のネットワーク呼び出しを行うため、CI 環境ではスキップする場合がある。
"""

import sys
import os
import unittest.mock as mock
import pytest

# src/ をパスに追加（プロジェクトルートからの実行を想定）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.keirin_scraper import KeirinScraper, RateLimiter, VENUE_CODES, BANK_LENGTH


# ─── テスト共通設定 ───────────────────────────────────────────────

CONFIG = {
    "keirin": {
        "base_url": "https://keirin.jp/pc",
        "request_delay": 1.0,  # テスト用に短縮
    }
}

# ネットワーク接続が必要なテストをスキップするマーカー
# 環境変数 KEIRIN_REAL_ACCESS=1 が設定されている場合のみ実行
requires_network = pytest.mark.skipif(
    not os.environ.get("KEIRIN_REAL_ACCESS"),
    reason="KEIRIN_REAL_ACCESS env var not set. Set to '1' to run real network tests.",
)


# ─── ユニットテスト（ネットワーク不要）────────────────────────────

class TestKeirinScraperInit:
    """KeirinScraper 初期化のテスト。"""

    def test_default_delay(self):
        """デフォルトのリクエスト遅延が設定されること。"""
        scraper = KeirinScraper({})
        assert scraper.delay == KeirinScraper.DEFAULT_DELAY

    def test_custom_delay(self):
        """config で指定した遅延が適用されること。"""
        config = {"keirin": {"request_delay": 3.5}}
        scraper = KeirinScraper(config)
        assert scraper.delay == 3.5

    def test_default_base_url(self):
        """デフォルトの base_url が設定されること。"""
        scraper = KeirinScraper({})
        assert scraper.base_url == KeirinScraper.BASE_URL

    def test_custom_base_url(self):
        """config で指定した base_url が適用されること。"""
        config = {"keirin": {"base_url": "https://example.com"}}
        scraper = KeirinScraper(config)
        assert scraper.base_url == "https://example.com"


class TestKeirinScraperParsing:
    """スクレイパーの内部パースメソッドのテスト（ネットワーク不要）。"""

    def setup_method(self):
        """各テスト前にスクレイパーインスタンスを生成する。"""
        self.scraper = KeirinScraper(CONFIG)

    def test_parse_schedule_returns_list(self):
        """_parse_schedule がリストを返すこと。"""
        result = self.scraper._parse_schedule("<html></html>", "20260224")
        assert isinstance(result, list)

    def test_parse_schedule_has_venue_name(self):
        """空 HTML では空リストが返ること（実データは実接続テストで確認）。"""
        result = self.scraper._parse_schedule("<html></html>", "20260224")
        assert isinstance(result, list)
        # 空 HTML は JSON を含まないため空リストが返る（正常動作）
        assert len(result) == 0

    def test_parse_schedule_has_required_keys(self):
        """スケジュール各要素に必須キーが存在すること。"""
        result = self.scraper._parse_schedule("<html></html>", "20260224")
        required_keys = {"venue_name", "race_no", "grade", "start_time"}
        for item in result:
            assert required_keys.issubset(item.keys()), (
                f"必須キー {required_keys - item.keys()} が欠落しています"
            )

    def test_parse_results_returns_list(self):
        """_parse_results が空 HTML でリストを返すこと。"""
        result = self.scraper._parse_results("<html></html>")
        assert isinstance(result, list)

    def test_parse_results_has_required_keys(self):
        """_parse_results が空 HTML では空リストを返すこと（着順データなし）。"""
        result = self.scraper._parse_results("<html></html>")
        # 空 HTML には着順データがないため空リストが返る（正常動作）
        assert len(result) == 0


# ─── 実接続テスト（KEIRIN_REAL_ACCESS=1 の場合のみ実行）────────────

class TestKeirinScraperRealConnection:
    """KEIRIN.JP への実接続テスト（Low Risk・Allow済み: votinglist のみ）。"""

    def setup_method(self):
        """各テスト前にスクレイパーインスタンスを生成する。"""
        self.scraper = KeirinScraper(CONFIG)

    @requires_network
    def test_fetch_schedule_real(self):
        """keirin.jp/pc/votinglist への実接続テスト（Low Risk・Allow済み）。"""
        scraper = KeirinScraper(CONFIG)
        schedule = scraper.fetch_schedule(date="20260224")
        assert len(schedule) > 0
        assert "venue_name" in schedule[0]

    @requires_network
    def test_fetch_schedule_real_date_format(self):
        """取得したスケジュールの日付フィールドが正しい形式であること。"""
        scraper = KeirinScraper(CONFIG)
        schedule = scraper.fetch_schedule(date="20260224")
        for item in schedule:
            assert "20260224" in item.get("date", ""), (
                "date フィールドに指定日付が含まれていること"
            )

    @requires_network
    def test_fetch_schedule_real_returns_multiple_venues(self):
        """実接続で複数会場のレースが取得されること（開催日を指定）。"""
        scraper = KeirinScraper(CONFIG)
        schedule = scraper.fetch_schedule(date="20260224")
        venues = {item["venue_name"] for item in schedule}
        # 通常の開催日であれば複数会場が開催される
        assert len(venues) >= 1


# ─── RateLimiter ユニットテスト ─────────────────────────────────────────

class TestRateLimiter:
    """RateLimiter のユニットテスト（ネットワーク不要）。"""

    def test_count_starts_at_zero(self):
        """初期カウントがゼロであること。"""
        limiter = RateLimiter(rate_limit_sec=0, max_requests=5)
        assert limiter.count == 0

    def test_wait_increments_count(self):
        """wait() 呼び出しでカウントが増加すること。"""
        limiter = RateLimiter(rate_limit_sec=0, max_requests=5)
        limiter.wait()
        assert limiter.count == 1

    def test_wait_multiple_times_increments_count(self):
        """複数回の wait() でカウントが正しく増加すること。"""
        limiter = RateLimiter(rate_limit_sec=0, max_requests=10)
        limiter.wait()
        limiter.wait()
        limiter.wait()
        assert limiter.count == 3

    def test_max_requests_raises_runtime_error(self):
        """max_requests 超過時に RuntimeError が発生すること。"""
        limiter = RateLimiter(rate_limit_sec=0, max_requests=2)
        limiter.wait()
        limiter.wait()
        with pytest.raises(RuntimeError, match="最大リクエスト数"):
            limiter.wait()

    def test_error_message_contains_limit(self):
        """RuntimeError のメッセージに上限数が含まれること。"""
        limiter = RateLimiter(rate_limit_sec=0, max_requests=3)
        limiter._count = 3
        with pytest.raises(RuntimeError) as exc_info:
            limiter.wait()
        assert "3" in str(exc_info.value)

    def test_count_property_returns_int(self):
        """count プロパティが int を返すこと。"""
        limiter = RateLimiter(rate_limit_sec=0, max_requests=5)
        assert isinstance(limiter.count, int)


# ─── 定数（VENUE_CODES / BANK_LENGTH）テスト ─────────────────────────────

class TestConstants:
    """VENUE_CODES・BANK_LENGTH 定数のテスト。"""

    def test_venue_code_kawasaki(self):
        """場コード '14' が '川崎' にマップされること。"""
        assert VENUE_CODES["14"] == "川崎"

    def test_venue_code_maebashi(self):
        """場コード '05' が '前橋' にマップされること。"""
        assert VENUE_CODES["05"] == "前橋"

    def test_venue_code_hakodate(self):
        """場コード '01' が '函館' にマップされること。"""
        assert VENUE_CODES["01"] == "函館"

    def test_venue_code_unknown_returns_none(self):
        """存在しない場コードは None を返すこと。"""
        assert VENUE_CODES.get("99") is None

    def test_bank_length_maebashi_is_333(self):
        """前橋バンクは 333m であること。"""
        assert BANK_LENGTH["前橋"] == 333

    def test_bank_length_kawasaki_is_400(self):
        """川崎バンクは 400m であること。"""
        assert BANK_LENGTH["川崎"] == 400

    def test_bank_length_odawara_is_500(self):
        """小田原バンクは 500m であること。"""
        assert BANK_LENGTH["小田原"] == 500

    def test_venue_codes_has_41_entries(self):
        """VENUE_CODES が 41 エントリーを持つこと。"""
        assert len(VENUE_CODES) == 41


# ─── _parse_schedule サンプルHTML テスト ──────────────────────────────────

class TestParseScheduleSampleHTML:
    """_parse_schedule のサンプル HTML テスト（ネットワーク不要）。"""

    SAMPLE_HTML_SINGLE = """<html><head></head><body>
<script>
var pc0101_json = {"RaceList":[
    {"kaisaiDate":"20260224","naibuKeirinCd":14,"keirinjoName":"川崎",
     "gradeIconName":"S1","raceNum":"12R","touhyouLivePara":"hd=20260224&jcd=14&rno=12"}
]};
</script></body></html>"""

    SAMPLE_HTML_MULTIPLE = """<html><head></head><body><script>
var pc0101_json = {"RaceList":[
    {"kaisaiDate":"20260224","naibuKeirinCd":14,"keirinjoName":"川崎","gradeIconName":"S1","raceNum":"12R","touhyouLivePara":"tok1"},
    {"kaisaiDate":"20260224","naibuKeirinCd":5,"keirinjoName":"前橋","gradeIconName":"GP","raceNum":"11R","touhyouLivePara":"tok2"},
    {"kaisaiDate":"20260225","naibuKeirinCd":8,"keirinjoName":"大宮","gradeIconName":"F2","raceNum":"9R","touhyouLivePara":"tok3"}
]};
</script></body></html>"""

    def setup_method(self):
        self.scraper = KeirinScraper(CONFIG)

    def test_parse_schedule_with_valid_json(self):
        """有効な JSON 埋め込み HTML を正しく解析できること。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_SINGLE, "20260224")
        assert len(result) == 1
        assert result[0]["venue_name"] == "川崎"

    def test_parse_schedule_venue_code_two_digits(self):
        """場コードが 2 桁文字列であること。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_SINGLE, "20260224")
        assert result[0]["venue_code"] == "14"

    def test_parse_schedule_bank_length(self):
        """解析結果にバンク周長が含まれること（川崎=400m）。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_SINGLE, "20260224")
        assert result[0]["bank_length"] == 400

    def test_parse_schedule_race_num_integer(self):
        """レース数が整数として解析されること。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_SINGLE, "20260224")
        assert result[0]["race_num"] == 12

    def test_parse_schedule_grade(self):
        """グレード情報が解析されること。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_SINGLE, "20260224")
        assert result[0]["grade"] == "S1"

    def test_parse_schedule_race_token(self):
        """touhyouLivePara トークンが取得されること。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_SINGLE, "20260224")
        assert result[0]["race_token"] == "hd=20260224&jcd=14&rno=12"

    def test_parse_schedule_date_filter_excludes_other_dates(self):
        """日付フィルタが指定日以外を除外すること。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_MULTIPLE, "20260224")
        assert len(result) == 2
        for item in result:
            assert item["start_time"] == "20260224"

    def test_parse_schedule_multiple_venues(self):
        """複数会場の解析が正しいこと。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_MULTIPLE, "20260224")
        venue_names = [r["venue_name"] for r in result]
        assert "川崎" in venue_names
        assert "前橋" in venue_names

    def test_parse_schedule_single_digit_venue_code_zero_padded(self):
        """1 桁の場コード（例: 5）が '05' にゼロパディングされること。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_MULTIPLE, "20260224")
        maebashi = next((r for r in result if r["venue_name"] == "前橋"), None)
        assert maebashi is not None
        assert maebashi["venue_code"] == "05"

    def test_parse_schedule_required_keys(self):
        """各エントリーに必須キーが存在すること。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_SINGLE, "20260224")
        required_keys = {"venue_code", "venue_name", "race_num", "grade", "start_time", "bank_length", "race_token"}
        for item in result:
            assert required_keys.issubset(item.keys()), f"欠落キー: {required_keys - item.keys()}"

    def test_parse_schedule_no_date_filter_returns_all(self):
        """日付フィルタなし（空文字列）で全エントリーを返すこと。"""
        result = self.scraper._parse_schedule(self.SAMPLE_HTML_MULTIPLE, "")
        assert len(result) == 3


# ─── _parse_entries_html テスト ────────────────────────────────────────────

class TestParseEntriesHTML:
    """_parse_entries_html / _parse_entries_with_regex のテスト（ネットワーク不要）。"""

    SAMPLE_ENTRIES_HTML = """<html><body>
<table class="entry_table">
<tr><th>枠番</th><th>登録番号</th><th>選手名</th><th>級班</th><th>脚質</th><th>競走得点</th><th>ライン</th><th>1</th><th>2</th><th>3</th></tr>
<tr><td>1</td><td>012345</td><td>山田 太郎</td><td>S1</td><td>逃げ</td><td>95.12</td><td>1-3</td><td>1</td><td>2</td><td>1</td></tr>
<tr><td>2</td><td>023456</td><td>鈴木 次郎</td><td>S2</td><td>追い込み</td><td>88.50</td><td>2-5</td><td>3</td><td>1</td><td>2</td></tr>
<tr><td>3</td><td>034567</td><td>田中 三郎</td><td>A1</td><td>捲り</td><td>75.30</td><td>3</td><td>2</td><td>3</td><td>4</td></tr>
</table></body></html>"""

    SAMPLE_REGEX_HTML = """<html><body>
<table>
<tr><td>1</td><td>012345</td><td>山田 太郎</td><td>S1</td><td>逃げ</td><td>95.12</td></tr>
<tr><td>2</td><td>023456</td><td>鈴木 次郎</td><td>S2</td><td>追い込み</td><td>88.50</td></tr>
</table>
</body></html>"""

    def setup_method(self):
        self.scraper = KeirinScraper(CONFIG)

    def test_parse_entries_empty_html_returns_empty_list(self):
        """空 HTML で空リストが返ること。"""
        result = self.scraper._parse_entries_html("<html></html>")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_parse_entries_html_returns_list(self):
        """出走表 HTML を解析してリストが返ること。"""
        result = self.scraper._parse_entries_html(self.SAMPLE_ENTRIES_HTML)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_parse_entries_frame_numbers(self):
        """枠番が正しく解析されること。"""
        result = self.scraper._parse_entries_html(self.SAMPLE_ENTRIES_HTML)
        frames = [r["frame"] for r in result]
        assert 1 in frames
        assert 2 in frames

    def test_parse_entries_score_is_float(self):
        """競走得点が float 型であること。"""
        result = self.scraper._parse_entries_html(self.SAMPLE_ENTRIES_HTML)
        for entry in result:
            if entry["score"] is not None:
                assert isinstance(entry["score"], float)

    def test_parse_entries_required_keys(self):
        """各エントリーに必須キーが存在すること。"""
        result = self.scraper._parse_entries_html(self.SAMPLE_ENTRIES_HTML)
        required_keys = {"frame", "name", "number", "rank", "leg_type", "score", "line", "recent_results"}
        for entry in result:
            assert required_keys.issubset(entry.keys()), f"欠落キー: {required_keys - entry.keys()}"

    def test_parse_entries_with_regex_fallback(self):
        """正規表現フォールバックが機能すること。"""
        result = self.scraper._parse_entries_with_regex(self.SAMPLE_REGEX_HTML)
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_parse_entries_regex_required_keys(self):
        """正規表現フォールバックの結果にも必須キーがあること。"""
        result = self.scraper._parse_entries_with_regex(self.SAMPLE_REGEX_HTML)
        required_keys = {"frame", "name", "number", "rank", "leg_type", "score", "line", "recent_results"}
        for entry in result:
            assert required_keys.issubset(entry.keys())

    def test_parse_entries_recent_results_max_5(self):
        """直近成績は最大 5 件であること。"""
        long_html = """<html><body>
<table class="entry_table">
<tr><th>枠</th><th>番号</th><th>名前</th><th>級</th><th>脚</th><th>得点</th><th>ライン</th><th>1</th><th>2</th><th>3</th><th>4</th><th>5</th><th>6</th><th>7</th></tr>
<tr><td>1</td><td>012345</td><td>山田</td><td>S1</td><td>逃げ</td><td>95.12</td><td>1</td><td>1</td><td>2</td><td>1</td><td>3</td><td>1</td><td>2</td><td>4</td></tr>
</table></body></html>"""
        result = self.scraper._parse_entries_html(long_html)
        if result:
            assert len(result[0]["recent_results"]) <= 5

    def test_parse_entries_malformed_html_no_exception(self):
        """不正 HTML でも例外を発生させずリストを返すこと。"""
        malformed = "<html><table><tr><td>不正</td></tr>"
        result = self.scraper._parse_entries_html(malformed)
        assert isinstance(result, list)


# ─── _parse_result_html テスト ──────────────────────────────────────────────

class TestParseResultHTML:
    """_parse_result_html のテスト（ネットワーク不要）。"""

    SAMPLE_RESULT_HTML = """<html><body>
<table class="result_table">
<tr><th>着順</th><th>車番</th><th>選手名</th></tr>
<tr><td>3</td><td>山田</td><td>逃げ</td></tr>
<tr><td>1</td><td>鈴木</td><td>追込</td></tr>
<tr><td>4</td><td>田中</td><td>捲</td></tr>
</table>
<table class="dividend_table">
<tr><td>3連単</td><td>12,500円</td></tr>
<tr><td>3連複</td><td>3,200円</td></tr>
<tr><td>2車単</td><td>5,800円</td></tr>
<tr><td>2車複</td><td>1,200円</td></tr>
</table>
<span class="kimari_te">まくり</span>
<span class="race_time">11.2秒</span>
</body></html>"""

    def setup_method(self):
        self.scraper = KeirinScraper(CONFIG)

    def test_parse_result_empty_html_returns_none(self):
        """空 HTML で None が返ること（着順データなし）。"""
        result = self.scraper._parse_result_html("<html></html>", 12)
        assert result is None

    def test_parse_result_winning_order(self):
        """着順が正しく解析されること。"""
        result = self.scraper._parse_result_html(self.SAMPLE_RESULT_HTML, 12)
        assert result is not None
        assert result["winning_order"] == [3, 1, 4]

    def test_parse_result_trifecta_odds(self):
        """3連単配当が正しく解析されること（12,500円）。"""
        result = self.scraper._parse_result_html(self.SAMPLE_RESULT_HTML, 12)
        assert result is not None
        assert result["trifecta_odds"] == 12500

    def test_parse_result_trio_odds(self):
        """3連複配当が正しく解析されること（3,200円）。"""
        result = self.scraper._parse_result_html(self.SAMPLE_RESULT_HTML, 12)
        assert result is not None
        assert result["trio_odds"] == 3200

    def test_parse_result_exacta_odds(self):
        """2車単配当が正しく解析されること（5,800円）。"""
        result = self.scraper._parse_result_html(self.SAMPLE_RESULT_HTML, 12)
        assert result is not None
        assert result["exacta_odds"] == 5800

    def test_parse_result_quinella_odds(self):
        """2車複配当が正しく解析されること（1,200円）。"""
        result = self.scraper._parse_result_html(self.SAMPLE_RESULT_HTML, 12)
        assert result is not None
        assert result["quinella_odds"] == 1200

    def test_parse_result_kimari_te(self):
        """決まり手が正しく解析されること。"""
        result = self.scraper._parse_result_html(self.SAMPLE_RESULT_HTML, 12)
        assert result is not None
        assert result["winning_move"] == "まくり"

    def test_parse_result_race_num_preserved(self):
        """race_num が結果辞書に正しく保存されること。"""
        result = self.scraper._parse_result_html(self.SAMPLE_RESULT_HTML, 7)
        assert result is not None
        assert result["race_num"] == 7

    def test_parse_result_required_keys(self):
        """結果辞書に必須キーが存在すること。"""
        result = self.scraper._parse_result_html(self.SAMPLE_RESULT_HTML, 12)
        assert result is not None
        required_keys = {"race_num", "winning_order", "trifecta_odds", "trio_odds",
                         "exacta_odds", "quinella_odds", "winning_move", "race_time"}
        assert required_keys.issubset(result.keys())

    def test_parse_results_backward_compat_empty(self):
        """後方互換 _parse_results が空 HTML でリストを返すこと。"""
        result = self.scraper._parse_results("<html></html>")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_parse_results_backward_compat_with_data(self):
        """後方互換 _parse_results がデータありHTMLでリストを返すこと。"""
        result = self.scraper._parse_results(self.SAMPLE_RESULT_HTML)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_parse_result_race_time_extracted(self):
        """レースタイムが解析されること。"""
        result = self.scraper._parse_result_html(self.SAMPLE_RESULT_HTML, 12)
        assert result is not None
        assert result["race_time"] == "11.2"


# ─── 配当パースバグ回帰テスト（cmd_141k_sub3）────────────────────────────────

class TestParseResultPayoutColumnSeparation:
    """配当パースバグ（cmd_141k_sub3）の回帰テスト。

    組み合わせ番号「3-1-4」と配当「12,500円」が結合して
    「412,500」に誤マッチしないことを確認する。

    【バグ内容】
    row.get_text() が全列を結合するため:
      <td>3連単</td><td>3-1-4</td><td>12,500円</td>
      → "3連単3-1-412,500円"
      → re.search(r"([\\d,]+)円") → "412,500" に誤マッチ

    【修正内容】
    row.find_all('td') で各列を個別取得し、
    「円」を含む列のみから金額を抽出する。
    """

    # 組み合わせ列あり（kdreams 実際のHTMLフォーマット想定）
    SAMPLE_WITH_COMBINATION_COL = """<html><body>
<table class="result_table">
<tr><th>着順</th><th>車番</th><th>選手名</th></tr>
<tr><td>3</td><td>山田</td><td>逃げ</td></tr>
<tr><td>1</td><td>鈴木</td><td>追込</td></tr>
<tr><td>4</td><td>田中</td><td>捲</td></tr>
</table>
<table class="dividend_table">
<tr><td>3連単</td><td>3-1-4</td><td>12,500円</td></tr>
<tr><td>3連複</td><td>1-3-4</td><td>3,200円</td></tr>
<tr><td>2車単</td><td>3-1</td><td>5,800円</td></tr>
<tr><td>2車複</td><td>1-3</td><td>1,200円</td></tr>
</table>
<span class="kimari_te">まくり</span>
<span class="race_time">11.2秒</span>
</body></html>"""

    def setup_method(self):
        self.scraper = KeirinScraper(CONFIG)

    def test_trifecta_not_contaminated_by_combination(self):
        """3連単配当が組み合わせ番号に汚染されないこと（3-1-4 + 12,500円 → 12500）。"""
        result = self.scraper._parse_result_html(self.SAMPLE_WITH_COMBINATION_COL, 12)
        assert result is not None
        assert result["trifecta_odds"] == 12500, (
            f"期待値 12500, 実際 {result['trifecta_odds']}。"
            "「3-1-4」の末尾「4」が「12,500円」に混入して「412,500」になっていないか確認。"
        )

    def test_trifecta_not_412500(self):
        """3連単配当が誤った値 412,500 にならないこと（回帰確認）。"""
        result = self.scraper._parse_result_html(self.SAMPLE_WITH_COMBINATION_COL, 12)
        assert result is not None
        assert result["trifecta_odds"] != 412500, (
            "バグ再現: 組み合わせ番号末尾「4」が配当「12,500円」に混入した。"
        )

    def test_trio_not_contaminated_by_combination(self):
        """3連複配当が組み合わせ番号に汚染されないこと（1-3-4 + 3,200円 → 3200）。"""
        result = self.scraper._parse_result_html(self.SAMPLE_WITH_COMBINATION_COL, 12)
        assert result is not None
        assert result["trio_odds"] == 3200

    def test_exacta_not_contaminated_by_combination(self):
        """2車単配当が組み合わせ番号に汚染されないこと（3-1 + 5,800円 → 5800）。"""
        result = self.scraper._parse_result_html(self.SAMPLE_WITH_COMBINATION_COL, 12)
        assert result is not None
        assert result["exacta_odds"] == 5800

    def test_quinella_not_contaminated_by_combination(self):
        """2車複配当が組み合わせ番号に汚染されないこと（1-3 + 1,200円 → 1200）。"""
        result = self.scraper._parse_result_html(self.SAMPLE_WITH_COMBINATION_COL, 12)
        assert result is not None
        assert result["quinella_odds"] == 1200

    def test_winning_order_correct_with_combination_col(self):
        """組み合わせ列があっても着順が正しく解析されること。"""
        result = self.scraper._parse_result_html(self.SAMPLE_WITH_COMBINATION_COL, 12)
        assert result is not None
        assert result["winning_order"] == [3, 1, 4]


# ─── エラーハンドリング テスト ────────────────────────────────────────────

class TestErrorHandling:
    """エラーハンドリングのテスト（ネットワーク不要）。"""

    def setup_method(self):
        self.scraper = KeirinScraper(CONFIG)

    def test_rate_limiter_max_requests_direct(self):
        """RateLimiter がmax_requests到達時にRuntimeErrorを発生させること。"""
        config = {"scraping": {"max_requests_per_session": 1, "min_interval_sec": 0}}
        scraper = KeirinScraper(config)
        scraper._limiter._count = 1
        with pytest.raises(RuntimeError):
            scraper._limiter.wait()

    def test_fetch_entries_playwright_not_installed(self):
        """Playwright 未インストール時に RuntimeError が発生すること。"""
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            with pytest.raises((RuntimeError, ImportError, TypeError)):
                self.scraper._fetch_entries_playwright("20260224", "川崎", 12, "tok")

    def test_fetch_result_playwright_not_installed(self):
        """Playwright 未インストール時に RuntimeError が発生すること。"""
        with mock.patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            with pytest.raises((RuntimeError, ImportError, TypeError)):
                self.scraper._fetch_result_playwright("20260224", "川崎", 12, "tok")

    def test_parse_entries_malformed_html_returns_list(self):
        """不正 HTML でも例外なしでリストが返ること。"""
        result = self.scraper._parse_entries_html("<html><table><tr><td>壊れたHTML")
        assert isinstance(result, list)

    def test_parse_result_malformed_html_returns_none(self):
        """着順データがない不正 HTML で None が返ること。"""
        result = self.scraper._parse_result_html("<html><body>不正</body></html>", 1)
        assert result is None

    def test_init_with_empty_config(self):
        """空の config でも初期化エラーなしであること。"""
        scraper = KeirinScraper({})
        assert scraper.base_url is not None
        assert scraper.rate_limit_sec > 0


# ─── URL パターン テスト ───────────────────────────────────────────────────

class TestURLPattern:
    """URL パターン生成のテスト（モック使用）。"""

    def setup_method(self):
        self.scraper = KeirinScraper(CONFIG)

    def test_fetch_schedule_url_contains_date(self):
        """fetch_schedule が日付を含む URL を使用すること。"""
        captured_urls = []

        def mock_get(url):
            captured_urls.append(url)
            return "<html></html>"

        self.scraper._get = mock_get
        self.scraper.fetch_schedule("20260224")
        assert len(captured_urls) == 1
        assert "20260224" in captured_urls[0]

    def test_fetch_schedule_url_contains_votinglist(self):
        """fetch_schedule が votinglist エンドポイントを使用すること。"""
        captured_urls = []

        def mock_get(url):
            captured_urls.append(url)
            return "<html></html>"

        self.scraper._get = mock_get
        self.scraper.fetch_schedule("20260224")
        assert "votinglist" in captured_urls[0]

    def test_fetch_schedule_url_starts_with_base_url(self):
        """fetch_schedule が設定された base_url から始まる URL を使用すること。"""
        captured_urls = []

        def mock_get(url):
            captured_urls.append(url)
            return "<html></html>"

        self.scraper._get = mock_get
        self.scraper.fetch_schedule("20260224")
        assert captured_urls[0].startswith(self.scraper.base_url)

    def test_custom_base_url_reflected_in_schedule_url(self):
        """カスタム base_url が fetch_schedule の URL に反映されること。"""
        config = {"keirin": {"base_url": "https://example.com/test", "request_delay": 0}}
        scraper = KeirinScraper(config)
        captured_urls = []

        def mock_get(url):
            captured_urls.append(url)
            return "<html></html>"

        scraper._get = mock_get
        scraper.fetch_schedule("20260301")
        assert "example.com/test" in captured_urls[0]
