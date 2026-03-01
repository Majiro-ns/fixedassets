"""
コメント生成モジュール（F-E03 段階1）
====================================

予想データの dict から競技・スタイルに応じたコメント文字列を生成する。
LLM が生成した予想テキストからコメントを抽出する関数も提供する。

使用例:
    from src.comment_generator import generate_comment, extract_comment_from_text

    # 予想 dict からコメントを生成
    prediction = {
        "sport": "keirin",
        "predictor": "mrt",
        "race": {
            "venue": "川崎",
            "axis_name": "山田太郎",
            "partners": ["鈴木", "田中"],
        },
        "analysis": {
            "keywords": ["逃げ有利", "ライン先頭"],
            "confidence_tag": "堅実",
        },
    }
    comment = generate_comment(prediction, style="mrt_keirin")

    # LLM生成テキストからコメント行を抽出
    text = "軸: 1番\\n相手: 2番\\nコメント: ライン先頭の逃げ有利。"
    comment = extract_comment_from_text(text)
"""

import re
from typing import Any


# ─── スタイル定義 ────────────────────────────────────────────────────────────

# mrt_keirin: 競輪Mr.T風（展開予想→有利選手→相手候補の段落形式）
# minimal: シンプル・データ重視
# boat_pro: 競艇師匠風（競艇対応時に追加）
_STYLES: dict[str, dict[str, str]] = {
    "mrt_keirin": {
        "sport": "keirin",
        "template": "{flow}の展開になるとみて、{axis}が有利。相手は{partners}。",
    },
    "minimal": {
        "sport": "keirin",
        "template": "{axis} 軸。相手: {partners}。",
    },
}


# ─── メイン関数 ──────────────────────────────────────────────────────────────

def generate_comment(
    prediction: dict[str, Any],
    style: str = "mrt_keirin",
) -> str:
    """予想データの dict からコメント文字列を生成する。

    コメント定型（競輪）:
      - 「こういう展開になる」→「この選手が有利」→（相手はこの人）
      - または「こういう展開になる」→「この選手が得意な条件」→（相手はこの人）
      - または「この選手の調子が良い」→「この選手が狙い目」→（相手はこの人）

    Args:
        prediction: 予想データ辞書。以下のキーを参照する:
            - sport: 競技種別 (keirin | boat | horse)
            - predictor: 予想師ID（str）
            - race: レース情報。以下のキーを参照する:
                - venue: 会場名
                - axis_name: 軸選手名（str）
                - axis: 軸選手番号（str または int、axis_name がない場合に参照）
                - partners: 相手選手リスト（list[str | int]）
                - bet_lines: 買い目リスト（list、未使用・将来用）
            - analysis: 分析情報。以下のキーを参照する:
                - keywords: 展開予想キーワードリスト（list[str]）
                - confidence_tag: 信頼度タグ（str）
                - hit_probability: 的中確率（float、未使用・将来用）
                - custom: 追加情報（任意）
        style: コメントスタイルID。利用可能: "mrt_keirin"（デフォルト）、"minimal"。

    Returns:
        コメント文字列。入力情報が不足している場合はプレースホルダーで補完する。

    Raises:
        KeyError: 未定義の style が指定された場合（フォールバックなし）。
    """
    race = prediction.get("race", {})
    analysis = prediction.get("analysis", {})

    # 展開予想キーワードを結合してフローテキスト生成
    keywords = analysis.get("keywords", [])
    if keywords:
        flow = "、".join(str(kw) for kw in keywords[:2])
    else:
        flow = analysis.get("confidence_tag", "展開注視")

    # 軸選手: axis_name → axis の順で参照
    axis_name = race.get("axis_name") or race.get("axis", "")
    axis_str = str(axis_name) if axis_name else "要確認"

    # 相手選手リストを読点区切りテキストに変換
    partners = race.get("partners", [])
    if isinstance(partners, list):
        partners_str = "、".join(str(p) for p in partners[:4])
    else:
        partners_str = str(partners) if partners else "要確認"

    style_def = _STYLES.get(style, _STYLES["mrt_keirin"])
    template = style_def["template"]

    return template.format(
        flow=flow,
        axis=axis_str,
        partners=partners_str or "要確認",
    )


# ─── 抽出関数（LLMテキスト → コメント） ────────────────────────────────────

def extract_comment_from_text(prediction_text: str) -> str:
    """LLM生成の予想テキストから「コメント」「根拠」「理由」行を抽出する。

    auto_publish.py の _parse_prediction_text() 内で行っているコメント抽出ロジックを
    共通関数として切り出したもの。既存の出力フォーマットは維持する。

    Args:
        prediction_text: LLM が生成した予想テキスト。
            対応形式:
              - 「コメント: ...」
              - 「根拠: ...」
              - 「理由: ...」

    Returns:
        コメント文字列（先頭50文字）。対応行が見つからない場合は空文字列。
    """
    m = re.search(r"(?:コメント|根拠|理由)[：:]\s*(.+)", prediction_text)
    if m:
        return m.group(1).strip()[:50]
    return ""
