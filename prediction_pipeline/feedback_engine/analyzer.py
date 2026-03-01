"""
feedback_engine/analyzer.py — フィードバック分析エンジン（真AI予想システムの学習する心臓部）

predictions_log.jsonl を読み込み、週次・月次の成績を多角分析して
フィルター改善のための知見を自動抽出する。

設計書: true_ai_prediction_system_design.md セクション6「フィードバックエンジン」準拠
"""

import json
import statistics
from collections import defaultdict
from datetime import datetime, date


# ---- 定数 ------------------------------------------------------------------

TIER_ROI_TARGETS = {
    "S": 1.30,   # 130%
    "A": 1.05,   # 105%
    "B": 0.95,   # 95%
}

REVERSE_INDICATOR_THRESHOLD_N   = 10
REVERSE_INDICATOR_THRESHOLD_ROI = 0.50   # 50%

POSITIVE_INDICATOR_THRESHOLD_N   = 10
POSITIVE_INDICATOR_THRESHOLD_ROI = 1.30  # 130%

ANOMALY_MIN_HIT_RATE = 0.10   # 週次的中率10%未満で異常
VENUE_CHANGE_DELTA   = 0.30   # 場の成績が30pt超変動で異常


# ---- FeedbackAnalyzer -------------------------------------------------------

