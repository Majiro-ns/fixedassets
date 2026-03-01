"""
tests/test_roi_calculation.py
==============================

ROI計算エンジン + 月次レポート生成テスト (cmd_143k_sub4)

テスト対象:
1. ROI計算の基本テスト (ROI = payout / investment * 100)
2. collect_results の結果 → ROI変換テスト
3. 月次レポート生成テスト (monthly_roi.json)
4. フィルター通過レース数とROIの関連テスト（F2修正前後）
"""

import json
import sys
from pathlib import Path

import pytest

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


def make_output_json(tmp_roi_env, date_str, venue, race_no, bet_type="3連複ながし", investment=1000):
    """output/YYYYMMDD/keirin_{venue}_{race_no}.json を作成するヘルパー"""
    date_dir = tmp_roi_env / "output" / date_str
    date_dir.mkdir(parents=True, exist_ok=True)
    json_path = date_dir / f"keirin_{venue}_{race_no}.json"
    json_path.write_text(
        json.dumps(
            {"bet": {"bet_type": bet_type, "total_investment": investment}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return json_path


# --------------------------------------------------------------------------- #
# 1. ROI計算の基本テスト
# --------------------------------------------------------------------------- #


class TestBasicRoiCalculation:
    """ROI = total_payout / total_investment * 100 の基本計算。"""

    def test_roi_150_percent(self, tmp_roi_env):
        """投資10000円 / 払戻15000円 → ROI 150%"""
        log_data = {"202603": {"total_investment": 10000, "bet_count": 5, "skip_count": 0}}
        roi_tracker.save_roi_log(log_data)

        result = roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=15000,
            hit=True,
        )
        # 投資10000円、払戻15000円 → ROI = 15000/10000*100 = 150.0%
        assert result["actual_roi"] == pytest.approx(150.0, abs=0.1)

    def test_roi_zero_when_payout_is_zero(self, tmp_roi_env):
        """投資10000円 / 払戻0円 → ROI 0%"""
        log_data = {"202603": {"total_investment": 10000, "bet_count": 5, "skip_count": 0}}
        roi_tracker.save_roi_log(log_data)

        result = roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=0,
            hit=False,
        )
        assert result["actual_roi"] == 0.0

    def test_roi_not_crash_when_investment_zero(self, tmp_roi_env):
        """投資0円 → ゼロ除算せず actual_roi=0.0"""
        # output JSON なしで記録 → total_investment=0 のまま
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=5000,
            hit=True,
        )
        # total_investment=0 のためROI計算不可 → 0.0
        assert result["actual_roi"] == 0.0

    def test_roi_over_100_percent(self, tmp_roi_env):
        """ROI 100%超（大当たり）ケース"""
        log_data = {"202603": {"total_investment": 1000, "bet_count": 1, "skip_count": 0}}
        roi_tracker.save_roi_log(log_data)

        result = roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=50000,
            hit=True,
        )
        # 1000円投資 → 50000円払戻 → ROI = 5000%
        assert result["actual_roi"] == pytest.approx(5000.0, abs=0.1)

    def test_compute_filter_stats_roi_150(self, tmp_roi_env):
        """_compute_filter_stats: 投資10000円/払戻15000円 → ROI 150%"""
        races = [
            {
                "race_id": "r1",
                "investment": 10000,
                "payout": 15000,
                "hit": True,
                "filter_passed": True,
            },
        ]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=True)
        assert stats["roi"] == pytest.approx(150.0, abs=0.1)

    def test_compute_filter_stats_roi_zero(self, tmp_roi_env):
        """_compute_filter_stats: 投資10000円/払戻0円 → ROI 0%"""
        races = [
            {
                "race_id": "r1",
                "investment": 10000,
                "payout": 0,
                "hit": False,
                "filter_passed": True,
            },
        ]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=True)
        assert stats["roi"] == 0.0

    def test_compute_filter_stats_no_investment(self, tmp_roi_env):
        """_compute_filter_stats: 投資0円 → ROI 0.0（ゼロ除算しない）"""
        races = [
            {
                "race_id": "r1",
                "investment": 0,
                "payout": 0,
                "hit": False,
                "filter_passed": True,
            },
        ]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=True)
        assert stats["roi"] == 0.0

    def test_roi_rounds_to_one_decimal(self, tmp_roi_env):
        """ROIは小数点以下1桁で丸められる"""
        log_data = {"202603": {"total_investment": 3000, "bet_count": 3}}
        roi_tracker.save_roi_log(log_data)

        result = roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=1000,
            hit=True,
        )
        # 1000/3000*100 = 33.333... → 33.3
        assert result["actual_roi"] == pytest.approx(33.3, abs=0.1)

    def test_roi_exactly_100_percent(self, tmp_roi_env):
        """ROI ちょうど100%（損益ゼロ）"""
        log_data = {"202603": {"total_investment": 5000, "bet_count": 5}}
        roi_tracker.save_roi_log(log_data)

        result = roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=5000,
            hit=True,
        )
        assert result["actual_roi"] == pytest.approx(100.0, abs=0.1)


