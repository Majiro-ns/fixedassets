"""
Kドリームス（keirin.kdreams.jp）出走表スクレイパー
=================================================

keirin.jp の出走表は JSF/SPA で Playwright 必須だが、
Kドリームスは静的 HTML で出走表を提供しているため requests + BeautifulSoup で取得可能。

URL パターン:
  開催一覧:  https://keirin.kdreams.jp/racecard/{YYYY}/{MM}/{DD}/
  開催詳細:  https://keirin.kdreams.jp/{venue}/racecard/{venue_code}{date}{day_num}00/
  レース詳細: https://keirin.kdreams.jp/{venue}/racedetail/{venue_code}{date}{day_num}{race_num:04d}/
"""

import re
import time
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup


DEFAULT_RATE_LIMIT_SEC = 3.0
DEFAULT_USER_AGENT = "PredictionPipeline/1.0 (research; DoS-safe)"

# kdreams のURL用場名マッピング
VENUE_SLUG: Dict[str, str] = {
    "01": "hakodate", "02": "aomori", "03": "iwakitaira", "04": "yahiko",
    "05": "maebashi", "06": "toride", "07": "utsunomiya", "08": "omiya",
    "09": "seibupark", "10": "keiokaku", "11": "tachikawa", "12": "matsudo",
    "13": "chiba", "14": "kawasaki", "15": "hiratsuka", "16": "odawara",
    "17": "ito", "18": "shizuoka", "19": "hamamatsu", "20": "toyohashi",
    "21": "nagoya", "22": "gifu", "23": "ogaki", "24": "yokkaichi",
    "25": "matsusaka", "26": "seibuen", "27": "mukomachi", "28": "wakayama",
    "29": "kishiwada", "30": "tamano", "31": "hiroshima", "32": "hofu",
    "33": "takamatsu", "34": "matsuyama", "35": "kochi", "36": "kokura",
    "37": "kurume", "38": "takeo", "39": "sasebo", "40": "beppu",
    "41": "kumamoto", "44": "ogaki", "47": "matsusaka",
    "53": "nara", "55": "wakayama", "62": "hiroshima",
    "75": "matsuyama", "81": "kokura",
}

VENUE_NAME: Dict[str, str] = {
    "01": "函館", "02": "青森", "03": "いわき平", "04": "弥彦",
    "05": "前橋", "06": "取手", "07": "宇都宮", "08": "大宮",
    "09": "西武園", "10": "京王閣", "11": "立川", "12": "松戸",
    "13": "千葉", "14": "川崎", "15": "平塚", "16": "小田原",
    "17": "伊東", "18": "静岡", "19": "浜松", "20": "豊橋",
    "21": "名古屋", "22": "岐阜", "23": "大垣", "24": "四日市",
    "25": "松阪", "26": "西武園", "27": "向日町", "28": "和歌山",
    "29": "岸和田", "30": "玉野", "31": "広島", "32": "防府",
    "33": "高松", "34": "松山", "35": "高知", "36": "小倉",
    "37": "久留米", "38": "武雄", "39": "佐世保", "40": "別府",
    "41": "熊本", "44": "大垣", "47": "松阪",
    "53": "奈良", "55": "和歌山", "62": "広島",
    "75": "松山", "81": "小倉",
}

BANK_LENGTH: Dict[str, int] = {
    "函館": 400, "青森": 400, "いわき平": 400, "弥彦": 400,
    "前橋": 335, "取手": 400, "宇都宮": 500, "大宮": 400,
    "西武園": 400, "京王閣": 400, "立川": 400, "松戸": 333,
    "千葉": 500, "川崎": 400, "平塚": 400, "小田原": 333,
    "伊東": 333, "静岡": 400, "浜松": 400, "豊橋": 400,
    "名古屋": 400, "岐阜": 400, "大垣": 400, "四日市": 400,
    "松阪": 400, "奈良": 333, "向日町": 400, "和歌山": 400,
    "岸和田": 400, "玉野": 400, "広島": 400, "防府": 333,
    "高松": 400, "松山": 400, "高知": 500, "小倉": 400,
    "久留米": 400, "武雄": 400, "佐世保": 400, "別府": 400,
    "熊本": 500,
}


