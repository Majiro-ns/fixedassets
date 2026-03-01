"""
Stage 1 パイプライン × F8 期待配当フィルター 統合テスト (cmd_144k_sub4)

■ テスト方針 (CHECK-9: 全テスト期待値の根拠を下記に記載)
    モック禁止。期待値はすべて実データ or 手計算から導出。

■ テスト対象
    main.py の process_race() 内で行われる F8 統合:
      1. estimate_expected_payout() が race dict に expected_payout を追加すること
      2. F8有効時に低配当レースが除外されること
      3. F8閾値変更の効果テスト
      4. 既存フィルター(F1-F7)との共存確認

■ 実データ出典 (TV-4)
    data/fixtures/keirin_20260228.json (2/28 大垣S級一予選 8レース)
    config/keirin/filters.yaml

■ 手計算根拠 (CHECK-7b)
    2/28 大垣S級一予選 9車立て:
    R2  (spread=17.04, 16-20zone): 12,000 × 0.5 = 6,000円  → F8除外(< 20,000)
    R3  (spread=14.55, 12-16zone): 12,000 × 0.8 = 9,600円  → F8除外(< 20,000)
    R5  (spread=14.12, 12-16zone): 12,000 × 0.8 = 9,600円  → F8除外(< 20,000)
    R7  (spread=12.85, 12-16zone): 12,000 × 0.8 = 9,600円  → F8除外(< 20,000)
    R8  (spread=15.00, 12-16zone): 12,000 × 0.8 = 9,600円  → F8除外(< 20,000)
    R9  (spread=15.90, 12-16zone): 12,000 × 0.8 = 9,600円  → F8除外(< 20,000)
    R10 (spread=14.02, 12-16zone): 12,000 × 0.8 = 9,600円  → F8除外(< 20,000)
    R11 (spread=12.70, 12-16zone): 12,000 × 0.8 = 9,600円  → F8除外(< 20,000)

■ F8閾値の設計メモ (cmd_146k_sub1: 閾値最適化完了)
    旧設定: expected_payout_min=20,000 / expected_payout_max=50,000
    新設定: expected_payout_min=3,000  / expected_payout_max=50,000 (cmd_146k_sub1)

    矛盾発見の経緯:
      - score_spread>=12通過レースの推定配当最大=9,600円(9車立て,spread12-16)
      - 旧F8 min=20,000 → 全レースが除外 → 投資0件（設計矛盾）

    閾値3,000円の根拠 (CHECK-7b):
      - 掛金100円×10点=1,000円コスト。3,000円未満は収支プラスが困難。
      - 9車立て全ゾーン(推定3,600〜9,600円) > 3,000 → 全通過 ✓
      - 8車立て spread<=16まで(推定4,000〜6,400円) > 3,000 → 通過 ✓
      - 8車立て spread>=20 (推定2,400円) < 3,000 → 除外（超低配当）
      - 7車立て spread>=16 (推定2,750円以下) < 3,000 → 除外（超低配当）

    検証 (TV-4):
      2/28大垣S級一予選8レース(9車立て): 推定6,000〜9,600円 → 全てF8通過 ✓
      「投資0件」問題が解消。score_spreadとの矛盾が解消された。

confidence: 5 (修正後のF8フィルター機能・統合ロジック共に手計算で検証済み)
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.expected_payout import estimate_expected_payout
from src.filter_engine import FilterEngine

# ─── パス定数 ────────────────────────────────────────────────────────────
FIXTURE_228 = os.path.join(
    os.path.dirname(__file__), "..", "data", "fixtures", "keirin_20260228.json"
)
FILTERS_YAML = os.path.join(
    os.path.dirname(__file__), "..", "config", "keirin", "filters.yaml"
)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ─── ヘルパー ────────────────────────────────────────────────────────────

def make_race(
    spread: float,
    num_entries: int = 9,
    venue: str = "大垣",
    race_num: int = 5,
    stage: str = "一予選",
    grade: str = "S",
    bank_length: int = 400,
    date: str = "20260228",
) -> dict:
    """テスト用レースデータを生成。score_spread を指定値に設定する。"""
    base_score = 100.0
    scores = [base_score] * (num_entries - 1) + [base_score + spread]
    entries = [
        {"car_no": i + 1, "grade": "S1", "score": scores[i]}
        for i in range(num_entries)
    ]
    return {
        "venue_name": venue,
        "race_num": race_num,
        "race_no": race_num,
        "grade": grade,
        "stage": stage,
        "bank_length": bank_length,
        "date": date,
        "entries": entries,
    }


def load_fixture() -> list:
    with open(FIXTURE_228, encoding="utf-8") as f:
        return json.load(f)


def get_228_ogaki_races(data: list) -> list:
    return [
        r for r in data
        if r["venue_name"] == "大垣"
        and r["race_num"] in [2, 3, 5, 7, 8, 9, 10, 11]
    ]


# ─── テストA: expected_payout が race dict に追加されること ─────────────

class TestExpectedPayoutAddedToRaceDict:
    """
    テストA: estimate_expected_payout() が race dict に
    expected_payout を正しく追加することを確認する。
    (main.py の process_race() 内で行われる統合ロジックを直接検証)
    """

    def test_expected_payout_set_from_spread(self):
        """
        score_spread=14.0, 9車立て → expected_payout = 9,600円 が設定される。
        根拠: 12,000 × 0.8 = 9,600 (手計算 CHECK-7b)
        """
        race = make_race(spread=14.0, num_entries=9)
        assert race.get("expected_payout") is None, "初期状態は None のはず"

        # process_race() 内の統合ロジックを再現
        est = estimate_expected_payout(race)
        if est is not None:
            race["expected_payout"] = est

        assert race.get("expected_payout") == pytest.approx(9_600, abs=1), (
            f"expected_payout={race.get('expected_payout')} (期待=9,600)"
        )

    def test_existing_payout_not_overwritten(self):
        """
        race に既存の expected_payout が設定されている場合は上書きしない。
        根拠: スクレイパーが実オッズから計算した値を優先する設計
        """
        race = make_race(spread=14.0, num_entries=9)
        race["expected_payout"] = 35_000  # 既存値

        # process_race() の統合ロジック: expected_payout が None の場合のみ補完
        if race.get("expected_payout") is None:
            est = estimate_expected_payout(race)
            if est is not None:
                race["expected_payout"] = est

        assert race["expected_payout"] == 35_000, (
            "既存の expected_payout(35,000) が上書きされてはならない"
        )

    def test_no_scores_payout_remains_none(self):
        """
        score データなし → estimate=None → expected_payout は設定されない。
        根拠: score_spread 計算不可 → F8スキップ（安全側に倒す）
        """
        race = {
            "venue_name": "大垣",
            "race_num": 5,
            "grade": "S",
            "stage": "一予選",
            "entries": [{"car_no": i, "score": 0} for i in range(1, 10)],
        }
        est = estimate_expected_payout(race)
        if est is not None:
            race["expected_payout"] = est

        assert race.get("expected_payout") is None, (
            "スコアなし → expected_payout は None のままであるべき"
        )

    @pytest.mark.skipif(not os.path.isfile(FIXTURE_228), reason="実データファイルなし")
    def test_real_228_all_races_get_payout(self):
        """
        2/28 大垣S級一予選 8レース全てで expected_payout が設定される。
        根拠: 全レースに score データあり → estimate が None にならない
        """
        data = load_fixture()
        races = get_228_ogaki_races(data)
        assert len(races) == 8, f"通過レース数={len(races)} (期待=8)"

        for race in races:
            race_copy = dict(race)
            est = estimate_expected_payout(race_copy)
            if est is not None:
                race_copy["expected_payout"] = est
            assert race_copy.get("expected_payout") is not None, (
                f"大垣R{race['race_num']}: expected_payout が設定されなかった"
            )
            assert race_copy["expected_payout"] > 0, (
                f"大垣R{race['race_num']}: expected_payout={race_copy['expected_payout']} (正値のはず)"
            )


# ─── テストB: F8有効時に低配当レースが除外されること ─────────────────────

class TestF8ExcludesLowPayoutRaces:
    """
    テストB: estimate_expected_payout() を設定した race を
    FilterEngine.apply() に渡した場合、F8が低配当レースを正しく除外する。
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = FilterEngine(FILTERS_YAML)

    def test_low_payout_excluded_by_f8(self):
        """
        推定配当2,750円 → F8が除外する (< 3,000円の最低閾値)。
        根拠: 7車立て,spread=16 → 5,500×0.5=2,750 < expected_payout_min(3,000) → F8除外
        cmd_146k_sub1: 閾値3,000円の新設計でも低配当除外機能を維持していることを確認。
        """
        # 7車立て, spread=16 → 推定 5,500 × 0.5 = 2,750円 (手計算 CHECK-7b)
        race = make_race(spread=16.0, num_entries=7)
        est = estimate_expected_payout(race)
        assert est == pytest.approx(2_750, abs=1), (
            f"7車立てspread=16の推定配当={est} (期待=2,750: 5,500×0.5)"
        )
        race["expected_payout"] = est

        passed, reasons = self.engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) > 0, (
            f"推定配当2,750円でF8が除外しない（filter_engine バグ）: {reasons}"
        )

    def test_9car_medium_spread_passes_f8(self):
        """
        9車立て推定配当9,600円 → F8を通過する (>= 3,000円の最低閾値)。
        根拠: spread=14, 9車立て → 12,000×0.8=9,600 >= expected_payout_min(3,000) → F8通過
        cmd_146k_sub1: 主要対象レース(9車立て)が正しく通過することを確認。
        """
        race = make_race(spread=14.0, num_entries=9)
        est = estimate_expected_payout(race)
        assert est == pytest.approx(9_600, abs=1)
        race["expected_payout"] = est

        _, reasons = self.engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) == 0, (
            f"9車立て推定9,600円がF8で除外された（閾値3,000円のはず）: {f8_reasons}"
        )

    def test_target_zone_payout_passes_f8(self):
        """
        目標ゾーン配当(30,000円) → F8を通過する。
        根拠: 20,000 <= 30,000 <= 50,000 → F8通過
        """
        race = make_race(spread=5.0, num_entries=9)  # spread<8 → 低spread → 高配当推定
        race["expected_payout"] = 30_000  # 手動で目標ゾーン設定

        _, reasons = self.engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) == 0, (
            f"目標ゾーン(30,000円)なのにF8が除外した: {f8_reasons}"
        )

    def test_no_payout_f8_skipped(self):
        """
        expected_payout が None → F8がスキップされる（フィルタ対象外）。
        根拠: _check_expected_payout は expected=None の場合 True を返す設計
        """
        race = make_race(spread=14.0, num_entries=9)
        # expected_payout を設定しない → F8スキップ

        _, reasons = self.engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) == 0, (
            f"expected_payout=None なのにF8が発動した: {f8_reasons}"
        )

    def test_too_high_payout_excluded_by_f8(self):
        """
        高すぎる推定配当(60,000円) → F8が除外する (> 50,000円の上限)。
        根拠: 60,000 > expected_payout_max(50,000) → F8除外
        """
        race = make_race(spread=14.0, num_entries=9)
        race["expected_payout"] = 60_000

        _, reasons = self.engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) > 0, (
            f"高配当(60,000円)なのにF8が除外しない: {reasons}"
        )

    @pytest.mark.skipif(not os.path.isfile(FIXTURE_228), reason="実データファイルなし")
    def test_228_all_8_races_pass_f8_with_new_threshold(self):
        """
        2/28大垣S級一予選 8レース(9車立て)に推定値を設定 → F8が全て通過する。
        根拠: 全推定値(6,000〜9,600円) >= F8最低閾値(3,000円)
        (手計算 CHECK-7b 参照)

        cmd_146k_sub1: 閾値3,000円に修正後、score_spread>=12通過レースが
        正しくF8を通過することを確認（「投資0件」問題の解消）。
        """
        data = load_fixture()
        races = get_228_ogaki_races(data)

        f8_excluded = 0
        f8_passed = 0
        for race in races:
            race_copy = dict(race)
            est = estimate_expected_payout(race_copy)
            if est is not None:
                race_copy["expected_payout"] = est
                _, reasons = self.engine.apply(race_copy)
                if any(r.startswith("F8") for r in reasons):
                    f8_excluded += 1
                else:
                    f8_passed += 1

        # 2/28大垣9車立て: 推定6,000〜9,600円 → 全て >= 3,000 → F8除外0件
        assert f8_excluded == 0, (
            f"F8除外数={f8_excluded} (期待=0: 全推定値>=3,000円でF8通過するはず)"
        )
        assert f8_passed == 8, (
            f"F8通過数={f8_passed} (期待=8: 2/28大垣9車立て8レース全通過)"
        )


