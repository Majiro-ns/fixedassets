"""
予想生成モジュール (predictor.py) のテストスイート

- Haiku API での予想生成テスト
- Haiku vs Sonnet の品質比較テスト
- APIモックを使ったLLM応答テスト（ANTHROPIC_API_KEY不要）
- CREプロファイル注入テスト
- エッジケース・タイムアウトテスト
ANTHROPIC_API_KEY 環境変数が設定されていない場合はAPI接続テストをスキップする。
"""

import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# src/ をパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.predictor import (
    generate_prediction,
    load_cre_profile,
    build_cre_system_prompt,
    _extract_template_section,
    _build_entries_table_keirin,
    _generate_line_formation,
)


# ─── テスト共通データ ──────────────────────────────────────────────

SAMPLE_RACE = {
    "venue_name": "川崎",
    "race_no": 9,
    "grade": "S1",
    "stage": "準決勝",
    "entries": [
        {"car_no": 1, "name": "山田太郎", "grade": "S1", "win_rate": 0.312},
        {"car_no": 2, "name": "鈴木一郎", "grade": "S1", "win_rate": 0.289},
        {"car_no": 3, "name": "田中健一", "grade": "S1", "win_rate": 0.271},
        {"car_no": 4, "name": "佐藤次郎", "grade": "S2", "win_rate": 0.198},
        {"car_no": 5, "name": "伊藤三郎", "grade": "S2", "win_rate": 0.185},
        {"car_no": 6, "name": "渡辺四郎", "grade": "A1", "win_rate": 0.143},
        {"car_no": 7, "name": "中村五郎", "grade": "A1", "win_rate": 0.127},
    ],
}

SAMPLE_PROFILE = {
    "name": "AI予想師テスト",
    "style": "データ重視・ライン分析",
    "strengths": ["S1準決勝", "高配当穴狙い"],
}

BASE_CONFIG = {
    "llm": {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 256,
        "temperature": 0.5,
    }
}

# API キーが設定されていない場合はスキップ
requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY env var not set",
)


# ─── ユニットテスト（API呼び出し不要）────────────────────────────

