"""
feedback_engine/optimizer.py — フィルター自動最適化エンジン

analyzer.py の分析結果に基づき、CREフィルター条件（filters.yaml）を
自動で最適化する。「予想→結果→分析→フィルター改善」学習ループの心臓部。

実行タイミング: 毎月1日（monthly_optimize.py から呼び出し）
安全装置:
  - 1回の更新で変更は最大3件まで
  - N閾値未満の変更は保留
  - dry_run=True がデフォルト（殿の承認後に False で再実行）
  - 変更前の filters.yaml をバックアップ
  - 変更ログを data/feedback/filter_changelog.jsonl に記録

外部依存: pyyaml のみ
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Any

import yaml


# ──────────────────────────────────────────────
# 最適化ルール定数
# ──────────────────────────────────────────────

# 場の除外 / 除外解除
VENUE_EXCLUDE_ROI_THRESHOLD = 60.0   # ROI < 60% かつ N >= 20 → 除外追加
VENUE_RESTORE_ROI_THRESHOLD = 100.0  # ROI > 100% かつ N >= 20 → 除外解除
VENUE_MIN_N = 20

# 逆指標キーワード追加 / 解除
KEYWORD_EXCLUDE_ROI_THRESHOLD = 50.0  # ROI < 50% かつ N >= 10 → 逆指標追加
KEYWORD_RESTORE_ROI_THRESHOLD = 80.0  # ROI > 80% かつ N >= 20 → 解除候補（要確認フラグ付き）
KEYWORD_EXCLUDE_MIN_N = 10
KEYWORD_RESTORE_MIN_N = 20

# レース種別除外 / 解除
RACE_TYPE_EXCLUDE_ROI_THRESHOLD = 70.0   # ROI < 70% かつ N >= 15 → 除外追加
RACE_TYPE_RESTORE_ROI_THRESHOLD = 110.0  # ROI > 110% かつ N >= 15 → 解除
RACE_TYPE_MIN_N = 15

# Tier目標ROI
TIER_S_TARGET_ROI = 130.0
TIER_A_TARGET_ROI = 105.0
TIER_B_TARGET_ROI = 95.0

# 安全装置: 1回の更新で変更できる最大件数
MAX_CHANGES_PER_UPDATE = 3


class FilterOptimizer:
    """
    月次フィルター自動最適化エンジン。

    analyzer.py の月次分析結果（複数週分を統合したもの）を受け取り、
    filters.yaml への変更案を生成・適用する。

    Args:
        config_dir: prediction_pipeline/config/ ディレクトリのパス。
                    配下に keirin/filters.yaml, kyotei/filters.yaml が存在すること。

    Usage:
        optimizer = FilterOptimizer(config_dir="/path/to/config")
        changes = optimizer.optimize("keirin", monthly_analysis_result)
        result = optimizer.apply_changes("keirin", changes, dry_run=True)
    """

    def __init__(self, config_dir: str) -> None:
        self.config_dir = config_dir
        # data/feedbackはconfig_dirの2階層上 → prediction_pipeline/data/feedback/
        pipeline_root = os.path.dirname(config_dir)
        self.feedback_dir = os.path.join(pipeline_root, "data", "feedback")
        self.changelog_path = os.path.join(self.feedback_dir, "filter_changelog.jsonl")
        os.makedirs(self.feedback_dir, exist_ok=True)

    # ──────────────────────────────────────────────
    # 公開メソッド
    # ──────────────────────────────────────────────

    def optimize(self, sport: str, analysis_result: dict) -> dict:
        """
        月次分析結果に基づきフィルター最適化案を生成する。

        変更の優先度は信頼度（confidence）の高い順に並び替え、
        安全装置として最大 MAX_CHANGES_PER_UPDATE 件に絞り込む。

        Args:
            sport: "keirin" または "kyotei"
            analysis_result: analyzer.py の analyze_weekly() / analyze_monthly()
                             が返す辞書。以下のキーを参照する:
                               - by_venue: dict[場名, {"roi": float, "n": int, "excluded": bool}]
                               - keyword_analysis: dict[キーワード, {"roi": float, "n": int, "is_negative": bool}]
                               - by_race_type: dict[種別名, {"roi": float, "n": int, "excluded": bool}]
                               - tier_boundary_check: dict[tier名, {"actual_roi": float}]

        Returns:
            {
                "sport": "keirin",
                "changes": [
                    {
                        "type": "venue_add_exclude",
                        "target": "玉野",
                        "reason": "ROI 24.5% (N=27)",
                        "confidence": "high"
                    },
                    ...
                ],
                "tier_adjustments": {
                    "S": {"current_roi": 118.0, "target_roi": 130.0, "action": "tighten"},
                    ...
                },
                "new_version": "v1.1.0",
                "changelog": "2026-03-01: 玉野を除外場に追加 / ...",
                "skipped": [
                    {"type": "venue_add_exclude", "target": "大宮", "reason": "N=8 < 閾値20"}
                ]
            }
        """
        current_version = self._load_current_version(sport)
        all_changes: list[dict] = []

        # 各カテゴリの変更候補を収集
        all_changes.extend(self._check_venue_changes(analysis_result))
        all_changes.extend(self._check_keyword_changes(analysis_result))
        all_changes.extend(self._check_race_type_changes(analysis_result))

        # 信頼度順にソート (high > medium > low)
        confidence_rank = {"high": 0, "medium": 1, "low": 2}
        all_changes.sort(key=lambda c: confidence_rank.get(c.get("confidence", "low"), 2))

        # 最大3件に絞り込み（安全装置）
        applied_changes = all_changes[:MAX_CHANGES_PER_UPDATE]
        skipped_changes = all_changes[MAX_CHANGES_PER_UPDATE:]

        # Tier境界の調整案を生成（changes件数制限の対象外: 設定値変更ではなくレポートのみ）
        tier_adjustments = self._adjust_tier_boundaries(analysis_result)

        # 新バージョンを計算
        new_version = self._increment_version(current_version) if applied_changes else current_version

        # changelog文字列を生成
        today = datetime.now().strftime("%Y-%m-%d")
        changelog_entries = [f"{today}: {c['target']}を{self._change_type_label(c['type'])}" for c in applied_changes]
        changelog = " / ".join(changelog_entries) if changelog_entries else "変更なし"

        return {
            "sport": sport,
            "changes": applied_changes,
            "tier_adjustments": tier_adjustments,
            "new_version": new_version,
            "changelog": changelog,
            "skipped": [
                {"type": c["type"], "target": c["target"], "reason": f"優先度3件超過のため保留"}
                for c in skipped_changes
            ],
        }

    def apply_changes(self, sport: str, changes: dict, dry_run: bool = True) -> dict:
        """
        最適化案を filters.yaml に適用する。

        安全装置:
          - dry_run=True（デフォルト）では実際の書き込みは行わない
          - 適用前に filters.yaml のバックアップを自動作成
          - 変更ログを data/feedback/filter_changelog.jsonl に記録
          - 1回の更新で変更できる件数は MAX_CHANGES_PER_UPDATE 件まで

        Args:
            sport: "keirin" または "kyotei"
            changes: optimize() が返した辞書
            dry_run: True なら変更内容を表示するだけで実際には書き込まない

        Returns:
            {
                "dry_run": bool,
                "sport": str,
                "applied": [変更内容リスト],
                "backup_path": str または None（dry_run=True 時は None）,
                "new_version": str,
                "changelog": str
            }
        """
        change_list: list[dict] = changes.get("changes", [])
        if len(change_list) > MAX_CHANGES_PER_UPDATE:
            change_list = change_list[:MAX_CHANGES_PER_UPDATE]

        filters_path = self._get_filters_path(sport)

        if dry_run:
            print(f"[DRY RUN] {sport} フィルター最適化案:")
            if not change_list:
                print("  変更なし")
            for i, c in enumerate(change_list, 1):
                print(f"  [{i}] {self._change_type_label(c['type'])}: {c['target']}")
                print(f"       理由: {c['reason']}  信頼度: {c['confidence']}")
            print(f"\n  新バージョン: {changes['new_version']}")
            print(f"  Tier調整案: {changes['tier_adjustments']}")
            print("\n  ※ dry_run=False で実際に適用されます。")
            return {
                "dry_run": True,
                "sport": sport,
                "applied": change_list,
                "backup_path": None,
                "new_version": changes["new_version"],
                "changelog": changes["changelog"],
            }

        # ─── 本番適用 ───
        if not change_list:
            return {
                "dry_run": False,
                "sport": sport,
                "applied": [],
                "backup_path": None,
                "new_version": changes["new_version"],
                "changelog": "変更なし",
            }

        # バックアップ作成
        backup_path = self._backup_config(sport)

        # filters.yaml を読み込んで変更を適用
        with open(filters_path, "r", encoding="utf-8") as f:
            filters_data = yaml.safe_load(f) or {}

        for c in change_list:
            filters_data = self._apply_single_change(filters_data, c)

        # バージョンを更新
        filters_data["version"] = changes["new_version"]
        filters_data.setdefault("changelog", [])
        filters_data["changelog"].append(changes["changelog"])

        # 書き込み
        with open(filters_path, "w", encoding="utf-8") as f:
            yaml.dump(filters_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # 変更ログを記録
        for c in change_list:
            self._log_change(sport, {**c, "version": changes["new_version"], "applied_at": datetime.now().isoformat()})

        print(f"[APPLIED] {sport} フィルター更新完了: {changes['new_version']}")
        return {
            "dry_run": False,
            "sport": sport,
            "applied": change_list,
            "backup_path": backup_path,
            "new_version": changes["new_version"],
            "changelog": changes["changelog"],
        }

    # ──────────────────────────────────────────────
    # プライベートメソッド: 変更候補の判定
    # ──────────────────────────────────────────────

    def _check_venue_changes(self, analysis: dict) -> list:
        """
        場の除外/解除を判定する。

        除外追加: ROI < VENUE_EXCLUDE_ROI_THRESHOLD (60%) かつ N >= VENUE_MIN_N (20)
        除外解除: ROI > VENUE_RESTORE_ROI_THRESHOLD (100%) かつ N >= VENUE_MIN_N (20)
            ただし現在除外中の場のみが解除対象。

        Returns:
            変更候補リスト（N閾値未満は除外）
        """
        by_venue: dict[str, dict] = analysis.get("by_venue", {})
        changes: list[dict] = []

        for venue, stats in by_venue.items():
            roi = stats.get("roi", 100.0)
            n = stats.get("n", 0)
            is_excluded = stats.get("excluded", False)

            if n < VENUE_MIN_N:
                # N不足 → スキップ（早計な判断を防ぐ）
                continue

            if not is_excluded and roi < VENUE_EXCLUDE_ROI_THRESHOLD:
                confidence = "high" if n >= VENUE_MIN_N * 2 else "medium"
                changes.append({
                    "type": "venue_add_exclude",
                    "target": venue,
                    "reason": f"ROI {roi:.1f}% (N={n})",
                    "confidence": confidence,
                })
            elif is_excluded and roi > VENUE_RESTORE_ROI_THRESHOLD:
                confidence = "high" if n >= VENUE_MIN_N * 2 else "medium"
                changes.append({
                    "type": "venue_remove_exclude",
                    "target": venue,
                    "reason": f"ROI {roi:.1f}% (N={n}) — 除外解除",
                    "confidence": confidence,
                })

        return changes

    def _check_keyword_changes(self, analysis: dict) -> list:
        """
        逆指標キーワードの追加/解除を判定する。

        追加: ROI < KEYWORD_EXCLUDE_ROI_THRESHOLD (50%) かつ N >= KEYWORD_EXCLUDE_MIN_N (10)
        解除: ROI > KEYWORD_RESTORE_ROI_THRESHOLD (80%) かつ N >= KEYWORD_RESTORE_MIN_N (20)
              ※ 解除候補は confidence="low" + requires_review フラグを付与して
                 殿の確認を促す。

        Returns:
            変更候補リスト
        """
        keyword_analysis: dict[str, dict] = analysis.get("keyword_analysis", {})
        changes: list[dict] = []

        for keyword, stats in keyword_analysis.items():
            roi = stats.get("roi", 100.0)
            n = stats.get("n", 0)
            is_negative = stats.get("is_negative", False)

            # 新規逆指標追加
            if not is_negative and n >= KEYWORD_EXCLUDE_MIN_N and roi < KEYWORD_EXCLUDE_ROI_THRESHOLD:
                confidence = "high" if n >= KEYWORD_EXCLUDE_MIN_N * 2 else "medium"
                changes.append({
                    "type": "keyword_add_negative",
                    "target": keyword,
                    "reason": f"ROI {roi:.1f}% (N={n})",
                    "confidence": confidence,
                })
            # 既存逆指標の解除候補
            elif is_negative and n >= KEYWORD_RESTORE_MIN_N and roi > KEYWORD_RESTORE_ROI_THRESHOLD:
                changes.append({
                    "type": "keyword_remove_negative",
                    "target": keyword,
                    "reason": f"ROI {roi:.1f}% (N={n}) — 解除候補",
                    "confidence": "low",    # 慎重に: 必ず要確認
                    "requires_review": True,
                })

        return changes

    def _check_race_type_changes(self, analysis: dict) -> list:
        """
        レース種別の除外/解除を判定する。

        除外追加: ROI < RACE_TYPE_EXCLUDE_ROI_THRESHOLD (70%) かつ N >= RACE_TYPE_MIN_N (15)
        除外解除: ROI > RACE_TYPE_RESTORE_ROI_THRESHOLD (110%) かつ N >= RACE_TYPE_MIN_N (15)

        Returns:
            変更候補リスト
        """
        by_race_type: dict[str, dict] = analysis.get("by_race_type", {})
        changes: list[dict] = []

        for race_type, stats in by_race_type.items():
            roi = stats.get("roi", 100.0)
            n = stats.get("n", 0)
            is_excluded = stats.get("excluded", False)

            if n < RACE_TYPE_MIN_N:
                continue

            if not is_excluded and roi < RACE_TYPE_EXCLUDE_ROI_THRESHOLD:
                confidence = "high" if n >= RACE_TYPE_MIN_N * 2 else "medium"
                changes.append({
                    "type": "race_type_add_exclude",
                    "target": race_type,
                    "reason": f"ROI {roi:.1f}% (N={n})",
                    "confidence": confidence,
                })
            elif is_excluded and roi > RACE_TYPE_RESTORE_ROI_THRESHOLD:
                confidence = "medium" if n >= RACE_TYPE_MIN_N * 2 else "low"
                changes.append({
                    "type": "race_type_remove_exclude",
                    "target": race_type,
                    "reason": f"ROI {roi:.1f}% (N={n}) — 除外解除",
                    "confidence": confidence,
                })

        return changes

    def _adjust_tier_boundaries(self, analysis: dict) -> dict:
        """
        Tier境界の調整案を生成する。

        目標ROI:
          S: > 130% (TIER_S_TARGET_ROI)
          A: > 105% (TIER_A_TARGET_ROI)
          B: > 95%  (TIER_B_TARGET_ROI)

        実際のROIが目標を下回っている場合、どのような条件変更が推奨されるかを
        テキスト形式でレポートする（自動適用はせず、殿の判断を仰ぐ）。

        Returns:
            {
                "S": {"actual_roi": float, "target_roi": float, "action": str, "note": str},
                "A": {...},
                "B": {...}
            }
        """
        tier_check: dict[str, dict] = analysis.get("tier_boundary_check", {})
        adjustments: dict[str, dict] = {}

        tier_targets = {
            "S": TIER_S_TARGET_ROI,
            "A": TIER_A_TARGET_ROI,
            "B": TIER_B_TARGET_ROI,
        }
        tier_actions = {
            "S": {
                "below": "tighten",
                "note_below": "S条件に「優良場限定」を追加、または500m場を除外することを推奨",
                "ok": "maintain",
                "note_ok": "現行条件を維持",
            },
            "A": {
                "below": "tighten",
                "note_below": "A条件を厳格化、またはROI改善まで一時的にB評価へ降格を検討",
                "ok": "maintain",
                "note_ok": "現行条件を維持",
            },
            "B": {
                "below": "demote",
                "note_below": "B評価のROIがSKIP水準。SKIPに降格するか条件を見直すことを推奨",
                "ok": "maintain",
                "note_ok": "現行条件を維持",
            },
        }

        for tier, target_roi in tier_targets.items():
            stats = tier_check.get(tier, {})
            actual_roi = stats.get("actual_roi", None)

            if actual_roi is None:
                adjustments[tier] = {
                    "actual_roi": None,
                    "target_roi": target_roi,
                    "action": "insufficient_data",
                    "note": "データ不足（N < 閾値）。来月以降に判定",
                }
                continue

            if actual_roi < target_roi:
                adjustments[tier] = {
                    "actual_roi": actual_roi,
                    "target_roi": target_roi,
                    "action": tier_actions[tier]["below"],
                    "note": tier_actions[tier]["note_below"],
                }
            else:
                adjustments[tier] = {
                    "actual_roi": actual_roi,
                    "target_roi": target_roi,
                    "action": tier_actions[tier]["ok"],
                    "note": tier_actions[tier]["note_ok"],
                }

        return adjustments

    # ──────────────────────────────────────────────
    # プライベートメソッド: ファイル操作
    # ──────────────────────────────────────────────

    def _backup_config(self, sport: str) -> str:
        """
        filters.yaml のタイムスタンプ付きバックアップを作成する。

        バックアップ先: config/{sport}/filters_backup_{YYYYMMDD_HHMMSS}.yaml

        Returns:
            バックアップファイルのパス
        """
        filters_path = self._get_filters_path(sport)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.dirname(filters_path)
        backup_path = os.path.join(backup_dir, f"filters_backup_{timestamp}.yaml")
        shutil.copy2(filters_path, backup_path)
        print(f"[BACKUP] {filters_path} → {backup_path}")
        return backup_path

    def _log_change(self, sport: str, change: dict) -> None:
        """
        変更ログを data/feedback/filter_changelog.jsonl に追記する（JSONL形式）。

        各行が1件の変更レコードを表す。ロールバック時の参照に使用する。

        Args:
            sport: "keirin" または "kyotei"
            change: 変更内容の辞書
        """
        record: dict[str, Any] = {
            "sport": sport,
            "logged_at": datetime.now().isoformat(),
            **change,
        }
        with open(self.changelog_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ──────────────────────────────────────────────
    # プライベートメソッド: ヘルパー
    # ──────────────────────────────────────────────

    def _get_filters_path(self, sport: str) -> str:
        """filters.yaml の絶対パスを返す。"""
        return os.path.join(self.config_dir, sport, "filters.yaml")

    def _load_current_version(self, sport: str) -> str:
        """
        現在の filters.yaml から version を読み込む。

        バージョンフィールドが存在しない場合は "v1.0.0" を返す。
        """
        filters_path = self._get_filters_path(sport)
        if not os.path.exists(filters_path):
            return "v1.0.0"
        with open(filters_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("version", "v1.0.0")

    @staticmethod
    def _increment_version(version: str) -> str:
        """
        セマンティックバージョン（vX.Y.Z）のパッチ番号をインクリメントする。

        例: "v1.0.0" → "v1.0.1"、"v1.0.9" → "v1.0.10"
        パース失敗時は元のバージョン文字列をそのまま返す。
        """
        try:
            v = version.lstrip("v")
            parts = v.split(".")
            parts[-1] = str(int(parts[-1]) + 1)
            return "v" + ".".join(parts)
        except (ValueError, IndexError):
            return version

    @staticmethod
    def _change_type_label(change_type: str) -> str:
        """変更タイプを日本語ラベルに変換する。"""
        labels = {
            "venue_add_exclude": "除外場に追加",
            "venue_remove_exclude": "除外場から解除",
            "keyword_add_negative": "逆指標キーワードに追加",
            "keyword_remove_negative": "逆指標キーワードから解除",
            "race_type_add_exclude": "除外レース種別に追加",
            "race_type_remove_exclude": "除外レース種別から解除",
        }
        return labels.get(change_type, change_type)

    def _apply_single_change(self, filters_data: dict, change: dict) -> dict:
        """
        1件の変更を filters_data に適用して返す。

        競輪・競艇でフィルター構造が異なるため、キーの存在を確認しながら安全に操作する。

        Args:
            filters_data: yaml.safe_load で読み込んだフィルター辞書
            change: {type, target, reason, confidence} の変更辞書

        Returns:
            変更後の filters_data
        """
        change_type = change["type"]
        target = change["target"]

        if change_type == "venue_add_exclude":
            exclude_list = filters_data.setdefault("excluded_venues", [])
            if target not in exclude_list:
                exclude_list.append(target)

        elif change_type == "venue_remove_exclude":
            exclude_list = filters_data.get("excluded_venues", [])
            if target in exclude_list:
                exclude_list.remove(target)

        elif change_type == "keyword_add_negative":
            neg_list = filters_data.setdefault("negative_keywords", [])
            if target not in neg_list:
                neg_list.append(target)

        elif change_type == "keyword_remove_negative":
            neg_list = filters_data.get("negative_keywords", [])
            if target in neg_list:
                neg_list.remove(target)
            # 解除候補を requires_review リストに記録
            review_list = filters_data.setdefault("keywords_requires_review", [])
            if target not in review_list:
                review_list.append(target)

        elif change_type == "race_type_add_exclude":
            exclude_list = filters_data.setdefault("excluded_race_types", [])
            if target not in exclude_list:
                exclude_list.append(target)

        elif change_type == "race_type_remove_exclude":
            exclude_list = filters_data.get("excluded_race_types", [])
            if target in exclude_list:
                exclude_list.remove(target)

        return filters_data


# ──────────────────────────────────────────────
# __main__ テストブロック
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import os as _os

    # config_dir は prediction_pipeline/config/ を想定
    _script_dir = _os.path.dirname(_os.path.abspath(__file__))
    _config_dir = _os.path.join(_os.path.dirname(_script_dir), "config")

    optimizer = FilterOptimizer(config_dir=_config_dir)

    # ── モック: 月次分析結果 ──────────────────────────────
    mock_analysis = {
        "by_venue": {
            # 除外追加候補: ROI < 60% かつ N >= 20
            "玉野":  {"roi": 24.5,  "n": 27,  "excluded": False},
            # 除外解除候補: 除外中だが ROI > 100% かつ N >= 20
            "小倉":  {"roi": 112.3, "n": 22,  "excluded": True},
            # N不足 → スキップ
            "大宮":  {"roi": 35.0,  "n": 8,   "excluded": False},
            # 正常 → 変更なし
            "熊本":  {"roi": 169.0, "n": 45,  "excluded": False},
        },
        "keyword_analysis": {
            # 逆指標追加候補: ROI < 50% かつ N >= 10
            "自信":       {"roi": 27.0, "n": 46, "is_negative": False},
            # 逆指標解除候補: ROI > 80% かつ N >= 20（要確認）
            "大本命":     {"roi": 88.0, "n": 25, "is_negative": True},
            # N不足 → スキップ
            "絶対軸":     {"roi": 40.0, "n": 5,  "is_negative": False},
        },
        "by_race_type": {
            # 除外追加候補: ROI < 70% かつ N >= 15
            "初日一般": {"roi": 55.0, "n": 18, "excluded": False},
            # 正常
            "二次予選": {"roi": 144.0, "n": 60, "excluded": False},
        },
        "tier_boundary_check": {
            "S": {"actual_roi": 118.0},  # 目標130%を下回っている → tighten
            "A": {"actual_roi": 108.0},  # 目標105%を上回っている → maintain
            "B": {"actual_roi": 91.0},   # 目標95%を下回っている → demote推奨
        },
    }

    print("=" * 60)
    print("TEST 1: optimize() — 競輪フィルター最適化案を生成")
    print("=" * 60)
    result = optimizer.optimize("keirin", mock_analysis)
    print(f"スポーツ: {result['sport']}")
    print(f"新バージョン: {result['new_version']}")
    print(f"changelog: {result['changelog']}")
    print(f"\n変更候補 ({len(result['changes'])}件 / 最大{MAX_CHANGES_PER_UPDATE}件):")
    for c in result["changes"]:
        print(f"  - [{c['confidence']}] {c['type']}: {c['target']}  ({c['reason']})")
    if result["skipped"]:
        print(f"\n保留 ({len(result['skipped'])}件):")
        for s in result["skipped"]:
            print(f"  - {s['type']}: {s['target']}  ({s['reason']})")
    print(f"\nTier調整案:")
    for tier, adj in result["tier_adjustments"].items():
        print(f"  Tier {tier}: 実績ROI={adj.get('actual_roi')}%  目標={adj['target_roi']}%  "
              f"→ {adj['action']}  ({adj['note']})")

    print()
    print("=" * 60)
    print("TEST 2: apply_changes(dry_run=True) — 適用プレビュー")
    print("=" * 60)
    apply_result = optimizer.apply_changes("keirin", result, dry_run=True)
    print(f"\n結果: dry_run={apply_result['dry_run']}, 変更件数={len(apply_result['applied'])}")

    print()
    print("=" * 60)
    print("TEST 3: バックアップとログの動作確認")
    print("=" * 60)
    # バックアップ先ファイルの存在確認（filters.yamlが存在する場合のみ）
    _filters_path = _os.path.join(_config_dir, "keirin", "filters.yaml")
    if _os.path.exists(_filters_path):
        _backup = optimizer._backup_config("keirin")
        print(f"バックアップ作成: {_backup}")
        assert _os.path.exists(_backup), "バックアップファイルが見つかりません"
        print("バックアップ確認: OK")
    else:
        print(f"filters.yaml が存在しないためバックアップテストをスキップ: {_filters_path}")

    # ログ書き込みテスト
    _test_log = {
        "type": "test_log",
        "target": "TEST",
        "reason": "__main__ テスト実行",
        "confidence": "high",
        "version": "v0.0.0",
        "applied_at": datetime.now().isoformat(),
    }
    optimizer._log_change("keirin", _test_log)
    assert _os.path.exists(optimizer.changelog_path), "changelogが作成されていません"
    with open(optimizer.changelog_path, "r", encoding="utf-8") as _f:
        _last_line = _f.readlines()[-1]
    _parsed = json.loads(_last_line)
    assert _parsed["target"] == "TEST", "ログ内容が不正です"
    print(f"ログ書き込み確認: OK  ({optimizer.changelog_path})")

    print()
    print("=" * 60)
    print("全テスト PASS")
    print("=" * 60)
