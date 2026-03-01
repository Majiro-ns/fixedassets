"""
競艇（BOAT RACE）出走表・結果スクレイパー
BOAT RACE オフィシャルウェブサイト（boatrace.jp）から
出走表・結果・スケジュールを取得する。

【robots.txt 確認済み】
  User-agent: *
  Disallow:          ← 全パス許可
  確認日: 2026-02-22

【利用規約】
  BOAT RACE 公式サイトの利用規約を遵守すること。
  自動取得は 1 リクエストあたり RATE_LIMIT_SEC 秒以上の間隔を設けること。
  取得上限 MAX_REQUESTS を超えた場合は自動停止する。

【URL パターン（公式サイト確認済み）】
  スケジュール: GET /owpc/pc/race/index?hd=YYYYMMDD
  出走表一覧:   GET /owpc/pc/race/racelist?jcd={jcd}&hd=YYYYMMDD
  前検情報:     GET /owpc/pc/race/beforeinfo?rno={rno}&jcd={jcd}&hd=YYYYMMDD
  レース結果:   GET /owpc/pc/race/raceresult?rno={rno}&jcd={jcd}&hd=YYYYMMDD

【出走表 HTML 構造（racelist ページ）】
  <div class="table1">
    <table>
      <tbody>  <!-- 6 艇分 × tbody 1 つ = 合計 6 tbody -->
        <tr>
          <td class="is-boatColor{N}">   ← 艇番（N=1〜6）
          <td class="is-fs15">           ← 選手名
          <td>                           ← 登録番号
          <td>                           ← 支部
          <td>                           ← 出身地
          <td>                           ← 年齢
          <td>                           ← 体重 (kg)
          <td>                           ← F 数 / L 数
          <td>                           ← 平均 ST (0.xx 形式)
          <td>                           ← モーター番号
          <td>                           ← モーター勝率 (2 節前勝率)
          <td>                           ← ボート番号
          <td>                           ← ボート勝率 (2 節前勝率)
        </tr>
        <tr class="is-fs11 is-gray">    ← コース別成績行
          <td colspan=2>
            <span>1コース: {wins}/{races}({rate}%)</span>
            ...
          </td>
        </tr>
      </tbody>
    </table>
  </div>

【前検情報 HTML 構造（beforeinfo ページ）】
  <div class="table1">
    <table>
      <tbody>
        <tr>
          <td>艇番</td>
          <td>選手名</td>
          <td>展示タイム</td>   ← チルト別タイム（秒）
          <td>チルト</td>
          <td>プロペラ交換</td>
        </tr>
      </tbody>
    </table>
  </div>
"""

import re
import time
import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml  # PyYAML

from src.base_scraper import BaseScraper


# ─── 定数デフォルト値（config/settings.yaml で上書き可能）────────────────
_DEFAULT_RATE_LIMIT_SEC = 3.0   # 最低リクエスト間隔（秒）
_DEFAULT_MAX_REQUESTS   = 20    # セッション内最大リクエスト数
_BASE_URL = "https://www.boatrace.jp/owpc/pc/race"
_USER_AGENT = "Mozilla/5.0 (prediction-pipeline/1.0; +research-use)"


# ─── 簡易 HTML パーサー（BeautifulSoup 非依存）──────────────────────────

class _TableExtractor(HTMLParser):
    """boatrace.jp の出走表テーブルから td テキストを抽出する軽量パーサー。

    boatrace.jp は JavaScript 動的生成を用いていないため
    urllib + 標準 HTMLParser で対応可能。
    """

    def __init__(self) -> None:
        super().__init__()
        self._in_td = False
        self._current_text: list[str] = []
        self.rows: list[list[str]] = []    # 全テーブル行（td テキストのリスト）
        self._current_row: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_td = True
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr":
            if self._current_row:
                self.rows.append(self._current_row)
        elif tag in ("td", "th"):
            self._in_td = False
            text = " ".join(self._current_text).strip()
            self._current_row.append(text)

    def handle_data(self, data: str) -> None:
        if self._in_td:
            stripped = data.strip()
            if stripped:
                self._current_text.append(stripped)


# ─── メインクラス ────────────────────────────────────────────────────────