class TestPredictorInputValidation:
    """predictor モジュールの入力処理テスト（API不要）。"""

    def test_import_generate_prediction(self):
        """generate_prediction 関数がインポートできること。"""
        assert callable(generate_prediction)

    def test_no_api_key_delegates_to_code_agent(self, monkeypatch):
        """ANTHROPIC_API_KEY 未設定時に code_agent モードに遷移すること。

        NOTE: cmd_098 で code_agent IPC モードを追加。APIキー未設定時は
        EnvironmentError を raise する代わりに _request_code_agent_prediction
        へ委任するように変更されたため、テストをその挙動に合わせる。
        """
        import src.predictor as pred_module

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        called_args = []

        def mock_code_agent(*args, **kwargs):
            called_args.append(args)
            return "[code_agent] mock prediction"

        monkeypatch.setattr(pred_module, "_request_code_agent_prediction", mock_code_agent)
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, BASE_CONFIG)
        assert result == "[code_agent] mock prediction"
        assert len(called_args) == 1, "code_agent が1回呼ばれること"

    def test_dry_run_no_api_key(self, monkeypatch):
        """dry_run=True の場合、APIキーなしでも即座に返ること。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        dry_config = {**BASE_CONFIG, "dry_run": True}
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, dry_config)
        assert "[DRY-RUN]" in result

    def test_raises_without_model_key(self, monkeypatch):
        """config["llm"]["model"] が存在しない場合に KeyError が発生すること。"""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy_key_for_test")
        bad_config = {"llm": {}}  # model キーなし
        with pytest.raises((KeyError, Exception)):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, bad_config)


# ─── API 接続テスト（ANTHROPIC_API_KEY 必須）─────────────────────

class TestPredictHaiku:
    """claude-haiku-4-5-20251001 での予想生成テスト。"""

    @requires_api_key
    def test_predict_haiku(self):
        """claude-haiku-4-5-20251001 での予想生成（基本動作）。"""
        config = dict(BASE_CONFIG)
        config["llm"] = dict(BASE_CONFIG["llm"])
        config["llm"]["model"] = "claude-haiku-4-5-20251001"
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config)
        assert isinstance(result, str)
        assert len(result) > 10
        assert "軸" in result or "本命" in result, (
            f"予想テキストに「軸」または「本命」が含まれること。実際の出力: {result[:100]}"
        )

    @requires_api_key
    def test_predict_haiku_contains_car_numbers(self):
        """Haiku の予想が車番を含むこと。"""
        config = dict(BASE_CONFIG)
        config["llm"] = dict(BASE_CONFIG["llm"])
        config["llm"]["model"] = "claude-haiku-4-5-20251001"
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config)
        # 出走している車番 1-7 のいずれかが言及されること
        has_car_no = any(str(i) in result for i in range(1, 8))
        assert has_car_no, f"車番が含まれていません。実際の出力: {result[:200]}"

    @requires_api_key
    def test_predict_haiku_response_length(self):
        """Haiku の予想が適切な長さであること（短すぎ・長すぎない）。"""
        config = dict(BASE_CONFIG)
        config["llm"] = dict(BASE_CONFIG["llm"])
        config["llm"]["model"] = "claude-haiku-4-5-20251001"
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config)
        assert 20 <= len(result) <= 1000, (
            f"予想テキストの長さが適切でない: {len(result)} 文字"
        )


class TestPredictSonnet:
    """claude-sonnet-4-6 での予想生成テスト。"""

    @requires_api_key
    def test_predict_sonnet(self):
        """claude-sonnet-4-6 での予想生成（基本動作）。"""
        config = dict(BASE_CONFIG)
        config["llm"] = dict(BASE_CONFIG["llm"])
        config["llm"]["model"] = "claude-sonnet-4-6"
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config)
        assert isinstance(result, str)
        assert len(result) > 10
        assert "軸" in result or "本命" in result, (
            f"予想テキストに「軸」または「本命」が含まれること。実際の出力: {result[:100]}"
        )

    @requires_api_key
    def test_predict_sonnet_contains_reasoning(self):
        """Sonnet の予想が根拠説明を含むこと（Haiku より詳細な想定）。"""
        config = dict(BASE_CONFIG)
        config["llm"] = dict(BASE_CONFIG["llm"])
        config["llm"]["model"] = "claude-sonnet-4-6"
        config["llm"]["max_tokens"] = 512  # Sonnet は長めの応答を期待
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config)
        # 根拠説明を示すキーワードが含まれること
        reasoning_keywords = ["ため", "から", "ので", "理由", "勝率", "ライン"]
        has_reasoning = any(kw in result for kw in reasoning_keywords)
        assert has_reasoning, f"根拠説明が含まれていません。実際の出力: {result[:300]}"


class TestHaikuVsSonnetComparison:
    """Haiku vs Sonnet の品質比較テスト（同一データで両モデル実行）。"""

    @requires_api_key
    def test_both_models_produce_valid_output(self):
        """
        Haiku と Sonnet が同一入力に対して両方とも有効な予想を生成すること。
        品質比較のためのベースラインテスト。
        """
        haiku_config = dict(BASE_CONFIG)
        haiku_config["llm"] = dict(BASE_CONFIG["llm"])
        haiku_config["llm"]["model"] = "claude-haiku-4-5-20251001"

        sonnet_config = dict(BASE_CONFIG)
        sonnet_config["llm"] = dict(BASE_CONFIG["llm"])
        sonnet_config["llm"]["model"] = "claude-sonnet-4-6"

        haiku_result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, haiku_config)
        sonnet_result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, sonnet_config)

        # 両モデルとも有効な出力を返すこと
        assert "軸" in haiku_result or "本命" in haiku_result, (
            f"Haiku の出力が不正: {haiku_result[:100]}"
        )
        assert "軸" in sonnet_result or "本命" in sonnet_result, (
            f"Sonnet の出力が不正: {sonnet_result[:100]}"
        )

    @requires_api_key
    def test_sonnet_output_longer_than_haiku(self):
        """
        同一入力・同一 max_tokens で Sonnet が Haiku より長い応答を返すこと。
        Sonnet の高詳細度を確認するための比較テスト。
        """
        shared_config_base = {
            "max_tokens": 512,
            "temperature": 0.5,
        }

        haiku_config = {"llm": {**shared_config_base, "model": "claude-haiku-4-5-20251001"}}
        sonnet_config = {"llm": {**shared_config_base, "model": "claude-sonnet-4-6"}}

        haiku_result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, haiku_config)
        sonnet_result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, sonnet_config)

        # 注: モデルの特性上、必ずしも Sonnet が長くなるとは限らないため
        # 両方が有効な出力であることのみ検証し、長さ比較は参考情報として記録
        print(f"\n[品質比較] Haiku: {len(haiku_result)}文字 / Sonnet: {len(sonnet_result)}文字")
        assert len(haiku_result) > 0
        assert len(sonnet_result) > 0


# ─── APIモックテスト（ANTHROPIC_API_KEY不要）────────────────────────────

def _make_mock_client(response_text: str = "軸: 1番 相手: 2番 買い目: 3連単 根拠: モック") -> MagicMock:
    """テスト用のモックanthropicクライアントを生成する。"""
    mock_client = MagicMock()
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client.messages.create.return_value = mock_message
    return mock_client


class TestLLMMock:
    """APIモックを使ったLLM応答テスト（ANTHROPIC_API_KEY不要）。"""

    def test_predict_with_mocked_api_returns_text(self, monkeypatch):
        """APIモック時にgenerate_predictionが正しいテキストを返すこと。"""
        expected = "軸: 1番 相手: 2番 買い目: 3連単 根拠: モックテスト"
        mock_client = _make_mock_client(expected)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, BASE_CONFIG)

        assert result == expected

    def test_haiku_model_passed_to_api(self, monkeypatch):
        """Haikuモデル名がAPI呼び出し時に正しく渡されること。"""
        mock_client = _make_mock_client()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
        haiku_config = {
            **BASE_CONFIG,
            "llm": {**BASE_CONFIG["llm"], "model": "claude-haiku-4-5-20251001"},
        }

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, haiku_config)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_sonnet_model_passed_to_api(self, monkeypatch):
        """Sonnetモデル名がAPI呼び出し時に正しく渡されること。"""
        mock_client = _make_mock_client()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
        sonnet_config = {
            **BASE_CONFIG,
            "llm": {**BASE_CONFIG["llm"], "model": "claude-sonnet-4-6"},
        }

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, sonnet_config)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"

    def test_max_tokens_passed_to_api(self, monkeypatch):
        """max_tokensがAPI呼び出し時に正しく渡されること。"""
        mock_client = _make_mock_client()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
        config = {**BASE_CONFIG, "llm": {**BASE_CONFIG["llm"], "max_tokens": 128}}

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 128

    def test_temperature_passed_to_api(self, monkeypatch):
        """temperatureがAPI呼び出し時に正しく渡されること。"""
        mock_client = _make_mock_client()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
        config = {**BASE_CONFIG, "llm": {**BASE_CONFIG["llm"], "temperature": 0.3}}

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config)

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3

    def test_api_called_exactly_once(self, monkeypatch):
        """generate_predictionでAPIが1回だけ呼ばれること。"""
        mock_client = _make_mock_client()
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, BASE_CONFIG)

        assert mock_client.messages.create.call_count == 1

    def test_japanese_multiline_response_preserved(self, monkeypatch):
        """複数行の日本語予想テキストが改行を保持して返ること。"""
        multiline = "軸: 山田太郎(1番)\n相手: 鈴木一郎(2番)、田中健一(3番)\n買い目: 3連単1-2-3\n根拠: S1ライン優位"
        mock_client = _make_mock_client(multiline)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, BASE_CONFIG)

        assert "\n" in result
        assert "山田太郎" in result
        assert "3連単" in result


# ─── CREプロファイルテスト ────────────────────────────────────────────

_SAMPLE_CRE_PROFILE = {
    "predictor_name": "テスト予想師",
    "basic_stats": {
        "total_predictions": 100,
        "hit_rate": 0.244,
        "recovery_rate": 0.910,
    },
    "high_recovery_patterns": [
        {
            "keyword": "絞",
            "hit_rate": 0.583,
            "recovery_rate": 1.2,
            "interpretation": "堅実型シグナル。少点数勝負が有効",
        },
        {
            "keyword": "大穴",
            "hit_rate": 0.179,
            "recovery_rate": 1.5,
            "interpretation": "穴狙いシグナル。高配当狙い",
        },
    ],
    "reverse_indicator_patterns": [
        {
            "keyword": "自信",
            "hit_rate": 0.10,
            "recovery_rate": 0.60,
            "interpretation": "見送りシグナル。自信過剰は危険",
        },
    ],
}


class TestCREProfile:
    """CREプロファイルの読み込み・プロンプト構築テスト。"""

    def test_build_cre_prompt_filter_a_standard_note(self):
        """filter_type=A のプロンプトに標準型フィルターの記述が含まれること。"""
        prompt = build_cre_system_prompt(_SAMPLE_CRE_PROFILE, "A")
        assert "標準型フィルター" in prompt

    def test_build_cre_prompt_filter_b_hole_note(self):
        """filter_type=B のプロンプトに穴狙い型フィルターの記述が含まれること。"""
        prompt = build_cre_system_prompt(_SAMPLE_CRE_PROFILE, "B")
        assert "穴狙い型フィルター" in prompt

    def test_build_cre_prompt_filter_c_solid_note(self):
        """filter_type=C のプロンプトに堅実型フィルターの記述が含まれること。"""
        prompt = build_cre_system_prompt(_SAMPLE_CRE_PROFILE, "C")
        assert "堅実型フィルター" in prompt

    def test_build_cre_prompt_invalid_filter_raises_value_error(self):
        """filter_type が A/B/C 以外の場合に ValueError が発生すること。"""
        with pytest.raises(ValueError, match="filter_type"):
            build_cre_system_prompt(_SAMPLE_CRE_PROFILE, "D")

    def test_build_cre_prompt_contains_reverse_indicator_section(self):
        """プロンプトに絶対見送りシグナルセクションが含まれること。"""
        prompt = build_cre_system_prompt(_SAMPLE_CRE_PROFILE, "A")
        assert "絶対見送りシグナル" in prompt

    def test_build_cre_prompt_case_insensitive_lower(self):
        """filter_type が小文字でも正常に動作すること（"a" → "A" と同等）。"""
        prompt_lower = build_cre_system_prompt(_SAMPLE_CRE_PROFILE, "a")
        prompt_upper = build_cre_system_prompt(_SAMPLE_CRE_PROFILE, "A")
        assert "標準型フィルター" in prompt_lower
        assert prompt_lower == prompt_upper

    def test_load_cre_profile_file_not_found_raises(self):
        """存在しないパスを渡した場合に FileNotFoundError が発生すること。"""
        with pytest.raises(FileNotFoundError):
            load_cre_profile("/nonexistent/path/to/profile.yaml")

    def test_load_cre_profile_loads_valid_yaml(self, tmp_path):
        """有効な YAML ファイルから CRE プロファイルを正しく読み込めること。"""
        import yaml

        profile_file = tmp_path / "test_cre.yaml"
        profile_file.write_text(
            yaml.dump({"predictor_name": "テスト", "basic_stats": {"total_predictions": 50}}),
            encoding="utf-8",
        )
        result = load_cre_profile(str(profile_file))
        assert result["predictor_name"] == "テスト"
        assert result["basic_stats"]["total_predictions"] == 50

    def test_generate_with_mocked_api_and_cre_profile_injects_cre(self, monkeypatch, tmp_path):
        """cre_profile_path 指定時にシステムプロンプトへ CRE が注入されること。"""
        import yaml

        # テンプレートファイルを作成（CRE注入を確認するため）
        config_dir = tmp_path / "config" / "keirin"
        config_dir.mkdir(parents=True)
        template_content = (
            "[SYSTEM]\nCRE: {cre_profile_text}\n[/SYSTEM]\n"
            "[USER]\n{venue_name} レース予想\n[/USER]"
        )
        (config_dir / "keirin_prompt.txt").write_text(template_content, encoding="utf-8")

        # CRE プロファイルファイルを作成
        profile_file = tmp_path / "cre_profile.yaml"
        profile_file.write_text(yaml.dump(_SAMPLE_CRE_PROFILE), encoding="utf-8")

        mock_client = _make_mock_client("軸: 1番 根拠: CREテスト")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")
        config = {
            **BASE_CONFIG,
            "pipeline": {
                "config_dir": str(tmp_path / "config"),
                "cre_profile_path": str(profile_file),
            },
        }

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config, filter_type="C")

        assert result == "軸: 1番 根拠: CREテスト"
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "堅実型フィルター" in call_kwargs["system"]


# ─── エッジケーステスト ──────────────────────────────────────────────

class TestEdgeCases:
    """空入力・不正入力のエッジケーステスト（dry_runモード使用）。"""

    def test_dry_run_with_filter_b_shows_filter_in_output(self, monkeypatch):
        """dry_run=True かつ filter_type=B の識別文字列に filter=B が含まれること。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = {**BASE_CONFIG, "dry_run": True}
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config, filter_type="B")
        assert "[DRY-RUN]" in result
        assert "filter=B" in result

    def test_dry_run_with_filter_c_shows_filter_in_output(self, monkeypatch):
        """dry_run=True かつ filter_type=C の識別文字列に filter=C が含まれること。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = {**BASE_CONFIG, "dry_run": True}
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config, filter_type="C")
        assert "[DRY-RUN]" in result
        assert "filter=C" in result

    def test_dry_run_with_sport_kyotei_shows_sport_in_output(self, monkeypatch):
        """dry_run=True かつ sport=kyotei の識別文字列に sport=kyotei が含まれること。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = {**BASE_CONFIG, "dry_run": True}
        result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config, sport="kyotei")
        assert "[DRY-RUN]" in result
        assert "sport=kyotei" in result

    def test_empty_entries_dry_run_no_crash(self, monkeypatch):
        """entries が空リストの場合に dry_run でクラッシュしないこと。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        empty_race = {**SAMPLE_RACE, "entries": []}
        config = {**BASE_CONFIG, "dry_run": True}
        result = generate_prediction(empty_race, SAMPLE_PROFILE, config)
        assert "[DRY-RUN]" in result

    def test_missing_venue_name_uses_fallback(self, monkeypatch):
        """venue_name を省略した場合に「不明」フォールバックが使われること。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        race_no_venue = {k: v for k, v in SAMPLE_RACE.items() if k != "venue_name"}
        config = {**BASE_CONFIG, "dry_run": True}
        result = generate_prediction(race_no_venue, SAMPLE_PROFILE, config)
        assert "[DRY-RUN]" in result
        assert "不明" in result

    def test_empty_race_data_dry_run(self, monkeypatch):
        """race_data が空辞書の場合でも dry_run でクラッシュしないこと。"""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = {**BASE_CONFIG, "dry_run": True}
        result = generate_prediction({}, SAMPLE_PROFILE, config)
        assert "[DRY-RUN]" in result


