"""
月別ROI監視スクリプト
======================

output/ 配下の予想JSONから月別投資額を集計し、
data/logs/monthly_roi.json に記録する。

health_check.py から参照できる形式で出力する。

使用例:
    python scripts/roi_tracker.py
    python scripts/roi_tracker.py --month 202602
    python scripts/roi_tracker.py --show-history
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
ROI_LOG = ROOT / "data" / "logs" / "monthly_roi.json"


def scan_output_for_month(month_str: str, sport: str = "keirin") -> dict:
    """
    output/YYYYMMDD/ 配下のJSONから指定月・指定スポーツの投資額を集計する。

    Args:
        month_str: 対象月（YYYYMM形式、例: 202602）
        sport:     スポーツ種別（"keirin" または "kyotei"）。
                   デフォルト "keirin"。glob パターン "{sport}_*.json" で絞り込む。

    Returns:
        {
            "month": "202602",
            "total_investment": int,
            "total_payout": int,       # record_result() で更新
            "actual_roi": float,       # record_result() で更新（%）
            "bet_count": int,          # BUYしたレース数
            "hit_count": int,          # 的中レース数（record_result() で更新）
            "hit_rate": float,         # 的中率（%）（record_result() で更新）
            "skip_count": int,         # SKIPしたレース数
            "race_results": list,      # [{race_id, venue, race_no, bet_type, investment, payout, hit}]
            "dates_processed": list,   # 処理した日付リスト
            "last_updated": str,
        }
    """
    total_investment = 0
    bet_count = 0
    skip_count = 0
    dates_processed = []

    for date_dir in sorted(OUTPUT_DIR.iterdir()):
        if not date_dir.is_dir():
            continue
        date_str = date_dir.name
        if not date_str.startswith(month_str[:4]):  # 年チェック
            continue
        if len(date_str) == 8 and date_str[:6] != month_str:
            continue

        dates_processed.append(date_str)

        # 日付ディレクトリ内のJSONをスポーツ別に絞り込んで読む
        # glob("{sport}_*.json") でkeirin/kyotei が混在しないようにする
        for json_file in date_dir.glob(f"{sport}_*.json"):
            try:
                with open(json_file, encoding="utf-8") as f:
                    data = json.load(f)
                bet_info = data.get("bet", {})
                bet_type = bet_info.get("bet_type", "skip")
                if bet_type != "skip":
                    investment = bet_info.get("total_investment", 0)
                    total_investment += investment
                    bet_count += 1
                else:
                    skip_count += 1
            except (json.JSONDecodeError, KeyError):
                pass

    return {
        "month": month_str,
        "total_investment": total_investment,
        "total_payout": 0,
        "actual_roi": 0.0,
        "bet_count": bet_count,
        "hit_count": 0,
        "hit_rate": 0.0,
        "skip_count": skip_count,
        "race_results": [],
        "dates_processed": dates_processed,
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


def load_roi_log() -> dict:
    """monthly_roi.jsonを読み込む。存在しない場合は空辞書を返す。"""
    if ROI_LOG.exists():
        try:
            with open(ROI_LOG, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_roi_log(data: dict) -> None:
    """monthly_roi.jsonに保存する。"""
    ROI_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ROI_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_current_month(sport: str = "keirin") -> dict:
    """現在月のROI集計を更新して返す。既存のrace_results/payout情報は保持する。"""
    month_str = datetime.now().strftime("%Y%m")
    stats = scan_output_for_month(month_str, sport=sport)

    log_data = load_roi_log()
    existing = log_data.get(month_str, {})

    # 既存のpayout/hit情報を保持（scan_output_for_monthは投資額のみ集計）
    for preserve_key in ("total_payout", "hit_count", "hit_rate", "actual_roi", "race_results"):
        if preserve_key in existing:
            stats[preserve_key] = existing[preserve_key]

    # actual_roi の再計算（投資額が更新された場合）
    if stats["total_investment"] > 0 and stats.get("total_payout", 0) > 0:
        stats["actual_roi"] = round(
            stats["total_payout"] / stats["total_investment"] * 100, 1
        )

    log_data[month_str] = stats
    save_roi_log(log_data)

    return stats


def _compute_filter_stats(race_results: list, filter_passed: bool | None) -> dict:
    """race_resultsからfilter_passed別のROI統計を計算する。

    Args:
        race_results: record_resultで蓄積されたレース結果リスト
        filter_passed: True=フィルター通過レースのみ / None=全レース（unfiltered）

    Returns:
        {total_investment, total_payout, hit_count, race_count, roi}
    """
    if filter_passed is None:
        races = race_results
    else:
        races = [r for r in race_results if r.get("filter_passed", True) == filter_passed]

    total_investment = sum(r.get("investment", 0) for r in races)
    total_payout = sum(r.get("payout", 0) for r in races)
    hit_count = sum(1 for r in races if r.get("hit", False))
    race_count = len(races)
    roi = round(total_payout / total_investment * 100, 1) if total_investment > 0 else 0.0

    return {
        "total_investment": total_investment,
        "total_payout": total_payout,
        "hit_count": hit_count,
        "race_count": race_count,
        "roi": roi,
    }


def record_result(
    race_id: str,
    venue: str,
    race_no: int,
    payout: int,
    hit: bool,
    filter_passed: bool = True,
    investment: int = 0,
) -> dict:
    """
    レース結果を月次ROIログに記録する。record_bet()と対になる関数。

    output/YYYYMMDD/keirin_{venue}_{race_no}.json から投資額・bet_typeを
    自動取得する。race_idの先頭8文字がYYYYMMDD形式であること。

    Args:
        race_id:      レースID。例: "20260301_和歌山_12"
        venue:        競輪場名。例: "和歌山"
        race_no:      レース番号。例: 12
        payout:       払戻額（円）。未的中は0
        hit:          的中したか
        filter_passed: フィルター通過レースか（デフォルト: True で後方互換）
        investment:   投資額（円）。0の場合はoutput JSONから自動取得する。
                      collect_results.py から呼ぶ際は bet["total_investment"] を渡すと
                      output/ が削除された後も投資額が正確に記録される。

    Returns:
        更新後の月次集計データ
    """
    # race_idから日付・月を推定
    if len(race_id) >= 8 and race_id[:8].isdigit():
        date_str = race_id[:8]
    else:
        date_str = datetime.now().strftime("%Y%m%d")
    month_str = date_str[:6]

    # 投資額・bet_typeをoutput JSONから取得（investment未指定時のみ）
    bet_type = "unknown"
    output_json = OUTPUT_DIR / date_str / f"keirin_{venue}_{race_no}.json"
    if output_json.exists():
        try:
            with open(output_json, encoding="utf-8") as f:
                data = json.load(f)
            bet_info = data.get("bet", {})
            if investment == 0:
                investment = bet_info.get("total_investment", 0)
            bet_type = bet_info.get("bet_type", "unknown")
        except (json.JSONDecodeError, IOError):
            pass

    # 月次ログ読み込み・新フィールド初期化
    log_data = load_roi_log()
    month_data = log_data.get(month_str, {})
    month_data.setdefault("month", month_str)
    month_data.setdefault("total_investment", 0)
    month_data.setdefault("total_payout", 0)
    month_data.setdefault("actual_roi", 0.0)
    month_data.setdefault("bet_count", 0)
    month_data.setdefault("hit_count", 0)
    month_data.setdefault("hit_rate", 0.0)
    month_data.setdefault("skip_count", 0)
    month_data.setdefault("race_results", [])
    month_data.setdefault("dates_processed", [])
    month_data.setdefault("last_updated", "")
    month_data.setdefault("filtered_stats", {})
    month_data.setdefault("unfiltered_stats", {})

    # race_results へ追加（race_id重複チェック）
    race_results = month_data["race_results"]
    existing_entry = next(
        (r for r in race_results if r.get("race_id") == race_id), None
    )
    if existing_entry:
        existing_entry.update({"payout": payout, "hit": hit})
    else:
        race_results.append(
            {
                "race_id": race_id,
                "venue": venue,
                "race_no": race_no,
                "bet_type": bet_type,
                "investment": investment,
                "payout": payout,
                "hit": hit,
                "filter_passed": filter_passed,
            }
        )

    # 集計再計算
    month_data["total_payout"] = sum(r.get("payout", 0) for r in race_results)
    month_data["hit_count"] = sum(1 for r in race_results if r.get("hit", False))

    total_investment = month_data["total_investment"]
    total_payout = month_data["total_payout"]
    hit_count = month_data["hit_count"]
    bet_count = month_data["bet_count"]

    month_data["actual_roi"] = (
        round(total_payout / total_investment * 100, 1) if total_investment > 0 else 0.0
    )
    month_data["hit_rate"] = (
        round(hit_count / bet_count * 100, 1) if bet_count > 0 else 0.0
    )
    month_data["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # フィルター別ROI集計
    month_data["filtered_stats"] = _compute_filter_stats(race_results, filter_passed=True)
    month_data["unfiltered_stats"] = _compute_filter_stats(race_results, filter_passed=None)

    log_data[month_str] = month_data
    save_roi_log(log_data)

    return month_data


def check_investment_consistency(month_str: str) -> tuple:
    """
    ARCH-1対策: scan_output_for_month() の total_investment と
    race_results 積算値の整合性をチェックする。

    scan_output_for_month() は output/ の全 JSON を集計し total_investment を返す。
    record_result() は race_results の各エントリに investment を記録する。
    両者が一致しない場合、集計源の不整合が生じている。

    Args:
        month_str: 対象月（YYYYMM形式）

    Returns:
        (ok: bool, message: str)
        ok=True  → 整合（差分が全投資の10%以内）
        ok=False → 不整合（WARNING ログを出力）
    """
    log_data = load_roi_log()
    month_data = log_data.get(month_str)
    if not month_data:
        return True, f"月次データなし ({month_str})"

    scan_investment = month_data.get("total_investment", 0)
    race_results = month_data.get("race_results", [])
    records_investment = sum(r.get("investment", 0) for r in race_results)

    # race_results が空の場合は整合チェック不能（未記録状態）
    if not race_results:
        return True, f"race_results 未記録 ({month_str}): scan={scan_investment:,}円"

    diff = abs(scan_investment - records_investment)
    # 差分が scan 投資の 10% 以内なら OK（丸め誤差・タイミング差を許容）
    threshold = max(scan_investment * 0.1, 100)  # 最低100円の許容
    ok = diff <= threshold

    message = (
        f"ROI整合性 ({month_str}): "
        f"scan={scan_investment:,}円 / records={records_investment:,}円 "
        f"/ 差分={diff:,}円"
    )
    if not ok:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[ARCH-1] %s — 投資額不整合。output/削除またはrecord_result未呼び出しの可能性",
            message,
        )
        return False, f"⚠ 投資額不整合 {message}"
    return True, f"✅ {message}"


def check_roi_alert(threshold_ratio: float = 0.5) -> tuple:
    """
    今月の賭け割合が閾値を下回っていたらアラートを返す。

    Args:
        threshold_ratio: BET/(BET+SKIP)の最低比率

    Returns:
        (ok: bool, message: str)
    """
    log_data = load_roi_log()
    month_str = datetime.now().strftime("%Y%m")
    stats = log_data.get(month_str, {})

    if not stats:
        return True, f"今月({month_str})のROIデータなし"

    total = stats.get("bet_count", 0) + stats.get("skip_count", 0)
    if total == 0:
        return True, f"今月({month_str})のレース処理なし"

    bet_ratio = stats["bet_count"] / total
    investment = stats["total_investment"]

    # 払戻・的中情報があれば追加表示
    payout_info = ""
    if stats.get("total_payout", 0) > 0 or stats.get("hit_count", 0) > 0:
        payout_info = (
            f" / 払戻={stats.get('total_payout', 0):,}円"
            f" / 実ROI={stats.get('actual_roi', 0.0):.1f}%"
            f" / 的中={stats.get('hit_count', 0)}件({stats.get('hit_rate', 0.0):.1f}%)"
        )

    message = (
        f"今月({month_str}): BET={stats['bet_count']}件 / SKIP={stats['skip_count']}件 "
        f"/ 投資合計={investment:,}円 / BET率={bet_ratio:.1%}{payout_info}"
    )

    if bet_ratio < threshold_ratio:
        return False, f"⚠ BET率低下 {message}"
    return True, f"✅ {message}"


def main() -> None:
    parser = argparse.ArgumentParser(description="月別ROI監視スクリプト")
    parser.add_argument("--month", default=None, help="対象月 YYYYMM（デフォルト: 今月）")
    parser.add_argument("--scan-month", default=None, metavar="YYYYMM",
                        help="指定月を再スキャンして monthly_roi.json を更新する（--month の別名）")
    parser.add_argument("--sport", default="keirin", choices=["keirin", "kyotei"],
                        help="集計対象スポーツ（デフォルト: keirin）")
    parser.add_argument("--show-history", action="store_true", help="全月の履歴を表示")
    parser.add_argument("--check-alert", action="store_true", help="アラートチェック")
    args = parser.parse_args()

    if args.show_history:
        log_data = load_roi_log()
        if not log_data:
            print("履歴なし")
            return
        for month, stats in sorted(log_data.items()):
            total = stats.get("bet_count", 0) + stats.get("skip_count", 0)
            bet_ratio = stats["bet_count"] / total if total > 0 else 0
            payout_info = ""
            if stats.get("total_payout", 0) > 0 or stats.get("hit_count", 0) > 0:
                payout_info = (
                    f" 払戻={stats.get('total_payout', 0):,}円"
                    f" 実ROI={stats.get('actual_roi', 0.0):.1f}%"
                    f" 的中={stats.get('hit_count', 0)}件({stats.get('hit_rate', 0.0):.1f}%)"
                )
            print(
                f"{month}: BET={stats['bet_count']}件 SKIP={stats['skip_count']}件 "
                f"投資={stats['total_investment']:,}円 BET率={bet_ratio:.1%}{payout_info}"
            )
        return

    if args.check_alert:
        ok, message = check_roi_alert()
        print(message)
        sys.exit(0 if ok else 1)

    # --scan-month は --month の別名（cron から使いやすいように）
    month_str = args.scan_month or args.month or datetime.now().strftime("%Y%m")
    sport = args.sport
    stats = scan_output_for_month(month_str, sport=sport)

    log_data = load_roi_log()
    existing = log_data.get(month_str, {})

    # 既存のpayout/hit情報を保持
    for preserve_key in ("total_payout", "hit_count", "hit_rate", "actual_roi", "race_results"):
        if preserve_key in existing:
            stats[preserve_key] = existing[preserve_key]

    log_data[month_str] = stats
    save_roi_log(log_data)

    print(f"月別ROI集計 ({month_str}, sport={sport}):")
    print(f"  BET件数: {stats['bet_count']}件")
    print(f"  SKIP件数: {stats['skip_count']}件")
    print(f"  投資合計: {stats['total_investment']:,}円")
    if stats.get("total_payout", 0) > 0 or stats.get("hit_count", 0) > 0:
        print(f"  払戻合計: {stats.get('total_payout', 0):,}円")
        print(f"  実ROI:    {stats.get('actual_roi', 0.0):.1f}%")
        print(f"  的中件数: {stats.get('hit_count', 0)}件")
        print(f"  的中率:   {stats.get('hit_rate', 0.0):.1f}%")
    print(f"  処理日数: {len(stats['dates_processed'])}日")
    print(f"  保存先: {ROI_LOG}")


if __name__ == "__main__":
    main()