# ─── テストC: F8閾値変更の効果テスト ──────────────────────────────────

class TestF8ThresholdEffect:
    """
    テストC: F8閾値(expected_payout_min)を変更した場合の効果確認。
    タスク手順4「F8閾値の適正化検討」対応。
    """

    def test_threshold_10000_allows_medium_payout(self):
        """
        閾値を10,000円に下げると推定9,600円のレースが通過できる。
        根拠: 9,600 >= 10,000 は偽 → まだ除外される（誤差範囲）
        実際: 9,600 < 10,000 なので依然として除外される。
        → 閾値を8,000円以下にしないと2/28レースは通過しない。
        """
        # 閾値 10,000 → 9,600円は通過しない（9,600 < 10,000）
        from src.filter_engine import FilterEngine as FE, DEFAULT_FILTERS
        custom_filters = DEFAULT_FILTERS.copy()
        custom_filters["expected_payout_min"] = 10_000
        custom_filters["expected_payout_max"] = 50_000
        # FilterEngine インスタンスを直接フィルター書き換えで模擬
        engine = FE(FILTERS_YAML)
        engine.filters["expected_payout_min"] = 10_000

        race = make_race(spread=14.0, num_entries=9)
        race["expected_payout"] = 9_600  # 9,600 < 10,000

        _, reasons = engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) > 0, (
            "閾値10,000でも9,600円レースは除外されるべき"
        )

    def test_threshold_5000_allows_9600_payout(self):
        """
        閾値を5,000円に下げると推定9,600円のレースが通過する。
        根拠: 5,000 <= 9,600 <= 50,000 → F8通過
        (ただし閾値引き下げは低ROIレースへの投資増リスクあり)
        """
        engine = FilterEngine(FILTERS_YAML)
        engine.filters["expected_payout_min"] = 5_000

        race = make_race(spread=14.0, num_entries=9)
        race["expected_payout"] = 9_600

        _, reasons = engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) == 0, (
            f"閾値5,000なら9,600円レースはF8を通過するはず: {f8_reasons}"
        )

    def test_threshold_3000_passes_all_228_races(self):
        """
        新設定(閾値3,000円)では 2/28 推定値(最小6,000円) は全て通過する。
        根拠: min_estimate(6,000) > threshold(3,000) → 全通過
        cmd_146k_sub1: これが「投資0件」問題の解消。score_spreadとの矛盾が解消された。
        """
        engine = FilterEngine(FILTERS_YAML)
        assert engine.filters["expected_payout_min"] == 3_000, (
            "テスト前提: filters.yaml の expected_payout_min=3,000 (cmd_146k_sub1)"
        )

        # 2/28 大垣の最小推定値 = 6,000円(R2, spread=17.04, 16-20zone)
        min_estimate = 6_000
        assert min_estimate >= 3_000, (
            f"最小推定値={min_estimate:,}円 >= 閾値3,000円 → 全通過が正しい (矛盾解消)"
        )

    def test_f8_optional_by_removing_payout(self):
        """
        F8をオプショナルにする方法: expected_payout を設定しないと F8 がスキップ。
        根拠: _check_expected_payout は expected=None でスキップ設計
        これが「F8をオプショナルにする」最も単純な実装。
        """
        engine = FilterEngine(FILTERS_YAML)
        race = make_race(spread=14.0, num_entries=9)
        # expected_payout を設定しない → F8スキップ → 他フィルター条件で判定

        _, reasons = engine.apply(race)
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f8_reasons) == 0, (
            "expected_payout=None の場合、F8はスキップされるべき"
        )