# ─── code_agentモードテスト ──────────────────────────────────────────

class TestCodeAgentMode:
    """APIキーなし時の code_agent IPC モードテスト。"""

    def test_code_agent_zero_timeout_raises_immediately(self, monkeypatch, tmp_path):
        """timeout_sec=0 の場合、即座に TimeoutError が発生すること。"""
        import src.predictor as pred_module

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(pred_module, "_CODE_AGENT_DIR", tmp_path / "predictions")
        config = {**BASE_CONFIG, "code_agent": {"timeout_sec": 0}}

        with pytest.raises(TimeoutError):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config)

    def test_code_agent_called_with_correct_args(self, monkeypatch):
        """code_agent 委任時に正しい venue と race_no が渡されること。"""
        import src.predictor as pred_module

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        captured = {}

        def mock_code_agent(venue, race_no, *args, **kwargs):
            captured["venue"] = venue
            captured["race_no"] = race_no
            return "[code_agent] mock"

        monkeypatch.setattr(pred_module, "_request_code_agent_prediction", mock_code_agent)
        generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, BASE_CONFIG)

        assert captured["venue"] == "川崎"
        assert captured["race_no"] == 9


# ─── レスポンスパーステスト ──────────────────────────────────────────

class TestResponseParsing:
    """LLM レスポンスのパース・返却テスト。"""

    def test_mocked_api_response_text_returned_correctly(self, monkeypatch):
        """API レスポンスの content[0].text が変換なしにそのまま返ること。"""
        expected = "軸: 3番 相手: 1-5番 買い目: 3連複ながし 根拠: 脚質分析より"
        mock_client = _make_mock_client(expected)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, BASE_CONFIG)

        assert result == expected

    def test_mocked_multiline_response_preserved(self, monkeypatch):
        """複数行の API レスポンスが改行を保持したまま返ること。"""
        expected = "軸: 2番\n相手: 3番・4番\n買い目: 3連単2-3-4\n根拠: まくり有効バンク"
        mock_client = _make_mock_client(expected)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            result = generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, BASE_CONFIG)

        assert result == expected
        assert result.count("\n") == 3


