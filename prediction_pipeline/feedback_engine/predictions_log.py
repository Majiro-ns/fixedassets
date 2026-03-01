"""
feedback_engine/predictions_log.py — 教師データ JSONL 書込・読込ロジック

予想生成時に append() で記録し、翌日 fetch_results.py が update_result() で
的中/払戻結果を追記する。FeedbackAnalyzer はこのファイルを load() で読み込む。

設計書: true_ai_prediction_system_design.md Section 5「教師データ」
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any


# ─── 必須フィールド（設計書 Section 5 スキーマ準拠） ──────────────────────────
REQUIRED_FIELDS: tuple[str, ...] = (
    "prediction_id",
    "timestamp",
    "sport",
    "date",
    "venue",
    "race_number",
    "tier",
    "filter_type",
    "confidence_score",
    "pivot",
    "partners",
    "bet_type",
    "bet_amount",
    "total_investment",
    "reasoning",
    "features",
    "result",
    "model_version",
    "filter_version",
    "prompt_version",
)

# result フィールドの初期値（fetch_results.py が後から更新する）
RESULT_INITIAL: dict[str, Any] = {
    "fetched": False,
    "result_rank": None,
    "hit": None,
    "payout": None,
    "roi": None,
    "popular_hit": None,
    "upset_level": None,
}


class PredictionsLog:
    """
    教師データ JSONL（predictions_log.jsonl）の書込・読込・更新を担う。

    ファイル構成:
        {log_dir}/keirin_predictions_log.jsonl
        {log_dir}/kyotei_predictions_log.jsonl

    各行は JSON オブジェクト 1件（改行区切り）。
    設計書スキーマの全フィールドを保持し、フィードバックエンジンの教師データとして機能する。

    使用例::

        log = PredictionsLog("data/logs")
        log.append(record, sport="keirin")          # 予想生成時
        log.update_result(pid, "keirin", result)    # 翌日結果取得時
        records = log.load("keirin", "2026-02-24", "2026-03-02")  # 分析時
    """

    def __init__(self, log_dir: str) -> None:
        """
        Args:
            log_dir: JSONL ファイルを格納するディレクトリ（例: "data/logs"）。
                     ディレクトリが存在しない場合は自動作成する。
        """
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    # ─── 公開 API ─────────────────────────────────────────────────────────────

    def append(self, record: dict[str, Any], sport: str) -> None:
        """
        予想レコードを JSONL に追記する。

        スキーマバリデーションを実施し、不正なレコードは ValueError を送出する。
        result フィールドが未設定の場合は RESULT_INITIAL で初期化する。

        Args:
            record: 設計書 Section 5 スキーマ準拠の予想レコード辞書。
            sport:  "keirin" | "kyotei"（ファイル振り分けに使用）

        Raises:
            ValueError: 必須フィールドが欠如している場合。
        """
        if not self.validate_schema(record):
            missing = [f for f in REQUIRED_FIELDS if f not in record]
            raise ValueError(
                f"predictions_log.append: 必須フィールドが欠如しています: {missing}"
            )

        # result が未設定なら初期値を補完
        if "result" not in record or not record["result"]:
            record = dict(record)
            record["result"] = RESULT_INITIAL.copy()

        log_path = self._log_path(sport)
        with open(log_path, mode="a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load(
        self,
        sport: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """
        JSONL から指定スポーツ・期間のレコードを読み込む。

        Args:
            sport:       "keirin" | "kyotei"
            start_date:  開始日 "YYYY-MM-DD"
            end_date:    終了日 "YYYY-MM-DD"（inclusive）

        Returns:
            条件に一致するレコードのリスト（日付昇順）。
            ファイルが存在しない場合は空リストを返す。
        """
        start = date.fromisoformat(start_date)
        end   = date.fromisoformat(end_date)
        log_path = self._log_path(sport)

        records: list[dict[str, Any]] = []
        if not os.path.exists(log_path):
            return records

        with open(log_path, mode="r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                rec_date_str = rec.get("date", "")
                if not rec_date_str:
                    continue
                try:
                    rec_date = date.fromisoformat(rec_date_str)
                except ValueError:
                    continue

                if start <= rec_date <= end:
                    records.append(rec)

        return records

    def update_result(
        self,
        prediction_id: str,
        sport: str,
        result: dict[str, Any],
    ) -> bool:
        """
        既存レコードの result フィールドを更新する。

        prediction_id でレコードを特定し、result フィールドを上書きする。
        ファイルを全行読み込んで書き直す（ログサイズが大きくなるまでは十分な速度）。

        Args:
            prediction_id: 更新対象のレコード ID（例: "keirin_20260224_熊本_11R"）
            sport:         "keirin" | "kyotei"
            result:        更新する result 辞書。以下のキーを想定:
                               fetched    : bool
                               result_rank: list[int] | None
                               hit        : bool | None
                               payout     : int | None
                               roi        : float | None
                               popular_hit: bool | None
                               upset_level: str | None

        Returns:
            True: 更新成功。False: prediction_id が見つからなかった場合。
        """
        log_path = self._log_path(sport)
        if not os.path.exists(log_path):
            return False

        lines: list[str] = []
        updated = False

        with open(log_path, mode="r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    lines.append(line)
                    continue
                try:
                    rec = json.loads(stripped)
                except json.JSONDecodeError:
                    lines.append(line)
                    continue

                if rec.get("prediction_id") == prediction_id:
                    # result フィールドをマージ更新（既存キーを保持しつつ上書き）
                    existing_result = rec.get("result", {})
                    if not isinstance(existing_result, dict):
                        existing_result = {}
                    existing_result.update(result)
                    rec["result"] = existing_result
                    lines.append(json.dumps(rec, ensure_ascii=False) + "\n")
                    updated = True
                else:
                    lines.append(line if line.endswith("\n") else line + "\n")

        if updated:
            with open(log_path, mode="w", encoding="utf-8") as fh:
                fh.writelines(lines)

        return updated

    def validate_schema(self, record: dict[str, Any]) -> bool:
        """
        レコードが必須フィールドを全て含むか検証する。

        Args:
            record: 検証対象の辞書

        Returns:
            True: 全必須フィールドが存在する。False: 欠如フィールドあり。
        """
        return all(field in record for field in REQUIRED_FIELDS)

    def stats(self, sport: str) -> dict[str, Any]:
        """
        JSONL ファイルの簡易統計を返す。

        Args:
            sport: "keirin" | "kyotei"

        Returns:
            {"total": int, "fetched": int, "pending": int, "log_path": str}
        """
        log_path = self._log_path(sport)
        if not os.path.exists(log_path):
            return {"total": 0, "fetched": 0, "pending": 0, "log_path": log_path}

        total = fetched = 0
        with open(log_path, mode="r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                total += 1
                if rec.get("result", {}).get("fetched", False):
                    fetched += 1

        return {
            "total":    total,
            "fetched":  fetched,
            "pending":  total - fetched,
            "log_path": log_path,
        }

    # ─── 内部ヘルパー ─────────────────────────────────────────────────────────

    def _log_path(self, sport: str) -> str:
        """sport に対応する JSONL ファイルパスを返す。"""
        return os.path.join(self.log_dir, f"{sport}_predictions_log.jsonl")


# ─── 動作確認 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import shutil

    print("=" * 60)
    print("PredictionsLog 動作確認")
    print("=" * 60)

    tmp_dir = tempfile.mkdtemp(prefix="predictions_log_test_")
    try:
        log = PredictionsLog(tmp_dir)

        # ── テスト用レコード（設計書 Section 5 スキーマ）
        base_record: dict[str, Any] = {
            "prediction_id":   "keirin_20260224_熊本_11R",
            "timestamp":       "2026-02-24T06:15:00",
            "sport":           "keirin",
            "date":            "2026-02-24",
            "venue":           "熊本",
            "race_number":     11,
            "grade":           "G1",
            "race_type":       "二次予選",
            "tier":            "S",
            "filter_type":     "A",
            "confidence_score": 0.82,
            "pivot":           {"number": 3, "name": "松浦悠士", "score": 117.50},
            "partners":        [
                {"number": 1, "name": "脇本雄太",  "score": 119.00},
                {"number": 7, "name": "新山響平",  "score": 113.20},
            ],
            "bet_type":        "3連複ながし",
            "bet_amount":      1200,
            "total_investment": 2400,
            "reasoning":       "S級二予×熊本優良場×逆指標なし",
            "cre_keywords_matched":  ["絞れる"],
            "cre_keywords_negative": [],
            "features": {
                "class":       "S",
                "race_type":   "二次予選",
                "bank_length": 400,
                "day_of_week": "月",
                "race_hour":   16,
            },
            "result":          {},   # 初期値は append() が補完
            "model_version":   "v1.0.0",
            "filter_version":  "v1.0.0",
            "prompt_version":  "v1.0.0",
        }

        # ── [1] append テスト
        print("\n[1] append テスト")
        log.append(base_record, sport="keirin")
        # 2件目: 別レース
        rec2 = dict(base_record)
        rec2["prediction_id"] = "keirin_20260224_防府_7R"
        rec2["date"] = "2026-02-24"
        rec2["venue"] = "防府"
        rec2["race_number"] = 7
        rec2["tier"] = "A"
        rec2["confidence_score"] = 0.65
        log.append(rec2, sport="keirin")
        # 3件目: 別日
        rec3 = dict(base_record)
        rec3["prediction_id"] = "keirin_20260301_熊本_9R"
        rec3["date"] = "2026-03-01"
        rec3["race_number"] = 9
        log.append(rec3, sport="keirin")
        s = log.stats("keirin")
        print(f"  追記後 stats: total={s['total']}, fetched={s['fetched']}, pending={s['pending']}")
        assert s["total"] == 3, f"total 期待値3 != {s['total']}"
        assert s["fetched"] == 0
        print("  → OK")

        # ── [2] load テスト（期間フィルター）
        print("\n[2] load テスト（2026-02-24〜2026-02-28）")
        records = log.load("keirin", "2026-02-24", "2026-02-28")
        print(f"  取得件数: {len(records)}")
        assert len(records) == 2, f"期待値2 != {len(records)}"
        ids = [r["prediction_id"] for r in records]
        assert "keirin_20260224_熊本_11R" in ids
        assert "keirin_20260224_防府_7R" in ids
        print(f"  IDs: {ids}")
        print("  → OK")

        # ── [3] update_result テスト
        print("\n[3] update_result テスト")
        result_data = {
            "fetched":     True,
            "result_rank": [3, 1, 7],
            "hit":         True,
            "payout":      3300,
            "roi":         1.375,
            "popular_hit": False,
            "upset_level": "中穴",
        }
        ok = log.update_result("keirin_20260224_熊本_11R", "keirin", result_data)
        assert ok, "update_result が False を返した"
        records_after = log.load("keirin", "2026-02-24", "2026-02-24")
        updated_rec = next(
            r for r in records_after
            if r["prediction_id"] == "keirin_20260224_熊本_11R"
        )
        assert updated_rec["result"]["fetched"] is True
        assert updated_rec["result"]["hit"] is True
        assert updated_rec["result"]["payout"] == 3300
        print(f"  更新後 result: {updated_rec['result']}")
        s2 = log.stats("keirin")
        assert s2["fetched"] == 1, f"fetched 期待値1 != {s2['fetched']}"
        print(f"  stats 更新: total={s2['total']}, fetched={s2['fetched']}, pending={s2['pending']}")
        print("  → OK")

        # ── [4] validate_schema テスト
        print("\n[4] validate_schema テスト")
        assert log.validate_schema(base_record) is True
        invalid = {"prediction_id": "x", "sport": "keirin"}  # 必須フィールド欠如
        assert log.validate_schema(invalid) is False
        print("  有効レコード → True  ✓")
        print("  不正レコード → False ✓")
        print("  → OK")

        # ── [5] 不正レコードの append は ValueError
        print("\n[5] 不正レコード append → ValueError テスト")
        try:
            log.append({"prediction_id": "bad"}, sport="keirin")
            assert False, "ValueError が発生しなかった"
        except ValueError as exc:
            print(f"  ValueError 確認: {exc}")
        print("  → OK")

        # ── [6] 存在しない prediction_id の update は False
        print("\n[6] 存在しない prediction_id の update → False テスト")
        result_ng = log.update_result("non_existent_id", "keirin", {"fetched": True})
        assert result_ng is False
        print("  → OK")

        print("\n" + "=" * 60)
        print("全テストケース PASSED")
        print("=" * 60)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
