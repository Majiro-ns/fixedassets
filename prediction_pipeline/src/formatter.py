"""
予想結果フォーマッター（競輪・競艇共通）
=========================================

予想パイプラインの各ステップ出力を JSON / テキスト形式に変換する。
data/predictions/ ディレクトリへの保存も担当する。

使用例:
    from src.formatter import format_prediction, save_prediction

    result = {
        "race_info": {...},
        "prediction": "軸: 1番...",
        "bet": {...},
    }
    formatted = format_prediction(result)
    save_prediction(formatted, output_dir="data/predictions")
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


def format_prediction(
    race_info: Dict[str, Any],
    prediction_text: str,
    bet_result: Optional[Dict[str, Any]] = None,
    profile: Optional[Dict[str, Any]] = None,
    model_used: Optional[str] = None,
) -> Dict[str, Any]:
    """
    予想結果を標準 JSON 形式に変換する。

    Args:
        race_info: レース情報辞書（venue_name, race_no, grade, stage 等）。
        prediction_text: LLM が生成した予想テキスト。
        bet_result: bet_calculator の出力辞書（オプション）。
        profile: 使用した予想師プロファイル（オプション）。
        model_used: 使用した LLM モデル名（オプション）。

    Returns:
        標準化された予想結果辞書。
    """
    now = datetime.now()
    return {
        "timestamp": now.isoformat(),
        "date": now.strftime("%Y%m%d"),
        "sport": race_info.get("sport", "keirin"),
        "race_info": {
            "venue_name": race_info.get("venue_name", ""),
            "race_no": race_info.get("race_no", ""),
            "grade": race_info.get("grade", ""),
            "stage": race_info.get("stage", ""),
            "start_time": race_info.get("start_time", ""),
        },
        "predictor": {
            "name": (profile or {}).get("predictor_name", "unknown"),
            "profile_id": (profile or {}).get("profile_id", ""),
            "model": model_used or "unknown",
        },
        "prediction": {
            "text": prediction_text,
            "entries": race_info.get("entries", []),
        },
        "bet": bet_result or {},
    }


def format_batch(
    predictions: List[Dict[str, Any]],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    複数レースの予想結果をバッチ形式にまとめる。

    Args:
        predictions: format_prediction() の返り値リスト。
        meta: バッチ全体のメタ情報（オプション）。

    Returns:
        バッチ形式の辞書。
    """
    now = datetime.now()
    return {
        "batch_id": now.strftime("%Y%m%d_%H%M%S"),
        "generated_at": now.isoformat(),
        "total_races": len(predictions),
        "meta": meta or {},
        "predictions": predictions,
    }