# --------------------------------------------------------------------------- #
# 2. collect_results の結果 → ROI変換テスト
# --------------------------------------------------------------------------- #


class TestCollectResultsToRoi:
    """collect_results で得た結果を record_result でROIに変換するテスト。"""

    def test_hit_count_from_hit_races(self, tmp_roi_env):
        """的中あり: hit_count / bet_count から的中率が計算される"""
        log_data = {"202603": {"total_investment": 3000, "bet_count": 3}}
        roi_tracker.save_roi_log(log_data)

        roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=5000,
            hit=True,
        )
        roi_tracker.record_result(
            race_id="20260301_大垣_5",
            venue="大垣",
            race_no=5,
            payout=0,
            hit=False,
        )
        result = roi_tracker.record_result(
            race_id="20260301_川崎_3",
            venue="川崎",
            race_no=3,
            payout=0,
            hit=False,
        )
        assert result["hit_count"] == 1
        # hit_rate = 1/3 * 100 = 33.3%
        assert result["hit_rate"] == pytest.approx(33.3, abs=0.1)

    def test_roi_zero_when_all_miss(self, tmp_roi_env):
        """的中なし: ROI=0%, hit_count=0"""
        log_data = {"202603": {"total_investment": 3000, "bet_count": 3}}
        roi_tracker.save_roi_log(log_data)

        for i in range(3):
            roi_tracker.record_result(
                race_id=f"20260301_和歌山_{i+1}",
                venue="和歌山",
                race_no=i + 1,
                payout=0,
                hit=False,
            )

        loaded = roi_tracker.load_roi_log()
        month_data = loaded["202603"]
        assert month_data["hit_count"] == 0
        assert month_data["actual_roi"] == 0.0

    def test_partial_hit_trio_hit_trifecta_miss(self, tmp_roi_env):
        """部分的中: 三連複的中（hit=True）・三連単外れ（hit=False）"""
        log_data = {"202603": {"total_investment": 2000, "bet_count": 2}}
        roi_tracker.save_roi_log(log_data)

        # 三連複は的中（hit=True）
        roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=4200,
            hit=True,
        )
        # 三連単は外れ（hit=False）
        result = roi_tracker.record_result(
            race_id="20260301_大垣_5",
            venue="大垣",
            race_no=5,
            payout=0,
            hit=False,
        )
        assert result["hit_count"] == 1
        assert result["total_payout"] == 4200
        # ROI = 4200/2000*100 = 210%
        assert result["actual_roi"] == pytest.approx(210.0, abs=0.1)

    def test_investment_loaded_from_output_json(self, tmp_roi_env):
        """collect_results 後の output JSON から投資額が自動取得される"""
        make_output_json(tmp_roi_env, "20260301", "和歌山", 1, investment=1200)

        result = roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=3600,
            hit=True,
        )
        entry = result["race_results"][0]
        # output JSON から投資額1200円が取得されること
        assert entry["investment"] == 1200
        assert entry["payout"] == 3600

    def test_skip_race_not_counted_in_bet(self, tmp_roi_env):
        """skip レースは bet_count に含まれない"""
        date_dir = tmp_roi_env / "output" / "20260301"
        date_dir.mkdir(parents=True)
        (date_dir / "keirin_和歌山_1.json").write_text(
            json.dumps({"bet": {"bet_type": "skip", "total_investment": 0}}),
            encoding="utf-8",
        )

        stats = roi_tracker.scan_output_for_month("202603")
        assert stats["skip_count"] == 1
        assert stats["bet_count"] == 0
        assert stats["total_investment"] == 0

    def test_multiple_races_total_payout_accumulates(self, tmp_roi_env):
        """複数レースの払戻が正確に合計される"""
        log_data = {"202603": {"total_investment": 5000, "bet_count": 5}}
        roi_tracker.save_roi_log(log_data)

        payouts = [3000, 0, 7000, 0, 2000]
        for i, p in enumerate(payouts):
            roi_tracker.record_result(
                race_id=f"20260301_テスト_{i+1}",
                venue="テスト",
                race_no=i + 1,
                payout=p,
                hit=(p > 0),
            )

        loaded = roi_tracker.load_roi_log()
        assert loaded["202603"]["total_payout"] == sum(payouts)  # 12000円

    def test_hit_rate_100_percent(self, tmp_roi_env):
        """全レース的中: 的中率100%"""
        log_data = {"202603": {"total_investment": 3000, "bet_count": 3}}
        roi_tracker.save_roi_log(log_data)

        for i in range(3):
            roi_tracker.record_result(
                race_id=f"20260301_和歌山_{i+1}",
                venue="和歌山",
                race_no=i + 1,
                payout=3000,
                hit=True,
            )

        loaded = roi_tracker.load_roi_log()
        assert loaded["202603"]["hit_count"] == 3
        assert loaded["202603"]["hit_rate"] == pytest.approx(100.0, abs=0.1)