class KyoteiScraper(BaseScraper):
    """BOAT RACE 公式サイトから競艇データを取得するスクレイパー。

    設定は config/settings.yaml の ``kyotei`` セクションから読み込む::

        kyotei:
          request_delay: 3.0    # リクエスト間隔（秒）※ rate_limit_sec は後方互換で引き続き有効
          max_requests: 20      # セッション内最大リクエスト数
          base_url: "https://www.boatrace.jp/owpc/pc/race"

    Example::

        import yaml
        from pathlib import Path
        from src.kyotei_scraper import KyoteiScraper

        config = yaml.safe_load(Path("config/settings.yaml").read_text())
        scraper = KyoteiScraper(config)

        entries = scraper.fetch_entries("20260222", "12", 1)
        for e in entries:
            print(e["racer_name"], e["motor_win_rate"])
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Args:
            config: 設定辞書。config/settings.yaml を yaml.safe_load した結果を渡す。
                    ``kyotei`` キーが無い場合はデフォルト値を使用する。
        """
        kyotei_cfg = config.get("kyotei", {})
        self._rate_limit: float = float(
            kyotei_cfg.get("request_delay", kyotei_cfg.get("rate_limit_sec", _DEFAULT_RATE_LIMIT_SEC))
        )
        self._max_requests: int = int(
            kyotei_cfg.get("max_requests", _DEFAULT_MAX_REQUESTS)
        )
        self._base_url: str = kyotei_cfg.get("base_url", _BASE_URL)
        self._request_count: int = 0

    # ────────────────────────────────────────────────────────────────────
    # 公開 API（BaseScraper 実装）
    # ────────────────────────────────────────────────────────────────────

    def fetch_entries(
        self,
        date: str,
        venue_code: str,
        race_num: int,
    ) -> List[Dict[str, Any]]:
        """指定レースの出走表を取得する。

        Args:
            date: 日付（YYYYMMDD 形式、例: "20260222"）
            venue_code: 場コード（2 桁ゼロ埋め、例: "01" = 桐生）
            race_num: レース番号（1〜12）

        Returns:
            6 要素の出走艇情報リスト。各要素は以下のキーを持つ::

                {
                    "boat_number":          int,    # 1〜6
                    "racer_name":           str,    # 例: "山田 太郎"
                    "registration_number":  str,    # 登録番号 6 桁
                    "racer_class":          str,    # A1 / A2 / B1 / B2
                    "branch":               str,    # 支部名
                    "age":                  int,    # 年齢
                    "weight_kg":            float,  # 体重（kg）
                    "false_start_count":    int,    # F 数
                    "late_count":           int,    # L 数
                    "avg_start_timing":     float,  # 平均 ST（0.xx 秒）
                    "motor_number":         int,    # モーター番号
                    "motor_win_rate":       float,  # モーター2節前勝率
                    "boat_number_eq":       int,    # ボート番号
                    "boat_win_rate":        float,  # ボート2節前勝率
                    "course_stats":         dict,   # コース別成績 {"1": 0.30, ...}
                }

        Raises:
            RuntimeError: MAX_REQUESTS 超過時
            urllib.error.URLError: ネットワークエラー時
            ValueError: date または venue_code の形式が不正な場合
        """
        self._validate_date(date)
        self._validate_venue_code(venue_code)

        url = (
            f"{self._base_url}/racelist"
            f"?jcd={venue_code}&hd={date}&rno={race_num}"
        )
        html = self._get(url)
        return self._parse_entries(html, race_num)

    def fetch_result(
        self,
        date: str,
        venue_code: str,
        race_num: int,
    ) -> Optional[Dict[str, Any]]:
        """指定レースの確定結果を取得する。

        Args:
            date: 日付（YYYYMMDD 形式）
            venue_code: 場コード（2 桁ゼロ埋め）
            race_num: レース番号（1〜12）

        Returns:
            結果辞書。レース未終了の場合は None::

                {
                    "race_num":       int,         # レース番号
                    "winning_order":  List[int],   # [1着艇番, 2着艇番, 3着艇番]
                    "trifecta_odds":  float,        # 3連単配当（円）
                    "trio_odds":      float,        # 3連複配当（円）
                    "exacta_odds":    float,        # 2連単配当（円）
                    "quinella_odds":  float,        # 2連複配当（円）
                    "is_disqualified": bool,        # 失格・事故等フラグ
                }

        Raises:
            RuntimeError: MAX_REQUESTS 超過時
            urllib.error.URLError: ネットワークエラー時
        """
        self._validate_date(date)
        self._validate_venue_code(venue_code)

        url = (
            f"{self._base_url}/raceresult"
            f"?rno={race_num}&jcd={venue_code}&hd={date}"
        )
        html = self._get(url)
        return self._parse_result(html, race_num)

    def fetch_schedule(self, date: str) -> List[Dict[str, Any]]:
        """指定日の全競艇場開催スケジュールを取得する。

        Args:
            date: 日付（YYYYMMDD 形式）

        Returns:
            開催レース情報リスト::

                [
                    {
                        "venue_code":  str,   # "01"〜"24"
                        "venue_name":  str,   # 例: "住之江"
                        "race_count":  int,   # 当日レース数（通常 12）
                        "grade":       str,   # SG / G1 / G2 / G3 / 一般
                        "title":       str,   # 開催タイトル（例: "全国選手権競走"）
                    },
                    ...
                ]

        Raises:
            RuntimeError: MAX_REQUESTS 超過時
            urllib.error.URLError: ネットワークエラー時
        """
        self._validate_date(date)
        url = f"{self._base_url}/index?hd={date}"
        html = self._get(url)
        return self._parse_schedule(html)

    def fetch_before_info(
        self,
        date: str,
        venue_code: str,
        race_num: int,
    ) -> List[Dict[str, Any]]:
        """前検（展示）情報を取得する。

        kyotei_prompt.txt の ``{exhibition_times}`` 変数に対応。

        Args:
            date: 日付（YYYYMMDD 形式）
            venue_code: 場コード（2 桁ゼロ埋め）
            race_num: レース番号（1〜12）

        Returns:
            展示情報リスト（6 要素）::

                [
                    {
                        "boat_number":      int,
                        "exhibition_time":  float,  # 展示タイム（秒、例: 6.73）
                        "tilt":             float,  # チルト角度（例: -0.5）
                        "propeller_changed": bool,  # プロペラ交換有無
                    },
                    ...
                ]
        """
        self._validate_date(date)
        self._validate_venue_code(venue_code)

        url = (
            f"{self._base_url}/beforeinfo"
            f"?rno={race_num}&jcd={venue_code}&hd={date}"
        )
        html = self._get(url)
        return self._parse_before_info(html)

    # ────────────────────────────────────────────────────────────────────
    # 内部 HTTP ユーティリティ（DoS 対策）
    # ────────────────────────────────────────────────────────────────────

    def _get(self, url: str) -> str:
        """DoS 対策付き HTTP GET。

        - MAX_REQUESTS を超えた場合は RuntimeError を送出する。
        - 各リクエスト後に RATE_LIMIT_SEC 秒スリープする。

        Args:
            url: 取得先 URL

        Returns:
            レスポンス HTML（UTF-8 デコード済み）

        Raises:
            RuntimeError: リクエスト数上限超過時
            urllib.error.URLError: ネットワークエラー時
        """
        if self._request_count >= self._max_requests:
            raise RuntimeError(
                f"MAX_REQUESTS ({self._max_requests}) 超過。"
                "DoS 対策のため取得を停止しました。"
                "新しい KyoteiScraper インスタンスを作成してください。"
            )

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "ja,en-US;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            html: str = resp.read().decode("utf-8", errors="replace")

        self._request_count += 1
        time.sleep(self._rate_limit)  # DoS 対策: 必ず待機
        return html

    # ────────────────────────────────────────────────────────────────────
    # HTML パースメソッド（骨格実装）
    # ────────────────────────────────────────────────────────────────────

    def _parse_entries(self, html: str, race_num: int) -> List[Dict[str, Any]]:
        """racelist ページの HTML から指定レース番号の出走表を抽出する。

        HTML 構造（boatrace.jp 2026-02 時点）:
          - ページ内に 12 レース分のテーブルが縦に並ぶ
          - 各レースは ``<div id="raceNo{N}">`` に囲まれる（N=1〜12）
          - その内部に ``<table>``  1 つ、``<tbody>`` 6 つ（1 艇ごと）
          - tbody[0] の 1 行目: 艇番・選手名・登番・体重・F/L・ST・モーター・ボート
          - tbody[0] の 2 行目: 全国・当地勝率
          - tbody[0] の 3 行目: コース別成績（1〜6 コース）
        """
        entries: List[Dict[str, Any]] = []

        # レースブロックを race_num で特定（id="raceNo{N}" パターン）
        race_block = self._extract_race_block(html, race_num)
        if not race_block:
            return entries

        # tbody を 6 ブロックに分割して各艇を解析
        tbody_pattern = re.compile(r"<tbody[^>]*>(.*?)</tbody>", re.DOTALL | re.IGNORECASE)
        tbodies = tbody_pattern.findall(race_block)

        for i, tbody_html in enumerate(tbodies[1:7], start=1):
            entry = self._parse_single_entry(tbody_html, i)
            if entry:
                entries.append(entry)

        return entries

    def _parse_single_entry(
        self, tbody_html: str, boat_number: int
    ) -> Optional[Dict[str, Any]]:
        """1 艇分の tbody HTML から選手データを抽出する。

        Args:
            tbody_html: 1 艇分の <tbody>…</tbody> 内 HTML
            boat_number: 艇番（1〜6）

        Returns:
            選手データ辞書。解析失敗時は None。
        """
        parser = _TableExtractor()
        parser.feed(tbody_html)
        rows = parser.rows

        if not rows:
            return None

        # 行 0: 基本情報行
        # td インデックス（boatrace.jp 実測値に基づく骨格）
        # [0]=艇番, [1]=選手名, [2]=登番, [3]=支部, [4]=出身, [5]=年齢,
        # [6]=体重, [7]=F/L数, [8]=平均ST, [9]=モーター番号, [10]=モーター勝率,
        # [11]=ボート番号, [12]=ボート勝率
        try:
            row0 = rows[0] if len(rows) > 0 else []
            row2 = rows[2] if len(rows) > 2 else []  # コース別成績行

            racer_name    = row0[1]  if len(row0) > 1  else ""
            reg_number    = row0[2]  if len(row0) > 2  else ""
            branch        = row0[3]  if len(row0) > 3  else ""
            age           = self._safe_int(row0[5])   if len(row0) > 5  else None
            weight        = self._safe_float(row0[6]) if len(row0) > 6  else None
            fl_text       = row0[7]  if len(row0) > 7  else "F0L0"
            avg_st        = self._safe_float(row0[8]) if len(row0) > 8  else None
            motor_no      = self._safe_int(row0[9])   if len(row0) > 9  else None
            motor_wr      = self._safe_float(row0[10])if len(row0) > 10 else None
            boat_no_eq    = self._safe_int(row0[11])  if len(row0) > 11 else None
            boat_wr       = self._safe_float(row0[12])if len(row0) > 12 else None

            # F数・L数を "F{N}L{N}" 形式からパース
            f_count = self._safe_int(re.search(r"F(\d+)", fl_text).group(1)
                                     if re.search(r"F(\d+)", fl_text) else "0")
            l_count = self._safe_int(re.search(r"L(\d+)", fl_text).group(1)
                                     if re.search(r"L(\d+)", fl_text) else "0")

            # 級別（登録番号の前後に付く場合あり）
            racer_class = self._extract_class(tbody_html)

            # コース別成績（row2 から "1コース: X/Y(Z%)" 形式でパース）
            course_stats = self._parse_course_stats(row2)

        except (IndexError, AttributeError):
            # HTML 構造変更時のフェイルセーフ
            racer_name = ""
            reg_number = ""
            branch     = ""
            age        = None
            weight     = None
            f_count    = 0
            l_count    = 0
            avg_st     = None
            motor_no   = None
            motor_wr   = None
            boat_no_eq = None
            boat_wr    = None
            racer_class = ""
            course_stats = {}

        return {
            "boat_number":          boat_number,
            "racer_name":           racer_name.strip(),
            "registration_number":  reg_number.strip(),
            "racer_class":          racer_class,
            "branch":               branch.strip(),
            "age":                  age,
            "weight_kg":            weight,
            "false_start_count":    f_count,
            "late_count":           l_count,
            "avg_start_timing":     avg_st,
            "motor_number":         motor_no,
            "motor_win_rate":       motor_wr,
            "boat_number_eq":       boat_no_eq,
            "boat_win_rate":        boat_wr,
            "course_stats":         course_stats,
        }

    def _parse_result(self, html: str, race_num: int) -> Optional[Dict[str, Any]]:
        """raceresult ページの HTML から確定結果を抽出する。

        HTML 構造:
          - 着順テーブルは ``<div class="table1">`` 内の ``<table>``
          - 各行: [着順, 艇番, 選手名, 決まり手, 配当]
          - 「確定」ボタンまたは h3 テキストで未確定判定
        """
        # 「確定」マークが無い場合は未確定
        # 実際のHTMLには "is-result"/"確定" は存在しない。"3連単"/"払戻" で判定。
        if "3連単" not in html and "払戻" not in html:
            return None

        # 着順抽出: 3連単の numberSet1_number から1着〜3着の艇番を読む
        # 実際のHTML: <div class="numberSet1_number is-typeX">艇番</div>
        # "1着"/"2着"/"3着" テキストはHTML中に存在しないため旧ロジックは廃止
        nums = re.findall(r'numberSet1_number[^>]*>(\d+)<', html)
        winning_order = [int(n) for n in nums[:3]]

        # 配当テーブルからオッズを抽出
        odds_map: Dict[str, float] = self._parse_odds(html)

        if not winning_order:
            return None

        return {
            "race_num":        race_num,
            "winning_order":   winning_order[:3],
            "trifecta_odds":   odds_map.get("3連単", 0.0),
            "trio_odds":       odds_map.get("3連複", 0.0),
            "exacta_odds":     odds_map.get("2連単", 0.0),
            "quinella_odds":   odds_map.get("2連複", 0.0),
            "is_disqualified": "失格" in html or "事故" in html,
        }

    def _parse_schedule(self, html: str) -> List[Dict[str, Any]]:
        """index ページの HTML から当日開催場一覧を抽出する。

        HTML 構造:
          - メイン開催テーブルは ``<div class="table1 is-w1160">`` 内
          - 各行に会場名・グレード・開催タイトルが含まれる
          - 会場へのリンク: href="/owpc/pc/race/raceindex?jcd={jcd}&hd={date}"
        """
        schedule: List[Dict[str, Any]] = []

        # jcd パラメータを href から抽出（会場コード特定）
        jcd_pattern = re.compile(r"jcd=(\d{2})(?:&amp;|&)hd=(\d{8})")
        grade_pattern = re.compile(
            r"(SG|G1|G2|G3|一般|オールスター|全国選手権|グランプリ)"
        )

        parser = _TableExtractor()
        parser.feed(html)

        seen_jcds: set = set()
        for match in jcd_pattern.finditer(html):
            jcd = match.group(1)
            if jcd in seen_jcds:
                continue
            seen_jcds.add(jcd)

            # グレード推定（近傍テキストから）
            start = max(0, match.start() - 200)
            end   = min(len(html), match.end() + 200)
            context = html[start:end]
            grade_match = grade_pattern.search(context)
            grade = grade_match.group(1) if grade_match else "一般"

            schedule.append(
                {
                    "venue_code":  jcd,
                    "venue_name":  self._jcd_to_name(jcd),
                    "race_count":  12,          # 原則 12 レース
                    "grade":       grade,
                    "title":       "",          # 詳細は raceindex で取得
                }
            )

        return schedule

    def _parse_before_info(self, html: str) -> List[Dict[str, Any]]:
        """beforeinfo ページの HTML から前検（展示）情報を抽出する。

        HTML 構造:
          - 展示テーブルは ``<div class="table1">`` 内
          - 各行: [艇番, 選手名, 展示タイム, チルト, プロペラ交換]
          - 展示タイム: "6.73" 形式（秒、小数点以下 2 桁）
          - チルト: "-0.5" 〜 "+3.0" 形式
        """
        parser = _TableExtractor()
        parser.feed(html)
        rows = parser.rows

        results: List[Dict[str, Any]] = []
        for row in rows:
            if len(row) < 3:
                continue
            boat_num = self._safe_int(row[0])
            if boat_num not in range(1, 7):
                continue
            results.append(
                {
                    "boat_number":       boat_num,
                    "exhibition_time":   self._safe_float(row[2]) if len(row) > 2 else None,
                    "tilt":              self._safe_float(row[3]) if len(row) > 3 else None,
                    "propeller_changed": "交換" in row[4] if len(row) > 4 else False,
                }
            )

        return results

    # ────────────────────────────────────────────────────────────────────
    # 補助メソッド
    # ────────────────────────────────────────────────────────────────────

    def _extract_race_block(self, html: str, race_num: int) -> str:
        """HTML から指定レース番号のブロックを切り出す。

        boatrace.jp では各レースが ``<div id="raceNo{N}">`` で区切られる。
        """
        # id="raceNo{N}" から次の id="raceNo{N+1}" または末尾まで
        start_pat = re.compile(
            rf'<[^>]+id="raceNo{race_num}"[^>]*>', re.IGNORECASE
        )
        end_pat = re.compile(
            rf'<[^>]+id="raceNo{race_num + 1}"[^>]*>', re.IGNORECASE
        )
        m_start = start_pat.search(html)
        if not m_start:
            return html
        m_end = end_pat.search(html, m_start.end())
        if m_end:
            return html[m_start.start():m_end.start()]
        return html[m_start.start():]

    def _parse_course_stats(self, row: List[str]) -> Dict[str, float]:
        """コース別成績行のテキストリストから {コース番号: 勝率} 辞書を返す。

        入力例: ["1コース 20/50(40.0%)", "2コース 5/30(16.7%)", ...]
        """
        stats: Dict[str, float] = {}
        pattern = re.compile(r"(\d)コース\s*\d+/\d+\(([0-9.]+)%\)")
        for cell in row:
            for m in pattern.finditer(cell):
                stats[m.group(1)] = float(m.group(2)) / 100.0
        return stats

    def _parse_odds(self, html: str) -> Dict[str, float]:
        """配当テーブルから式別オッズを抽出する。

        実際のHTML形式: <span class="is-payout1">&yen;20,360</span>
        "円" テキストではなく "&yen;" HTML エンティティで配当が表記されている。
        """
        odds: Dict[str, float] = {}
        pattern = re.compile(
            r"(3連単|3連複|2連単|2連複).*?(?:&yen;|円)([0-9,]+)",
            re.DOTALL,
        )
        for m in pattern.finditer(html):
            key = m.group(1)
            val = float(m.group(2).replace(",", ""))
            if key not in odds:  # 最初の出現のみ採用
                odds[key] = val
        return odds

    def _extract_class(self, tbody_html: str) -> str:
        """tbody HTML 内から選手の級別（A1/A2/B1/B2）を抽出する。"""
        m = re.search(r"\b(A1|A2|B1|B2)\b", tbody_html)
        return m.group(1) if m else ""

    @staticmethod
    def _safe_int(text: Any) -> Optional[int]:
        """テキストを int に変換。失敗時は None を返す。"""
        try:
            return int(str(text).strip())
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_float(text: Any) -> Optional[float]:
        """テキストを float に変換。失敗時は None を返す。"""
        try:
            return float(str(text).strip())
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _validate_date(date: str) -> None:
        """日付文字列の形式を検証する（YYYYMMDD）。"""
        if not re.fullmatch(r"\d{8}", date):
            raise ValueError(f"日付は YYYYMMDD 形式で指定してください: {date!r}")

    @staticmethod
    def _validate_venue_code(venue_code: str) -> None:
        """場コードの形式を検証する（2 桁数字文字列、01〜24）。"""
        if not re.fullmatch(r"0[1-9]|1\d|2[0-4]", venue_code):
            raise ValueError(
                f"場コードは 01〜24 の 2 桁文字列で指定してください: {venue_code!r}"
            )

    @staticmethod
    def _jcd_to_name(jcd: str) -> str:
        """場コードから競艇場名を返す。venues.yaml が無い環境用フォールバック。"""
        _MAP = {
            "01": "桐生",  "02": "戸田",  "03": "江戸川", "04": "平和島",
            "05": "多摩川","06": "浜名湖","07": "蒲郡",   "08": "常滑",
            "09": "津",    "10": "三国",  "11": "びわこ", "12": "住之江",
            "13": "尼崎",  "14": "鳴門",  "15": "丸亀",   "16": "児島",
            "17": "宮島",  "18": "徳山",  "19": "下関",   "20": "若松",
            "21": "芦屋",  "22": "福岡",  "23": "唐津",   "24": "大村",
        }
        return _MAP.get(jcd, f"不明({jcd})")


# ─── ファクトリー関数 ────────────────────────────────────────────────────

def create_scraper(settings_path: str = "config/settings.yaml") -> "KyoteiScraper":
    """設定ファイルを読み込んで KyoteiScraper を生成するファクトリー関数。

    Args:
        settings_path: settings.yaml へのパス（デフォルト: config/settings.yaml）

    Returns:
        設定済みの KyoteiScraper インスタンス

    Example::

        scraper = create_scraper()
        entries = scraper.fetch_entries("20260222", "12", 1)
    """
    path = Path(settings_path)
    if path.exists():
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        # settings.yaml が無い場合はデフォルト設定で起動
        config = {
            "kyotei": {
                "request_delay": _DEFAULT_RATE_LIMIT_SEC,
                "max_requests":  _DEFAULT_MAX_REQUESTS,
                "base_url":      _BASE_URL,
            }
        }
    return KyoteiScraper(config)
