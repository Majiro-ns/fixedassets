"""
keirin レース結果収集スクリプト
================================

指定日の全レース結果（払戻金）を kdreams.jp から収集し、
output/ 配下の予測と突合して的中判定を行う。

URL構造:
  結果一覧: https://keirin.kdreams.jp/raceresult/{YYYY}/{MM}/{DD}/
  会場結果: https://keirin.kdreams.jp/{venue_slug}/raceresult/{venue_code}{date}{day_num}/
  レース結果: https://keirin.kdreams.jp/{venue_slug}/racedetail/{venue_code}{date}{day_num}{race_no:04d}/?pageType=showResult

使用例:
    python scripts/collect_results.py --date 20260228
    python scripts/collect_results.py --date 20260228 --dry-run
    python scripts/collect_results.py --date 20260228 --no-roi-update
"""

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
OUTPUT_DIR = ROOT / "output"
RESULTS_DIR = ROOT / "data" / "results"
VENUE_MAP_PATH = ROOT / "config" / "venue_map.yaml"


def load_venue_slug_map() -> Dict[str, str]:
    """config/venue_map.yaml から英語slug→日本語venue_name マッピングを読み込む。

    venue_code がVENUE_NAMEに存在しない場合（BUG-3）の2次ルックアップに使用。

    Returns:
        {"kishiwada": "岸和田", "komatsushima": "小松島", ...} の辞書
    """
    try:
        with open(VENUE_MAP_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("slug_to_name", {})
    except (FileNotFoundError, yaml.YAMLError) as e:
        logger.warning("venue_map.yaml の読み込み失敗（BUG-3対策無効化）: %s", e)
        return {}


# モジュール起動時にロード（テスト時もモック可能）
_VENUE_SLUG_MAP: Dict[str, str] = {}

RATE_LIMIT_SEC = 1.5  # レート制限: 1.5秒間隔
USER_AGENT = "PredictionPipeline/1.0 (research; DoS-safe)"
BASE_URL = "https://keirin.kdreams.jp"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _get_venue_slug_map() -> Dict[str, str]:
    """_VENUE_SLUG_MAP を遅延初期化して返す（テスト時にモック置換可能）。"""
    global _VENUE_SLUG_MAP
    if not _VENUE_SLUG_MAP:
        _VENUE_SLUG_MAP = load_venue_slug_map()
    return _VENUE_SLUG_MAP


def resolve_venue_name(venue_code: str, venue_slug: str, venue_name_map: Dict[str, str]) -> str:
    """venue_codeまたはvenue_slugから日本語venue_nameを解決する（BUG-3対策）。

    ルックアップ優先順位:
      1. venue_code → VENUE_NAME_MAP（既存ロジック）
      2. venue_slug → _VENUE_SLUG_MAP（BUG-3新規追加）
      3. venue_slug をそのまま使用（最終フォールバック）

    Args:
        venue_code: kdreamsのvenue_code（2桁文字列）
        venue_slug: kdreamsのvenue_slug（英語、例: "kishiwada"）
        venue_name_map: VENUE_NAME辞書（venue_code→日本語名）

    Returns:
        日本語venue_name（例: "岸和田"）または英語slug（フォールバック）
    """
    # 1次ルックアップ: venue_code
    name = venue_name_map.get(venue_code)
    if name:
        return name
    # 2次ルックアップ: slug→日本語名（BUG-3対策）
    slug_map = _get_venue_slug_map()
    name = slug_map.get(venue_slug)
    if name:
        logger.debug(
            "BUG-3フォールバック: venue_code=%s slug=%s → %s", venue_code, venue_slug, name
        )
        return name
    # 最終フォールバック: 英語slugをそのまま使用
    return venue_slug


# ─── スクレイパー ────────────────────────────────────────────────────────────

class KdreamsResultScraper:
    """kdreams.jp からレース結果を取得するスクレイパー。"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._request_count = 0

    def _get(self, url: str) -> str:
        """GETリクエスト（レート制限付き）。"""
        if self._request_count > 0:
            time.sleep(RATE_LIMIT_SEC)
        self._request_count += 1
        logger.debug("GET %s", url)
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text

    def fetch_result_venues(self, date: str) -> List[Dict[str, str]]:
        """指定日の開催会場と結果URLを取得。

        Args:
            date: YYYYMMDD形式

        Returns:
            会場情報リスト（venue_slug, venue_code, venue_name, day_num, result_url）
        """
        yyyy, mm, dd = date[:4], date[4:6], date[6:8]
        url = f"{BASE_URL}/raceresult/{yyyy}/{mm}/{dd}/"
        html = self._get(url)
        soup = BeautifulSoup(html, "html.parser")

        from src.kdreams_scraper import VENUE_NAME as VENUE_NAME_MAP

        venues = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # raceresult URL: /{slug}/raceresult/{venue_code2}{date8}{day_num2}{suffix2}/
            m = re.search(r"/(\w+)/raceresult/(\d{2})(\d{8})(\d{2})\d{2}/", href)
            if not m:
                continue
            if m.group(3) != date:
                continue
            venue_slug = m.group(1)
            venue_code = m.group(2)
            day_num = m.group(4)  # 2桁（例: "01"）
            key = f"{venue_code}_{day_num}"
            if key in seen:
                continue
            seen.add(key)
            venue_name = resolve_venue_name(venue_code, venue_slug, VENUE_NAME_MAP)
            result_url = href if href.startswith("http") else BASE_URL + href
            venues.append({
                "venue_slug": venue_slug,
                "venue_code": venue_code,
                "venue_name": venue_name,
                "day_num": day_num,
                "date": date,
                "result_url": result_url,
            })
        logger.info("開催会場: %d会場", len(venues))
        return venues

    def fetch_race_result_links(self, venue: Dict[str, str]) -> List[Tuple[int, str]]:
        """会場結果ページから各レースの結果URLを取得。

        Returns:
            [(race_no, url), ...]のリスト（race_no昇順）
        """
        html = self._get(venue["result_url"])
        soup = BeautifulSoup(html, "html.parser")

        races = []
        seen: set = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # racedetail URL: /{slug}/racedetail/{venue_code2}{date8}{day_num2}{race_no4}/
            m = re.search(
                r"/(\w+)/racedetail/(\d{2})(\d{8})(\d{2})(\d{4})/",
                href,
            )
            if not m:
                continue
            if m.group(3) != venue["date"] or m.group(4) != venue["day_num"]:
                continue
            race_no = int(m.group(5))
            if race_no in seen:
                continue
            seen.add(race_no)
            full_url = href if href.startswith("http") else BASE_URL + href
            if "pageType=showResult" not in full_url:
                separator = "&" if "?" in full_url else "?"
                full_url += f"{separator}pageType=showResult"
            races.append((race_no, full_url))
        return sorted(races)

    def parse_race_result(self, html: str) -> Dict[str, Any]:
        """レース結果ページから着順と払戻金をパース。

        Returns:
            {
                "top3": [int, int, int],  # 1着・2着・3着の車番
                "payouts": {
                    "trio": [{"numbers": [...], "payout": int}],     # 3連複
                    "trifecta": [{"numbers": [...], "payout": int}], # 3連単
                    "quinella": [{"numbers": [...], "payout": int}], # 2車連複
                    "exacta": [{"numbers": [...], "payout": int}],   # 2車連単
                    "wide": [{"numbers": [...], "payout": int}],     # ワイド
                }
            }
        """
        soup = BeautifulSoup(html, "html.parser")

        # ── 着順テーブル (class="result_table") ──
        finish_order: List[Tuple[int, int]] = []
        result_table = soup.find("table", class_="result_table")
        if result_table:
            rows = result_table.find_all("tr")
            for row in rows[1:]:  # ヘッダー行をスキップ
                cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cells) >= 3 and cells[1].isdigit() and cells[2].isdigit():
                    order = int(cells[1])
                    car_no = int(cells[2])
                    finish_order.append((order, car_no))
        finish_order.sort(key=lambda x: x[0])
        top3 = [car_no for _, car_no in finish_order[:3]]

        # ── 払戻テーブル (class="refund_table") ──
        payouts: Dict[str, List[Dict[str, Any]]] = {}
        refund_table = soup.find("table", class_="refund_table")
        if refund_table:
            # 払戻テーブルのthからbet_typeを特定
            # 各th（2枠連・2車連・3連勝・ワイド）に対応するtdを取得
            _parse_refund_table(refund_table, payouts)

        return {"top3": top3, "payouts": payouts}


def _parse_refund_table(
    refund_table: Any, payouts: Dict[str, List[Dict[str, Any]]]
) -> None:
    """refund_tableを解析して払戻情報をpayoutsに格納する。

    bet_typeはdt内の数字パターンで判定:
    - A=B=C (3数字, =) → 3連複
    - A-B-C (3数字, -) → 3連単
    - A=B   (2数字, =) → 2車連複 or ワイド（dl位置で判断）
    - A-B   (2数字, -) → 2車連単
    """
    # 全dl要素を順番通りに収集
    all_dls = refund_table.find_all("dl", class_="cf")

    for dl in all_dls:
        dt = dl.find("dt")
        if not dt:
            continue
        dt_text = dt.get_text(strip=True)
        if not dt_text or dt_text in ("未発売", "—", "-"):
            continue

        # 払戻金額パース（"2,830円(10)" → 2830）
        dd = dl.find("dd")
        payout_amount = 0
        if dd:
            dd_text = dd.get_text(strip=True)
            m = re.search(r"([\d,]+)円", dd_text)
            if m:
                payout_amount = int(m.group(1).replace(",", ""))

        # 車番組合せ判定
        nums_eq = _split_nums(dt_text, "=")
        nums_dash = _split_nums(dt_text, "-")

        if len(nums_eq) == 3:
            payouts.setdefault("trio", []).append(
                {"numbers": nums_eq, "payout": payout_amount}
            )
        elif len(nums_dash) == 3:
            payouts.setdefault("trifecta", []).append(
                {"numbers": nums_dash, "payout": payout_amount}
            )
        elif len(nums_eq) == 2:
            # ワイド と 2車連複 の区別はdlの位置から判断する
            # 簡略化: 同じ払戻テーブルでdl数が3以上ならワイドと推定
            # 実際はth "ワイド" の下にあるかで判断するが、
            # ここでは後続処理で利用しないためまとめて格納
            payouts.setdefault("quinella_or_wide", []).append(
                {"numbers": nums_eq, "payout": payout_amount}
            )
        elif len(nums_dash) == 2:
            payouts.setdefault("exacta", []).append(
                {"numbers": nums_dash, "payout": payout_amount}
            )


def _split_nums(text: str, sep: str) -> List[int]:
    """テキストをsepで分割し、全要素が整数ならintリストを返す。"""
    parts = text.split(sep)
    try:
        return [int(p.strip()) for p in parts]
    except ValueError:
        return []


# ─── 予測突合・的中判定 ───────────────────────────────────────────────────────

def load_predictions_for_date(date: str) -> Dict[str, Dict[str, Any]]:
    """output/YYYYMMDD/ 配下の予測JSONを全て読み込む。

    Returns:
        {"{venue_name}_{race_no}": prediction_data} の辞書
    """
    date_dir = OUTPUT_DIR / date
    predictions: Dict[str, Dict[str, Any]] = {}
    if not date_dir.exists():
        logger.warning("予測ディレクトリなし: %s", date_dir)
        return predictions

    for json_file in date_dir.glob("keirin_*.json"):
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
            race_info = data.get("race_info", {})
            venue_name = race_info.get("venue_name", "")
            race_no_str = race_info.get("race_no", "")
            if venue_name and race_no_str:
                key = f"{venue_name}_{race_no_str}"
                predictions[key] = data
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("予測JSONの読み込み失敗: %s - %s", json_file, e)
    logger.info("予測ファイル: %d件", len(predictions))
    return predictions


def check_hit(
    bet: Dict[str, Any], race_result: Dict[str, Any]
) -> Tuple[bool, int]:
    """予測と実際の結果を照合して的中判定を行う。

    Args:
        bet: 予測JSONのbetフィールド
        race_result: parse_race_result()の戻り値

    Returns:
        (hit, payout_amount)
        - hit: 的中したか
        - payout_amount: 払戻額（円）。未的中は0
    """
    top3 = race_result.get("top3", [])
    payouts = race_result.get("payouts", {})

    if len(top3) < 3:
        return False, 0

    bet_type = bet.get("bet_type", "")
    combinations = bet.get("combinations", [])
    unit_bet = bet.get("unit_bet", 100)

    # 的中組合せを探す
    if "3連複" in bet_type or "trio" in bet_type.lower():
        trio_result = sorted(top3[:3])
        trio_payouts = payouts.get("trio", [])
        for combo in combinations:
            combo_sorted = sorted(combo)
            if combo_sorted == trio_result:
                # 払戻金額を取得
                for tp in trio_payouts:
                    if sorted(tp["numbers"]) == trio_result:
                        payout = (tp["payout"] * unit_bet) // 100
                        return True, payout
                # 払戻データがない場合でも的中フラグ
                return True, 0

    elif "3連単" in bet_type or "trifecta" in bet_type.lower():
        trifecta_result = list(top3[:3])
        trifecta_payouts = payouts.get("trifecta", [])
        for combo in combinations:
            if list(combo) == trifecta_result:
                for tp in trifecta_payouts:
                    if tp["numbers"] == trifecta_result:
                        payout = (tp["payout"] * unit_bet) // 100
                        return True, payout
                return True, 0

    elif "2車連" in bet_type or "2連" in bet_type:
        quinella_result = sorted(top3[:2])
        quinella_payouts = payouts.get("quinella_or_wide", [])
        for combo in combinations:
            if sorted(combo) == quinella_result:
                for qp in quinella_payouts:
                    if sorted(qp["numbers"]) == quinella_result:
                        payout = (qp["payout"] * unit_bet) // 100
                        return True, payout
                return True, 0

    return False, 0


# ─── メイン処理 ──────────────────────────────────────────────────────────────

def collect_results(date: str, dry_run: bool = False, no_roi_update: bool = False) -> Dict[str, Any]:
    """指定日のレース結果を収集して突合する。

    Args:
        date: YYYYMMDD形式
        dry_run: Trueの場合、ファイル保存・ROI更新をスキップ
        no_roi_update: Trueの場合、roi_tracker更新をスキップ

    Returns:
        出力JSONデータ
    """
    scraper = KdreamsResultScraper()
    predictions = load_predictions_for_date(date)

    if not predictions:
        logger.warning("予測データなし（date=%s）。スクレイピングのみ実施。", date)

    # 会場一覧を取得
    venues = scraper.fetch_result_venues(date)
    if not venues:
        logger.error("開催会場が見つかりません（date=%s）。", date)
        return {}

    output_races = []

    for venue in venues:
        venue_name = venue["venue_name"]
        logger.info("[%s] 結果取得中...", venue_name)

        # 各レースのURLを取得
        try:
            race_links = scraper.fetch_race_result_links(venue)
        except requests.RequestException as e:
            logger.error("[%s] レースリスト取得失敗: %s", venue_name, e)
            continue

        for race_no, race_url in race_links:
            pred_key = f"{venue_name}_{race_no}"
            pred_data = predictions.get(pred_key)

            # 予測がないレースもスクレイピング（全結果を記録）
            try:
                html = scraper._get(race_url)
                result = scraper.parse_race_result(html)
            except requests.RequestException as e:
                logger.warning("[%s R%d] 結果取得失敗: %s", venue_name, race_no, e)
                continue

            top3 = result.get("top3", [])
            payouts = result.get("payouts", {})

            # 払戻金サマリー
            trio_payout = 0
            trio_numbers: List[int] = []
            for tp in payouts.get("trio", []):
                if sorted(tp["numbers"]) == sorted(top3[:3]):
                    trio_payout = tp["payout"]
                    trio_numbers = tp["numbers"]

            trifecta_payout = 0
            trifecta_numbers: List[int] = []
            for tp in payouts.get("trifecta", []):
                if tp["numbers"] == top3[:3]:
                    trifecta_payout = tp["payout"]
                    trifecta_numbers = tp["numbers"]

            # 予測突合
            our_prediction = None
            hit = False
            our_payout = 0

            if pred_data:
                bet = pred_data.get("bet", {})
                our_prediction = {
                    "axis": bet.get("axis"),
                    "partners": bet.get("partners", []),
                    "bet_type": bet.get("bet_type", ""),
                    "combinations": bet.get("combinations", []),
                    "investment": bet.get("total_investment", 0),
                }
                hit, our_payout = check_hit(bet, result)
                filter_passed = pred_data.get("filter_passed", True)  # デフォルト: True（後方互換）

                if hit:
                    logger.info(
                        "[%s R%d] ✅ 的中！ filter_passed=%s 払戻=%d円",
                        venue_name, race_no, filter_passed, our_payout,
                    )
                else:
                    logger.info(
                        "[%s R%d] ❌ 外れ filter_passed=%s（top3=%s）",
                        venue_name, race_no, filter_passed, top3,
                    )

                # ROI tracker 更新
                if not dry_run and not no_roi_update:
                    try:
                        import roi_tracker as _roi_tracker
                        race_id = f"{date}_{venue_name}_{race_no}"
                        _roi_tracker.record_result(
                            race_id=race_id,
                            venue=venue_name,
                            race_no=race_no,
                            payout=our_payout,
                            hit=hit,
                            filter_passed=filter_passed,
                            investment=our_prediction["investment"],
                        )
                        logger.info("[%s R%d] ROI更新完了", venue_name, race_no)
                    except Exception as e:
                        logger.warning("[%s R%d] ROI更新失敗: %s", venue_name, race_no, e)
            else:
                logger.debug("[%s R%d] 予測なし（top3=%s）", venue_name, race_no, top3)

            race_entry: Dict[str, Any] = {
                "venue": venue_name,
                "race_no": race_no,
                "trifecta_result": top3,
                "trifecta_payout": trifecta_payout,
                "trio_result": sorted(top3[:3]) if top3 else [],
                "trio_payout": trio_payout,
            }
            if our_prediction is not None:
                race_entry["our_prediction"] = our_prediction
                race_entry["hit"] = hit
                race_entry["payout"] = our_payout

            output_races.append(race_entry)

    output_data: Dict[str, Any] = {
        "date": date,
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "races": output_races,
    }

    # 保存
    if not dry_run:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = RESULTS_DIR / f"{date}_results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        logger.info("保存完了: %s", out_path)
    else:
        logger.info("[dry-run] 保存をスキップ。取得レース数: %d", len(output_races))

    # サマリー表示
    bet_races = [r for r in output_races if "hit" in r]
    hit_races = [r for r in bet_races if r.get("hit")]
    logger.info(
        "結果: 全%d件 / 予測あり%d件 / 的中%d件",
        len(output_races), len(bet_races), len(hit_races),
    )

    return output_data


# ─── CLI エントリーポイント ────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="keirin レース結果収集・予測突合スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python scripts/collect_results.py --date 20260228
  python scripts/collect_results.py --date 20260228 --dry-run
  python scripts/collect_results.py --date 20260228 --no-roi-update
        """,
    )
    parser.add_argument(
        "--date",
        required=True,
        help="対象日付 YYYYMMDD形式（例: 20260228）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイル保存・ROI更新をスキップ（動作確認用）",
    )
    parser.add_argument(
        "--no-roi-update",
        action="store_true",
        help="roi_tracker への反映をスキップ",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="デバッグログを表示",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 日付バリデーション
    try:
        datetime.strptime(args.date, "%Y%m%d")
    except ValueError:
        logger.error("日付形式エラー: %s（YYYYMMDD形式で指定してください）", args.date)
        return 1

    result = collect_results(
        date=args.date,
        dry_run=args.dry_run,
        no_roi_update=args.no_roi_update,
    )
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