class KdreamsScraper:
    """Kドリームスから競輪の出走表を取得するスクレイパー。"""

    def __init__(self, config: Optional[Dict] = None):
        self.rate_limit_sec = DEFAULT_RATE_LIMIT_SEC
        self.user_agent = DEFAULT_USER_AGENT
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})
        self._request_count = 0

    def _get(self, url: str) -> str:
        self._request_count += 1
        if self._request_count > 1:
            time.sleep(self.rate_limit_sec)
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text

    def fetch_schedule(self, date: str) -> List[Dict[str, Any]]:
        """指定日の開催一覧を取得し、各レースの出走表URLを構築する。

        Args:
            date: YYYYMMDD形式

        Returns:
            レース情報のリスト（venue_code, venue_name, grade, races等を含む）
        """
        yyyy, mm, dd = date[:4], date[4:6], date[6:8]
        url = f"https://keirin.kdreams.jp/racecard/{yyyy}/{mm}/{dd}/"
        html = self._get(url)
        soup = BeautifulSoup(html, "html.parser")

        results = []
        # 開催リンクを探す: /venue/racecard/XXYYYYMMDDNNNN/
        links = soup.find_all("a", href=True)
        seen = set()
        for a in links:
            href = a["href"]
            m = re.search(r"/(\w+)/racecard/(\d{2})(\d{8})(\d{4})/", href)
            if m:
                venue_slug = m.group(1)
                venue_code = m.group(2)
                race_date = m.group(3)
                day_code = m.group(4)
                if race_date != date:
                    continue
                key = f"{venue_code}_{race_date}_{day_code}"
                if key in seen:
                    continue
                seen.add(key)

                venue_name = VENUE_NAME.get(venue_code, venue_slug)
                results.append({
                    "venue_code": venue_code,
                    "venue_name": venue_name,
                    "venue_slug": venue_slug,
                    "date": race_date,
                    "day_code": day_code,
                    "bank_length": BANK_LENGTH.get(venue_name, 400),
                    "racecard_url": href,
                })

        return results

    def fetch_race_list(self, venue: Dict[str, Any]) -> List[Dict[str, Any]]:
        """開催の全レース一覧を取得する。

        Args:
            venue: fetch_schedule()の1要素

        Returns:
            各レースのURL・番号・ステージ情報
        """
        url = venue["racecard_url"]
        if not url.startswith("http"):
            url = "https://keirin.kdreams.jp" + url
        html = self._get(url)
        soup = BeautifulSoup(html, "html.parser")

        races = []
        links = soup.find_all("a", href=True)
        seen = set()
        for a in links:
            href = a["href"]
            m = re.search(
                r"/(\w+)/racedetail/(\d{2})(\d{8})(\d{2})(\d{4})/",
                href,
            )
            if m:
                venue_slug = m.group(1)
                venue_code = m.group(2)
                race_date = m.group(3)
                day_num = m.group(4)
                race_num_str = m.group(5)
                race_num = int(race_num_str)

                key = f"{venue_code}_{race_num}"
                if key in seen:
                    continue
                seen.add(key)

                # リンクテキストからステージ情報を取得
                text = a.get_text(strip=True)
                grade = ""
                stage = ""
                # "1RＳ級一予選" のようなテキストを解析
                stage_match = re.match(r"(\d+)R(.+)", text)
                if stage_match:
                    stage_text = stage_match.group(2)
                    if "Ｓ級" in stage_text or "S級" in stage_text:
                        grade = "S"
                    elif "Ａ級" in stage_text or "A級" in stage_text:
                        grade = "A"
                    stage = stage_text

                races.append({
                    "venue_code": venue_code,
                    "venue_name": venue.get("venue_name", ""),
                    "venue_slug": venue_slug,
                    "race_num": race_num,
                    "race_no": str(race_num),
                    "grade": grade,
                    "stage": stage,
                    "date": race_date,
                    "bank_length": venue.get("bank_length", 400),
                    "sport": "keirin",
                    "detail_url": href,
                })

        return sorted(races, key=lambda r: r["race_num"])

    def fetch_entries(self, race: Dict[str, Any]) -> List[Dict[str, Any]]:
        """個別レースの出走表（選手情報）を取得する。

        Args:
            race: fetch_race_list()の1要素

        Returns:
            選手エントリーのリスト
        """
        url = race.get("detail_url", "")
        if not url.startswith("http"):
            url = "https://keirin.kdreams.jp" + url
        html = self._get(url)
        soup = BeautifulSoup(html, "html.parser")

        # Table 1 (選手コメント付きテーブル) を探す
        # ヘッダーに「車番」「級班」「脚質」「競走得点」を含むテーブル
        entries = []
        tables = soup.find_all("table")

        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 3:
                continue

            # ヘッダー行を確認
            header_text = rows[0].get_text()
            if "車番" not in header_text or "級班" not in header_text:
                continue
            if "選手コメント" not in header_text:
                continue  # Table 1 (コメント付き) を優先

            # データ行をパース
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) < 10:
                    continue

                cell_texts = [c.get_text(strip=True) for c in cells]

                # rowspan で枠番セルが省略されると cells=11 になる
                # 12 cells: 予想/好気合/総評/枠番/車番/選手名/級班/脚質/ギヤ/得点/コメント/短評
                # 11 cells: 予想/好気合/総評/      車番/選手名/級班/脚質/ギヤ/得点/コメント/短評
                try:
                    if len(cells) >= 12:
                        idx_car, idx_name = 4, 5
                    else:
                        idx_car, idx_name = 3, 4

                    car_no = int(cell_texts[idx_car]) if cell_texts[idx_car].isdigit() else 0
                    if car_no == 0:
                        continue

                    # 選手名を抽出（"阿部 英斗福　岡/21/125" → "阿部 英斗"）
                    name_raw = cell_texts[idx_name]
                    # まず /年齢/期 を除去
                    name = re.sub(r"/\d+/\d+$", "", name_raw)
                    # 全角スペース正規化
                    name = re.sub(r"\u3000+", " ", name).strip()
                    # 末尾の県名を除去
                    # パターン1: 「福 岡」「京 都」等（漢字+半角SP+漢字）
                    name_before = name
                    name = re.sub(r"[\u4e00-\u9fff] [\u4e00-\u9fff]$", "", name).strip()
                    if name == name_before:
                        # パターン2: 「和歌山」等（スペースなし漢字2-3文字の県名）
                        name = re.sub(r"(?:北海道|和歌山|鹿児島|神奈川|三重|岡山|広島|群馬|埼玉|新潟|長野|石川|富山|福井|滋賀|愛知|奈良|香川|愛媛|徳島|高知|福岡|佐賀|長崎|熊本|大分|宮崎|沖縄)$", "", name).strip()

                    idx_grade = idx_name + 1
                    grade = cell_texts[idx_grade] if len(cell_texts) > idx_grade else ""
                    leg_type = cell_texts[idx_grade + 1] if len(cell_texts) > idx_grade + 1 else ""
                    score_str = cell_texts[idx_grade + 3] if len(cell_texts) > idx_grade + 3 else "0"
                    try:
                        score = float(score_str)
                    except ValueError:
                        score = 0.0

                    comment = cell_texts[idx_grade + 4] if len(cell_texts) > idx_grade + 4 else ""

                    entries.append({
                        "car_no": car_no,
                        "name": name,
                        "grade": grade,
                        "leg_type": leg_type,
                        "score": score,
                        "comment": comment,
                    })
                except (IndexError, ValueError):
                    continue

            if entries:
                break  # 最初に見つかったテーブルを使用

        return entries

    def fetch_all_races(self, date: str) -> List[Dict[str, Any]]:
        """指定日の全レース情報（出走表付き）を一括取得する。

        Args:
            date: YYYYMMDD形式

        Returns:
            レース情報のリスト。各レースにentriesを含む。
        """
        schedule = self.fetch_schedule(date)
        all_races = []

        for venue in schedule:
            races = self.fetch_race_list(venue)
            for race in races:
                entries = self.fetch_entries(race)
                race["entries"] = entries
                all_races.append(race)

        return all_races