def save_prediction(
    formatted: Dict[str, Any],
    output_dir: str = "data/predictions",
    filename: Optional[str] = None,
) -> str:
    """
    予想結果を JSON ファイルとして保存する。

    Args:
        formatted: format_prediction() または format_batch() の出力。
        output_dir: 保存先ディレクトリ（存在しない場合は作成）。
        filename: ファイル名（省略時は自動生成）。

    Returns:
        保存したファイルのパス文字列。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sport = formatted.get("sport", formatted.get("predictions", [{}])[0].get("sport", "unknown"))
        filename = f"prediction_{sport}_{ts}.json"

    file_path = output_path / filename
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(formatted, f, ensure_ascii=False, indent=2)
        logger.info("予想結果を保存しました: %s", file_path)
        return str(file_path)
    except OSError as e:
        logger.error("ファイル保存エラー (%s): %s", file_path, e)
        raise


def to_text_summary(formatted: Dict[str, Any]) -> str:
    """
    予想結果辞書を人間が読みやすいテキスト形式に変換する。

    Args:
        formatted: format_prediction() の返り値。

    Returns:
        テキスト形式のサマリー文字列。
    """
    race = formatted.get("race_info", {})
    predictor = formatted.get("predictor", {})
    prediction = formatted.get("prediction", {})
    bet = formatted.get("bet", {})

    lines = [
        "=" * 50,
        f"【{race.get('venue_name', '')} {race.get('race_no', '')}R】"
        f" {race.get('grade', '')} {race.get('stage', '')}",
        f"予想: {predictor.get('name', '')} / モデル: {predictor.get('model', '')}",
        "-" * 50,
        prediction.get("text", ""),
    ]

    if bet and bet.get("bet_type") != "skip":
        lines += [
            "-" * 50,
            f"賭け式: {bet.get('bet_type', '')}",
            f"点数: {bet.get('num_bets', '')}点 / 合計: {bet.get('total_investment', '')}円",
        ]
    elif bet.get("bet_type") == "skip":
        lines.append(f"[見送り] {bet.get('reason', '')}")

    lines.append("=" * 50)
    return "\n".join(lines)


def batch_to_text_summary(batch: Dict[str, Any]) -> str:
    """
    バッチ予想結果をテキストサマリーに変換する。

    Args:
        batch: format_batch() の返り値。

    Returns:
        バッチ全体のテキストサマリー。
    """
    predictions = batch.get("predictions", [])
    meta = batch.get("meta", {})
    total = batch.get("total_races", len(predictions))

    lines = [
        f"=== 予想バッチ {batch.get('batch_id', '')} ===",
        f"生成日時: {batch.get('generated_at', '')}",
        f"対象レース数: {total}",
    ]

    if meta:
        lines.append(f"メタ情報: {meta}")

    lines.append("")
    for p in predictions:
        lines.append(to_text_summary(p))
        lines.append("")

    # 投資サマリー
    total_investment = sum(
        p.get("bet", {}).get("total_investment", 0)
        for p in predictions
        if p.get("bet", {}).get("bet_type") != "skip"
    )
    if total_investment > 0:
        lines.append(f"【本日合計投資額】 {total_investment:,}円")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 新規追加: JSON / Markdown / netkeirin形式フォーマット関数
# (predictor.py + bet_calculator.py の出力に特化)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_axis_partners(prediction_text: str) -> Tuple[Optional[int], List[int]]:
    """
    予想テキストから軸番号と相手番号を正規表現で抽出する。

    対応パターン例:
        「軸: 1番」「軸: 1」「◎1番」「本命: 3番」「本命3番」
        「相手: 2, 4, 5番」「相手: 2番、4番、5番」「△2番、4番」

    Args:
        prediction_text: predictor.py の generate_prediction が返す予想テキスト

    Returns:
        (axis, partners) のタプル。
        axis: 軸番号（int）。抽出不可なら None。
        partners: 相手番号のリスト（list[int]）。抽出不可なら []。
    """
    axis: Optional[int] = None
    partners: List[int] = []

    # ── 軸番号の抽出 ──────────────────────────────────────────────────────
    axis_patterns = [
        r"軸\s*[:：]\s*(\d+)\s*番?",
        r"◎\s*(\d+)\s*番?",
        r"本命\s*[:：]?\s*(\d+)\s*番?",
        r"軸選手\s*[:：]?\s*(\d+)\s*番?",
        r"軸\s*（(\d+)番）",
    ]
    for pattern in axis_patterns:
        m = re.search(pattern, prediction_text)
        if m:
            axis = int(m.group(1))
            break

    # ── 相手番号の抽出 ────────────────────────────────────────────────────
    partner_patterns = [
        r"相手\s*[:：]\s*([\d\s,、・番]+)",
        r"△\s*([\d\s,、・番]+)",
        r"相手選手\s*[:：]?\s*([\d\s,、・番]+)",
        r"ヒモ\s*[:：]?\s*([\d\s,、・番]+)",
    ]
    for pattern in partner_patterns:
        m = re.search(pattern, prediction_text)
        if m:
            raw = m.group(1)
            nums = re.findall(r"\d+", raw)
            extracted = [int(n) for n in nums if axis is None or int(n) != axis]
            if extracted:
                partners = extracted
                break

    return axis, partners


def _get_filter_headline(filter_type: str) -> str:
    """
    filter_type に対応する netkeirin「ウマい車券」風ヘッドラインを返す。

    Mr.T認知プロファイルのフィルター定義に準拠:
        C (堅実×S級×特選/二次予選): 「獲りやすさ」で的中率54.5%
        B (穴狙い×S級×特選/二次予選): 「高配当」で回収率263.9%
        A (S級×特選/二次予選×逆指標除外): 波乱・中穴ゾーン

    Args:
        filter_type: "A" / "B" / "C"（それ以外は汎用ヘッドラインを返す）

    Returns:
        ヘッドライン文字列
    """
    headlines: Dict[str, str] = {
        "C": "獲りやすさ抜群！点数絞って攻める！",
        "B": "高配当狙える！妙味ある一戦！",
        "A": "波乱の可能性あり！中穴ゾーンで攻める！",
    }
    return headlines.get(filter_type.upper(), "注目の一戦！買い目を絞って勝負！")


def _format_partners(partners: List[int]) -> str:
    """
    相手番号リストを日本語読点（、）区切りに変換する。

    例: [1, 2, 3] → "1、2、3"

    Args:
        partners: 相手番号の整数リスト

    Returns:
        読点区切りの文字列。空リストの場合は "要確認"。
    """
    if not partners:
        return "要確認"
    return "、".join(str(p) for p in partners)


def format_json(
    prediction: str,
    bet_result: Union[Dict, List[Dict]],
    race_data: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    予想結果と賭け式計算結果をJSON文字列に変換する。

    Args:
        prediction: predictor.py の generate_prediction が返す予想テキスト（str）
        bet_result: bet_calculator.py の calc_* が返す辞書、またはそのリスト
        race_data:  レース情報。venue_name, race_no, grade を含む辞書
        metadata:   任意の付加情報。sport, filter_type, model 等を含む辞書

    Returns:
        JSONフォーマット済み文字列（indent=2, ensure_ascii=False）
    """
    if metadata is None:
        metadata = {}

    generated_at = datetime.now().isoformat(timespec="seconds")
    axis, partners = _extract_axis_partners(prediction)

    output = {
        "meta": {
            "generated_at": generated_at,
            "sport": metadata.get("sport", "keirin"),
            "filter_type": metadata.get("filter_type", None),
            "model": metadata.get("model", None),
        },
        "race": {
            "venue_name": race_data.get("venue_name", "不明"),
            "race_no": race_data.get("race_no", None),
            "grade": race_data.get("grade", None),
        },
        "prediction": {
            "raw_text": prediction,
            "axis": axis,
            "partners": partners,
        },
        "bet": bet_result,
    }

    return json.dumps(output, ensure_ascii=False, indent=2)


