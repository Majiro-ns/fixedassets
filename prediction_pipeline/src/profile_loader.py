"""
予想師プロファイルローダー（競輪・競艇共通）
============================================

config/{sport}/profiles/{profile_id}.yaml を読み込み、
LLM予想プロンプト生成に必要なプロファイル辞書を返す。

使用例:
    loader = ProfileLoader("config/keirin/profiles")
    profile = loader.load("mr_t")
    # → {"profile_id": "mr_t_634", "predictor_name": "Mr.T", ...}
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


class ProfileLoader:
    """予想師プロファイルを YAML から読み込むクラス。"""

    def __init__(self, profiles_dir: str) -> None:
        """
        Args:
            profiles_dir: プロファイル YAML が格納されたディレクトリパス。
                          例: "config/keirin/profiles"
        """
        self.profiles_dir = Path(profiles_dir)

    def load(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """
        指定された profile_id に対応する YAML ファイルを読み込む。

        Args:
            profile_id: プロファイル識別子（ファイル名から .yaml を除いた部分）。
                        例: "mr_t"

        Returns:
            プロファイル辞書。ファイルが存在しない・読み込めない場合は None。
        """
        yaml_path = self.profiles_dir / f"{profile_id}.yaml"
        if not yaml_path.exists():
            logger.warning("プロファイルファイルが見つかりません: %s", yaml_path)
            return None

        try:
            with open(yaml_path, encoding="utf-8") as f:
                profile = yaml.safe_load(f)
            logger.debug("プロファイル読み込み完了: %s", profile_id)
            return profile
        except yaml.YAMLError as e:
            logger.error("YAML パースエラー (%s): %s", yaml_path, e)
            return None
        except OSError as e:
            logger.error("ファイル読み込みエラー (%s): %s", yaml_path, e)
            return None

    def load_or_default(
        self,
        profile_id: str,
        default: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        プロファイルを読み込む。失敗した場合はデフォルト値を返す。

        Args:
            profile_id: プロファイル識別子。
            default: 読み込み失敗時のデフォルト辞書。None の場合は空辞書。

        Returns:
            プロファイル辞書またはデフォルト値。
        """
        result = self.load(profile_id)
        if result is None:
            logger.warning(
                "プロファイル '%s' 読み込み失敗。デフォルト値を使用します。",
                profile_id,
            )
            return default if default is not None else {}
        return result

    def list_profiles(self) -> list:
        """
        profiles_dir 内に存在するプロファイル ID の一覧を返す。

        Returns:
            profile_id のリスト（拡張子なし）。
        """
        if not self.profiles_dir.exists():
            return []
        return [
            p.stem
            for p in self.profiles_dir.glob("*.yaml")
            if not p.name.startswith(".")
        ]


def load_profile_from_path(yaml_path: str) -> Optional[Dict[str, Any]]:
    """
    パスを直接指定してプロファイルを読み込む便利関数。

    Args:
        yaml_path: プロファイル YAML のフルパス。

    Returns:
        プロファイル辞書。失敗した場合は None。
    """
    path = Path(yaml_path)
    if not path.exists():
        logger.warning("指定パスが存在しません: %s", yaml_path)
        return None

    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as e:
        logger.error("プロファイル読み込みエラー (%s): %s", yaml_path, e)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # 動作確認
    loader = ProfileLoader("config/keirin/profiles")
    profiles = loader.list_profiles()
    print(f"利用可能なプロファイル: {profiles}")

    profile = loader.load("mr_t")
    if profile:
        print(f"プロファイル名: {profile.get('predictor_name')}")
        print(f"得意会場: {[v['name'] for v in profile.get('strengths', {}).get('venues', [])]}")
    else:
        print("mr_t プロファイルが見つかりません")
