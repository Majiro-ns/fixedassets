import os
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # Fallback to JSON if needed


def _default_config_path() -> str:
    # When frozen by PyInstaller, data files are in sys._MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS  # type: ignore[attr-defined]
        return os.path.join(base, "config", "defaults.yaml")
    # In source layout: repo/config/defaults.yaml
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config", "defaults.yaml")


def _load_yaml(path: str) -> Dict[str, Any]:
    if yaml is None:
        # Basic fallback: allow JSON superset if yaml not available
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(custom_path: str | None = None) -> Dict[str, Any]:
    path = custom_path or os.environ.get("AIWD_CONFIG", _default_config_path())
    return _load_yaml(path)


def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)
