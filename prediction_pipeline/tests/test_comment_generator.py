"""
tests/test_comment_generator.py
================================

F-E03 段階1: comment_generator モジュールのユニットテスト

受け入れ基準:
  - generate_comment() が dict 入力からコメントを生成できる
  - extract_comment_from_text() の出力が既存 _parse_prediction_text の出力と一致する
  - mrt_keirin スタイルで定型コメントが生成される
"""

import pytest

from src.comment_generator import extract_comment_from_text, generate_comment


# ─── generate_comment() のテスト ─────────────────────────────────────────────

class TestGenerateComment:
    """generate_comment() の動作確認。"""

    def _make_prediction(self, **overrides) -> dict:
        """テスト用の予想 dict を生成する。"""
        base = {
            "sport": "keirin",
            "predictor": "mrt",
            "race": {
                "venue": "川崎",
                "axis_name": "山田太郎",
                "partners": ["鈴木一郎", "田中次郎", "佐藤三郎"],
            },
            "analysis": {
                "keywords": ["逃げ有利", "ライン先頭"],
                "confidence_tag": "堅実",
            },
        }
        base.update(overrides)
        return base

    def test_mrt_keirin_style_contains_flow(self):
        """mrt_keirinスタイル: キーワードが展開部分に含まれる。"""
        prediction = self._make_prediction()
        comment = generate_comment(prediction, style="mrt_keirin")
        assert "逃げ有利" in comment

    def test_mrt_keirin_style_contains_axis(self):
        """mrt_keirinスタイル: 軸選手名が含まれる。"""
        prediction = self._make_prediction()
        comment = generate_comment(prediction, style="mrt_keirin")
        assert "山田太郎" in comment

    def test_mrt_keirin_style_contains_partner(self):
        """mrt_keirinスタイル: 相手選手名が含まれる。"""
        prediction = self._make_prediction()
        comment = generate_comment(prediction, style="mrt_keirin")
        assert "鈴木一郎" in comment

    def test_mrt_keirin_default_style(self):
        """引数省略時はmrt_keirinがデフォルト。"""
        prediction = self._make_prediction()
        comment_default = generate_comment(prediction)
        comment_explicit = generate_comment(prediction, style="mrt_keirin")
        assert comment_default == comment_explicit

    def test_minimal_style_contains_axis(self):
        """minimalスタイル: 軸選手名が含まれる。"""
        prediction = self._make_prediction()
        comment = generate_comment(prediction, style="minimal")
        assert "山田太郎" in comment

    def test_minimal_style_different_from_mrt(self):
        """minimalスタイルはmrt_keirinと異なる出力を返す。"""
        prediction = self._make_prediction()
        c_mrt = generate_comment(prediction, style="mrt_keirin")
        c_min = generate_comment(prediction, style="minimal")
        assert c_mrt != c_min

    def test_axis_fallback_to_axis_key(self):
        """axis_name がない場合、axis キーを参照する。"""
        prediction = {
            "sport": "keirin",
            "race": {"axis": "3番", "partners": ["1番"]},
            "analysis": {"keywords": ["まくり有効"]},
        }
        comment = generate_comment(prediction)
        assert "3番" in comment

    def test_no_keywords_uses_confidence_tag(self):
        """keywords が空の場合、confidence_tag を使用する。"""
        prediction = {
            "sport": "keirin",
            "race": {"axis_name": "田中", "partners": ["山田"]},
            "analysis": {"confidence_tag": "中穴狙い", "keywords": []},
        }
        comment = generate_comment(prediction)
        assert "中穴狙い" in comment

    def test_partners_list_limit_4(self):
        """相手が5人以上いても先頭4人のみ使用する。"""
        prediction = {
            "sport": "keirin",
            "race": {
                "axis_name": "軸",
                "partners": ["A", "B", "C", "D", "E"],
            },
            "analysis": {"keywords": ["展開注視"]},
        }
        comment = generate_comment(prediction)
        assert "E" not in comment  # 5番目は除外
        assert "D" in comment      # 4番目は含む

    def test_returns_string(self):
        """戻り値が str であることを確認。"""
        prediction = self._make_prediction()
        result = generate_comment(prediction)
        assert isinstance(result, str)

    def test_empty_prediction(self):
        """空の dict でもエラーにならない。"""
        comment = generate_comment({})
        assert isinstance(comment, str)
        assert len(comment) > 0


# ─── extract_comment_from_text() のテスト ───────────────────────────────────

class TestExtractCommentFromText:
    """extract_comment_from_text() の動作確認。

    既存 _parse_prediction_text() との出力一致を検証する。
    """

    def test_extracts_comment_keyword(self):
        """「コメント:」行を抽出できる。"""
        text = "軸: 1番\n相手: 2番\nコメント: ライン先頭の逃げ有利。"
        result = extract_comment_from_text(text)
        assert result == "ライン先頭の逃げ有利。"

    def test_extracts_konkyou_keyword(self):
        """「根拠:」行を抽出できる。"""
        text = "軸: 3番\n相手: 1番、5番\n根拠: ラインが揃う展開。"
        result = extract_comment_from_text(text)
        assert result == "ラインが揃う展開。"

    def test_extracts_riyuu_keyword(self):
        """「理由:」行を抽出できる。"""
        text = "軸: 2番\n相手: 4番\n理由: まくりが決まりやすい。"
        result = extract_comment_from_text(text)
        assert result == "まくりが決まりやすい。"

    def test_extracts_full_width_colon(self):
        """「コメント：」（全角コロン）にも対応する。"""
        text = "コメント：全角コロンのテスト。"
        result = extract_comment_from_text(text)
        assert result == "全角コロンのテスト。"

    def test_truncates_to_50_chars(self):
        """50文字を超えるコメントは50文字に切り詰める。"""
        long_text = "コメント: " + "A" * 60
        result = extract_comment_from_text(long_text)
        assert len(result) == 50

    def test_returns_empty_if_not_found(self):
        """コメント行がなければ空文字列を返す。"""
        text = "軸: 1番\n相手: 2番、3番"
        result = extract_comment_from_text(text)
        assert result == ""

    def test_empty_string_returns_empty(self):
        """空文字列入力は空文字列を返す。"""
        result = extract_comment_from_text("")
        assert result == ""

    def test_output_matches_original_logic(self):
        """既存ロジック（auto_publish._parse_prediction_text 相当）との出力一致確認。"""
        import re

        def original_extract(text: str) -> str:
            """auto_publish.py の _parse_prediction_text 内の元ロジック。"""
            m = re.search(r"(?:コメント|根拠|理由)[：:]\s*(.+)", text)
            if m:
                return m.group(1).strip()[:50]
            return ""

        test_cases = [
            "軸: 1番\n相手: 2番\nコメント: ライン先頭の逃げ有利。",
            "根拠: まくりが決まりやすい条件だ。",
            "理由: ラインが揃う展開になりそう。",
            "コメント：全角コロン。",
            "コメント: " + "X" * 60,
            "コメントなし",
            "",
        ]
        for text in test_cases:
            assert extract_comment_from_text(text) == original_extract(text), (
                f"不一致: text={text!r}"
            )
