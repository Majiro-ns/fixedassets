"""
競輪レーススケジュール・出走表・結果スクレイパー
KEIRIN.JP の votinglist (Tier 1) および racevote/raceresult (Tier 2 / Playwright) から
データを取得する。

robots.txt 確認済み（2026-02-22）:
  Allow:/pc/votinglist, /pc/raceschedule, /pc/racerprofile
  NOT Allowed:/pc/racevote, /pc/raceresult  → Tier 2 (Playwright必須)

DoS対策:
  - rate_limit_sec=3.0 秒
  - max_requests=20 件/セッション
  - User-Agent: 正直な識別子を使用
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.base_scraper import BaseScraper


# ─────────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://keirin.jp/pc"
DEFAULT_RATE_LIMIT_SEC = 3.0
DEFAULT_MAX_REQUESTS = 20
DEFAULT_USER_AGENT = "PredictionPipeline/1.0 (research; DoS-safe)"
REQUEST_TIMEOUT = 15

# keirin.jp 場コード → 場名マッピング
VENUE_CODES: Dict[str, str] = {
    "01": "函館",
    "02": "青森",
    "03": "いわき平",
    "04": "弥彦",
    "05": "前橋",
    "06": "取手",
    "07": "宇都宮",
    "08": "大宮",
    "09": "西武園",
    "10": "京王閣",
    "11": "立川",
    "12": "松戸",
    "13": "千葉",
    "14": "川崎",
    "15": "平塚",
    "16": "小田原",
    "17": "伊東",
    "18": "静岡",
    "19": "浜松",
    "20": "豊橋",
    "21": "名古屋",
    "22": "岐阜",
    "23": "大垣",
    "24": "四日市",
    "25": "松阪",
    "26": "奈良",
    "27": "向日町",
    "28": "和歌山",
    "29": "岸和田",
    "30": "玉野",
    "31": "広島",
    "32": "防府",
    "33": "高松",
    "34": "松山",
    "35": "高知",
    "36": "小倉",
    "37": "久留米",
    "38": "武雄",
    "39": "佐世保",
    "40": "別府",
    "41": "熊本",
}

# バンク周長マッピング（メートル）
BANK_LENGTH: Dict[str, int] = {
    "函館": 333,
    "青森": 400,
    "いわき平": 400,
    "弥彦": 400,
    "前橋": 333,
    "取手": 400,
    "宇都宮": 333,
    "大宮": 400,
    "西武園": 400,
    "京王閣": 400,
    "立川": 400,
    "松戸": 400,
    "千葉": 400,
    "川崎": 400,
    "平塚": 400,
    "小田原": 500,
    "伊東": 333,
    "静岡": 400,
    "浜松": 400,
    "豊橋": 400,
    "名古屋": 400,
    "岐阜": 400,
    "大垣": 400,
    "四日市": 333,
    "松阪": 400,
    "奈良": 400,
    "向日町": 333,
    "和歌山": 400,
    "岸和田": 400,
    "玉野": 400,
    "広島": 400,
    "防府": 400,
    "高松": 400,
    "松山": 400,
    "高知": 333,
    "小倉": 400,
    "久留米": 400,
    "武雄": 400,
    "佐世保": 400,
    "別府": 400,
    "熊本": 400,
}


# ─────────────────────────────────────────────────────────────
# DoS対策レートリミッター
# ─────────────────────────────────────────────────────────────

class RateLimiter:
    """リクエスト間隔・上限数を管理するクラス。"""

    def __init__(
        self,
        rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
        max_requests: int = DEFAULT_MAX_REQUESTS,
    ) -> None:
        """
        Args:
            rate_limit_sec: リクエスト間最小待機秒数。
            max_requests: セッション内最大リクエスト数。
        """
        self.rate_limit_sec = rate_limit_sec
        self.max_requests = max_requests
        self._count = 0
        self._last_time: Optional[float] = None

    def wait(self) -> None:
        """次リクエスト前に待機する。上限超過時は RuntimeError を送出。"""
        if self._count >= self.max_requests:
            raise RuntimeError(
                f"最大リクエスト数 ({self.max_requests}件) に達した。DoS対策のため終了。"
            )
        if self._last_time is not None:
            elapsed = time.time() - self._last_time
            wait_sec = self.rate_limit_sec - elapsed
            if wait_sec > 0:
                time.sleep(wait_sec)
        self._last_time = time.time()
        self._count += 1

    @property
    def count(self) -> int:
        """現在のリクエスト数を返す。"""
        return self._count


# ─────────────────────────────────────────────────────────────
# KeirinScraper 本体
# ─────────────────────────────────────────────────────────────

class KeirinScraper(BaseScraper):
    """
    KEIRIN.JP から競輪レース情報を取得するスクレイパー。

    BaseScraper を継承し fetch_schedule / fetch_entries / fetch_result を実装する。

    Tier 1 (Low Risk):
        - fetch_schedule: /pc/votinglist (robots.txt Allow済み)
    Tier 2 (High Risk / Playwright必須):
        - fetch_entries: /pc/racevote (Disallow)
        - fetch_result:  /pc/raceresult (Disallow)

    DoS対策:
        rate_limit_sec=3.0, max_requests=20
    """

    # 後方互換クラス属性
    DEFAULT_DELAY: float = DEFAULT_RATE_LIMIT_SEC
    BASE_URL: str = DEFAULT_BASE_URL

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Args:
            config: 設定辞書。settings.yaml を yaml.safe_load した結果を想定。
                    keirin.base_url / keirin.request_delay を参照する。
        """
        keirin_cfg = config.get("keirin", {})
        scraping_cfg = config.get("scraping", {})

        self.base_url: str = keirin_cfg.get("base_url", DEFAULT_BASE_URL)
        self.rate_limit_sec: float = float(
            keirin_cfg.get("request_delay", scraping_cfg.get("min_interval_sec", DEFAULT_RATE_LIMIT_SEC))
        )
        self.max_requests: int = int(
            scraping_cfg.get("max_requests_per_session", DEFAULT_MAX_REQUESTS)
        )
        self.user_agent: str = scraping_cfg.get("user_agent", DEFAULT_USER_AGENT)
        self.delay: float = self.rate_limit_sec  # 後方互換エイリアス
        self._limiter = RateLimiter(self.rate_limit_sec, self.max_requests)

    # ─── BaseScraper 抽象メソッド実装 ─────────────────────────

    def fetch_schedule(self, date: str) -> List[Dict[str, Any]]:
        """
        指定日の競輪開催スケジュールを取得する（Tier 1 / Low Risk）。

        keirin.jp/pc/votinglist から取得し HTML 埋め込み JSON をパースする。
        robots.txt: Allow:/pc/votinglist

        Args:
            date: YYYYMMDD 形式（例: "20260224"）

        Returns:
            開催レース情報のリスト。各要素は以下のキーを含む::

                {
                    "venue_code": "14",
                    "venue_name": "川崎",
                    "race_num": 12,
                    "grade": "S1",
                    "start_time": "20260224",
                    "bank_length": 400,
                    "race_token": "<touhyouLivePara>",
                }

        Raises:
            urllib.error.URLError: ネットワークエラー時
        """
        url = f"{self.base_url}/votinglist?hd={date}"
        html = self._get(url)
        return self._parse_schedule(html, date)

    def fetch_entries(
        self,
        date: str,
        venue_code: str,
        race_num: int,
    ) -> List[Dict[str, Any]]:
        """
        指定レースの出走表を取得する（Tier 2 / Playwright）。

        robots.txt: Disallow → High Risk。利用規約を必ず確認のこと。
        JavaScript レンダリングが必要なため Playwright を使用する。

        Args:
            date: YYYYMMDD 形式（例: "20260224"）
            venue_code: 会場コード 2桁文字列（例: "14"）
            race_num: レース番号（1〜12）

        Returns:
            選手情報のリスト。各要素は以下のキーを含む::

                {
                    "frame": 1,
                    "name": "山田 太郎",
                    "number": "012345",
                    "rank": "S1",
                    "leg_type": "逃げ",
                    "score": 95.12,
                    "line": [1, 3],
                    "recent_results": [1, 2, 1, 3, 1],
                }
        """
        venue_name = VENUE_CODES.get(venue_code, venue_code)
        # スケジュールからトークンを取得
        schedule = self.fetch_schedule(date)
        token = ""
        for s in schedule:
            if s.get("venue_code") == venue_code:
                token = s.get("race_token", "")
                break

        return self._fetch_entries_playwright(date, venue_name, race_num, token)

    def fetch_result(
        self,
        date: str,
        venue_code: str,
        race_num: int,
    ) -> Optional[Dict[str, Any]]:
        """
        指定レースの結果・配当を取得する（Tier 2 / Playwright）。

        robots.txt: Disallow → High Risk。
        JavaScript レンダリングが必要なため Playwright を使用する。

        Args:
            date: YYYYMMDD 形式
            venue_code: 会場コード 2桁文字列
            race_num: レース番号（1〜12）

        Returns:
            レース結果辞書。未終了・取得失敗時は None::

                {
                    "race_num": 12,
                    "winning_order": [3, 1, 4],
                    "trifecta_odds": 1250,
                    "trio_odds": 320,
                    "exacta_odds": 580,
                    "quinella_odds": 120,
                    "winning_move": "まくり",
                    "race_time": "11.2",
                }
        """
        venue_name = VENUE_CODES.get(venue_code, venue_code)
        schedule = self.fetch_schedule(date)
        token = ""
        for s in schedule:
            if s.get("venue_code") == venue_code:
                token = s.get("race_token", "")
                break

        return self._fetch_result_playwright(date, venue_name, race_num, token)

    # ─── Tier 1: スケジュールパース ──────────────────────────

    def _parse_schedule(self, html: str, date: str) -> List[Dict[str, Any]]:
        """
        votinglist HTML から開催スケジュールを抽出する。

        keirin.jp の votinglist ページには JavaScript 変数として
        ``var pc0101_json = {...};`` 形式で JSON が埋め込まれている。

        Args:
            html: fetch_schedule で取得した HTML 文字列
            date: フィルタ用日付 YYYYMMDD

        Returns:
            開催レース情報のリスト
        """
        # votinglist の JSON 変数名パターン
        patterns = [
            r'var\s+pc0101_json\s*=\s*(\{.*?\});',
            r'var\s+\w+_json\s*=\s*(\{.*?\});',
        ]

        data: Dict[str, Any] = {}
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    break
                except json.JSONDecodeError:
                    continue

        race_list = data.get("RaceList", [])
        entries: List[Dict[str, Any]] = []

        for race in race_list:
            race_date = race.get("kaisaiDate", "")
            if date and race_date and race_date != date:
                continue

            venue_code = str(race.get("naibuKeirinCd", "")).zfill(2)
            venue_name = race.get("keirinjoName", VENUE_CODES.get(venue_code, venue_code))
            grade = race.get("gradeIconName", race.get("gradeKbn", ""))
            race_num_str = race.get("raceNum", "12R")
            race_count = int(re.sub(r"\D", "", str(race_num_str)) or "12")
            token = race.get("touhyouLivePara", "")
            bank_length = BANK_LENGTH.get(venue_name, 400)

            entries.append({
                "venue_code": venue_code,
                "venue_name": venue_name,
                "race_num": race_count,
                "grade": grade,
                "start_time": race_date,
                "bank_length": bank_length,
                "race_token": token,
            })

        return entries

    # ─── Tier 2: 出走表取得 (Playwright) ────────────────────

    def _fetch_entries_playwright(
        self,
        date: str,
        venue_name: str,
        race_num: int,
        race_token: str,
    ) -> List[Dict[str, Any]]:
        """
        Playwright で出走表ページを取得しパースする。

        Args:
            date: YYYYMMDD
            venue_name: 開催場名
            race_num: レース番号
            race_token: votinglist から取得した touhyouLivePara トークン

        Returns:
            選手エントリーのリスト
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright がインストールされていない。"
                " pip install playwright && playwright install chromium を実行してください。"
            )

        url = f"{self.base_url}/racevote?{race_token}"
        time.sleep(self.rate_limit_sec)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()
            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                time.sleep(2)
                html = page.content()
            except Exception as exc:
                raise urllib.error.URLError(f"Playwright 出走表取得失敗: {exc}") from exc
            finally:
                browser.close()

        return self._parse_entries_html(html)

    def _parse_entries_html(self, html: str) -> List[Dict[str, Any]]:
        """
        出走表 HTML から選手エントリーを抽出する。

        keirin.jp 出走表ページの構造（2026-02-22 調査）:
        - 選手情報テーブル: class に "entry" または "shutsuso" を含む
        - 列順: 枠番 / 登録番号 / 選手名 / 級班 / 脚質 / 競走得点 / 直近成績...

        Args:
            html: Playwright で取得した出走表ページの HTML

        Returns:
            選手エントリーのリスト
        """
        # BeautifulSoup を優先使用し、未インストール時はフォールバック
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            return self._parse_entries_with_bs4(soup)
        except ImportError:
            return self._parse_entries_with_regex(html)

    def _parse_entries_with_bs4(self, soup: Any) -> List[Dict[str, Any]]:
        """BeautifulSoup を使った出走表パース。"""
        entries: List[Dict[str, Any]] = []

        # 出走表テーブルを探す（複数の候補を試みる）
        table_candidates = [
            soup.find("table", class_=re.compile(r"entry|shutsuso|race_player", re.I)),
            soup.find("table", id=re.compile(r"entry|shutsuso", re.I)),
        ]
        entry_table = next((t for t in table_candidates if t is not None), None)

        if entry_table is None:
            tables = soup.find_all("table")
            if tables:
                entry_table = max(tables, key=lambda t: len(t.find_all("tr")))

        if entry_table is None:
            return entries

        rows = entry_table.find_all("tr")
        for row in rows[1:]:  # ヘッダー行をスキップ
            cols = row.find_all("td")
            if len(cols) < 5:
                continue
            try:
                frame_text = re.sub(r"\D", "", cols[0].get_text(strip=True))
                frame = int(frame_text) if frame_text else 0
                number = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                name = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                rank = cols[3].get_text(strip=True) if len(cols) > 3 else ""
                leg_type = cols[4].get_text(strip=True) if len(cols) > 4 else ""
                score_text = re.sub(r"[^\d.]", "", cols[5].get_text(strip=True)) if len(cols) > 5 else ""
                score = float(score_text) if score_text else None

                # ライン情報（複数選手が同一行に記載されることがある）
                line_text = cols[6].get_text(strip=True) if len(cols) > 6 else ""
                line = [int(n) for n in re.findall(r"\d+", line_text)] if line_text else [frame]

                # 直近成績（列7〜11程度）
                recent_results = []
                for i in range(7, min(len(cols), 13)):
                    r_text = re.sub(r"\D", "", cols[i].get_text(strip=True))
                    if r_text:
                        recent_results.append(int(r_text))

                if frame > 0 or name:
                    entries.append({
                        "frame": frame,
                        "name": name,
                        "number": number,
                        "rank": rank,
                        "leg_type": leg_type,
                        "score": score,
                        "line": line,
                        "recent_results": recent_results[:5],
                    })
            except (ValueError, IndexError):
                continue

        return entries

    def _parse_entries_with_regex(self, html: str) -> List[Dict[str, Any]]:
        """BeautifulSoup 未インストール時の正規表現フォールバック。"""
        entries: List[Dict[str, Any]] = []
        # tr タグ内の td を抽出する簡易パース
        tr_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
        tag_pattern = re.compile(r"<[^>]+>")

        for tr_match in tr_pattern.finditer(html):
            tr_content = tr_match.group(1)
            cols = [tag_pattern.sub("", td.group(1)).strip() for td in td_pattern.finditer(tr_content)]
            if len(cols) < 5:
                continue
            frame_text = re.sub(r"\D", "", cols[0])
            if not frame_text:
                continue
            try:
                frame = int(frame_text)
                score_text = re.sub(r"[^\d.]", "", cols[5]) if len(cols) > 5 else ""
                entries.append({
                    "frame": frame,
                    "name": cols[2] if len(cols) > 2 else "",
                    "number": cols[1] if len(cols) > 1 else "",
                    "rank": cols[3] if len(cols) > 3 else "",
                    "leg_type": cols[4] if len(cols) > 4 else "",
                    "score": float(score_text) if score_text else None,
                    "line": [frame],
                    "recent_results": [],
                })
            except (ValueError, IndexError):
                continue

        return entries

    # ─── Tier 2: 結果取得 (Playwright) ──────────────────────

    def _fetch_result_playwright(
        self,
        date: str,
        venue_name: str,
        race_num: int,
        race_token: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Playwright でレース結果ページを取得しパースする。

        Args:
            date: YYYYMMDD
            venue_name: 開催場名
            race_num: レース番号
            race_token: votinglist から取得したトークン

        Returns:
            レース結果辞書、または None
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright がインストールされていない。"
                " pip install playwright && playwright install chromium を実行してください。"
            )

        url = f"{self.base_url}/raceresult?{race_token}"
        time.sleep(self.rate_limit_sec)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()
            try:
                page.goto(url, timeout=30000, wait_until="networkidle")
                time.sleep(2)
                html = page.content()
            except Exception as exc:
                return None
            finally:
                browser.close()

        return self._parse_result_html(html, race_num)

    def _parse_result_html(self, html: str, race_num: int) -> Optional[Dict[str, Any]]:
        """
        結果 HTML から着順・配当・決まり手を抽出する。

        keirin.jp 結果ページ HTML 構造（2026-02-22 調査）:
        - 着順テーブル: class="result_table" または "chakujun" を含む
        - 配当テーブル: class="dividend_table" または "haraimodoshi" を含む
        - 決まり手: class="kimari_te" または "winning_move" を含む

        Args:
            html: Playwright で取得した結果ページ HTML
            race_num: レース番号

        Returns:
            レース結果辞書
        """
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
        except ImportError:
            soup = None

        result: Dict[str, Any] = {
            "race_num": race_num,
            "winning_order": [],
            "trifecta_odds": None,
            "trio_odds": None,
            "exacta_odds": None,
            "quinella_odds": None,
            "winning_move": "",
            "race_time": None,
        }

        if soup is None:
            # 正規表現フォールバック（簡易版）
            order_match = re.findall(r'chakujun[^>]*>.*?(\d)', html)
            result["winning_order"] = [int(n) for n in order_match[:3]]
            return result if result["winning_order"] else None

        # 着順テーブル
        result_table = soup.find("table", class_=re.compile(r"result|chakujun", re.I))
        if result_table:
            for row in result_table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if cols:
                    frame_text = re.sub(r"\D", "", cols[0].get_text(strip=True))
                    if frame_text:
                        result["winning_order"].append(int(frame_text))

        # 配当テーブル
        div_table = soup.find("table", class_=re.compile(r"dividend|haraimodoshi|harai", re.I))
        if div_table:
            for row in div_table.find_all("tr"):
                cols = row.find_all("td")
                if not cols:
                    continue
                # ベット種別はrow全体で判定
                row_text = row.get_text()
                # 配当金額は「円」を含む列から個別取得（組み合わせ列との結合を防ぐ）
                # 例: <td>3連単</td><td>3-1-4</td><td>12,500円</td> で
                #     row.get_text()="3連単3-1-412,500円" → "412,500" に誤マッチするバグを修正
                amount = None
                for col in cols:
                    col_text = col.get_text(strip=True)
                    amount_match = re.search(r"([\d,]+)円", col_text)
                    if amount_match:
                        amount = int(re.sub(r",", "", amount_match.group(1)))
                        break
                if "3連単" in row_text:
                    result["trifecta_odds"] = amount
                elif "3連複" in row_text:
                    result["trio_odds"] = amount
                elif "2車単" in row_text:
                    result["exacta_odds"] = amount
                elif "2車複" in row_text:
                    result["quinella_odds"] = amount

        # 決まり手
        kimari_el = soup.find(class_=re.compile(r"kimari|winning_move", re.I))
        if kimari_el:
            result["winning_move"] = kimari_el.get_text(strip=True)

        # タイム
        time_el = soup.find(class_=re.compile(r"race_time|lap_time", re.I))
        if time_el:
            time_text = time_el.get_text(strip=True)
            time_match = re.search(r"(\d+\.\d+)", time_text)
            if time_match:
                result["race_time"] = time_match.group(1)

        return result if result["winning_order"] else None

    # ─── 内部ユーティリティ ───────────────────────────────

    def _get(self, url: str) -> str:
        """
        指定 URL に GET リクエストを送り HTML を返す。

        DoS対策のレートリミットを適用する。

        Args:
            url: 取得先 URL

        Returns:
            レスポンス HTML 文字列

        Raises:
            urllib.error.URLError: ネットワークエラー時
        """
        self._limiter.wait()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en;q=0.5",
            },
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    def _parse_results(self, html: str) -> List[Dict[str, Any]]:
        """
        後方互換メソッド。結果 HTML から結果リストを返す。

        Args:
            html: 結果ページの HTML 文字列

        Returns:
            結果情報のリスト（空 HTML の場合は空リスト）
        """
        result = self._parse_result_html(html, 0)
        if result is None:
            return []
        return [result]
