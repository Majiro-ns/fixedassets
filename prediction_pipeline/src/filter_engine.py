"""
レースフィルターエンジン
YAML で定義されたフィルター条件をレースデータに適用する。

フィルター設定は config/settings.yaml の filters.{sport} セクションから動的に読み込む。
ハードコードは禁止。全閾値は settings.yaml または各スポーツの filters.yaml を参照すること。

【競輪フィルター一覧（sport="keirin"）】
    F1: クラスフィルター（S級のみ）
    F2: レース種別フィルター（特選・二次予選のみ）
    F3: 逆指標キーワードフィルター（「自信」等を含む予想は除外）
    F4: 競輪場フィルター（回収率0-30%の場を除外）
    F5: バンク長フィルター（500mバンクは除外）
    F6: 曜日フィルター（月・日は除外）
    F7: レース番号フィルター（4R・6Rは除外）
    F8: 期待配当ゾーンフィルター（5-10万ゾーン回避）
    F9: フィルター分類（堅実型C / 標準型A / 穴狙い型B）

【競艇フィルター一覧（sport="kyotei"）】
    KF1: 級別フィルター（A1選手の最低人数チェック）
    KF2: グレードフィルター（SG/G1/G2/G3のみ対象）
    KF3: モーター勝率フィルター（平均モーター勝率の閾値）
    KF4: コース別イン逃げ率フィルター（1号艇の1コース勝率）
    KF5: F数フィルター（フライング持ち選手を含むレースの除外）
    KF6: 水面特性フィルター（荒れやすい場・強風の除外）
    KF7: 曜日フィルター（競輪と同様）
    KF8: 期待配当ゾーンフィルター
    KF9: 分類（堅実型C / 標準型A / 穴狙い型B）

使用例:
    # 競輪（従来通り・後方互換）
    engine = FilterEngine("config/keirin/filters.yaml")
    passed, reasons = engine.apply(race_data)

    # 競艇
    engine = FilterEngine("config/kyotei/filters.yaml", sport="kyotei")
    passed, reasons = engine.apply(race_data)
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# デフォルトフィルター設定（config/settings.yaml が存在しない場合に使用）
DEFAULT_FILTERS: Dict[str, Any] = {
    # 既存フィルター（後方互換）
    "min_s1_count": 3,
    # cmd_126k_sub2 2026-03-01: ROI>=91.0%のrace_typeのみ通過
    "allowed_stages": ["予選", "一予選", "特選", "初特選", "一般", "一次予選"],
    "min_grade": "S1",
    # F1: クラス
    "class": ["S"],
    # F2: レース種別（ROI>=91.0%のみ通過 cmd_126k_sub2 2026-03-01）
    "race_type": ["予選", "一予選", "特選", "初特選", "一般", "一次予選"],
    # F3: 逆指標キーワード
    "exclude_keywords": ["自信", "見えた", "鉄板", "間違いない"],
    # F4: 除外競輪場
    "exclude_velodromes": ["小田原", "名古屋", "高知", "玉野", "武雄"],
    # F5: 500mバンク除外
    "exclude_track_500m": True,
    # F6: 除外曜日
    "exclude_day_of_week": ["月", "日"],
    # F7: 除外レース番号
    "exclude_race_number": [4, 6],
    # F8: 期待配当ゾーン（この範囲内を「通過」とみなす）
    "expected_payout_min": 20000,
    "expected_payout_max": 50000,
    # score_spread フィルター（#T002対策案2 cmd_132k_sub2 2026-03-01）
    # 競走得点 max-min < 閾値なら拮抗レース → SKIP。0=無効
    "min_score_spread": 0,
}


# 競艇デフォルトフィルター設定（config/kyotei/filters.yaml が存在しない場合に使用）
DEFAULT_KYOTEI_FILTERS: Dict[str, Any] = {
    # KF1: 級別フィルター
    "allowed_classes": ["A1", "A2"],
    "min_a1_count": 3,
    # KF2: グレードフィルター
    "allowed_grades": ["SG", "G1", "G2", "G3"],
    "allow_general_with_conditions": True,
    # KF3: モーター勝率フィルター
    "min_motor_win_rate": 0.40,
    # KF4: 1コースイン逃げ率フィルター
    "min_course1_win_rate": 0.45,
    # KF5: F数フィルター
    "max_f_count_for_axis": 0,
    "exclude_race_with_f": False,
    # KF6: 水面特性・除外会場
    "exclude_venues": ["江戸川"],
    "max_wind_speed_ms": 7.0,
    # KF7: 曜日フィルター（競輪と同じキー名で共用）
    "exclude_day_of_week": ["月", "日"],
    # KF8: 期待配当ゾーン（競輪と同じキー名で共用）
    "expected_payout_min": 15000,
    "expected_payout_max": 60000,
    # KF3 逆指標キーワード（コメントがある場合のみ適用）
    "exclude_keywords": ["自信", "見えた", "鉄板", "間違いない"],
}


class FilterEngine:
    """
    YAML フィルター設定をレースデータに適用するエンジン。

    filter.apply(race) → True: 全フィルター通過（予想対象）
    filter.apply(race) → False: いずれかのフィルターに引っかかる（対象外）

    filter.classify(race, comment) → {'type': 'A'/'B'/'C', 'reasons': [...]}
    """

    def __init__(self, config_path: str, sport: str = "keirin") -> None:
        """
        Args:
            config_path: filters.yaml のパス（例: "config/keirin/filters.yaml"）。
                         ファイルが存在しない場合はデフォルト設定を使用する。
            sport: 競技種別。"keirin"（競輪・デフォルト）または "kyotei"（競艇）。
                   デフォルト "keirin" のため、既存の呼び出しコードは変更不要。

        インターフェース:
            FilterEngine(config_path)                    # 競輪（後方互換）
            FilterEngine(config_path, sport="kyotei")   # 競艇
        """
        self.sport = sport  # _load_filters より先に設定すること
        self.filters = self._load_filters(config_path)

    # ─── 公開メソッド ──────────────────────────────────────

    def apply(self, race: Dict[str, Any], comment: str = "") -> Tuple[bool, List[str]]:
        """
        レースが全フィルター条件を満たすか判定する。

        sport="keirin"（デフォルト）は競輪フィルター F1〜F8 を適用する。
        sport="kyotei" は競艇フィルター KF1〜KF8 を適用する。

        Args:
            race: レースデータ辞書。
                競輪の場合::

                    {
                        "stage":        "特選",        # レース種別
                        "grade":        "S1",           # グレード
                        "venue_name":   "川崎",         # 競輪場名
                        "bank_length":  400,            # バンク周長（m）
                        "race_num":     12,             # レース番号
                        "date":         "20260224",     # YYYYMMDD
                        "entries":      [...],          # 出走選手リスト
                        "expected_payout": 35000,       # 期待配当（任意）
                    }

                競艇の場合::

                    {
                        "grade":        "G1",           # SG/G1/G2/G3/一般
                        "venue_name":   "住之江",       # 競艇場名
                        "wind_speed_ms": 3.5,           # 風速（m/s、任意）
                        "date":         "20260224",     # YYYYMMDD（任意）
                        "entries": [                    # 出走艇リスト
                            {
                                "boat_number": 1,
                                "racer_class": "A1",    # A1/A2/B1/B2
                                "motor_win_rate": 0.45, # モーター勝率
                                "false_start_count": 0, # F数
                                "course_stats": {"1": 0.55, ...},
                            },
                            ...
                        ],
                        "expected_payout": 25000,       # 期待配当（任意）
                    }

            comment: 予想コメントテキスト（逆指標キーワードチェック用）。

        Returns:
            Tuple[bool, List[str]]:
                - bool: True=全通過、False=除外
                - List[str]: 除外理由のリスト（通過時は空リスト）
        """
        if self.sport == "kyotei":
            return self._apply_kyotei(race, comment)
        return self._apply_keirin(race, comment)

    def _apply_keirin(self, race: Dict[str, Any], comment: str = "") -> Tuple[bool, List[str]]:
        """競輪フィルター F1〜F8 + score_spread を適用する。"""
        reasons: List[str] = []
        checks = [
            self._check_class,
            self._check_race_type,
            self._check_velodrome,
            self._check_bank_length,
            self._check_day_of_week,
            self._check_race_number,
            self._check_expected_payout,
            self._check_score_spread,
        ]
        for check in checks:
            passed, reason = check(race)
            if not passed:
                reasons.append(reason)

        # 逆指標キーワードはコメントがある場合のみ
        if comment:
            passed, reason = self._check_keywords(comment)
            if not passed:
                reasons.append(reason)

        return (len(reasons) == 0), reasons

    def _apply_kyotei(self, race: Dict[str, Any], comment: str = "") -> Tuple[bool, List[str]]:
        """競艇フィルター KF1〜KF8 を適用する。"""
        reasons: List[str] = []
        checks = [
            self._kf1_check_class,
            self._kf2_check_grade,
            self._kf3_check_motor_win_rate,
            self._kf4_check_course1_win_rate,
            self._kf5_check_f_count,
            self._kf6_check_venue,
            self._check_day_of_week,    # KF7: 曜日（競輪と同一ロジック・同一キー）
            self._check_expected_payout,  # KF8: 配当ゾーン（競輪と同一ロジック・同一キー）
        ]
        for check in checks:
            passed, reason = check(race)
            if not passed:
                reasons.append(reason)

        # 逆指標キーワードはコメントがある場合のみ
        if comment:
            passed, reason = self._check_keywords(comment)
            if not passed:
                reasons.append(reason)

        return (len(reasons) == 0), reasons

    def apply_legacy(self, race: Dict[str, Any]) -> bool:
        """
        後方互換用: 旧インターフェース（stage + s1_count のみ）。

        Args:
            race: レースデータ。stage, entries を含む。

        Returns:
            全フィルターを通過した場合 True。
        """
        return (
            self._check_stage(race)
            and self._check_s1_count(race)
        )

    def classify(
        self,
        race: Dict[str, Any],
        comment: str = "",
    ) -> Dict[str, Any]:
        """
        レースを堅実型(C) / 標準型(A) / 穴狙い型(B) に分類する（F9）。

        分類基準:
            C (堅実型):  期待配当 < expected_payout_min（低配当・堅い）
            A (標準型):  expected_payout_min ≤ 期待配当 ≤ expected_payout_max
            B (穴狙い型): 期待配当 > expected_payout_max（高配当・穴）

        グレード補正:
            - S1 かつ 特選/二次予選 → 堅実度 +1
            - 逆指標キーワードなし  → 堅実度 +1
            - 有名除外場以外         → 堅実度 +1

        Args:
            race: レースデータ辞書
            comment: 予想コメント

        Returns:
            分類結果辞書::

                {
                    "type":    "A",         # "A" / "B" / "C"
                    "reasons": ["..."],     # 分類理由
                    "confidence": 2,        # 堅実度スコア (0-3)
                }
        """
        _default_payout = DEFAULT_KYOTEI_FILTERS if self.sport == "kyotei" else DEFAULT_FILTERS
        payout_min = self.filters.get("expected_payout_min", _default_payout["expected_payout_min"])
        payout_max = self.filters.get("expected_payout_max", _default_payout["expected_payout_max"])

        expected_payout = race.get("expected_payout", 0)
        confidence_score = 0
        reasons: List[str] = []

        if self.sport == "kyotei":
            # KF9: 競艇グレード・種別スコア
            grade = str(race.get("grade", ""))
            allowed_grades = self.filters.get("allowed_grades", DEFAULT_KYOTEI_FILTERS["allowed_grades"])
            if grade in allowed_grades:
                confidence_score += 1
                reasons.append(f"{grade}グレード（対象グレード）")
        else:
            # F9: 競輪グレード・種別スコア
            grade = str(race.get("grade", ""))
            stage = str(race.get("stage", ""))
            allowed_classes = self.filters.get("class", DEFAULT_FILTERS["class"])
            allowed_types = self.filters.get("race_type", DEFAULT_FILTERS["race_type"])
            if any(c in grade for c in allowed_classes) and stage in allowed_types:
                confidence_score += 1
                reasons.append(f"S級×{stage}（安定ステージ）")

        # 逆指標キーワードなし
        if comment:
            _default_kw = DEFAULT_KYOTEI_FILTERS if self.sport == "kyotei" else DEFAULT_FILTERS
            exclude_kw = self.filters.get("exclude_keywords", _default_kw["exclude_keywords"])
            has_bad_kw = any(kw in comment for kw in exclude_kw)
            if not has_bad_kw:
                confidence_score += 1
                reasons.append("逆指標キーワードなし")
        else:
            reasons.append("コメント未提供（キーワードチェックなし）")

        # 場の安全性（競輪: 除外場+500mバンク / 競艇: 除外場のみ）
        venue_name = str(race.get("venue_name", ""))
        if self.sport == "kyotei":
            exclude_venues = self.filters.get("exclude_venues", DEFAULT_KYOTEI_FILTERS["exclude_venues"])
            venue_ok = venue_name not in exclude_venues
            bank_ok = True
        else:
            exclude_venues = self.filters.get("exclude_velodromes", DEFAULT_FILTERS["exclude_velodromes"])
            bank_length = int(race.get("bank_length", 400))
            exclude_500m = self.filters.get("exclude_track_500m", DEFAULT_FILTERS["exclude_track_500m"])
            venue_ok = venue_name not in exclude_venues
            bank_ok = not (exclude_500m and bank_length == 500)

        if venue_ok and bank_ok:
            confidence_score += 1
            if self.sport == "kyotei":
                reasons.append(f"{venue_name} 適正会場")
            else:
                bank_length = int(race.get("bank_length", 400))
                reasons.append(f"{venue_name} 標準バンク（{bank_length}m）")

        # 配当ゾーン分類
        if expected_payout < payout_min:
            race_type = "C"
            reasons.append(f"期待配当 {expected_payout:,}円 < {payout_min:,}円（堅実型）")
        elif expected_payout <= payout_max:
            race_type = "A"
            reasons.append(f"期待配当 {expected_payout:,}円（標準ゾーン）")
        else:
            race_type = "B"
            reasons.append(f"期待配当 {expected_payout:,}円 > {payout_max:,}円（穴狙い型）")

        # confidence_score で A を C に格上げする補正
        if race_type == "A" and confidence_score == 3:
            race_type = "C"
            reasons.append("堅実度MAX → 堅実型(C)に格上げ")

        return {
            "type": race_type,
            "reasons": reasons,
            "confidence": confidence_score,
        }

    # ─── C3強化フィルター（MLフィルター改善 2026-02-28 cmd_089）──────────

    def apply_ml_filters(
        self,
        race: Dict[str, Any],
        comment: str = "",
        num_bets: Optional[int] = None,
    ) -> Tuple[bool, List[str]]:
        """
        C3強化フィルター（F10〜F12）を適用する。

        旧パイプラインの hit_probability >= 0.9 / score_spread >= 12 ロジックの
        新パイプライン対応版。MLモデルなしでルールベース実装。

        F10: 信頼度スコア閾値（min_confidence_score）
            classify()の confidence_score がこの値未満なら SKIP。
            hit_probability >= 0.9 相当 → min_confidence_score: 3（C型のみ）

        F11: 実力差フィルター（min_win_rate_spread）
            entries[].win_rate の max-min < 閾値なら実力拮抗 → SKIP。
            score_spread < 12 相当。win_rateが未設定なら自動スキップ。

        F12: C3拡張フィルター・点数上限（max_bets_per_race）
            num_bets > 設定値 なら SKIP（C3条件5: 点数11以上は的中率低下）。

        Args:
            race: レースデータ辞書
            comment: 予想コメント（classify用）
            num_bets: 賭け点数（F12チェック用。Noneはスキップ）

        Returns:
            Tuple[bool, List[str]]: (通過=True, 除外理由リスト)
        """
        reasons: List[str] = []

        # F10: 信頼度スコア閾値
        min_conf = self.filters.get("min_confidence_score", 0)
        if min_conf > 0:
            classification = self.classify(race, comment)
            conf_score = classification.get("confidence", 0)
            if conf_score < min_conf:
                reasons.append(
                    f"F10[信頼度]: confidence_score={conf_score} < 閾値{min_conf}"
                    f"（filter_type={classification.get('type')}）"
                )

        # F11: 実力差フィルター（win_rate_spread）
        min_spread = self.filters.get("min_win_rate_spread", 0.0)
        if min_spread > 0.0:
            entries = race.get("entries", [])
            win_rates = [
                float(e.get("win_rate", 0) or 0)
                for e in entries
                if e.get("win_rate") is not None
            ]
            if len(win_rates) >= 2:
                spread = max(win_rates) - min(win_rates)
                if spread < min_spread:
                    reasons.append(
                        f"F11[実力差]: win_rate_spread={spread:.3f} < 閾値{min_spread}"
                        "（実力拮抗レース: 予測精度低下）"
                    )

        # F12: 点数上限（C3条件5）
        max_bets = self.filters.get("max_bets_per_race", 0)
        if max_bets > 0 and num_bets is not None:
            if num_bets > max_bets:
                reasons.append(
                    f"F12[点数上限]: {num_bets}点 > 上限{max_bets}点"
                    "（C3条件5: 11点以上は的中率低下）"
                )

        return (len(reasons) == 0), reasons

    # ─── F1〜F9 個別フィルターチェック ──────────────────────

    def _check_class(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        F1: クラスフィルター。
        設定: filters.keirin.class (例: ["S"])
        S級のみ通過。A級は回収率80%で除外。
        """
        allowed = self.filters.get("class", DEFAULT_FILTERS["class"])
        grade = str(race.get("grade", ""))
        passed = any(c in grade for c in allowed)
        return passed, f"F1[クラス]: {grade} は除外クラス（許可: {allowed}）"

    def _check_race_type(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        F2: レース種別フィルター。
        設定: filters.keirin.race_type (例: ["特選", "二次予選"])
        決勝67%・選抜49%は除外。特選・二次予選のみ通過。
        """
        allowed = self.filters.get("race_type", DEFAULT_FILTERS["race_type"])
        stage = str(race.get("stage", ""))
        # 完全一致で判定（部分一致だと「予選」⊆「二次予選」等のfalse positiveが発生）
        passed = stage in allowed
        return passed, f"F2[種別]: {stage!r} は除外種別（許可: {allowed}）"

    def _check_score_spread(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        score_spread フィルター（#T002対策案2 cmd_132k_sub2）。
        設定: filters.keirin.min_score_spread (例: 12)
        競走得点 max-min < 閾値なら拮抗レース → SKIP。
        score データが欠損している場合は通過させる（除外しない）。
        """
        min_spread = self.filters.get("min_score_spread", 0)
        if min_spread <= 0:
            return True, ""

        entries = race.get("entries", [])
        scores = [
            float(e.get("score", 0) or 0)
            for e in entries
            if e.get("score") is not None and float(e.get("score", 0) or 0) > 0
        ]
        if len(scores) < 2:
            # データ欠損時は通過
            return True, ""

        spread = max(scores) - min(scores)
        passed = spread >= min_spread
        return passed, (
            f"score_spread[実力差]: spread={spread:.2f} < 閾値{min_spread}"
            "（拮抗レース: 予測精度低下）"
        )

    def _check_keywords(self, comment: str) -> Tuple[bool, str]:
        """
        F3: 逆指標キーワードフィルター。
        設定: filters.keirin.exclude_keywords
        「自信」「見えた」「鉄板」「間違いない」を含む予想は除外。
        """
        exclude = self.filters.get("exclude_keywords", DEFAULT_FILTERS["exclude_keywords"])
        found = [kw for kw in exclude if kw in comment]
        passed = len(found) == 0
        return passed, f"F3[キーワード]: 逆指標語 {found} を検出"

    def _check_velodrome(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        F4: 競輪場フィルター。
        設定: filters.keirin.exclude_velodromes
        小田原・名古屋・高知・玉野・武雄は回収率0-30%のため除外。
        """
        exclude = self.filters.get("exclude_velodromes", DEFAULT_FILTERS["exclude_velodromes"])
        venue = str(race.get("venue_name", ""))
        passed = venue not in exclude
        return passed, f"F4[競輪場]: {venue!r} は低回収率場（除外リスト: {exclude}）"

    def _check_bank_length(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        F5: バンク長フィルター。
        設定: filters.keirin.exclude_track_500m
        500mバンクは回収率62%のため除外。
        """
        exclude_500m = self.filters.get("exclude_track_500m", DEFAULT_FILTERS["exclude_track_500m"])
        bank_length = int(race.get("bank_length", 400))
        passed = not (exclude_500m and bank_length == 500)
        return passed, f"F5[バンク長]: {bank_length}m バンクは除外対象（500m除外設定）"

    def _check_day_of_week(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        F6: 曜日フィルター。
        設定: filters.keirin.exclude_day_of_week (例: ["月", "日"])
        月曜・日曜は回収率79-80%のため除外。
        """
        exclude_days = self.filters.get("exclude_day_of_week", DEFAULT_FILTERS["exclude_day_of_week"])
        date_str = str(race.get("date", ""))
        if not date_str or len(date_str) < 8:
            return True, ""  # 日付不明は通過

        try:
            dt = datetime.strptime(date_str, "%Y%m%d")
            day_map = {0: "月", 1: "火", 2: "水", 3: "木", 4: "金", 5: "土", 6: "日"}
            day_ja = day_map[dt.weekday()]
            passed = day_ja not in exclude_days
            return passed, f"F6[曜日]: {day_ja}曜日は除外対象（除外: {exclude_days}）"
        except ValueError:
            return True, ""  # パース失敗は通過

    def _check_race_number(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        F7: レース番号フィルター。
        設定: filters.keirin.exclude_race_number (例: [4, 6])
        4R・6Rは回収率24-33%のため除外。
        """
        exclude_nums = self.filters.get("exclude_race_number", DEFAULT_FILTERS["exclude_race_number"])
        race_num = int(race.get("race_num", 0))
        passed = race_num not in exclude_nums
        return passed, f"F7[R番号]: {race_num}R は除外対象（除外: {exclude_nums}）"

    def _check_expected_payout(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        F8: 期待配当ゾーンフィルター。
        設定: filters.keirin.expected_payout_min/max
        5万〜10万ゾーン（回収率87.5%で最悪）は回避。
        expected_payout が [min, max] の範囲外は除外。
        ※ expected_payout が未設定の場合はこのフィルターをスキップ。
        """
        expected = race.get("expected_payout")
        if expected is None:
            return True, ""  # 未設定はスキップ

        payout_min = self.filters.get("expected_payout_min", DEFAULT_FILTERS["expected_payout_min"])
        payout_max = self.filters.get("expected_payout_max", DEFAULT_FILTERS["expected_payout_max"])

        # 5万〜10万ゾーンは除外（設定ではmax=50000, excludeゾーン=50000-100000）
        # 現設定: min=20000, max=50000 → この範囲外を除外
        passed = payout_min <= int(expected) <= payout_max
        return passed, (
            f"F8[配当ゾーン]: 期待配当 {expected:,}円 が適正ゾーン"
            f"({payout_min:,}〜{payout_max:,}円)の外"
        )

    # ─── KF1〜KF8 競艇専用フィルターチェック ────────────────

    def _kf1_check_class(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        KF1: 級別フィルター。
        設定: allowed_classes（例: ["A1", "A2"]）、min_a1_count（例: 3）
        A1選手が最低人数出走しているレースのみ通過。
        """
        min_a1 = self.filters.get("min_a1_count", DEFAULT_KYOTEI_FILTERS["min_a1_count"])
        entries = race.get("entries", [])
        a1_count = sum(1 for e in entries if e.get("racer_class") == "A1")
        passed = a1_count >= min_a1
        return passed, f"KF1[級別]: A1選手 {a1_count}名（最低 {min_a1}名必要）"

    def _kf2_check_grade(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        KF2: グレードフィルター。
        設定: allowed_grades（例: ["SG", "G1", "G2", "G3"]）
        一般戦は原則除外。SG/G1/G2/G3のみ通過。
        """
        allowed = self.filters.get("allowed_grades", DEFAULT_KYOTEI_FILTERS["allowed_grades"])
        grade = str(race.get("grade", ""))
        passed = grade in allowed
        return passed, f"KF2[グレード]: {grade!r} は対象外（許可: {allowed}）"

    def _kf3_check_motor_win_rate(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        KF3: モーター勝率フィルター。
        設定: min_motor_win_rate（例: 0.40）
        全出走艇の平均モーター勝率が閾値以上のレースのみ通過。
        motor_win_rate データがない場合はスキップ。
        """
        min_rate = self.filters.get("min_motor_win_rate", DEFAULT_KYOTEI_FILTERS["min_motor_win_rate"])
        entries = race.get("entries", [])
        rates = [e.get("motor_win_rate") for e in entries if e.get("motor_win_rate") is not None]
        if not rates:
            return True, ""  # データなしはスキップ
        avg_rate = sum(rates) / len(rates)
        passed = avg_rate >= min_rate
        return passed, (
            f"KF3[モーター勝率]: 平均 {avg_rate:.1%}（最低 {min_rate:.1%}）"
        )

    def _kf4_check_course1_win_rate(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        KF4: コース別イン逃げ率フィルター。
        設定: min_course1_win_rate（例: 0.45）
        1号艇の1コース勝率が閾値以上のレースのみ通過。
        course_stats データがない場合はスキップ。
        """
        min_rate = self.filters.get("min_course1_win_rate", DEFAULT_KYOTEI_FILTERS["min_course1_win_rate"])
        entries = race.get("entries", [])
        boat1 = next((e for e in entries if e.get("boat_number") == 1), None)
        if boat1 is None or not boat1.get("course_stats"):
            return True, ""  # データなしはスキップ
        course1_rate = boat1.get("course_stats", {}).get("1")
        if course1_rate is None:
            return True, ""  # データなしはスキップ
        passed = course1_rate >= min_rate
        return passed, (
            f"KF4[イン逃げ率]: 1号艇1コース勝率 {course1_rate:.1%}（最低 {min_rate:.1%}）"
        )

    def _kf5_check_f_count(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        KF5: F数（フライング）フィルター。
        設定: exclude_race_with_f（True の場合のみ有効）、max_f_count_for_axis（例: 0）
        exclude_race_with_f=True の場合、出走選手のF数合計が max_f_count_for_axis を
        超えるレースを除外する。False の場合はこのフィルターをスキップ。
        """
        exclude_race = self.filters.get("exclude_race_with_f", DEFAULT_KYOTEI_FILTERS["exclude_race_with_f"])
        if not exclude_race:
            return True, ""  # レース除外しない設定ならスキップ
        max_f = self.filters.get("max_f_count_for_axis", DEFAULT_KYOTEI_FILTERS["max_f_count_for_axis"])
        entries = race.get("entries", [])
        f_total = sum(int(e.get("false_start_count") or 0) for e in entries)
        passed = f_total <= max_f
        return passed, f"KF5[F数]: 出走選手合計F数 {f_total}（上限 {max_f}）"

    def _kf6_check_venue(self, race: Dict[str, Any]) -> Tuple[bool, str]:
        """
        KF6: 水面特性フィルター。
        設定: exclude_venues（荒れやすい場のリスト）、max_wind_speed_ms（強風上限）
        除外会場または強風時は除外。wind_speed_ms データがない場合は風速チェックをスキップ。
        """
        exclude = self.filters.get("exclude_venues", DEFAULT_KYOTEI_FILTERS["exclude_venues"])
        max_wind = self.filters.get("max_wind_speed_ms", DEFAULT_KYOTEI_FILTERS["max_wind_speed_ms"])
        venue = str(race.get("venue_name", ""))
        if venue in exclude:
            return False, f"KF6[水面]: {venue!r} は除外会場"
        wind = race.get("wind_speed_ms")
        if wind is not None and float(wind) >= max_wind:
            return False, f"KF6[強風]: 風速 {wind}m/s（上限 {max_wind}m/s）"
        return True, ""

    # ─── 旧インターフェース互換 ────────────────────────────

    def _check_stage(self, race: Dict[str, Any]) -> bool:
        """後方互換: レースステージが許可リストに含まれるか確認。"""
        allowed = self.filters.get("allowed_stages", DEFAULT_FILTERS["allowed_stages"])
        stage = race.get("stage", "")
        return stage in allowed

    def _check_s1_count(self, race: Dict[str, Any]) -> bool:
        """後方互換: S1 選手が最低人数以上出走しているか確認。"""
        min_count = self.filters.get("min_s1_count", DEFAULT_FILTERS["min_s1_count"])
        entries = race.get("entries", [])
        s1_count = sum(1 for e in entries if e.get("grade") == "S1")
        return s1_count >= min_count

    # ─── フィルター設定読み込み ────────────────────────────

    def _load_filters(self, config_path: str) -> Dict[str, Any]:
        """
        filters.yaml または settings.yaml から filters.{sport} セクションを読み込む。

        検索順序:
            1. data["filters"][sport] セクション（settings.yaml 形式）
            2. トップレベルキー（config/keirin/filters.yaml 等の個別ファイル形式）

        Args:
            config_path: フィルター設定ファイルのパス
                         例: "config/keirin/filters.yaml"、"config/settings.yaml"

        Returns:
            フィルター設定辞書。スポーツのデフォルト設定にファイルの値をマージして返す。
        """
        default = (
            DEFAULT_KYOTEI_FILTERS.copy()
            if self.sport == "kyotei"
            else DEFAULT_FILTERS.copy()
        )

        if not os.path.exists(config_path):
            return default

        if not _YAML_AVAILABLE:
            return default

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            return default

        # filters.{sport} セクションを取得し、デフォルトにマージ
        filters_section = data.get("filters", {})
        sport_filters = filters_section.get(self.sport, {})

        # filters.{sport} が空の場合はトップレベルキーを直接使用（後方互換）
        if not sport_filters:
            sport_filters = {k: v for k, v in data.items() if k != "filters"}

        merged = default
        merged.update(sport_filters)
        return merged
