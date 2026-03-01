"""
tests/test_roi_tracker.py
=========================
roi_tracker.py の単体テスト。
新規追加機能: total_payout, hit_count, actual_roi, hit_rate, race_results, record_result()
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# テスト対象モジュールのパス調整
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import roi_tracker


# --------------------------------------------------------------------------- #
# フィクスチャ
# --------------------------------------------------------------------------- #

@pytest.fixture
def tmp_roi_env(tmp_path, monkeypatch):
    """一時ディレクトリにROI_LOG・OUTPUT_DIRをリダイレクト"""
    roi_log = tmp_path / "data" / "logs" / "monthly_roi.json"
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True)

    monkeypatch.setattr(roi_tracker, "ROI_LOG", roi_log)
    monkeypatch.setattr(roi_tracker, "OUTPUT_DIR", output_dir)
    return tmp_path


@pytest.fixture
def sample_output_json(tmp_roi_env):
    """output/20260301/keirin_和歌山_12.json を作成"""
    date_dir = tmp_roi_env / "output" / "20260301"
    date_dir.mkdir(parents=True)
    json_path = date_dir / "keirin_和歌山_12.json"
    json_path.write_text(
        json.dumps(
            {
                "bet": {
                    "bet_type": "3連複ながし",
                    "total_investment": 1200,
                    "axis": 4,
                    "partners": [2, 6],
                    "combinations": [[2, 4, 6]],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return json_path


# --------------------------------------------------------------------------- #
# load_roi_log / save_roi_log
# --------------------------------------------------------------------------- #

class TestLoadSaveRoiLog:
    def test_load_nonexistent_returns_empty(self, tmp_roi_env):
        data = roi_tracker.load_roi_log()
        assert data == {}

    def test_save_and_load(self, tmp_roi_env):
        payload = {"202603": {"total_investment": 5000}}
        roi_tracker.save_roi_log(payload)
        loaded = roi_tracker.load_roi_log()
        assert loaded["202603"]["total_investment"] == 5000

    def test_load_corrupt_json_returns_empty(self, tmp_roi_env):
        roi_log = roi_tracker.ROI_LOG
        roi_log.parent.mkdir(parents=True, exist_ok=True)
        roi_log.write_text("{invalid json", encoding="utf-8")
        assert roi_tracker.load_roi_log() == {}


# --------------------------------------------------------------------------- #
# scan_output_for_month — 新フィールドのデフォルト値
# --------------------------------------------------------------------------- #

class TestScanOutputNewFields:
    def test_new_fields_present_with_defaults(self, tmp_roi_env):
        result = roi_tracker.scan_output_for_month("202603")
        assert "total_payout" in result
        assert result["total_payout"] == 0
        assert "hit_count" in result
        assert result["hit_count"] == 0
        assert "actual_roi" in result
        assert result["actual_roi"] == 0.0
        assert "hit_rate" in result
        assert result["hit_rate"] == 0.0
        assert "race_results" in result
        assert result["race_results"] == []

    def test_investment_scan_still_works(self, tmp_roi_env):
        """既存の投資額スキャン機能が壊れていないことを確認"""
        date_dir = tmp_roi_env / "output" / "20260301"
        date_dir.mkdir(parents=True)
        (date_dir / "keirin_和歌山_12.json").write_text(
            json.dumps({"bet": {"bet_type": "3連複ながし", "total_investment": 1200}}),
            encoding="utf-8",
        )
        (date_dir / "keirin_大垣_9.json").write_text(
            json.dumps({"bet": {"bet_type": "skip", "total_investment": 0}}),
            encoding="utf-8",
        )
        result = roi_tracker.scan_output_for_month("202603")
        assert result["total_investment"] == 1200
        assert result["bet_count"] == 1
        assert result["skip_count"] == 1


# --------------------------------------------------------------------------- #
# record_result — 正常ケース
# --------------------------------------------------------------------------- #

class TestRecordResult:
    def test_basic_hit(self, tmp_roi_env, sample_output_json):
        """的中ケース: payout > 0, hit=True"""
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山",
            race_no=12,
            payout=5000,
            hit=True,
        )
        assert result["total_payout"] == 5000
        assert result["hit_count"] == 1
        assert len(result["race_results"]) == 1

        entry = result["race_results"][0]
        assert entry["race_id"] == "20260301_和歌山_12"
        assert entry["venue"] == "和歌山"
        assert entry["race_no"] == 12
        assert entry["payout"] == 5000
        assert entry["hit"] is True

    def test_miss_case(self, tmp_roi_env, sample_output_json):
        """未的中ケース: payout=0, hit=False"""
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山",
            race_no=12,
            payout=0,
            hit=False,
        )
        assert result["total_payout"] == 0
        assert result["hit_count"] == 0
        entry = result["race_results"][0]
        assert entry["hit"] is False
        assert entry["payout"] == 0

    def test_investment_lookup_from_output_json(self, tmp_roi_env, sample_output_json):
        """output JSONから投資額・bet_typeが自動取得されること"""
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山",
            race_no=12,
            payout=5000,
            hit=True,
        )
        entry = result["race_results"][0]
        assert entry["investment"] == 1200
        assert entry["bet_type"] == "3連複ながし"

    def test_investment_zero_if_no_output_json(self, tmp_roi_env):
        """output JSONがない場合: investment=0, bet_type='unknown'"""
        result = roi_tracker.record_result(
            race_id="20260301_大垣_7",
            venue="大垣",
            race_no=7,
            payout=0,
            hit=False,
        )
        entry = result["race_results"][0]
        assert entry["investment"] == 0
        assert entry["bet_type"] == "unknown"

    def test_investment_direct_param_overrides_file_lookup(self, tmp_roi_env):
        """investment引数を直接渡した場合、output JSONが存在しなくても投資額が記録されること。
        根拠(CHECK-7b): output/20260228が削除された状態でcollect_results.pyを実行しても
        our_prediction["investment"]を渡せば投資額が失われない。"""
        result = roi_tracker.record_result(
            race_id="20260228_大垣_12",
            venue="大垣",
            race_no=12,
            payout=0,
            hit=False,
            investment=1200,  # output JSONなしで直接渡す
        )
        entry = result["race_results"][0]
        assert entry["investment"] == 1200, "output JSONがなくても investment 引数が使われること"

    def test_investment_direct_param_takes_priority_over_file(self, tmp_roi_env, sample_output_json):
        """investment引数がoutput JSONの値より優先されること。
        根拠: 明示的に渡した値の方が信頼できる（ファイルが古い情報を持つ可能性への対策）。"""
        # sample_output_jsonは investment=1200 を持つ
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山",
            race_no=12,
            payout=0,
            hit=False,
            investment=3600,  # JSONの1200より大きい値を渡す
        )
        entry = result["race_results"][0]
        assert entry["investment"] == 3600, "investment引数がoutput JSONの値より優先されること"

    def test_persists_to_json(self, tmp_roi_env, sample_output_json):
        """monthly_roi.jsonに書き込まれること"""
        roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山",
            race_no=12,
            payout=3600,
            hit=True,
        )
        loaded = roi_tracker.load_roi_log()
        assert "202603" in loaded
        assert loaded["202603"]["total_payout"] == 3600
        assert loaded["202603"]["hit_count"] == 1


# --------------------------------------------------------------------------- #
# record_result — 集計計算
# --------------------------------------------------------------------------- #

class TestRecordResultCalculations:
    def test_actual_roi_calculation(self, tmp_roi_env):
        """actual_roi = total_payout / total_investment * 100"""
        # まず投資額を直接セット（scan不要）
        log_data = {"202603": {"total_investment": 10000, "bet_count": 5}}
        roi_tracker.save_roi_log(log_data)

        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山",
            race_no=12,
            payout=6940,
            hit=True,
        )
        # 10000円投資 → 6940円払戻 → ROI 69.4%
        assert result["actual_roi"] == pytest.approx(69.4, abs=0.1)

    def test_actual_roi_zero_when_no_investment(self, tmp_roi_env):
        """total_investment=0 のとき actual_roi=0.0（ゼロ除算しない）"""
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山",
            race_no=12,
            payout=5000,
            hit=True,
        )
        assert result["actual_roi"] == 0.0

    def test_hit_rate_calculation(self, tmp_roi_env):
        """hit_rate = hit_count / bet_count * 100"""
        log_data = {"202603": {"total_investment": 12000, "bet_count": 3}}
        roi_tracker.save_roi_log(log_data)

        # 1件的中
        roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=5000, hit=True,
        )
        # 2件外れ
        roi_tracker.record_result(
            race_id="20260301_大垣_9",
            venue="大垣", race_no=9, payout=0, hit=False,
        )
        result = roi_tracker.record_result(
            race_id="20260301_川崎_6",
            venue="川崎", race_no=6, payout=0, hit=False,
        )
        # hit_count=1, bet_count=3 → 33.3%
        assert result["hit_count"] == 1
        assert result["hit_rate"] == pytest.approx(33.3, abs=0.1)

    def test_total_payout_accumulates(self, tmp_roi_env):
        """複数レース結果の合計払戻が正確に集計されること"""
        log_data = {"202603": {"total_investment": 6000, "bet_count": 3}}
        roi_tracker.save_roi_log(log_data)

        roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=3000, hit=True,
        )
        roi_tracker.record_result(
            race_id="20260301_大垣_9",
            venue="大垣", race_no=9, payout=2000, hit=True,
        )
        result = roi_tracker.record_result(
            race_id="20260301_川崎_6",
            venue="川崎", race_no=6, payout=0, hit=False,
        )
        assert result["total_payout"] == 5000
        assert result["hit_count"] == 2


# --------------------------------------------------------------------------- #
# record_result — 重複更新
# --------------------------------------------------------------------------- #

class TestRecordResultIdempotency:
    def test_duplicate_race_id_updates_existing(self, tmp_roi_env):
        """同じrace_idで再呼び出しすると既存エントリが更新される"""
        roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=0, hit=False,
        )
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=5000, hit=True,
        )
        # race_resultsは1件のまま（追加されない）
        assert len(result["race_results"]) == 1
        assert result["race_results"][0]["payout"] == 5000
        assert result["race_results"][0]["hit"] is True
        assert result["total_payout"] == 5000
        assert result["hit_count"] == 1

    def test_preserves_existing_investment_data(self, tmp_roi_env):
        """既存の total_investment が上書きされないこと"""
        log_data = {
            "202603": {
                "month": "202603",
                "total_investment": 36000,
                "bet_count": 10,
                "skip_count": 6,
            }
        }
        roi_tracker.save_roi_log(log_data)

        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=25000, hit=True,
        )
        # total_investmentが保持されること
        assert result["total_investment"] == 36000
        assert result["total_payout"] == 25000
        # ROI: 25000/36000*100 = 69.4%
        assert result["actual_roi"] == pytest.approx(69.4, abs=0.1)


# --------------------------------------------------------------------------- #
# update_current_month — race_results保持
# --------------------------------------------------------------------------- #

class TestUpdateCurrentMonth:
    def test_preserves_race_results_on_rescan(self, tmp_roi_env):
        """scan後の update_current_month がrace_resultsを上書きしないこと"""
        # まず record_result でデータを書き込む
        log_data = {"202603": {"total_investment": 1200, "bet_count": 1, "skip_count": 0}}
        roi_tracker.save_roi_log(log_data)

        roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=5000, hit=True,
        )

        # update_current_month を呼んでも race_results が消えないこと
        with patch("roi_tracker.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "202603"
            # scan_output_for_month は output_dir が空なので 0 を返す
            result = roi_tracker.update_current_month()

        loaded = roi_tracker.load_roi_log()
        assert "202603" in loaded
        # race_results が保持されている
        assert len(loaded["202603"].get("race_results", [])) == 1


# --------------------------------------------------------------------------- #
# monthly_roi.json スキーマ互換性
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# _compute_filter_stats
# --------------------------------------------------------------------------- #

class TestComputeFilterStats:
    def test_filtered_only_includes_filter_passed_true(self, tmp_roi_env):
        """filter_passed=True のレースのみが filtered_stats に集計されること"""
        races = [
            {"race_id": "r1", "investment": 1000, "payout": 3000, "hit": True,  "filter_passed": True},
            {"race_id": "r2", "investment": 1000, "payout": 0,    "hit": False, "filter_passed": False},
            {"race_id": "r3", "investment": 1000, "payout": 2000, "hit": True,  "filter_passed": True},
        ]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=True)
        assert stats["race_count"] == 2
        assert stats["total_investment"] == 2000
        assert stats["total_payout"] == 5000
        assert stats["hit_count"] == 2
        assert stats["roi"] == pytest.approx(250.0, abs=0.1)

    def test_unfiltered_includes_all_races(self, tmp_roi_env):
        """filter_passed=None で全レースが unfiltered_stats に集計されること"""
        races = [
            {"race_id": "r1", "investment": 1000, "payout": 3000, "hit": True,  "filter_passed": True},
            {"race_id": "r2", "investment": 1000, "payout": 0,    "hit": False, "filter_passed": False},
        ]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=None)
        assert stats["race_count"] == 2
        assert stats["total_investment"] == 2000
        assert stats["total_payout"] == 3000
        assert stats["roi"] == pytest.approx(150.0, abs=0.1)

    def test_roi_zero_when_no_investment(self, tmp_roi_env):
        """投資額0の場合 roi=0.0（ゼロ除算しない）"""
        races = [{"race_id": "r1", "investment": 0, "payout": 0, "hit": False, "filter_passed": True}]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=True)
        assert stats["roi"] == 0.0

    def test_empty_list_returns_zeros(self, tmp_roi_env):
        """空リストでゼロ埋めの辞書が返ること"""
        stats = roi_tracker._compute_filter_stats([], filter_passed=True)
        assert stats["race_count"] == 0
        assert stats["total_investment"] == 0
        assert stats["roi"] == 0.0

    def test_backward_compat_missing_filter_passed_defaults_true(self, tmp_roi_env):
        """filter_passed フィールドがない旧エントリは True として扱われること"""
        races = [
            {"race_id": "r1", "investment": 1000, "payout": 2000, "hit": True},  # filter_passed なし
        ]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=True)
        assert stats["race_count"] == 1  # 旧エントリは filtered に含まれる


# --------------------------------------------------------------------------- #
# record_result — filter_passed パラメータ
# --------------------------------------------------------------------------- #

class TestRecordResultFilterPassed:
    def test_filter_passed_stored_in_race_entry(self, tmp_roi_env):
        """filter_passed がrace_resultsエントリに保存されること"""
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=0, hit=False,
            filter_passed=False,
        )
        entry = result["race_results"][0]
        assert entry["filter_passed"] is False

    def test_default_filter_passed_is_true(self, tmp_roi_env):
        """filter_passed 省略時はTrueになること（後方互換）"""
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=0, hit=False,
        )
        entry = result["race_results"][0]
        assert entry["filter_passed"] is True

    def test_filtered_stats_and_unfiltered_stats_present(self, tmp_roi_env):
        """filtered_stats / unfiltered_stats が月次データに含まれること"""
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=3000, hit=True,
            filter_passed=True,
        )
        assert "filtered_stats" in result
        assert "unfiltered_stats" in result
        for key in ("total_investment", "total_payout", "hit_count", "race_count", "roi"):
            assert key in result["filtered_stats"]
            assert key in result["unfiltered_stats"]

    def test_filtered_roi_separates_from_unfiltered(self, tmp_roi_env):
        """filtered_stats と unfiltered_stats が正しく分離されること"""
        # filter_passed=True のレース（的中）
        roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=5000, hit=True,
            filter_passed=True,
        )
        # filter_passed=False のレース（外れ）
        result = roi_tracker.record_result(
            race_id="20260301_大垣_9",
            venue="大垣", race_no=9, payout=0, hit=False,
            filter_passed=False,
        )

        fs = result["filtered_stats"]
        ufs = result["unfiltered_stats"]

        # filtered: 的中1件のみ
        assert fs["race_count"] == 1
        assert fs["total_payout"] == 5000
        assert fs["hit_count"] == 1

        # unfiltered: 2件全て
        assert ufs["race_count"] == 2
        assert ufs["total_payout"] == 5000
        assert ufs["hit_count"] == 1

    def test_persists_filtered_stats_to_json(self, tmp_roi_env):
        """monthly_roi.json に filtered_stats / unfiltered_stats が保存されること"""
        roi_tracker.record_result(
            race_id="20260301_和歌山_12",
            venue="和歌山", race_no=12, payout=4000, hit=True,
            filter_passed=True,
        )
        loaded = roi_tracker.load_roi_log()
        assert "filtered_stats" in loaded["202603"]
        assert "unfiltered_stats" in loaded["202603"]
        assert loaded["202603"]["filtered_stats"]["total_payout"] == 4000


# --------------------------------------------------------------------------- #
# monthly_roi.json スキーマ互換性
# --------------------------------------------------------------------------- #

class TestJsonSchemaCompatibility:
    def test_old_format_entry_works_with_record_result(self, tmp_roi_env):
        """旧フォーマット（新フィールドなし）のエントリでも record_result が動くこと"""
        old_format = {
            "202602": {
                "month": "202602",
                "total_investment": 36000,
                "bet_count": 10,
                "skip_count": 6,
                "dates_processed": ["20260223", "20260228"],
                "last_updated": "2026-02-28T14:42:11",
            }
        }
        roi_tracker.save_roi_log(old_format)

        # 旧フォーマットエントリへのrecord_resultが例外なく動くこと
        result = roi_tracker.record_result(
            race_id="20260228_和歌山_12",
            venue="和歌山", race_no=12, payout=12500, hit=True,
        )
        assert result["total_investment"] == 36000  # 保持
        assert result["total_payout"] == 12500      # 新規
        assert result["hit_count"] == 1             # 新規
        assert result["actual_roi"] == pytest.approx(34.7, abs=0.1)  # 12500/36000*100


# --------------------------------------------------------------------------- #
# check_investment_consistency — ARCH-1対策
# --------------------------------------------------------------------------- #

class TestCheckInvestmentConsistency:
    def test_no_data_returns_ok(self, tmp_roi_env):
        """月次データが存在しない場合はok=True"""
        ok, msg = roi_tracker.check_investment_consistency("202699")
        assert ok is True
        assert "月次データなし" in msg

    def test_no_race_results_returns_ok(self, tmp_roi_env):
        """race_resultsが空（未記録状態）はok=True"""
        log_data = {"202603": {"total_investment": 10000, "race_results": []}}
        roi_tracker.save_roi_log(log_data)
        ok, msg = roi_tracker.check_investment_consistency("202603")
        assert ok is True
        assert "race_results 未記録" in msg

    def test_consistent_data_returns_ok(self, tmp_roi_env):
        """scan投資額とrace_results積算が一致 → ok=True"""
        log_data = {
            "202603": {
                "total_investment": 3600,
                "race_results": [
                    {"investment": 1200},
                    {"investment": 1200},
                    {"investment": 1200},
                ],
            }
        }
        roi_tracker.save_roi_log(log_data)
        ok, msg = roi_tracker.check_investment_consistency("202603")
        assert ok is True
        assert "✅" in msg

    def test_within_10pct_tolerance_returns_ok(self, tmp_roi_env):
        """差分がscan投資の10%以内 → ok=True（丸め誤差許容）"""
        log_data = {
            "202603": {
                "total_investment": 10000,
                "race_results": [
                    {"investment": 9500},  # 差分500 = 5% < 10%
                ],
            }
        }
        roi_tracker.save_roi_log(log_data)
        ok, msg = roi_tracker.check_investment_consistency("202603")
        assert ok is True

    def test_over_10pct_diff_returns_warning(self, tmp_roi_env):
        """差分がscan投資の10%超 → ok=False、WARNINGメッセージ"""
        log_data = {
            "202603": {
                "total_investment": 10000,
                "race_results": [
                    {"investment": 5000},  # 差分5000 = 50% > 10%
                ],
            }
        }
        roi_tracker.save_roi_log(log_data)
        ok, msg = roi_tracker.check_investment_consistency("202603")
        assert ok is False
        assert "⚠" in msg
        assert "投資額不整合" in msg

    def test_message_contains_scan_and_records_values(self, tmp_roi_env):
        """メッセージにscan値とrecords値が含まれること"""
        log_data = {
            "202603": {
                "total_investment": 8000,
                "race_results": [{"investment": 3000}],
            }
        }
        roi_tracker.save_roi_log(log_data)
        ok, msg = roi_tracker.check_investment_consistency("202603")
        assert "8,000" in msg or "8000" in msg
        assert "3,000" in msg or "3000" in msg

    def test_uses_scan_investment_not_records_sum(self, tmp_roi_env):
        """整合チェックにはtotal_investmentフィールドを使用すること"""
        # scan=0, records=1200 → 差分1200 > threshold(100) → 不整合
        log_data = {
            "202603": {
                "total_investment": 0,
                "race_results": [{"investment": 1200}],
            }
        }
        roi_tracker.save_roi_log(log_data)
        ok, msg = roi_tracker.check_investment_consistency("202603")
        # threshold = max(0 * 0.1, 100) = 100. diff=1200 > 100 → False
        assert ok is False