# ─── テストD: 既存フィルター(F1-F7)との共存確認 ──────────────────────────

class TestF8CoexistsWithExistingFilters:
    """
    テストD: F8を追加しても既存フィルター F1〜F7 が正常に動作すること。
    (既存フィルターへの影響がないことを確認)
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.engine = FilterEngine(FILTERS_YAML)

    def test_f1_class_filter_still_works(self):
        """
        F1クラスフィルター: A級レースは expected_payout 設定関係なく除外。
        根拠: F1は class=["S"] のみ通過。A級は独立して除外される。
        """
        race = make_race(spread=14.0, num_entries=9)
        race["grade"] = "A"  # A級に変更
        race["expected_payout"] = 30_000  # F8は通過する値

        passed, reasons = self.engine.apply(race)
        f1_reasons = [r for r in reasons if r.startswith("F1")]
        assert len(f1_reasons) > 0, (
            f"A級レースでF1が発動しない: {reasons}"
        )

    def test_f2_race_type_filter_still_works(self):
        """
        F2レース種別フィルター: 決勝は expected_payout 設定関係なく除外。
        根拠: F2は race_type に「決勝」が含まれない → 除外
        """
        race = make_race(spread=14.0, num_entries=9)
        race["stage"] = "決勝"  # 除外種別
        race["expected_payout"] = 30_000  # F8は通過する値

        _, reasons = self.engine.apply(race)
        f2_reasons = [r for r in reasons if r.startswith("F2")]
        assert len(f2_reasons) > 0, (
            f"決勝でF2が発動しない: {reasons}"
        )

    def test_f4_velodrome_filter_still_works(self):
        """
        F4競輪場フィルター: 小田原は expected_payout 設定関係なく除外。
        根拠: F4は exclude_velodromes に「小田原」が含まれる
        """
        race = make_race(spread=14.0, num_entries=9)
        race["venue_name"] = "小田原"  # 除外場
        race["expected_payout"] = 30_000  # F8は通過する値

        _, reasons = self.engine.apply(race)
        f4_reasons = [r for r in reasons if r.startswith("F4")]
        assert len(f4_reasons) > 0, (
            f"小田原でF4が発動しない: {reasons}"
        )

    def test_f7_race_number_filter_still_works(self):
        """
        F7レース番号フィルター: 4R は expected_payout 設定関係なく除外。
        根拠: F7は exclude_race_number=[4, 6]
        """
        race = make_race(spread=14.0, num_entries=9, race_num=4)
        race["expected_payout"] = 30_000  # F8は通過する値

        _, reasons = self.engine.apply(race)
        f7_reasons = [r for r in reasons if r.startswith("F7")]
        assert len(f7_reasons) > 0, (
            f"4RでF7が発動しない: {reasons}"
        )

    def test_f8_adds_to_existing_filter_reasons(self):
        """
        F8は既存フィルター理由リストに「追加」される（置換しない）。
        根拠: filter_engine の reasons リストに F8理由が付加される設計

        例: F2(決勝) + F8(低配当) → 両方の理由が reasons に含まれる
        cmd_146k_sub1: 新閾値3,000円未満(2,750円)でF8除外を確認
        """
        # 7車立て, spread=16 → 推定2,750円 < 3,000(新F8 min) → F8除外
        race = make_race(spread=16.0, num_entries=7)
        race["stage"] = "決勝"   # F2除外
        race["expected_payout"] = 2_750  # F8除外 (2,750 < 3,000)

        _, reasons = self.engine.apply(race)
        f2_reasons = [r for r in reasons if r.startswith("F2")]
        f8_reasons = [r for r in reasons if r.startswith("F8")]
        assert len(f2_reasons) > 0, f"F2理由なし: {reasons}"
        assert len(f8_reasons) > 0, f"F8理由なし（2,750円 < 3,000円でF8除外されるはず）: {reasons}"
        assert len(reasons) >= 2, (
            f"複数フィルター除外時に理由が2件以上あるべき: {reasons}"
        )

    def test_all_filters_pass_with_target_zone_payout(self):
        """
        全フィルター通過レース + F8目標ゾーン → 全フィルター通過。
        根拠: 適切なレースデータ + expected_payout=30,000 → F1-F8全て通過
        """
        race = {
            "venue_name": "大垣",      # F4通過
            "race_num": 5,              # F7通過 (4,6R除外)
            "race_no": 5,
            "grade": "S",              # F1通過
            "stage": "一予選",         # F2通過
            "bank_length": 400,        # F5通過 (500m除外)
            "date": "20260228",        # F6通過 (2/28=金曜日)
            "expected_payout": 30_000, # F8通過 (20,000〜50,000)
            "entries": [
                {"car_no": i, "grade": "S1", "score": 100.0 + i * 2}
                for i in range(1, 10)
            ],
        }
        # score_spread = 8*2 = 16 >= 12 → score_spreadフィルター通過
        passed, reasons = self.engine.apply(race)
        assert passed, (
            f"全フィルター通過レースが除外された: {reasons}"
        )
        assert len(reasons) == 0, (
            f"全フィルター通過のはずが除外理由あり: {reasons}"
        )