def format_markdown(
    prediction: str,
    bet_result: Union[Dict, List[Dict]],
    race_data: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    レポート用のMarkdown文字列を生成する。

    bet_result が allocation_plan キーを持つ場合（calc_kelly_allocation の返り値）、
    「### Kelly最適配分（filter_{filter_type}）」セクションを追加する。

    Args:
        prediction: predictor.py の generate_prediction が返す予想テキスト（str）
        bet_result: bet_calculator.py の calc_* が返す辞書、またはそのリスト
        race_data:  レース情報。venue_name, race_no, grade を含む辞書
        metadata:   任意の付加情報。filter_type 等を含む辞書

    Returns:
        Markdownフォーマット済み文字列
    """
    if metadata is None:
        metadata = {}

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    venue = race_data.get("venue_name", "不明")
    race_no = race_data.get("race_no", "?")
    grade = race_data.get("grade", "?")
    filter_type = metadata.get("filter_type", "-")

    lines: List[str] = []
    lines.append(f"## {venue} {race_no}R — {grade}")
    lines.append("")
    lines.append(f"**フィルタータイプ**: {filter_type}")
    lines.append(f"**生成日時**: {generated_at}")
    lines.append("")
    lines.append("### 予想")
    lines.append("")
    lines.append(prediction)
    lines.append("")
    lines.append("### 買い目")
    lines.append("")
    lines.append("| 賭け式 | 点数 | 単価 | 合計 |")
    lines.append("|--------|------|------|------|")

    # bet_result を行リストに正規化
    rows: List[Dict] = bet_result if isinstance(bet_result, list) else [bet_result]
    total_investment = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        bet_type = row.get("bet_type", "不明")
        if bet_type == "skip":
            lines.append(f"| {row.get('reason', '見送り')} | — | — | — |")
            continue
        num_bets = row.get("num_bets", 0)
        unit_bet = row.get("unit_bet", 0)
        invest = row.get("total_investment", 0)
        total_investment += invest
        lines.append(
            f"| {bet_type} | {num_bets}点 | ¥{unit_bet:,} | ¥{invest:,} |"
        )

    lines.append("")
    lines.append(f"**合計投資額**: ¥{total_investment:,} 円")
    lines.append("")

    # Kelly配分セクション（allocation_plan キーがある場合）
    if isinstance(bet_result, dict) and "allocation_plan" in bet_result:
        filter_label = f"filter_{filter_type}" if filter_type != "-" else "配分"
        lines.append(f"### Kelly最適配分（{filter_label}）")
        lines.append("")
        allocation = bet_result["allocation_plan"]
        if isinstance(allocation, dict):
            for key, val in allocation.items():
                lines.append(f"- **{key}**: {val}")
        elif isinstance(allocation, list):
            for item in allocation:
                lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)


def format_netkeirin_style(
    prediction: str,
    race_data: Dict[str, Any],
    filter_type: str = "A",
) -> str:
    """
    netkeirin「ウマい車券」掲載形式のテキストを生成する。
    Mr.Tの高収益コメントスタイル（mr_t_cognitive_profile.yaml より）を模倣する。

    filter_type 別ヘッドライン（Mr.T認知プロファイルのフィルター定義に準拠）:
        "C" → 「獲りやすさ抜群！点数絞って攻める！」  （的中率58.3%）
        "B" → 「高配当狙える！妙味ある一戦！」        （回収率197.7%）
        "A" → 「波乱の可能性あり！中穴ゾーンで攻める！」（回収率148.7%）

    Args:
        prediction:  predictor.py の generate_prediction が返す予想テキスト（str）
        race_data:   レース情報。venue_name, race_no を含む辞書
        filter_type: フィルタータイプ。"A" / "B" / "C"（デフォルト: "A"）

    Returns:
        netkeirin「ウマい車券」風のテキスト文字列
    """
    venue = race_data.get("venue_name", "不明")
    race_no = race_data.get("race_no", "?")
    headline = _get_filter_headline(filter_type)

    axis, partners = _extract_axis_partners(prediction)

    # 予想テキストを200文字以内に要約（先頭200文字）
    summary = prediction[:200].strip()
    if len(prediction) > 200:
        summary += "…"

    axis_display = f"{axis}番" if axis is not None else "要確認"
    partners_display = _format_partners(partners)

    if axis is not None and partners:
        # bet_calculator._format_nagashi と同じ形式: "3-145"（相手は連結）
        partners_str = "".join(str(p) for p in partners)
        bet_display = f"3連複ながし {axis}-{partners_str}"
    else:
        bet_display = "要確認"

    lines = [
        f"【{venue} {race_no}R】",
        headline,
        "",
        summary,
        "",
        f"◎軸: {axis_display}",
        f"△相手: {partners_display}番",
        f"買い目: {bet_display}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # 動作確認
    sample_race = {
        "sport": "keirin",
        "venue_name": "川崎",
        "race_no": 9,
        "grade": "S1",
        "stage": "準決勝",
        "entries": [
            {"car_no": 1, "name": "山田太郎", "grade": "S1"},
            {"car_no": 2, "name": "鈴木一郎", "grade": "S1"},
        ],
    }
    sample_prediction = "軸: 1番（山田）\n相手: 2番、3番、5番\nコメント: ライン先頭が絞れる。"
    sample_bet = {
        "bet_type": "3連複ながし",
        "num_bets": 3,
        "total_investment": 1500,
        "unit_bet": 500,
    }

    result = format_prediction(sample_race, sample_prediction, sample_bet, model_used="claude-haiku-4-5-20251001")
    print(to_text_summary(result))

    batch = format_batch([result], meta={"sport": "keirin", "date": "20260222"})
    print(batch_to_text_summary(batch))

    # ── 新規関数の動作確認 ────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("  新規関数 (format_json / format_markdown / format_netkeirin_style)")
    print("=" * 50)

    mock_race_data = {
        "venue_name": "平塚",
        "race_no": 7,
        "grade": "S1",
    }
    mock_prediction = (
        "軸: 3番 中田諒。ライン分析を踏まえると、今節の動きが違う。\n"
        "相手: 1番、4番、5番。3連複ながし推奨。\n"
        "展開次第で波乱の可能性あり。妙味ある一戦。"
    )
    mock_bet_result = {
        "bet_type": "3連複ながし",
        "axis": 3,
        "partners": [1, 4, 5],
        "combinations": [(1, 3, 4), (1, 3, 5), (3, 4, 5)],
        "num_bets": 3,
        "unit_bet": 1200,
        "total_investment": 3600,
        "display": "3連複ながし 3-145",
    }
    mock_metadata = {
        "sport": "keirin",
        "filter_type": "C",
        "model": "claude-haiku-4-5-20251001",
    }

    print("\n[1] format_json:")
    print(format_json(mock_prediction, mock_bet_result, mock_race_data, mock_metadata))

    print("\n[2] format_markdown:")
    print(format_markdown(mock_prediction, mock_bet_result, mock_race_data, mock_metadata))

    print("\n[3] format_netkeirin_style (filter A/B/C):")
    for ft in ["A", "B", "C"]:
        print(f"\n--- filter_type={ft} ---")
        print(format_netkeirin_style(mock_prediction, mock_race_data, filter_type=ft))
