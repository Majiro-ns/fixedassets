"""
Tier分類器
CREフィルター通過結果とレースデータに基づき、レースを S / A / B / SKIP に分類する。

設計書: true_ai_prediction_system_design.md Section 4
出典 : mr_t_cognitive_profile.yaml (842件 / 2026-02-22)
"""

from __future__ import annotations

import os
from typing import Any

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ─── デフォルト設定 ────────────────────────────────────────────────────────
# config/keirin/filters.yaml または config/kyotei/filters.yaml が存在しない場合の
# フォールバック値。全閾値の出典を下記コメントに記載する。

_DEFAULT_CONFIG: dict[str, dict[str, Any]] = {
    "keirin": {
        # ── Tier S 条件（出典: optimal_filters.filter_A, n=131, ROI=148.7%）
        "tier_s_required_grade": "S1",          # entries[].grade の最低値
        "tier_s_race_types": ["特選", "二次予選"],
        "tier_s_preferred_venues": [            # best_velodromes 上位5場
            "熊本", "別府", "防府", "立川", "川崎",
        ],
        "tier_s_avoid_track_lengths": [500],    # 500m: ROI=62%（by_track_length）
        # ── Tier A 条件（設計書 Section 4, 期待ROI=110-130%）
        "tier_a_required_grade": "S1",
        "tier_a_race_types": ["準決勝", "初日特別選抜"],
        # ── 逆指標キーワード（出典: reverse_indicator_patterns）
        #    「自信」ROI=27%, 「見えた」ROI=0%, 「鉄板」ROI=0%, 「間違いない」ROI=0%
        "reverse_indicator_keywords": ["自信", "見えた", "鉄板", "間違いない"],
        # ── S1選手最低人数（filter_engine.py DEFAULT_FILTERS 準拠）
        "min_s1_count": 3,
        # ── confidence_score 重み（各条件の寄与度、合計 = 1.0）
        "score_weights": {
            "s_class":             0.30,  # S1選手が最低数以上
            "race_type_premium":   0.25,  # 特選/二次予選
            "preferred_venue":     0.20,  # 優良場（best_velodromes）
            "non_500m":            0.15,  # 非500mバンク
            "no_reverse_indicator": 0.10, # 逆指標なし
        },
    },
    "kyotei": {
        # ── Tier S 条件（暫定, cmd_021データ拡充後に確定）
        "tier_s_anchor_course": 1,
        "tier_s_motor_win_rate_threshold": 42.0,  # %（上位モーター目安）
        "tier_s_preferred_venues": ["住之江", "若松", "芦屋"],
        # ── Tier A 条件
        "tier_a_anchor_courses": [1, 4],          # 1号艇軸 or 4号艇カド
        # ── SKIP 条件
        "skip_flying_count_threshold": 1,         # F保持選手含む場合
        # ── 逆指標
        "reverse_indicator_keywords": ["自信", "見えた", "鉄板", "間違いない"],
        # ── confidence_score 重み
        "score_weights": {
            "anchor_course":        0.30,
            "motor_win_rate":       0.25,
            "preferred_venue":      0.20,
            "no_reverse_indicator": 0.15,
            "no_flying":            0.10,
        },
    },
}


