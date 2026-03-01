"""
tests/test_profile_loader.py
============================

src/profile_loader.py の単体テスト。

テスト対象:
  - ProfileLoader.load()            YAMLファイル読み込み（正常系・異常系）
  - ProfileLoader.load_or_default() 失敗時フォールバック
  - ProfileLoader.list_profiles()   プロファイル一覧取得
  - load_profile_from_path()        パス直接指定読み込み
  - 実プロファイル（mr_t.yaml）のCREフィールド検証

テスト期待値根拠（CHECK-9）:
  - load() の None 返却: profile_loader.py:47-61（ファイル不在・YAMLError・OSError）
  - load_or_default() のフォールバック: profile_loader.py:79-84（default or {}）
  - list_profiles() の .yaml 除外: profile_loader.py:96-100（glob + not startswith('.')）
  - CREフィールド必須項目: mr_t.yaml のトップキー + cmd_131k_sub1 の CRE 統合実績
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from profile_loader import ProfileLoader, load_profile_from_path

# 実プロファイルのパス（統合テスト用）
KEIRIN_PROFILES_DIR = (
    Path(__file__).resolve().parent.parent / "config" / "keirin" / "profiles"
)
KYOTEI_PROFILES_DIR = (
    Path(__file__).resolve().parent.parent / "config" / "kyotei" / "profiles"
)


# ─────────────────────────────────────────────────────────────────────────────
# フィクスチャ
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def profiles_dir(tmp_path):
    """テスト用プロファイルディレクトリ（tmp_path内）を作成する。"""
    d = tmp_path / "profiles"
    d.mkdir()
    return d


@pytest.fixture
def valid_yaml_profile(profiles_dir):
    """正常なプロファイルYAMLファイルをtmp_pathに作成する。"""
    content = {
        "profile_id": "test_predictor_001",
        "predictor_name": "テスト予想師",
        "sport": "keirin",
        "basic_stats": {
            "total_predictions": 100,
            "hit_rate": 0.30,
            "recovery_rate": 1.20,
        },
        "high_recovery_patterns": [
            {"keyword": "絞", "hit_rate": 0.5, "recovery_rate": 1.65},
        ],
        "reverse_indicator_patterns": [
            {"keyword": "自信", "hit_rate": 0.11, "recovery_rate": 0.27},
        ],
    }
    yaml_file = profiles_dir / "test_predictor.yaml"
    with open(yaml_file, "w", encoding="utf-8") as f:
        yaml.dump(content, f, allow_unicode=True)
    return yaml_file


# ─────────────────────────────────────────────────────────────────────────────
# ProfileLoader.load() — 正常系
# ─────────────────────────────────────────────────────────────────────────────

class TestProfileLoaderLoad:
    def test_load_valid_yaml(self, profiles_dir, valid_yaml_profile):
        """存在するYAMLファイルを読み込むと辞書が返る。
        根拠: profile_loader.py:51-55 の yaml.safe_load 正常系"""
        loader = ProfileLoader(str(profiles_dir))
        profile = loader.load("test_predictor")
        assert profile is not None
        assert isinstance(profile, dict)
        assert profile["predictor_name"] == "テスト予想師"

    def test_load_nonexistent_returns_none(self, profiles_dir):
        """存在しない profile_id は None を返す。
        根拠: profile_loader.py:47-49 の yaml_path.exists() チェック"""
        loader = ProfileLoader(str(profiles_dir))
        result = loader.load("no_such_profile")
        assert result is None

    def test_load_invalid_yaml_returns_none(self, profiles_dir):
        """不正なYAMLファイルは None を返す（YAMLError を握りつぶす）。
        根拠: profile_loader.py:56-58 の yaml.YAMLError ハンドリング"""
        bad_yaml = profiles_dir / "broken.yaml"
        bad_yaml.write_text("key: [\ninvalid: yaml: content", encoding="utf-8")
        loader = ProfileLoader(str(profiles_dir))
        result = loader.load("broken")
        assert result is None

    def test_load_japanese_fields_decoded(self, profiles_dir, valid_yaml_profile):
        """日本語フィールドが文字化けせずに読み込まれる。
        根拠: profile_loader.py:52 の encoding='utf-8'"""
        loader = ProfileLoader(str(profiles_dir))
        profile = loader.load("test_predictor")
        assert profile["predictor_name"] == "テスト予想師"

    def test_load_path_constructed_correctly(self, profiles_dir, valid_yaml_profile):
        """ロードパスが profiles_dir / profile_id + '.yaml' で構築される。
        根拠: profile_loader.py:46 の yaml_path 構築"""
        loader = ProfileLoader(str(profiles_dir))
        # test_predictor.yaml が存在するので正常に読める
        profile = loader.load("test_predictor")
        assert profile is not None
        # test_predictor_nonexist.yaml は存在しないので None
        assert loader.load("test_predictor_nonexist") is None


# ─────────────────────────────────────────────────────────────────────────────
# ProfileLoader.load_or_default()
# ─────────────────────────────────────────────────────────────────────────────

class TestProfileLoaderOrDefault:
    def test_returns_profile_when_found(self, profiles_dir, valid_yaml_profile):
        """ファイルが存在する場合は通常のプロファイルを返す。
        根拠: profile_loader.py:78-79 の result is None チェック"""
        loader = ProfileLoader(str(profiles_dir))
        result = loader.load_or_default("test_predictor", default={"fallback": True})
        assert result["predictor_name"] == "テスト予想師"
        assert "fallback" not in result

    def test_returns_default_when_not_found(self, profiles_dir):
        """ファイルが存在しない場合は default を返す。
        根拠: profile_loader.py:83-84 の return default if default is not None else {}"""
        loader = ProfileLoader(str(profiles_dir))
        fallback = {"predictor_name": "デフォルト", "sport": "keirin"}
        result = loader.load_or_default("no_such_profile", default=fallback)
        assert result == fallback

    def test_returns_empty_dict_when_default_none(self, profiles_dir):
        """default=None かつファイルが存在しない場合は空辞書を返す。
        根拠: profile_loader.py:84 の else {} フォールバック"""
        loader = ProfileLoader(str(profiles_dir))
        result = loader.load_or_default("no_such_profile")
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# ProfileLoader.list_profiles()
# ─────────────────────────────────────────────────────────────────────────────

class TestProfileLoaderListProfiles:
    def test_lists_yaml_files(self, profiles_dir, valid_yaml_profile):
        """profiles_dir 内の .yaml ファイルのステム一覧を返す。
        根拠: profile_loader.py:97-99 の glob('*.yaml')"""
        loader = ProfileLoader(str(profiles_dir))
        profiles = loader.list_profiles()
        assert "test_predictor" in profiles

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        """profiles_dir が存在しない場合は空リストを返す。
        根拠: profile_loader.py:94-95 の not self.profiles_dir.exists()"""
        loader = ProfileLoader(str(tmp_path / "no_such_dir"))
        assert loader.list_profiles() == []

    def test_dotfiles_excluded(self, profiles_dir):
        """'.gitkeep' などのドットファイルは除外される。
        根拠: profile_loader.py:99 の not p.name.startswith('.')"""
        dotfile = profiles_dir / ".gitkeep"
        dotfile.write_text("")
        # 通常のYAMLも一つ作成
        (profiles_dir / "real_profile.yaml").write_text("profile_id: real\n")
        loader = ProfileLoader(str(profiles_dir))
        profiles = loader.list_profiles()
        assert ".gitkeep" not in profiles
        assert "real_profile" in profiles

    def test_multiple_profiles_listed(self, profiles_dir):
        """複数のYAMLファイルが全て列挙される。
        根拠: profile_loader.py:96-100 の glob で全ファイル取得"""
        for name in ["profile_a", "profile_b", "profile_c"]:
            (profiles_dir / f"{name}.yaml").write_text(f"profile_id: {name}\n")
        loader = ProfileLoader(str(profiles_dir))
        profiles = loader.list_profiles()
        assert set(["profile_a", "profile_b", "profile_c"]).issubset(set(profiles))


# ─────────────────────────────────────────────────────────────────────────────
# load_profile_from_path()
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadProfileFromPath:
    def test_load_valid_path(self, tmp_path):
        """有効なパスを指定すると辞書が返る。
        根拠: profile_loader.py:118-120 の yaml.safe_load"""
        yaml_file = tmp_path / "sample.yaml"
        yaml_file.write_text(
            "profile_id: sample_001\npredictor_name: サンプル予想師\n",
            encoding="utf-8",
        )
        result = load_profile_from_path(str(yaml_file))
        assert result is not None
        assert result["predictor_name"] == "サンプル予想師"

    def test_load_nonexistent_path_returns_none(self, tmp_path):
        """存在しないパスは None を返す。
        根拠: profile_loader.py:114-116 の path.exists() チェック"""
        result = load_profile_from_path(str(tmp_path / "ghost.yaml"))
        assert result is None

    def test_load_invalid_yaml_returns_none(self, tmp_path):
        """不正YAMLは None を返す。
        根拠: profile_loader.py:121-122 の (yaml.YAMLError, OSError) ハンドリング"""
        bad = tmp_path / "bad.yaml"
        bad.write_text("key: [unclosed", encoding="utf-8")
        result = load_profile_from_path(str(bad))
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# 実プロファイル（mr_t.yaml）CREフィールド検証（統合テスト）
# ─────────────────────────────────────────────────────────────────────────────

class TestMrTProfileIntegration:
    """実際の mr_t.yaml が必要なフィールドを持つか検証する。
    根拠: cmd_131k_sub1 で発見された CRE断絶バグの再発防止。
    build_cre_system_prompt() が参照する3フィールドの存在を保証する。"""

    @pytest.fixture(autouse=True)
    def load_mr_t(self):
        loader = ProfileLoader(str(KEIRIN_PROFILES_DIR))
        self.profile = loader.load("mr_t")
        if self.profile is None:
            pytest.skip("mr_t.yaml が見つかりません")

    def test_required_top_level_fields(self):
        """profile_id / predictor_name / sport が存在する。
        根拠: ProfileLoader の使用箇所は predictor_name と profile_id を参照する"""
        assert "profile_id" in self.profile
        assert "predictor_name" in self.profile
        assert "sport" in self.profile

    def test_basic_stats_fields(self):
        """basic_stats が total_predictions / hit_rate / recovery_rate を持つ。
        根拠: build_cre_system_prompt() の basic_stats 参照（cmd_131k_sub1修正済み）"""
        stats = self.profile.get("basic_stats", {})
        assert "total_predictions" in stats
        assert "hit_rate" in stats
        assert "recovery_rate" in stats
        assert isinstance(stats["hit_rate"], float)
        assert 0.0 <= stats["hit_rate"] <= 1.0

    def test_high_recovery_patterns_structure(self):
        """high_recovery_patterns が keyword / hit_rate / recovery_rate を持つリスト。
        根拠: build_cre_system_prompt() の high_recovery_patterns 参照（cmd_131k_sub1修正済み）"""
        patterns = self.profile.get("high_recovery_patterns", [])
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        for p in patterns:
            assert "keyword" in p, f"keyword が欠如: {p}"
            assert "hit_rate" in p, f"hit_rate が欠如: {p}"
            assert "recovery_rate" in p, f"recovery_rate が欠如: {p}"

    def test_reverse_indicator_patterns_structure(self):
        """reverse_indicator_patterns が keyword を持つリスト。
        根拠: build_cre_system_prompt() の reverse_indicator_patterns 参照"""
        patterns = self.profile.get("reverse_indicator_patterns", [])
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        for p in patterns:
            assert "keyword" in p, f"keyword が欠如: {p}"

    def test_mr_t_is_listed(self):
        """list_profiles() に 'mr_t' が含まれる。
        根拠: config/keirin/profiles/mr_t.yaml の存在確認"""
        loader = ProfileLoader(str(KEIRIN_PROFILES_DIR))
        profiles = loader.list_profiles()
        assert "mr_t" in profiles