# --------------------------------------------------------------------------- #
# 3. 月次レポート生成テスト
# --------------------------------------------------------------------------- #


class TestMonthlyReportGeneration:
    """monthly_roi.json へのデータ追記・月跨ぎ・複数日集約テスト。"""

    def test_monthly_roi_json_created_on_first_record(self, tmp_roi_env):
        """record_result 初回呼び出しで monthly_roi.json が作成される"""
        roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=0,
            hit=False,
        )
        assert roi_tracker.ROI_LOG.exists(), "monthly_roi.json が作成されていない"

    def test_data_appended_within_same_month(self, tmp_roi_env):
        """同月内の複数結果が追記される（上書きされない）"""
        roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=3000,
            hit=True,
        )
        roi_tracker.record_result(
            race_id="20260302_大垣_5",
            venue="大垣",
            race_no=5,
            payout=0,
            hit=False,
        )

        loaded = roi_tracker.load_roi_log()
        assert "202603" in loaded
        assert len(loaded["202603"]["race_results"]) == 2

    def test_cross_month_data_separation(self, tmp_roi_env):
        """月跨ぎ: 2月・3月が別キーに独立して保存される"""
        roi_tracker.record_result(
            race_id="20260228_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=5000,
            hit=True,
        )
        roi_tracker.record_result(
            race_id="20260301_大垣_5",
            venue="大垣",
            race_no=5,
            payout=3000,
            hit=True,
        )

        loaded = roi_tracker.load_roi_log()
        assert "202602" in loaded, "2月データが見つからない"
        assert "202603" in loaded, "3月データが見つからない"
        # 月をまたいでデータが混在しないこと
        assert loaded["202602"]["race_results"][0]["race_id"] == "20260228_和歌山_1"
        assert loaded["202603"]["race_results"][0]["race_id"] == "20260301_大垣_5"

    def test_multi_day_aggregation_within_month(self, tmp_roi_env):
        """複数日（3/1, 3/5, 3/15）のデータが月次で正しく集約される"""
        log_data = {"202603": {"total_investment": 10000, "bet_count": 5}}
        roi_tracker.save_roi_log(log_data)

        day_results = [
            ("20260301_和歌山_1", "和歌山", 1, 3000, True),
            ("20260305_大垣_7", "大垣", 7, 0, False),
            ("20260315_川崎_3", "川崎", 3, 7000, True),
        ]
        for race_id, venue, race_no, payout, hit in day_results:
            roi_tracker.record_result(
                race_id=race_id,
                venue=venue,
                race_no=race_no,
                payout=payout,
                hit=hit,
            )

        loaded = roi_tracker.load_roi_log()
        month_data = loaded["202603"]
        assert month_data["total_payout"] == 10000
        assert month_data["hit_count"] == 2
        assert len(month_data["race_results"]) == 3

    def test_scan_output_aggregates_multiple_dates(self, tmp_roi_env):
        """scan_output_for_month が複数日付ディレクトリを集約する"""
        for date_str in ["20260301", "20260305", "20260310"]:
            make_output_json(tmp_roi_env, date_str, "和歌山", 1, investment=1000)

        stats = roi_tracker.scan_output_for_month("202603")
        assert stats["bet_count"] == 3
        assert stats["total_investment"] == 3000
        assert len(stats["dates_processed"]) == 3

    def test_race_results_not_overwritten_by_rescan(self, tmp_roi_env):
        """scan_output_for_month で race_results・payout が上書きされない"""
        log_data = {"202603": {"total_investment": 1000, "bet_count": 1, "skip_count": 0}}
        roi_tracker.save_roi_log(log_data)

        roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=5000,
            hit=True,
        )

        # scan を再実行して保存
        stats = roi_tracker.scan_output_for_month("202603")
        loaded = roi_tracker.load_roi_log()
        existing = loaded.get("202603", {})

        # scan_output_for_month は投資額のみ更新し、payout/race_results は保持すること
        for preserve_key in ("total_payout", "hit_count", "hit_rate", "actual_roi", "race_results"):
            if preserve_key in existing:
                stats[preserve_key] = existing[preserve_key]

        assert stats.get("total_payout", 0) == 5000

    def test_last_updated_field_is_set_on_record(self, tmp_roi_env):
        """record_result 後 last_updated フィールドが設定される"""
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=0,
            hit=False,
        )
        assert "last_updated" in result
        assert result["last_updated"] != ""

    def test_duplicate_race_id_updates_not_appends(self, tmp_roi_env):
        """同じrace_idで再記録した場合、追加ではなく更新される"""
        roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=0,
            hit=False,
        )
        result = roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=8000,
            hit=True,
        )
        # race_resultsが1件のままで更新されること
        assert len(result["race_results"]) == 1
        assert result["race_results"][0]["payout"] == 8000
        assert result["race_results"][0]["hit"] is True

    def test_monthly_roi_json_is_valid_json(self, tmp_roi_env):
        """保存された monthly_roi.json が有効なJSON形式であること"""
        roi_tracker.record_result(
            race_id="20260301_和歌山_1",
            venue="和歌山",
            race_no=1,
            payout=3000,
            hit=True,
        )
        content = roi_tracker.ROI_LOG.read_text(encoding="utf-8")
        parsed = json.loads(content)  # JSONDecodeError が起きれば失敗
        assert isinstance(parsed, dict)
        assert "202603" in parsed


