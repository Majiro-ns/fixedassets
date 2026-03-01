"""
Stage 2 Mock Mode モジュール
==============================
環境変数 KEIRIN_MOCK_MODE=1 でAPIキーなしのデモ予想を生成する。

【目的】
- 殿へのデモ時にAPIキーなしでパイプライン全体を動作させる
- mock予想はnaive（score top3）。精度は期待しない
- 実APIとの切替が容易な設計

【使い方】
    KEIRIN_MOCK_MODE=1 python main.py --date 20260228 --dry-run

【設計方針】
- is_mock_mode(): 環境変数チェック
- _generate_mock_prediction(race): score上位3選手を機械的に選択
  - 軸: score最高の選手
  - 相手: score2位・3位（2名）
  - 出力フォーマット: 実APIと同一（軸/相手/買い目/根拠）
  - confidence: "mock"（実予想と区別）
"""

import os
from typing import Any, Dict, List, Optional

MOCK_MODE_ENV = "KEIRIN_MOCK_MODE"


def is_mock_mode() -> bool:
    """環境変数 KEIRIN_MOCK_MODE=1 が設定されているか確認する。

    Returns:
        True: KEIRIN_MOCK_MODE=1 が設定されている場合
        False: それ以外
    """
    return os.environ.get(MOCK_MODE_ENV, "0") == "1"


def _get_score(entry: Dict[str, Any]) -> float:
    """エントリーからスコアを取得する。複数フィールドに対応。

    Args:
        entry: 選手エントリー辞書

    Returns:
        スコア値（float）。見つからない場合は 0.0
    """
    for key in ("score", "competitive_score", "win_rate"):
        val = entry.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


def _generate_mock_prediction(race: Dict[str, Any]) -> Dict[str, Any]:
    """score上位3選手を機械的に選択してmock予想を生成する。

    実APIとの互換性のため、出力フォーマットは generate_prediction() の
    返り値と同一にする。

    Args:
        race: レース辞書（entries を含む）
            entries の各要素は以下のいずれかのスコアフィールドを持つ:
            - score (keirin: 競走得点)
            - competitive_score
            - win_rate

    Returns:
        mock予想辞書:
        {
            "axis": int,              # score最高選手のcar_no
            "partners": List[int],    # score2-3位のcar_no（2名）
            "prediction_text": str,   # 実APIと同フォーマット
            "confidence": "mock",     # 実予想と区別
            "reasoning": str,         # mock予想の理由
            "mock_mode": True,        # mockフラグ
        }
    """
    entries = race.get("entries", [])

    # scoreでソート（降順）
    scored_entries = sorted(entries, key=_get_score, reverse=True)

    if len(scored_entries) < 2:
        # 選手が2人未満の場合はデータ不足
        return {
            "axis": None,
            "partners": [],
            "prediction_text": "[MOCK] データ不足のため予想生成不可（選手数が2名未満）",
            "confidence": "mock",
            "reasoning": "Mock mode: entries insufficient (< 2 players)",
            "mock_mode": True,
        }

    axis_entry = scored_entries[0]
    partner_entries = scored_entries[1:3]  # score2位・3位（軸1名+相手2名=3選手合計でnaiveな3連単）

    axis_no: int = axis_entry.get("car_no", 1)
    axis_name: str = axis_entry.get("name", f"{axis_no}番選手")
    axis_score: float = _get_score(axis_entry)

    partner_nos: List[int] = [e.get("car_no", 0) for e in partner_entries]
    partner_names: List[str] = [e.get("name", f"{no}番") for e, no in zip(partner_entries, partner_nos)]  # noqa: F841

    venue = race.get("venue_name", "")
    race_no = race.get("race_no", "")
    grade = race.get("grade", "")
    stage = race.get("stage", "")

    # 実APIと同フォーマットの予想テキストを生成
    partners_text = "、".join([f"{no}番" for no in partner_nos])
    bet_nums = f"{axis_no}-{','.join(str(p) for p in partner_nos)}"

    prediction_text = (
        f"本命: {axis_no}番（{axis_name}）\n"
        f"軸相手: {partners_text}\n"
        f"買い目: 3連単 {bet_nums} ながし（{len(partner_nos)}点）\n"
        f"根拠: [MOCK MODE] 競走得点上位選手を機械的に選択。"
        f"軸{axis_no}番（{axis_name}、得点{axis_score:.2f}）が最高得点。"
        f"精度は期待しない。パイプライン動作確認用。"
    )

    reasoning = (
        f"Mock mode: score top3 from entries "
        f"(axis={axis_no} score={axis_score:.2f}, "
        f"partners={partner_nos})"
    )

    return {
        "axis": axis_no,
        "partners": partner_nos,
        "prediction_text": prediction_text,
        "confidence": "mock",
        "reasoning": reasoning,
        "mock_mode": True,
    }