class FeedbackAnalyzer:
    """
    predictions_log.jsonl を分析し、フィルター改善のための知見を自動抽出する。

    使用方法::

        analyzer = FeedbackAnalyzer("/path/to/predictions_log.jsonl")
        result = analyzer.analyze_weekly("keirin", "2026-02-24", "2026-03-02")
        print(result["tier_boundary_check"]["recommendation"])
    """

    def __init__(self, log_path: str):
        """
        Args:
            log_path: predictions_log.jsonl のパス（JSONL形式）
        """
        self.log_path = log_path

    # ---- 公開メソッド -------------------------------------------------------

    def analyze_weekly(self, sport: str, start_date: str, end_date: str) -> dict:
        """
        週次分析を実行する。

        Args:
            sport:      対象スポーツ ("keirin", "speedboat" 等)
            start_date: 分析開始日 (YYYY-MM-DD)
            end_date:   分析終了日 (YYYY-MM-DD)

        Returns:
            分析結果辞書（period / total_predictions / overall / by_tier /
            by_venue / by_race_type / by_day_of_week / by_filter /
            by_keyword / new_reverse_indicators / new_positive_indicators /
            tier_boundary_check / anomalies）
        """
        records = self._load_records(sport, start_date, end_date)

        result = {
            "period": {"start": start_date, "end": end_date},
            "sport": sport,
            "total_predictions": len(records),
            "overall":              self._calc_overall_stats(records),
            "by_tier":              self._calc_tier_stats(records),
            "by_venue":             self._calc_venue_stats(records),
            "by_race_type":         self._calc_race_type_stats(records),
            "by_day_of_week":       self._calc_dow_stats(records),
            "by_filter":            self._calc_filter_stats(records),
            "by_keyword":           self._analyze_keywords(records),
            "new_reverse_indicators":  self._find_reverse_indicators(records),
            "new_positive_indicators": self._find_positive_indicators(records),
            "tier_boundary_check":  self._check_tier_boundaries(records),
            "anomalies":            self._detect_anomalies(records),
        }
        return result

    def analyze_monthly(self, sport: str, year_month: str) -> dict:
        """
        月次分析を実行する。

        Args:
            sport:       対象スポーツ
            year_month:  "YYYY-MM" 形式

        Returns:
            analyze_weekly() と同形式の分析結果辞書
        """
        year, month = map(int, year_month.split("-"))
        # 月初〜月末を自動計算
        start_date = f"{year:04d}-{month:02d}-01"
        if month == 12:
            end_date = f"{year:04d}-12-31"
        else:
            import calendar
            last_day = calendar.monthrange(year, month)[1]
            end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

        records = self._load_records(sport, start_date, end_date)

        result = {
            "period":    {"year_month": year_month, "start": start_date, "end": end_date},
            "sport":     sport,
            "total_predictions": len(records),
            "overall":              self._calc_overall_stats(records),
            "by_tier":              self._calc_tier_stats(records),
            "by_venue":             self._calc_venue_stats(records),
            "by_race_type":         self._calc_race_type_stats(records),
            "by_day_of_week":       self._calc_dow_stats(records),
            "by_filter":            self._calc_filter_stats(records),
            "by_keyword":           self._analyze_keywords(records),
            "new_reverse_indicators":  self._find_reverse_indicators(records),
            "new_positive_indicators": self._find_positive_indicators(records),
            "tier_boundary_check":  self._check_tier_boundaries(records),
            "anomalies":            self._detect_anomalies(records),
        }
        return result

    # ---- 内部ヘルパー: データ読み込み ----------------------------------------

    def _load_records(self, sport: str, start_date: str, end_date: str) -> list:
        """
        JSONL ログを読み込み、指定スポーツ・期間のレコードを返す。

        Args:
            sport:      フィルタリングするスポーツ名
            start_date: YYYY-MM-DD
            end_date:   YYYY-MM-DD

        Returns:
            フィルタリング済みレコードのリスト
        """
        start = date.fromisoformat(start_date)
        end   = date.fromisoformat(end_date)

        records = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # スポーツ・期間フィルタ
                    if rec.get("sport") != sport:
                        continue
                    rec_date = date.fromisoformat(rec.get("date", "1970-01-01"))
                    if not (start <= rec_date <= end):
                        continue

                    records.append(rec)
        except FileNotFoundError:
            pass  # ログ未作成時は空リストを返す

        return records

    # ---- 内部ヘルパー: 統計計算 ----------------------------------------------

    def _calc_overall_stats(self, records: list) -> dict:
        """
        全体の的中率・回収率・利益を計算する。

        Returns:
            {"n": int, "hit_rate": float, "roi": float, "profit": int}
            N が 0 の場合は全値を None とする。
        """
        n = len(records)
        if n == 0:
            return {"n": 0, "hit_rate": None, "roi": None, "profit": None}

        hits    = sum(1 for r in records if r.get("result", {}).get("hit", False))
        payouts = [r.get("result", {}).get("payout", 0) for r in records]
        total_payout = sum(payouts)

        # ROI = 払戻合計 / 投資額合計（各レコードを1000円投資と仮定）
        # ※ predictions_log.jsonl の payout は 1000円/予想 基準で記録される
        total_invest = n * 1000
        roi = total_payout / total_invest if total_invest > 0 else None
        profit = total_payout - total_invest

        return {
            "n":        n,
            "hit_rate": round(hits / n, 3),
            "roi":      round(roi, 3) if roi is not None else None,
            "profit":   profit,
        }

    def _calc_tier_stats(self, records: list) -> dict:
        """
        Tier 別（S / A / B）成績を計算する。

        Returns:
            {"S": {"n":..., "hit_rate":..., "roi":...}, "A": {...}, "B": {...}}
        """
        grouped = defaultdict(list)
        for r in records:
            tier = r.get("tier", "unknown")
            grouped[tier].append(r)

        result = {}
        for tier in ["S", "A", "B"]:
            recs = grouped.get(tier, [])
            result[tier] = self._calc_overall_stats(recs)
            result[tier].pop("profit", None)  # Tier別には profit は不要

        return result

    def _calc_venue_stats(self, records: list) -> dict:
        """
        場別成績を計算する。

        Returns:
            {"立川": {"n":..., "hit_rate":..., "roi":...}, ...}
        """
        grouped = defaultdict(list)
        for r in records:
            venue = r.get("venue", "unknown")
            grouped[venue].append(r)

        result = {}
        for venue, recs in sorted(grouped.items()):
            stats = self._calc_overall_stats(recs)
            stats.pop("profit", None)
            if stats["n"] < 5:
                stats["warning"] = f"N={stats['n']} < 5: 信頼性低"
            result[venue] = stats

        return result

    def _calc_race_type_stats(self, records: list) -> dict:
        """
        レース種別（features.race_type）成績を計算する。

        Returns:
            {"F1": {...}, "F2": {...}, "GP": {...}, ...}
        """
        grouped = defaultdict(list)
        for r in records:
            race_type = r.get("features", {}).get("race_type", "unknown")
            grouped[race_type].append(r)

        result = {}
        for rt, recs in sorted(grouped.items()):
            stats = self._calc_overall_stats(recs)
            stats.pop("profit", None)
            result[rt] = stats

        return result

    def _calc_dow_stats(self, records: list) -> dict:
        """
        曜日別（features.day_of_week）成績を計算する。

        Returns:
            {"月": {...}, "火": {...}, ..., "日": {...}}
        """
        DOW_ORDER = ["月", "火", "水", "木", "金", "土", "日"]

        grouped = defaultdict(list)
        for r in records:
            dow = r.get("features", {}).get("day_of_week", "unknown")
            grouped[dow].append(r)

        result = {}
        # 曜日順で並べる
        for dow in DOW_ORDER:
            if dow in grouped:
                stats = self._calc_overall_stats(grouped[dow])
                stats.pop("profit", None)
                result[dow] = stats

        # 不明曜日があれば末尾に追加
        for dow, recs in grouped.items():
            if dow not in DOW_ORDER:
                stats = self._calc_overall_stats(recs)
                stats.pop("profit", None)
                result[dow] = stats

        return result

    def _calc_filter_stats(self, records: list) -> dict:
        """
        フィルタータイプ別（A / B / C）成績を計算する。

        Returns:
            {"A": {...}, "B": {...}, "C": {...}}
        """
        grouped = defaultdict(list)
        for r in records:
            ftype = r.get("filter_type", "unknown")
            grouped[ftype].append(r)

        result = {}
        for ftype in ["A", "B", "C"]:
            recs = grouped.get(ftype, [])
            stats = self._calc_overall_stats(recs)
            stats.pop("profit", None)
            result[ftype] = stats

        return result

    def _analyze_keywords(self, records: list) -> dict:
        """
        CRE キーワード別成績を集計する。

        cre_keywords_matched フィールドはキーワードのリスト。
        各キーワードが出現したレコードのROI・的中率を集計する。

        Returns:
            {"keyword_name": {"n":..., "hit_rate":..., "roi":..., "warning"?:...}, ...}
        """
        grouped = defaultdict(list)
        for r in records:
            keywords = r.get("cre_keywords_matched", [])
            for kw in keywords:
                grouped[kw].append(r)

        result = {}
        for kw, recs in sorted(grouped.items()):
            stats = self._calc_overall_stats(recs)
            stats.pop("profit", None)
            if stats["n"] < REVERSE_INDICATOR_THRESHOLD_N:
                stats["warning"] = f"N={stats['n']} < {REVERSE_INDICATOR_THRESHOLD_N}: 統計的信頼性低"
            result[kw] = stats

        return result

    # ---- 内部ヘルパー: 指標発見 -----------------------------------------------

    def _find_reverse_indicators(self, records: list) -> list:
        """
        新しい逆指標パターンを自動発見する。

        条件: N >= 10 かつ ROI < 50%

        分析対象パターン:
        - CREキーワード別
        - 場×Tier の組み合わせ
        - レース種別×フィルター の組み合わせ

        Returns:
            [{"pattern": str, "n": int, "roi": float, "significance": str}, ...]
        """
        indicators = []

        # --- CREキーワード別 ---
        kw_groups = defaultdict(list)
        for r in records:
            for kw in r.get("cre_keywords_matched", []):
                kw_groups[kw].append(r)

        for kw, recs in kw_groups.items():
            stats = self._calc_overall_stats(recs)
            if (stats["n"] >= REVERSE_INDICATOR_THRESHOLD_N
                    and stats["roi"] is not None
                    and stats["roi"] < REVERSE_INDICATOR_THRESHOLD_ROI):
                significance = "high" if stats["roi"] < 0.30 else "medium"
                indicators.append({
                    "pattern":     f"keyword:{kw}",
                    "n":           stats["n"],
                    "roi":         stats["roi"],
                    "significance": significance,
                })

        # --- 場×Tier の組み合わせ ---
        vt_groups = defaultdict(list)
        for r in records:
            key = f"{r.get('venue', '?')}×{r.get('tier', '?')}"
            vt_groups[key].append(r)

        for key, recs in vt_groups.items():
            stats = self._calc_overall_stats(recs)
            if (stats["n"] >= REVERSE_INDICATOR_THRESHOLD_N
                    and stats["roi"] is not None
                    and stats["roi"] < REVERSE_INDICATOR_THRESHOLD_ROI):
                significance = "high" if stats["roi"] < 0.30 else "medium"
                indicators.append({
                    "pattern":     f"venue_tier:{key}",
                    "n":           stats["n"],
                    "roi":         stats["roi"],
                    "significance": significance,
                })

        # ROI昇順でソート（最も危険なパターンを先頭に）
        indicators.sort(key=lambda x: x["roi"])
        return indicators

    def _find_positive_indicators(self, records: list) -> list:
        """
        新しい正指標パターンを自動発見する。

        条件: N >= 10 かつ ROI > 130%

        分析対象パターン:
        - CREキーワード別
        - 場×Tier の組み合わせ
        - 曜日×フィルター の組み合わせ

        Returns:
            [{"pattern": str, "n": int, "roi": float, "significance": str}, ...]
        """
        indicators = []

        # --- CREキーワード別 ---
        kw_groups = defaultdict(list)
        for r in records:
            for kw in r.get("cre_keywords_matched", []):
                kw_groups[kw].append(r)

        for kw, recs in kw_groups.items():
            stats = self._calc_overall_stats(recs)
            if (stats["n"] >= POSITIVE_INDICATOR_THRESHOLD_N
                    and stats["roi"] is not None
                    and stats["roi"] > POSITIVE_INDICATOR_THRESHOLD_ROI):
                significance = "high" if stats["roi"] > 1.80 else "medium"
                indicators.append({
                    "pattern":     f"keyword:{kw}",
                    "n":           stats["n"],
                    "roi":         stats["roi"],
                    "significance": significance,
                })

        # --- 場×Tier の組み合わせ ---
        vt_groups = defaultdict(list)
        for r in records:
            key = f"{r.get('venue', '?')}×{r.get('tier', '?')}"
            vt_groups[key].append(r)

        for key, recs in vt_groups.items():
            stats = self._calc_overall_stats(recs)
            if (stats["n"] >= POSITIVE_INDICATOR_THRESHOLD_N
                    and stats["roi"] is not None
                    and stats["roi"] > POSITIVE_INDICATOR_THRESHOLD_ROI):
                significance = "high" if stats["roi"] > 1.80 else "medium"
                indicators.append({
                    "pattern":     f"venue_tier:{key}",
                    "n":           stats["n"],
                    "roi":         stats["roi"],
                    "significance": significance,
                })

        # ROI降順でソート（最も有望なパターンを先頭に）
        indicators.sort(key=lambda x: x["roi"], reverse=True)
        return indicators

    def _check_tier_boundaries(self, records: list) -> dict:
        """
        Tier 間の ROI 差が目標値を満たしているかチェックする。

        目標:
        - S Tier: ROI > 130%
        - A Tier: ROI > 105%
        - B Tier: ROI > 95%

        Returns:
            {
                "s_roi": float, "s_ok": bool,
                "a_roi": float, "a_ok": bool,
                "b_roi": float, "b_ok": bool,
                "recommendation": str
            }
        """
        tier_stats = self._calc_tier_stats(records)

        def _ok(tier: str) -> tuple:
            """(roi_value_or_none, is_ok)"""
            roi = tier_stats.get(tier, {}).get("roi")
            if roi is None:
                return None, None  # データ不足
            return roi, roi >= TIER_ROI_TARGETS[tier]

        s_roi, s_ok = _ok("S")
        a_roi, a_ok = _ok("A")
        b_roi, b_ok = _ok("B")

        # 推奨アクション生成
        issues = []
        if s_ok is False:
            issues.append(f"S評価のROI {s_roi:.0%} が目標130%未満。S基準の引き上げを推奨")
        if a_ok is False:
            issues.append(f"A評価のROI {a_roi:.0%} が目標105%未満。A基準の見直しを推奨")
        if b_ok is False:
            issues.append(f"B評価のROI {b_roi:.0%} が目標95%未満。SKIP閾値の引き上げを推奨")

        if not issues:
            recommendation = "全Tier目標ROIを達成。現行フィルターを維持"
        else:
            recommendation = " / ".join(issues)

        return {
            "s_roi":          s_roi,
            "s_ok":           s_ok,
            "a_roi":          a_roi,
            "a_ok":           a_ok,
            "b_roi":          b_roi,
            "b_ok":           b_ok,
            "recommendation": recommendation,
        }

    def _detect_anomalies(self, records: list) -> list:
        """
        異常値を検出する。

        検出条件:
        1. 週次的中率が 10% 未満
        2. 特定場の急激な成績変動（直近 N と全体 N で ROI 差 > 30pt）
        3. 逆指標の新規出現（ROI < 50% のパターン）

        Returns:
            [{"type": str, "detail": str, "severity": str}, ...]
        """
        anomalies = []

        if not records:
            return anomalies

        # --- 1. 週次的中率チェック ---
        overall = self._calc_overall_stats(records)
        if overall["hit_rate"] is not None and overall["hit_rate"] < ANOMALY_MIN_HIT_RATE:
            anomalies.append({
                "type":     "low_hit_rate",
                "detail":   f"週次的中率 {overall['hit_rate']:.1%} が閾値 {ANOMALY_MIN_HIT_RATE:.0%} を下回っている",
                "severity": "high",
            })

        # --- 2. 場別の急激な成績変動 ---
        venue_groups = defaultdict(list)
        for r in records:
            venue_groups[r.get("venue", "unknown")].append(r)

        for venue, v_records in venue_groups.items():
            if len(v_records) < 5:
                continue  # データ不足
            v_stats = self._calc_overall_stats(v_records)
            if overall["roi"] is None or v_stats["roi"] is None:
                continue
            delta = abs(v_stats["roi"] - overall["roi"])
            if delta > VENUE_CHANGE_DELTA:
                direction = "高い" if v_stats["roi"] > overall["roi"] else "低い"
                anomalies.append({
                    "type":     "venue_performance_shift",
                    "detail":   (f"場 [{venue}] のROI {v_stats['roi']:.0%} が全体平均 "
                                 f"{overall['roi']:.0%} より {delta:.0%} {direction}（急激な変動）"),
                    "severity": "medium",
                })

        # --- 3. 逆指標の新規出現 ---
        reverse = self._find_reverse_indicators(records)
        for ind in reverse:
            if ind["significance"] == "high":
                anomalies.append({
                    "type":     "new_reverse_indicator",
                    "detail":   f"逆指標検出: {ind['pattern']} / N={ind['n']} / ROI={ind['roi']:.0%}",
                    "severity": "high",
                })

        return anomalies