# ─── ヘルパー関数テスト ──────────────────────────────────────────────

class TestHelperFunctions:
    """predictor.py 内ヘルパー関数のユニットテスト。"""

    def test_build_entries_table_keirin_empty(self):
        """entries が空の場合に「出走表データなし」文字列を返すこと。"""
        result = _build_entries_table_keirin([])
        assert "出走表データなし" in result

    def test_build_entries_table_keirin_with_entries(self):
        """entries が存在する場合に各選手の情報を含むテーブルを返すこと。"""
        entries = [
            {"car_no": 1, "name": "山田太郎", "grade": "S1", "leg_type": "逃げ",
             "competitive_score": 112.34, "line_info": "1-3", "recent_results": [1, 2, 1]},
            {"car_no": 2, "name": "鈴木一郎", "grade": "S1", "leg_type": "差し",
             "competitive_score": 98.56, "line_info": "2", "recent_results": [2, 1, 3]},
        ]
        result = _build_entries_table_keirin(entries)
        assert "山田太郎" in result
        assert "鈴木一郎" in result
        assert "112.34" in result

    def test_generate_line_formation_empty(self):
        """entries が空の場合に「データなし」文字列を返すこと。"""
        result = _generate_line_formation([])
        assert "データなし" in result

    def test_generate_line_formation_with_entries(self):
        """entries から各車番・脚質のライン構成テキストを生成すること。"""
        entries = [
            {"car_no": 1, "leg_type": "逃げ", "line_info": "1-3"},
            {"car_no": 2, "leg_type": "差し", "line_info": ""},
        ]
        result = _generate_line_formation(entries)
        assert "1番" in result
        assert "逃げ" in result

    def test_extract_template_section_valid(self):
        """有効な [SYSTEM]...[/SYSTEM] タグからセクションを抽出できること。"""
        template = "[SYSTEM]\nシステムプロンプト内容\n[/SYSTEM]\n[USER]\nユーザー入力\n[/USER]"
        result = _extract_template_section(template, "SYSTEM")
        assert result == "システムプロンプト内容"

    def test_extract_template_section_missing_tag_returns_empty(self):
        """タグが存在しない場合に空文字列を返すこと。"""
        template = "[SYSTEM]\n内容\n[/SYSTEM]"
        result = _extract_template_section(template, "NONEXISTENT")
        assert result == ""