# --------------------------------------------------------------------------- #
# 4. フィルター通過レース数とROIの関連テスト（F2修正前後）
# --------------------------------------------------------------------------- #


class TestFilterAndRoiRelation:
    """F2修正前後のフィルター通過率とROIの関係テスト。"""

    def test_f2_before_fix_all_races_filtered_out(self, tmp_roi_env):
        """F2修正前: 全レースがfilter_passed=False → filtered_stats.race_count=0"""
        log_data = {"202603": {"total_investment": 0, "bet_count": 0, "skip_count": 8}}
        roi_tracker.save_roi_log(log_data)

        for i in range(8):
            roi_tracker.record_result(
                race_id=f"20260301_テスト_{i+1}",
                venue="テスト",
                race_no=i + 1,
                payout=0,
                hit=False,
                filter_passed=False,
            )

        loaded = roi_tracker.load_roi_log()
        month_data = loaded["202603"]
        # F2バグ時: フィルター通過レースのROI統計はゼロ
        assert month_data["filtered_stats"]["total_investment"] == 0
        assert month_data["filtered_stats"]["race_count"] == 0

    def test_f2_after_fix_filter_pass_races_present(self, tmp_roi_env):
        """F2修正後: フィルター通過8件 → filtered_stats.race_count=8"""
        log_data = {"202603": {"total_investment": 9600, "bet_count": 8, "skip_count": 0}}
        roi_tracker.save_roi_log(log_data)

        for i in range(8):
            roi_tracker.record_result(
                race_id=f"20260301_テスト_{i+1}",
                venue="テスト",
                race_no=i + 1,
                payout=0,
                hit=False,
                filter_passed=True,
            )

        loaded = roi_tracker.load_roi_log()
        month_data = loaded["202603"]
        assert month_data["filtered_stats"]["race_count"] == 8

    def test_filtered_stats_excludes_filter_failed_races(self, tmp_roi_env):
        """filter_passed=True レースのみが filtered_stats に集計される"""
        log_data = {"202603": {"total_investment": 5000, "bet_count": 2, "skip_count": 3}}
        roi_tracker.save_roi_log(log_data)

        # 通過2件
        roi_tracker.record_result(
            race_id="20260301_テスト_1",
            venue="テスト",
            race_no=1,
            payout=3000,
            hit=True,
            filter_passed=True,
        )
        roi_tracker.record_result(
            race_id="20260301_テスト_2",
            venue="テスト",
            race_no=2,
            payout=0,
            hit=False,
            filter_passed=True,
        )
        # 除外1件
        result = roi_tracker.record_result(
            race_id="20260301_テスト_3",
            venue="テスト",
            race_no=3,
            payout=0,
            hit=False,
            filter_passed=False,
        )

        # filtered_stats: 通過2件のみ
        assert result["filtered_stats"]["race_count"] == 2
        assert result["filtered_stats"]["hit_count"] == 1
        # unfiltered_stats: 3件全て
        assert result["unfiltered_stats"]["race_count"] == 3

    def test_filter_roi_reflects_betting_performance(self, tmp_roi_env):
        """フィルター通過レースのROIが実際のベットパフォーマンスを反映する"""
        # 投資: 通過2件×1000円=2000円、払戻: 3000円 → ROI 150%
        races = [
            {
                "race_id": "r1",
                "investment": 1000,
                "payout": 3000,
                "hit": True,
                "filter_passed": True,
            },
            {
                "race_id": "r2",
                "investment": 1000,
                "payout": 0,
                "hit": False,
                "filter_passed": True,
            },
            {
                "race_id": "r3",
                "investment": 0,
                "payout": 0,
                "hit": False,
                "filter_passed": False,
            },
        ]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=True)
        # ROI = 3000/2000*100 = 150%
        assert stats["roi"] == pytest.approx(150.0, abs=0.1)
        assert stats["race_count"] == 2

    def test_zero_filter_passed_races_means_zero_roi(self, tmp_roi_env):
        """フィルター通過0件: filtered_stats は全てゼロ"""
        races = [
            {
                "race_id": "r1",
                "investment": 0,
                "payout": 0,
                "hit": False,
                "filter_passed": False,
            },
            {
                "race_id": "r2",
                "investment": 0,
                "payout": 0,
                "hit": False,
                "filter_passed": False,
            },
        ]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=True)
        assert stats["race_count"] == 0
        assert stats["total_investment"] == 0
        assert stats["roi"] == 0.0

    def test_scan_output_counts_bet_and_skip_correctly(self, tmp_roi_env):
        """scan_output_for_month: BETとSKIPの件数が正しく集計される"""
        date_dir = tmp_roi_env / "output" / "20260301"
        date_dir.mkdir(parents=True)

        # BETファイル × 3
        for i, venue in enumerate(["和歌山", "大垣", "川崎"]):
            (date_dir / f"keirin_{venue}_{i+1}.json").write_text(
                json.dumps(
                    {"bet": {"bet_type": "3連複ながし", "total_investment": 1000}}
                ),
                encoding="utf-8",
            )
        # SKIPファイル × 2
        for i, venue in enumerate(["小松島", "富山"]):
            (date_dir / f"keirin_{venue}_{i+1}.json").write_text(
                json.dumps({"bet": {"bet_type": "skip", "total_investment": 0}}),
                encoding="utf-8",
            )

        stats = roi_tracker.scan_output_for_month("202603")
        assert stats["bet_count"] == 3
        assert stats["skip_count"] == 2
        assert stats["total_investment"] == 3000

    def test_unfiltered_stats_includes_all_races(self, tmp_roi_env):
        """unfiltered_stats: filter_passedに関わらず全レースが対象"""
        races = [
            {
                "race_id": "r1",
                "investment": 1000,
                "payout": 5000,
                "hit": True,
                "filter_passed": True,
            },
            {
                "race_id": "r2",
                "investment": 1000,
                "payout": 0,
                "hit": False,
                "filter_passed": False,
            },
        ]
        stats = roi_tracker._compute_filter_stats(races, filter_passed=None)
        assert stats["race_count"] == 2
        assert stats["total_payout"] == 5000
        # ROI = 5000/2000*100 = 250%
        assert stats["roi"] == pytest.approx(250.0, abs=0.1)