# ---- __main__ テスト --------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    import os

    print("=" * 60)
    print("FeedbackAnalyzer テスト実行")
    print("=" * 60)

    # --- モックデータ生成（23件） ---
    MOCK_RECORDS = [
        # Tier S: 8件（高的中・高ROI）
        {"sport": "keirin", "date": "2026-02-24", "venue": "立川", "race_number": 9,
         "tier": "S", "filter_type": "A",
         "result": {"hit": True,  "payout": 1850, "roi": 1.85},
         "features": {"class": "A", "race_type": "F1", "bank_length": "500", "day_of_week": "月"},
         "cre_keywords_matched": ["先行有利", "連携実績"]},
        {"sport": "keirin", "date": "2026-02-24", "venue": "立川", "race_number": 11,
         "tier": "S", "filter_type": "A",
         "result": {"hit": True,  "payout": 2100, "roi": 2.10},
         "features": {"class": "A", "race_type": "F1", "bank_length": "500", "day_of_week": "月"},
         "cre_keywords_matched": ["先行有利"]},
        {"sport": "keirin", "date": "2026-02-25", "venue": "松戸", "race_number": 8,
         "tier": "S", "filter_type": "A",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "SS", "race_type": "GP", "bank_length": "400", "day_of_week": "火"},
         "cre_keywords_matched": ["先行有利", "追い込み警戒"]},
        {"sport": "keirin", "date": "2026-02-25", "venue": "松戸", "race_number": 10,
         "tier": "S", "filter_type": "B",
         "result": {"hit": True,  "payout": 1620, "roi": 1.62},
         "features": {"class": "A", "race_type": "F1", "bank_length": "400", "day_of_week": "火"},
         "cre_keywords_matched": ["連携実績"]},
        {"sport": "keirin", "date": "2026-02-26", "venue": "立川", "race_number": 7,
         "tier": "S", "filter_type": "A",
         "result": {"hit": True,  "payout": 3200, "roi": 3.20},
         "features": {"class": "A", "race_type": "F2", "bank_length": "500", "day_of_week": "水"},
         "cre_keywords_matched": ["先行有利"]},
        {"sport": "keirin", "date": "2026-02-27", "venue": "立川", "race_number": 9,
         "tier": "S", "filter_type": "A",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "SS", "race_type": "GP", "bank_length": "500", "day_of_week": "木"},
         "cre_keywords_matched": ["連携実績", "追い込み警戒"]},
        {"sport": "keirin", "date": "2026-02-28", "venue": "松戸", "race_number": 8,
         "tier": "S", "filter_type": "A",
         "result": {"hit": True,  "payout": 1900, "roi": 1.90},
         "features": {"class": "A", "race_type": "F1", "bank_length": "400", "day_of_week": "金"},
         "cre_keywords_matched": ["先行有利"]},
        {"sport": "keirin", "date": "2026-03-01", "venue": "立川", "race_number": 9,
         "tier": "S", "filter_type": "A",
         "result": {"hit": True,  "payout": 1450, "roi": 1.45},
         "features": {"class": "A", "race_type": "F1", "bank_length": "500", "day_of_week": "土"},
         "cre_keywords_matched": ["先行有利", "連携実績"]},

        # Tier A: 9件（中程度）
        {"sport": "keirin", "date": "2026-02-24", "venue": "玉野", "race_number": 6,
         "tier": "A", "filter_type": "B",
         "result": {"hit": True,  "payout": 980,  "roi": 0.98},
         "features": {"class": "A", "race_type": "F1", "bank_length": "333", "day_of_week": "月"},
         "cre_keywords_matched": ["追い込み警戒"]},
        {"sport": "keirin", "date": "2026-02-24", "venue": "玉野", "race_number": 8,
         "tier": "A", "filter_type": "B",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "B", "race_type": "F2", "bank_length": "333", "day_of_week": "月"},
         "cre_keywords_matched": []},
        {"sport": "keirin", "date": "2026-02-25", "venue": "玉野", "race_number": 5,
         "tier": "A", "filter_type": "B",
         "result": {"hit": True,  "payout": 1200, "roi": 1.20},
         "features": {"class": "A", "race_type": "F1", "bank_length": "333", "day_of_week": "火"},
         "cre_keywords_matched": ["追い込み警戒"]},
        {"sport": "keirin", "date": "2026-02-26", "venue": "松戸", "race_number": 6,
         "tier": "A", "filter_type": "B",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "A", "race_type": "F1", "bank_length": "400", "day_of_week": "水"},
         "cre_keywords_matched": ["先行有利"]},
        {"sport": "keirin", "date": "2026-02-27", "venue": "玉野", "race_number": 7,
         "tier": "A", "filter_type": "C",
         "result": {"hit": True,  "payout": 2100, "roi": 2.10},
         "features": {"class": "B", "race_type": "F2", "bank_length": "333", "day_of_week": "木"},
         "cre_keywords_matched": ["追い込み警戒"]},
        {"sport": "keirin", "date": "2026-02-28", "venue": "玉野", "race_number": 8,
         "tier": "A", "filter_type": "B",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "A", "race_type": "F1", "bank_length": "333", "day_of_week": "金"},
         "cre_keywords_matched": []},
        {"sport": "keirin", "date": "2026-03-01", "venue": "玉野", "race_number": 5,
         "tier": "A", "filter_type": "B",
         "result": {"hit": True,  "payout": 880,  "roi": 0.88},
         "features": {"class": "B", "race_type": "F2", "bank_length": "333", "day_of_week": "土"},
         "cre_keywords_matched": []},
        {"sport": "keirin", "date": "2026-03-02", "venue": "松戸", "race_number": 7,
         "tier": "A", "filter_type": "B",
         "result": {"hit": True,  "payout": 1100, "roi": 1.10},
         "features": {"class": "A", "race_type": "F1", "bank_length": "400", "day_of_week": "日"},
         "cre_keywords_matched": ["先行有利"]},
        {"sport": "keirin", "date": "2026-03-02", "venue": "玉野", "race_number": 9,
         "tier": "A", "filter_type": "C",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "B", "race_type": "F2", "bank_length": "333", "day_of_week": "日"},
         "cre_keywords_matched": []},

        # Tier B: 6件（低ROI傾向）
        {"sport": "keirin", "date": "2026-02-24", "venue": "松戸", "race_number": 4,
         "tier": "B", "filter_type": "C",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "B", "race_type": "F2", "bank_length": "400", "day_of_week": "月"},
         "cre_keywords_matched": ["逆境走法"]},
        {"sport": "keirin", "date": "2026-02-25", "venue": "松戸", "race_number": 5,
         "tier": "B", "filter_type": "C",
         "result": {"hit": True,  "payout": 650,  "roi": 0.65},
         "features": {"class": "B", "race_type": "F2", "bank_length": "400", "day_of_week": "火"},
         "cre_keywords_matched": ["逆境走法"]},
        {"sport": "keirin", "date": "2026-02-26", "venue": "玉野", "race_number": 4,
         "tier": "B", "filter_type": "C",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "B", "race_type": "F2", "bank_length": "333", "day_of_week": "水"},
         "cre_keywords_matched": ["逆境走法"]},
        {"sport": "keirin", "date": "2026-02-27", "venue": "松戸", "race_number": 3,
         "tier": "B", "filter_type": "C",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "B", "race_type": "F2", "bank_length": "400", "day_of_week": "木"},
         "cre_keywords_matched": ["逆境走法"]},
        {"sport": "keirin", "date": "2026-03-01", "venue": "玉野", "race_number": 4,
         "tier": "B", "filter_type": "C",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "B", "race_type": "F2", "bank_length": "333", "day_of_week": "土"},
         "cre_keywords_matched": ["逆境走法"]},
        {"sport": "keirin", "date": "2026-03-02", "venue": "松戸", "race_number": 3,
         "tier": "B", "filter_type": "C",
         "result": {"hit": False, "payout": 0,    "roi": 0.00},
         "features": {"class": "B", "race_type": "F2", "bank_length": "400", "day_of_week": "日"},
         "cre_keywords_matched": ["逆境走法"]},
    ]

    # --- 一時ファイルに書き出し ---
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as tmp:
        for rec in MOCK_RECORDS:
            tmp.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp_path = tmp.name

    print(f"モックデータ書き出し先: {tmp_path}")
    print(f"レコード数: {len(MOCK_RECORDS)}")
    print()

    try:
        analyzer = FeedbackAnalyzer(tmp_path)
        result = analyzer.analyze_weekly("keirin", "2026-02-24", "2026-03-02")

        # --- [1] 全体成績 ---
        print("[1] 全体成績")
        o = result["overall"]
        print(f"  件数: {o['n']}  的中率: {o['hit_rate']:.1%}  ROI: {o['roi']:.0%}  "
              f"利益: {o['profit']:+,}円（1000円/予想ベース）")
        print()

        # --- [2] Tier別成績 ---
        print("[2] Tier別成績")
        for tier in ["S", "A", "B"]:
            ts = result["by_tier"][tier]
            target = TIER_ROI_TARGETS[tier]
            ok_mark = "✓" if (ts["roi"] or 0) >= target else "✗"
            roi_str = f"{ts['roi']:.0%}" if ts["roi"] is not None else "N/A"
            hr_str  = f"{ts['hit_rate']:.1%}" if ts.get("hit_rate") is not None else "N/A"
            print(f"  {tier}: N={ts['n']:2d}  的中率={hr_str:>5}  "
                  f"ROI={roi_str:>5}  目標{target:.0%} {ok_mark}")
        print()

        # --- [3] 逆指標発見 ---
        print("[3] 逆指標発見")
        if result["new_reverse_indicators"]:
            for ind in result["new_reverse_indicators"]:
                print(f"  {ind['pattern']}  N={ind['n']}  ROI={ind['roi']:.0%}  "
                      f"重要度={ind['significance']}")
        else:
            print("  逆指標なし")
        print()

        # --- [4] 正指標発見 ---
        print("[4] 正指標発見")
        if result["new_positive_indicators"]:
            for ind in result["new_positive_indicators"]:
                print(f"  {ind['pattern']}  N={ind['n']}  ROI={ind['roi']:.0%}  "
                      f"重要度={ind['significance']}")
        else:
            print("  正指標なし")
        print()

        # --- [5] Tier境界チェック ---
        print("[5] Tier境界チェック")
        bc = result["tier_boundary_check"]
        print(f"  S_ok={bc['s_ok']}  A_ok={bc['a_ok']}  B_ok={bc['b_ok']}")
        print(f"  推奨: {bc['recommendation']}")
        print()

        # --- [6] 異常値検出 ---
        print("[6] 異常値検出")
        if result["anomalies"]:
            for a in result["anomalies"]:
                print(f"  [{a['severity'].upper()}] {a['type']}: {a['detail']}")
        else:
            print("  異常なし")
        print()

        # --- [7] 曜日別 ---
        print("[7] 曜日別成績（ROI上位3）")
        dow_items = [
            (dow, s) for dow, s in result["by_day_of_week"].items()
            if s["roi"] is not None
        ]
        dow_items.sort(key=lambda x: x[1]["roi"], reverse=True)
        for dow, s in dow_items[:3]:
            print(f"  {dow}: N={s['n']}  的中率={s['hit_rate']:.0%}  ROI={s['roi']:.0%}")
        print()

        print("=" * 60)
        print("全テスト正常完了")
        print("=" * 60)

    finally:
        os.unlink(tmp_path)