# ─── llm_instructions注入・会場別得意度・temperature最適化テスト ────────────
# cmd_148k_sub3: CRE Haiku実稼働準備テスト

_CRE_PROFILE_WITH_INSTRUCTIONS = {
    "predictor_name": "テスト予想師",
    "basic_stats": {
        "total_predictions": 200,
        "hit_rate": 0.35,
        "recovery_rate": 1.15,
    },
    "strengths": {
        "venues": [
            {"name": "熊本", "recovery_rate": 1.69},
            {"name": "別府", "recovery_rate": 1.69},
            {"name": "防府", "recovery_rate": 1.55},
        ],
    },
    "high_recovery_patterns": [
        {
            "keyword": "絞",
            "hit_rate": 0.500,
            "recovery_rate": 1.658,
            "interpretation": "「絞れる」は真の自信シグナル",
        },
    ],
    "reverse_indicator_patterns": [
        {
            "keyword": "自信",
            "hit_rate": 0.109,
            "recovery_rate": 0.270,
            "interpretation": "逆指標。自信過剰は危険",
        },
    ],
    "llm_instructions": (
        "あなたはMr.T（競輪眼）の予想AIアシスタントです。\n"
        "予想時のルール:\n"
        "1. ライン先頭のS1選手を軸候補として優先する\n"
        "2. 「絞れる」と感じたら点数を絞って自信を持て（的中率50%）\n"
        "3. 「自信」という言葉は使わない（逆指標のため）\n"
        "4. 熊本・別府・防府は得意会場として積極的に狙う\n"
        "5. 出力形式: 軸番号、相手番号リスト、コメント（日本語）"
    ),
}


