"""
公営競技スクレイパー 抽象基底クラス
各競技スクレイパー（競艇・競輪等）が継承する共通インターフェースを定義する。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseScraper(ABC):
    """公営競技スクレイパーの抽象基底クラス。

    サブクラスは fetch_entries / fetch_result / fetch_schedule の
    3メソッドを必ず実装しなければならない。
    """

    @abstractmethod
    def fetch_entries(
        self,
        date: str,
        venue_code: str,
        race_num: int,
    ) -> List[Dict[str, Any]]:
        """指定レースの出走表（エントリー情報）を取得する。

        Args:
            date: 日付文字列（YYYYMMDD 形式、例: "20260222"）
            venue_code: 会場コード（2 桁ゼロ埋め文字列、例: "01"）
            race_num: レース番号（1〜12）

        Returns:
            各出走艇（選手）の情報を格納した辞書のリスト。
            辞書キーはサブクラスの競技仕様に従う。
            例（競艇）::

                [
                    {
                        "boat_number": 1,
                        "racer_name": "山田 太郎",
                        "registration_number": "012345",
                        "racer_class": "A1",
                        "weight_kg": 55.0,
                        "false_start_count": 0,
                        "motor_win_rate": 0.52,
                        "boat_win_rate": 0.48,
                        "avg_start_timing": 0.14,
                        "course_stats": {"1": 0.30, "2": 0.40},
                    },
                    ...
                ]

        Raises:
            urllib.error.URLError: ネットワークエラー時
            ValueError: 日付・会場コードの形式が不正な場合
        """
        ...

    @abstractmethod
    def fetch_result(
        self,
        date: str,
        venue_code: str,
        race_num: int,
    ) -> Optional[Dict[str, Any]]:
        """指定レースの着順結果を取得する。

        Args:
            date: 日付文字列（YYYYMMDD 形式）
            venue_code: 会場コード（2 桁ゼロ埋め文字列）
            race_num: レース番号（1〜12）

        Returns:
            レース結果辞書。レース未終了時は None。
            例（競艇）::

                {
                    "race_num": 1,
                    "winning_order": [3, 1, 4],   # 1着〜3着の艇番
                    "trifecta_odds": 125.8,         # 3連単配当
                    "trio_odds": 18.5,              # 3連複配当
                }

        Raises:
            urllib.error.URLError: ネットワークエラー時
        """
        ...

    @abstractmethod
    def fetch_schedule(self, date: str) -> List[Dict[str, Any]]:
        """指定日の全会場開催スケジュールを取得する。

        Args:
            date: 日付文字列（YYYYMMDD 形式）

        Returns:
            開催レース情報のリスト。各要素は最低限
            venue_code / venue_name / race_num / grade を含む。
            例（競艇）::

                [
                    {
                        "venue_code": "12",
                        "venue_name": "住之江",
                        "race_num": 12,
                        "grade": "SG",
                        "start_time": "2026-02-22T15:30:00",
                    },
                    ...
                ]

        Raises:
            urllib.error.URLError: ネットワークエラー時
        """
        ...