class TierClassifier:
    """
    CREフィルター通過結果とレースデータに基づき、レースのTierを決定する。

    Tier定義（競輪）:
        S    : Filter A 通過
               = S1選手 >= min_s1_count × 特選/二次予選 × 逆指標除外 × 優良場 × 非500m
               期待ROI = 148.7%（出典: optimal_filters.filter_A, n=131）
        A    : S1選手 >= min_s1_count × 準決勝/初日特別選抜 × 逆指標除外
               期待ROI = 110-130%（設計書 Section 4）
        B    : CREフィルター通過かつ上位条件不満足
               期待ROI = 95-110%
        SKIP : 逆指標該当 or CREフィルター不通過
               期待ROI < 95%

    Tier定義（競艇, 暫定）:
        S    : 1号艇軸 × モーター好調 × 逆指標除外 × 優良場
        A    : 1号艇 or 4号艇カド × 逆指標除外
        B    : フィルター通過かつ上位条件不満足
        SKIP : F保持選手含む or 逆指標該当 or フィルター不通過
    """

    def __init__(self, config_path: str | None = None) -> None:
        """
        Args:
            config_path: filters.yaml の基底ディレクトリパス（例: "config"）。
                         None またはファイル不在の場合はデフォルト設定を使用する。
                         実際のロード対象は {config_path}/{sport}/filters.yaml。
        """
        self._keirin_cfg = self._load_config(config_path, "keirin")
        self._kyotei_cfg = self._load_config(config_path, "kyotei")

    # ─── 公開 API ──────────────────────────────────────────────────────────

    def classify(
        self,
        race_data: dict[str, Any],
        filter_result: dict[str, Any] | bool,
    ) -> dict[str, Any]:
        """
        レースの Tier を分類する。

        Args:
            race_data: レースデータ。使用するキー:
                sport         : "keirin" | "kyotei"
                race_type     : "特選" | "二次予選" | "準決勝" | "決勝" 等（競輪）
                venue         : 会場名（例: "熊本"）
                track_length  : バンク長 m（競輪のみ, 例: 400）
                race_number   : レース番号 int
                comment       : 予想コメント文字列（逆指標チェック用）
                entries       : 選手リスト。各要素:
                    grade         : "S1"|"S2"|"A1"|"A2"（競輪）
                    flying_count  : int（競艇, F保持数）
                    motor_win_rate: float %（競艇）
                anchor_course : int（競艇のみ、軸艇番号）
            filter_result: FilterEngine.apply() の結果。
                bool の場合: passed の値として解釈する。
                dict の場合: {"passed": bool, "details": dict} 形式。

        Returns:
            {
                "tier"            : "S" | "A" | "B" | "SKIP",
                "filter_type"     : "A" | "B" | "C" | "none",
                "confidence_score": float (0.0〜1.0),
                "reasons"         : list[str],   # Tier 決定の根拠
                "negative_flags"  : list[str],   # 問題のある条件
            }
        """
        sport = race_data.get("sport", "keirin")
        # filter_result が bool の場合は dict に正規化
        if isinstance(filter_result, bool):
            filter_result = {"passed": filter_result}

        if sport == "kyotei":
            return self._classify_kyotei(race_data, filter_result)
        return self._classify_keirin(race_data, filter_result)

    # ─── 競輪 分類ロジック ──────────────────────────────────────────────────

    def _classify_keirin(
        self,
        race_data: dict[str, Any],
        filter_result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        競輪の Tier を分類する。

        出典: mr_t_cognitive_profile.yaml
            - optimal_filters.filter_A: S級×特選/二次予選×逆指標除外, ROI=148.7%
            - reverse_indicator_patterns: 「自信」ROI=27%, 「見えた」ROI=0%
            - by_track_length: 500m ROI=62%（避けるべき）
            - best_velodromes: 熊本/別府/防府/立川/川崎（高回収場）
        """
        cfg = self._keirin_cfg
        reasons: list[str] = []
        negative_flags: list[str] = []

        # ── 1. 逆指標チェック（出典: reverse_indicator_patterns）
        reverse_keywords: list[str] = cfg.get(
            "reverse_indicator_keywords",
            _DEFAULT_CONFIG["keirin"]["reverse_indicator_keywords"],
        )
        comment = race_data.get("comment", "")
        matched_reverse = [kw for kw in reverse_keywords if kw in comment]
        has_reverse = bool(matched_reverse)
        if has_reverse:
            negative_flags.extend(
                [f"逆指標キーワード検出: 「{kw}」" for kw in matched_reverse]
            )

        # ── 2. 基本条件チェック
        race_type    = race_data.get("race_type", "")
        venue        = race_data.get("venue", "")
        track_length = race_data.get("track_length", 0)

        # S1選手が閾値以上か（filter_engine.py と同一ロジック）
        min_s1 = int(cfg.get("min_s1_count", _DEFAULT_CONFIG["keirin"]["min_s1_count"]))
        entries    = race_data.get("entries", [])
        s1_count   = sum(1 for e in entries if e.get("grade") == "S1")
        is_s_class = s1_count >= min_s1

        # 特選/二次予選（Tier S 用）
        tier_s_race_types: list[str] = cfg.get(
            "tier_s_race_types",
            _DEFAULT_CONFIG["keirin"]["tier_s_race_types"],
        )
        is_s_race_type = race_type in tier_s_race_types

        # 優良場（出典: best_velodromes — 熊本169%/別府169%/防府155%等）
        preferred_venues: list[str] = cfg.get(
            "tier_s_preferred_venues",
            _DEFAULT_CONFIG["keirin"]["tier_s_preferred_venues"],
        )
        is_preferred_venue = venue in preferred_venues

        # 非500mバンク（出典: by_track_length — 500m ROI=62%）
        avoid_lengths: list[int] = cfg.get(
            "tier_s_avoid_track_lengths",
            _DEFAULT_CONFIG["keirin"]["tier_s_avoid_track_lengths"],
        )
        is_non_500m = (track_length not in avoid_lengths) if track_length else True

        # 準決勝/初日特別選抜（Tier A 用）
        tier_a_race_types: list[str] = cfg.get(
            "tier_a_race_types",
            _DEFAULT_CONFIG["keirin"]["tier_a_race_types"],
        )
        is_a_race_type = race_type in tier_a_race_types

        filter_passed = bool(filter_result.get("passed", False))

        # ── 3. Tier 決定（優先順位: SKIP > S > A > B > SKIP）
        if has_reverse:
            # 逆指標は常に SKIP（最悪 ROI=0%, mr_t_cognitive_profile.yaml）
            tier = "SKIP"
            filter_type = "none"
            confidence = self._keirin_score(False, False, False, False, False, cfg)
            reasons.append(
                f"逆指標キーワード({', '.join(matched_reverse)}) → SKIP"
                f"（mr_t ROI 最悪: 「自信」=27%, 「見えた」=0%）"
            )

        elif is_s_class and is_s_race_type and is_preferred_venue and is_non_500m:
            # Tier S: filter_A 全条件通過
            tier = "S"
            filter_type = "A"
            confidence = self._keirin_score(True, True, True, True, True, cfg)
            reasons.append(
                f"S1×{s1_count}名 × {race_type} × 優良場({venue}) × "
                f"非500m → Tier S"
                f"（filter_A ROI=148.7%, n=131）"
            )

        elif is_s_class and is_s_race_type and not is_preferred_venue and is_non_500m:
            # Tier A 相当: 優良場以外の S1×特選/二次予選
            tier = "A"
            filter_type = "A"
            confidence = self._keirin_score(True, True, False, is_non_500m, True, cfg)
            reasons.append(
                f"S1×{s1_count}名 × {race_type}（優良場外: {venue}） → Tier A"
            )

        elif is_s_class and is_a_race_type and not has_reverse:
            # Tier A: 準決勝/初日特別選抜（設計書 Section 4 ROI=110-130%目標）
            tier = "A"
            filter_type = "A"
            confidence = self._keirin_score(True, False, is_preferred_venue, is_non_500m, True, cfg)
            reasons.append(
                f"S1×{s1_count}名 × {race_type} → Tier A（設計書Section4準拠）"
            )

        elif filter_passed and is_s_class:
            # Tier B: CREフィルター通過・S1あり・上位条件不満足
            tier = "B"
            filter_type = "none"
            confidence = self._keirin_score(True, False, is_preferred_venue, is_non_500m, True, cfg)
            reasons.append(
                f"CREフィルター通過・S1×{s1_count}名（上位条件未達） → Tier B"
            )
            if not is_s_race_type and not is_a_race_type:
                negative_flags.append(f"レース種別 {race_type!r} は優先種別外")

        else:
            # Tier SKIP
            tier = "SKIP"
            filter_type = "none"
            confidence = self._keirin_score(
                is_s_class, is_s_race_type, is_preferred_venue, is_non_500m, True, cfg
            )
            if not is_s_class:
                negative_flags.append(f"S1選手数不足（{s1_count}/{min_s1}名）")
                reasons.append(f"S1選手 {s1_count}名 < 閾値{min_s1}名 → SKIP")
            if not filter_passed:
                negative_flags.append("CREフィルター不通過")
                reasons.append("CREフィルター不通過 → SKIP")
            if not reasons:
                reasons.append("Tier S/A 条件不満足 → SKIP")

        return {
            "tier":             tier,
            "filter_type":      filter_type,
            "confidence_score": round(confidence, 3),
            "reasons":          reasons,
            "negative_flags":   negative_flags,
        }

    def _keirin_score(
        self,
        is_s_class:    bool,
        is_prem_type:  bool,
        is_pref_venue: bool,
        is_non_500m:   bool,
        no_reverse:    bool,
        cfg:           dict[str, Any],
    ) -> float:
        """競輪の confidence_score を重み付き合算で算出する（0.0〜1.0）。"""
        w = cfg.get("score_weights", _DEFAULT_CONFIG["keirin"]["score_weights"])
        score = 0.0
        if is_s_class:    score += w.get("s_class",              0.30)
        if is_prem_type:  score += w.get("race_type_premium",    0.25)
        if is_pref_venue: score += w.get("preferred_venue",      0.20)
        if is_non_500m:   score += w.get("non_500m",             0.15)
        if no_reverse:    score += w.get("no_reverse_indicator", 0.10)
        return min(score, 1.0)

    # ─── 競艇 分類ロジック ──────────────────────────────────────────────────

    def _classify_kyotei(
        self,
        race_data: dict[str, Any],
        filter_result: dict[str, Any],
    ) -> dict[str, Any]:
        """
        競艇の Tier を分類する（暫定実装: cmd_021データ拡充後に更新予定）。

        出典: true_ai_prediction_system_design.md Section 4（競艇Tier暫定基準）
        """
        cfg = self._kyotei_cfg
        reasons: list[str] = []
        negative_flags: list[str] = []
        entries = race_data.get("entries", [])

        # ── 1. SKIP: F保持選手チェック
        flying_threshold = int(
            cfg.get(
                "skip_flying_count_threshold",
                _DEFAULT_CONFIG["kyotei"]["skip_flying_count_threshold"],
            )
        )
        flying_entries = [
            e for e in entries if e.get("flying_count", 0) >= flying_threshold
        ]
        has_flying = bool(flying_entries)
        if has_flying:
            negative_flags.append(f"F保持選手 {len(flying_entries)}名含む")

        # ── 2. 逆指標チェック
        reverse_keywords: list[str] = cfg.get(
            "reverse_indicator_keywords",
            _DEFAULT_CONFIG["kyotei"]["reverse_indicator_keywords"],
        )
        comment = race_data.get("comment", "")
        matched_reverse = [kw for kw in reverse_keywords if kw in comment]
        has_reverse = bool(matched_reverse)
        if has_reverse:
            negative_flags.extend(
                [f"逆指標キーワード: 「{kw}」" for kw in matched_reverse]
            )

        # ── 3. 基本条件
        anchor_course = int(race_data.get("anchor_course", 0))
        venue = race_data.get("venue", "")

        # 軸艇のモーター勝率（entries の先頭艇から取得）
        anchor_entry = next(
            (e for e in entries if e.get("course", 0) == anchor_course), {}
        )
        motor_rate = float(anchor_entry.get("motor_win_rate", 0.0))

        # Tier S 条件
        tier_s_anchor:   int   = int(cfg.get("tier_s_anchor_course", 1))
        motor_threshold: float = float(
            cfg.get(
                "tier_s_motor_win_rate_threshold",
                _DEFAULT_CONFIG["kyotei"]["tier_s_motor_win_rate_threshold"],
            )
        )
        tier_s_venues: list[str] = cfg.get(
            "tier_s_preferred_venues",
            _DEFAULT_CONFIG["kyotei"]["tier_s_preferred_venues"],
        )
        is_s_anchor        = anchor_course == tier_s_anchor
        is_motor_good      = motor_rate >= motor_threshold
        is_preferred_venue = venue in tier_s_venues

        # Tier A 条件（1号艇 or 4号艇カド）
        tier_a_anchors: list[int] = cfg.get(
            "tier_a_anchor_courses",
            _DEFAULT_CONFIG["kyotei"]["tier_a_anchor_courses"],
        )
        is_a_anchor = anchor_course in tier_a_anchors

        filter_passed = bool(filter_result.get("passed", False))

        # ── 4. Tier 決定
        if has_flying or has_reverse:
            tier = "SKIP"
            filter_type = "none"
            confidence = self._kyotei_score(False, False, False, False, False, cfg)
            if has_flying:
                reasons.append("F保持選手含む → SKIP（競艇SKIP条件）")
            if has_reverse:
                reasons.append(
                    f"逆指標({', '.join(matched_reverse)}) → SKIP"
                )

        elif is_s_anchor and is_motor_good and is_preferred_venue:
            tier = "S"
            filter_type = "A"
            confidence = self._kyotei_score(True, True, True, True, True, cfg)
            reasons.append(
                f"{anchor_course}号艇軸 × モーター{motor_rate:.1f}%"
                f" × 優良場({venue}) → Tier S"
            )

        elif is_s_anchor and is_motor_good:
            tier = "A"
            filter_type = "A"
            confidence = self._kyotei_score(True, True, False, True, True, cfg)
            reasons.append(
                f"{anchor_course}号艇軸 × モーター{motor_rate:.1f}%"
                f"（優良場外: {venue}） → Tier A"
            )

        elif is_a_anchor and not has_reverse:
            tier = "A"
            filter_type = "A"
            confidence = self._kyotei_score(
                anchor_course == tier_s_anchor, False, is_preferred_venue, True, True, cfg
            )
            reasons.append(f"{anchor_course}号艇{'軸' if anchor_course == 1 else 'カド'} → Tier A")

        elif filter_passed:
            tier = "B"
            filter_type = "none"
            confidence = self._kyotei_score(
                is_s_anchor, is_motor_good, is_preferred_venue, True, True, cfg
            )
            reasons.append("フィルター通過・Tier A 条件不満足 → Tier B")
            if anchor_course not in tier_a_anchors:
                negative_flags.append(f"軸艇 {anchor_course}号艇（優先外）")

        else:
            tier = "SKIP"
            filter_type = "none"
            confidence = self._kyotei_score(
                is_s_anchor, is_motor_good, is_preferred_venue, True, True, cfg
            )
            negative_flags.append("フィルター不通過またはTier条件不満足")
            reasons.append("Tier 条件不満足・フィルター不通過 → SKIP")

        return {
            "tier":             tier,
            "filter_type":      filter_type,
            "confidence_score": round(confidence, 3),
            "reasons":          reasons,
            "negative_flags":   negative_flags,
        }

    def _kyotei_score(
        self,
        is_anchor:    bool,
        is_motor:     bool,
        is_pref_venue: bool,
        no_flying:    bool,
        no_reverse:   bool,
        cfg:          dict[str, Any],
    ) -> float:
        """競艇の confidence_score を重み付き合算で算出する（0.0〜1.0）。"""
        w = cfg.get("score_weights", _DEFAULT_CONFIG["kyotei"]["score_weights"])
        score = 0.0
        if is_anchor:     score += w.get("anchor_course",        0.30)
        if is_motor:      score += w.get("motor_win_rate",       0.25)
        if is_pref_venue: score += w.get("preferred_venue",      0.20)
        if no_reverse:    score += w.get("no_reverse_indicator", 0.15)
        if no_flying:     score += w.get("no_flying",            0.10)
        return min(score, 1.0)

    # ─── 設定ロード ────────────────────────────────────────────────────────

    def _load_config(
        self,
        config_base: str | None,
        sport: str,
    ) -> dict[str, Any]:
        """
        YAML 設定ファイルから sport 別の Tier 分類設定を読み込む。

        Args:
            config_base: 設定ファイルの基底ディレクトリ（例: "config"）。
            sport      : "keirin" | "kyotei"

        Returns:
            設定辞書。ファイルが存在しない場合は _DEFAULT_CONFIG の値を返す。
        """
        default = _DEFAULT_CONFIG.get(sport, {}).copy()

        if config_base is None:
            return default

        yaml_path = os.path.join(config_base, sport, "filters.yaml")
        if not os.path.exists(yaml_path):
            return default

        if not _YAML_AVAILABLE:
            return default

        with open(yaml_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        if not isinstance(data, dict):
            return default

        # YAML の値でデフォルトを上書き（存在するキーのみ）
        merged = default.copy()
        merged.update(data)
        return merged


# ─── 動作確認 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    classifier = TierClassifier(config_path=None)  # デフォルト設定で動作確認

    # ── Tier S テスト: 熊本×特選×S1×4名×400m×逆指標なし
    race_s = {
        "sport": "keirin",
        "race_type": "特選",
        "venue": "熊本",
        "track_length": 400,
        "race_number": 11,
        "comment": "点数絞って獲りにいく！S級決戦！",
        "entries": [
            {"grade": "S1"}, {"grade": "S1"}, {"grade": "S1"},
            {"grade": "S1"}, {"grade": "S2"}, {"grade": "A1"},
            {"grade": "A1"},
        ],
    }
    res_s = classifier.classify(race_s, {"passed": True})
    print("=== Tier S テスト（熊本×特選×S1×4名×400m）===")
    print(f"  tier            : {res_s['tier']}")
    print(f"  filter_type     : {res_s['filter_type']}")
    print(f"  confidence_score: {res_s['confidence_score']}")
    print(f"  reasons         : {res_s['reasons']}")
    print(f"  negative_flags  : {res_s['negative_flags']}")
    assert res_s["tier"] == "S", f"期待値 S != {res_s['tier']}"
    print("  → OK\n")

    # ── Tier A テスト: 防府×準決勝×S1×3名×333m×逆指標なし
    race_a = {
        "sport": "keirin",
        "race_type": "準決勝",
        "venue": "防府",
        "track_length": 333,
        "race_number": 10,
        "comment": "準決勝、S級上位が揃う一戦。",
        "entries": [
            {"grade": "S1"}, {"grade": "S1"}, {"grade": "S1"},
            {"grade": "S2"}, {"grade": "A1"}, {"grade": "A1"},
            {"grade": "A2"},
        ],
    }
    res_a = classifier.classify(race_a, {"passed": True})
    print("=== Tier A テスト（防府×準決勝×S1×3名×333m）===")
    print(f"  tier            : {res_a['tier']}")
    print(f"  filter_type     : {res_a['filter_type']}")
    print(f"  confidence_score: {res_a['confidence_score']}")
    print(f"  reasons         : {res_a['reasons']}")
    print(f"  negative_flags  : {res_a['negative_flags']}")
    assert res_a["tier"] == "A", f"期待値 A != {res_a['tier']}"
    print("  → OK\n")

    # ── Tier B テスト: 小倉×一般×S1×3名（優先race_type外）
    race_b = {
        "sport": "keirin",
        "race_type": "一般",
        "venue": "小倉",
        "track_length": 400,
        "race_number": 5,
        "comment": "S級選手が多く揃った一般戦。",
        "entries": [
            {"grade": "S1"}, {"grade": "S1"}, {"grade": "S1"},
            {"grade": "A1"}, {"grade": "A1"}, {"grade": "A1"},
            {"grade": "A2"},
        ],
    }
    res_b = classifier.classify(race_b, {"passed": True})
    print("=== Tier B テスト（小倉×一般×S1×3名, filter通過）===")
    print(f"  tier            : {res_b['tier']}")
    print(f"  filter_type     : {res_b['filter_type']}")
    print(f"  confidence_score: {res_b['confidence_score']}")
    print(f"  reasons         : {res_b['reasons']}")
    print(f"  negative_flags  : {res_b['negative_flags']}")
    assert res_b["tier"] == "B", f"期待値 B != {res_b['tier']}"
    print("  → OK\n")

    # ── Tier SKIP テスト: 逆指標「自信」含む（出典: reverse_indicator_patterns ROI=27%）
    race_skip = {
        "sport": "keirin",
        "race_type": "特選",
        "venue": "熊本",
        "track_length": 400,
        "race_number": 7,
        "comment": "自信あり！今日いちばん買いたいレース！",
        "entries": [
            {"grade": "S1"}, {"grade": "S1"}, {"grade": "S1"},
            {"grade": "S1"}, {"grade": "S2"}, {"grade": "A1"},
            {"grade": "A1"},
        ],
    }
    res_skip = classifier.classify(race_skip, {"passed": True})
    print("=== SKIP テスト（逆指標「自信」含む, filter通過でもSKIP）===")
    print(f"  tier            : {res_skip['tier']}")
    print(f"  filter_type     : {res_skip['filter_type']}")
    print(f"  confidence_score: {res_skip['confidence_score']}")
    print(f"  reasons         : {res_skip['reasons']}")
    print(f"  negative_flags  : {res_skip['negative_flags']}")
    assert res_skip["tier"] == "SKIP", f"期待値 SKIP != {res_skip['tier']}"
    print("  → OK\n")

    # ── 競艇 Tier S テスト
    race_kyotei_s = {
        "sport": "kyotei",
        "venue": "住之江",
        "race_number": 7,
        "anchor_course": 1,
        "comment": "1号艇がモーター好調、絞って獲りにいく。",
        "entries": [
            {"course": 1, "motor_win_rate": 45.2, "flying_count": 0},
            {"course": 2, "motor_win_rate": 38.1, "flying_count": 0},
            {"course": 3, "motor_win_rate": 40.5, "flying_count": 0},
            {"course": 4, "motor_win_rate": 36.0, "flying_count": 0},
            {"course": 5, "motor_win_rate": 41.0, "flying_count": 0},
            {"course": 6, "motor_win_rate": 37.8, "flying_count": 0},
        ],
    }
    res_ks = classifier.classify(race_kyotei_s, {"passed": True})
    print("=== 競艇 Tier S テスト（住之江×1号艇×モーター45.2%）===")
    print(f"  tier            : {res_ks['tier']}")
    print(f"  filter_type     : {res_ks['filter_type']}")
    print(f"  confidence_score: {res_ks['confidence_score']}")
    print(f"  reasons         : {res_ks['reasons']}")
    assert res_ks["tier"] == "S", f"期待値 S != {res_ks['tier']}"
    print("  → OK\n")

    # ── 競艇 SKIP テスト: F保持選手含む
    race_kyotei_skip = {
        "sport": "kyotei",
        "venue": "住之江",
        "race_number": 3,
        "anchor_course": 1,
        "comment": "F保持選手注意。",
        "entries": [
            {"course": 1, "motor_win_rate": 45.0, "flying_count": 0},
            {"course": 2, "motor_win_rate": 39.0, "flying_count": 1},  # F保持
            {"course": 3, "motor_win_rate": 41.0, "flying_count": 0},
            {"course": 4, "motor_win_rate": 37.0, "flying_count": 0},
            {"course": 5, "motor_win_rate": 38.0, "flying_count": 0},
            {"course": 6, "motor_win_rate": 36.0, "flying_count": 0},
        ],
    }
    res_kskip = classifier.classify(race_kyotei_skip, {"passed": True})
    print("=== 競艇 SKIP テスト（F保持選手含む）===")
    print(f"  tier            : {res_kskip['tier']}")
    print(f"  negative_flags  : {res_kskip['negative_flags']}")
    assert res_kskip["tier"] == "SKIP", f"期待値 SKIP != {res_kskip['tier']}"
    print("  → OK\n")

    print("=== 全テストケース PASSED ===")