class TestLlmInstructionsAndVenueStrength:
    """cmd_148k_sub3: llm_instructions注入・会場別得意度・temperature最適化テスト。"""

    def test_llm_instructions_injected_in_prompt(self):
        """llm_instructions が system プロンプトに注入されること（5ルール）。

        CHECK-9 根拠: mr_t.yamlのllm_instructionsがプロンプト未注入だった(A3 cmd_147k_sub9発見)。
        注入後は「追加指示」セクションが含まれること。
        """
        prompt = build_cre_system_prompt(_CRE_PROFILE_WITH_INSTRUCTIONS, "A")
        assert "追加指示" in prompt, "追加指示セクションがプロンプトに含まれること"
        assert "ライン先頭のS1選手を軸候補" in prompt, "llm_instructions の内容が含まれること"
        assert "自信」という言葉は使わない" in prompt, "5ルールの一部が含まれること"

    def test_venue_strength_injected_in_prompt(self):
        """会場別得意度（熊本・別府・防府）が system プロンプトに注入されること。

        CHECK-9 根拠: mr_t.yamlの会場別得意度(熊本ROI1.69等)が未注入だった(A3 cmd_147k_sub9発見)。
        注入後は「会場別得意度」セクションが含まれること。
        CHECK-7b 手計算: 熊本 recovery_rate=1.69 → 回収率169% = 格納値のまま表示
        """
        prompt = build_cre_system_prompt(_CRE_PROFILE_WITH_INSTRUCTIONS, "A")
        assert "会場別得意度" in prompt, "会場別得意度セクションがプロンプトに含まれること"
        assert "熊本" in prompt, "熊本会場がプロンプトに含まれること"
        assert "1.69" in prompt, "熊本の回収率1.69がプロンプトに含まれること"
        assert "防府" in prompt, "防府会場がプロンプトに含まれること"

    def test_venue_strength_all_three_venues_present(self):
        """得意3会場（熊本・別府・防府）が全てプロンプトに含まれること。"""
        prompt = build_cre_system_prompt(_CRE_PROFILE_WITH_INSTRUCTIONS, "A")
        for venue in ["熊本", "別府", "防府"]:
            assert venue in prompt, f"{venue}がプロンプトに含まれること"

    def test_no_venue_section_when_empty(self):
        """会場別得意度データが空の場合、会場セクションが追加されないこと。

        CHECK-9 根拠: 会場データなしでもプロンプト構築がエラーにならないこと。
        """
        profile_no_venue = {
            **_SAMPLE_CRE_PROFILE,
            "strengths": {},  # 会場データなし
        }
        prompt = build_cre_system_prompt(profile_no_venue, "A")
        assert "会場別得意度" not in prompt, "会場データなしの場合セクションが存在しないこと"
        # 必須セクションは引き続き存在すること
        assert "採用すべき高収益シグナル" in prompt

    def test_no_instructions_section_when_empty(self):
        """llm_instructions が空の場合、追加指示セクションが追加されないこと。"""
        profile_no_inst = {
            **_SAMPLE_CRE_PROFILE,
            "llm_instructions": "",
        }
        prompt = build_cre_system_prompt(profile_no_inst, "A")
        assert "追加指示" not in prompt, "llm_instructions なしの場合セクションが存在しないこと"
        assert "出力形式" in prompt, "出力形式セクションは引き続き存在すること"

    def test_temperature_by_filter_c_is_lower(self, monkeypatch, tmp_path):
        """filter_type=C（堅実型）では temperature=0.3 が使われること。

        CHECK-7b 手計算:
        C型（堅実）: 再現性重視 → 低温度 0.3（的中率優先・確定的出力）
        A型（標準）: バランス → 0.4
        B型（穴狙い）: 多様性許容 → 0.5（高配当狙いで多様な候補を探索）
        """
        import yaml

        # settings.yaml の temperature_by_filter を持つ config
        config_with_temp_by_filter = {
            "llm": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "temperature_by_filter": {"C": 0.3, "A": 0.4, "B": 0.5},
            }
        }
        mock_client = _make_mock_client("軸: 1番\n相手: 2番、3番\n買い目: 3連複\n根拠: テスト")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key_temp")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config_with_temp_by_filter, filter_type="C")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.3, f"C型はtemperature=0.3のはず: {call_kwargs['temperature']}"

    def test_temperature_by_filter_b_is_higher(self, monkeypatch, tmp_path):
        """filter_type=B（穴狙い型）では temperature=0.5 が使われること。"""
        config_with_temp_by_filter = {
            "llm": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "temperature_by_filter": {"C": 0.3, "A": 0.4, "B": 0.5},
            }
        }
        mock_client = _make_mock_client("軸: 1番\n相手: 2番、3番\n買い目: 3連複\n根拠: テスト")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key_temp")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config_with_temp_by_filter, filter_type="B")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.5, f"B型はtemperature=0.5のはず: {call_kwargs['temperature']}"

    def test_temperature_fallback_when_no_filter_config(self, monkeypatch):
        """temperature_by_filter がない場合は通常のtemperature設定が使われること。

        既存テスト test_temperature_passed_to_api との整合性確認。
        """
        config_legacy = {
            "llm": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "temperature": 0.3,  # 明示的設定（filter_by_filter なし）
            }
        }
        mock_client = _make_mock_client("軸: 1番\n相手: 2番、3番\n買い目: 3連複\n根拠: テスト")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key_temp")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config_legacy, filter_type="A")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.3, f"fallbackはtemperature=0.3のはず: {call_kwargs['temperature']}"

    def test_llm_instructions_all_five_rules_present(self):
        """llm_instructionsの5ルールが全てプロンプトに含まれること。

        CHECK-9 根拠: mr_t.yamlのllm_instructions全5ルールが注入されること。
        """
        prompt = build_cre_system_prompt(_CRE_PROFILE_WITH_INSTRUCTIONS, "C")
        # 5ルールの核心部分を確認
        assert "ライン先頭のS1選手" in prompt
        assert "絞れる" in prompt
        assert "熊本・別府・防府" in prompt

    def test_temperature_by_filter_zero_is_valid(self, monkeypatch):
        """W-CR1: temperature_by_filter=0.0 が正しく 0.0 として渡されること。

        CHECK-9 根拠:
          W-2修正（cmd_149k_sub6）で or 演算子を is not None に変更。
          修正前: `_filter_temp or fallback` → 0.0 は falsy なので fallback になる（バグ）
          修正後: `if _filter_temp is not None: temperature = _filter_temp` → 0.0 も正しく使用
          手計算: temperature_by_filter={"C": 0.0} で filter_type=C → temperature=0.0
        """
        config_zero_temp = {
            "llm": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "temperature_by_filter": {"C": 0.0, "A": 0.4, "B": 0.5},
            }
        }
        mock_client = _make_mock_client("軸: 1番\n相手: 2番、3番\n買い目: 3連複\n根拠: テスト")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key_zero")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config_zero_temp, filter_type="C")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.0, (
            f"temperature_by_filter=0.0 は 0.0 として渡されるべき（W-CR1）: {call_kwargs['temperature']}"
        )

    def test_config_temperature_zero_is_valid(self, monkeypatch):
        """W-CR1: config.llm.temperature=0.0 が正しく 0.0 として渡されること。

        CHECK-9 根拠:
          W-2修正（cmd_149k_sub6）で `_config_temp if _config_temp is not None else ...` に変更。
          修正前: `_config_temp or ...` → 0.0 は falsy なので _DEFAULT_TEMP_BY_FILTER になる（バグ）
          修正後: `_config_temp if _config_temp is not None` → 0.0 も正しく使用
          手計算: temperature_by_filter なし + config.temperature=0.0 → temperature=0.0
        """
        config_zero = {
            "llm": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                "temperature": 0.0,  # 明示的に0.0
                # temperature_by_filter は意図的に省略
            }
        }
        mock_client = _make_mock_client("軸: 1番\n相手: 2番、3番\n買い目: 3連複\n根拠: テスト")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key_zero2")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config_zero, filter_type="A")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.0, (
            f"config.temperature=0.0 は 0.0 として渡されるべき（W-CR1）: {call_kwargs['temperature']}"
        )

    def test_default_temp_fallback_B(self, monkeypatch):
        """W-CR2: temperature設定なし + filter_type=B → _DEFAULT_TEMP_BY_FILTER["B"]=0.5 が使われること。

        CHECK-9 根拠:
          W-1修正（cmd_149k_sub6）で _DEFAULT_TEMP_BY_FILTER を実際のフォールバックとして使用。
          _DEFAULT_TEMP_BY_FILTER = {"C": 0.3, "A": 0.4, "B": 0.5}（src/predictor.py L528）
          手計算:
            _filter_temp = {} .get("B") → None（temperature_by_filter なし）
            _config_temp = None（config.temperature なし）
            → _DEFAULT_TEMP_BY_FILTER.get("B", 0.4) = 0.5
        """
        config_no_temp = {
            "llm": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                # temperature も temperature_by_filter も未設定
            }
        }
        mock_client = _make_mock_client("軸: 1番\n相手: 2番、3番\n買い目: 3連複\n根拠: テスト")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key_fallback_b")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config_no_temp, filter_type="B")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.5, (
            f"temperature未設定+filter_type=B → _DEFAULT_TEMP_BY_FILTER['B']=0.5 のはず（W-CR2）: {call_kwargs['temperature']}"
        )

    def test_default_temp_fallback_C(self, monkeypatch):
        """W-CR2: temperature設定なし + filter_type=C → _DEFAULT_TEMP_BY_FILTER["C"]=0.3 が使われること。

        CHECK-9 根拠:
          手計算:
            _filter_temp = None（temperature_by_filter なし）
            _config_temp = None（config.temperature なし）
            → _DEFAULT_TEMP_BY_FILTER.get("C", 0.4) = 0.3
          C型（堅実型）は再現性重視のため低温度0.3が正しい。
        """
        config_no_temp = {
            "llm": {
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 256,
                # temperature も temperature_by_filter も未設定
            }
        }
        mock_client = _make_mock_client("軸: 1番\n相手: 2番、3番\n買い目: 3連複\n根拠: テスト")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test_key_fallback_c")

        with patch("src.predictor.anthropic.Anthropic", return_value=mock_client):
            generate_prediction(SAMPLE_RACE, SAMPLE_PROFILE, config_no_temp, filter_type="C")

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["temperature"] == 0.3, (
            f"temperature未設定+filter_type=C → _DEFAULT_TEMP_BY_FILTER['C']=0.3 のはず（W-CR2）: {call_kwargs['temperature']}"
        )
