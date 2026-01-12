from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from llama_cpp import Llama  # type: ignore
except ImportError as exc:  # pragma: no cover - runtime dependency
    raise ImportError("llama-cpp-python が必要です。`pip install llama-cpp-python` を実行してください。") from exc


DEFAULT_MODEL_PATH = Path(r"C:\Users\owner\Meta-Llama-3-8B-Instruct.Q6_K.gguf")


def _get_env_int(name: str, default: int) -> int:
    """
    Best-effort int reader with fallback to default when env is missing or invalid.
    """
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


class LocalLLM:
    """
    Simple wrapper around llama-cpp-python for chat completions.
    """

    def __init__(
        self,
        model_path: Path | str = DEFAULT_MODEL_PATH,
        n_ctx: int = 8192,
        n_gpu_layers: int | None = None,
        n_batch: int | None = None,
        n_threads: int = 8,
        temperature: float = 0.7,
        top_p: float = 0.9,
        repeat_penalty: float = 1.12,
    seed: int = 42,
    **kwargs: Any,
) -> None:
        env_gpu_layers = _get_env_int("N_GPU_LAYERS", 35)
        env_batch = _get_env_int("N_BATCH", 512)
        resolved_gpu_layers = env_gpu_layers if n_gpu_layers is None else _coerce_int(n_gpu_layers, env_gpu_layers)
        resolved_batch = env_batch if n_batch is None else _coerce_int(n_batch, env_batch)
        config_log = (
            f"model={model_path} n_ctx={n_ctx} n_gpu_layers={resolved_gpu_layers} "
            f"n_batch={resolved_batch} n_threads={n_threads}"
        )
        print(f"[INFO] llama: n_gpu_layers={resolved_gpu_layers} n_batch={resolved_batch}")
        print(f"[INFO] llama: initializing backend... {config_log}")
        self.params = {
            "temperature": temperature,
            "top_p": top_p,
            "repeat_penalty": repeat_penalty,
        }
        try:
            self.client = Llama(
                model_path=str(model_path),
                n_ctx=n_ctx,
                n_gpu_layers=resolved_gpu_layers,
                n_batch=resolved_batch,
                n_threads=n_threads,
                seed=seed,
                verbose=False,
                **kwargs,
            )
        except Exception as exc:  # pragma: no cover - runtime dependent
            print(f"[ERROR] llama init failed: {config_log}")
            raise
        print("[INFO] llama: backend ready")
        self.last_usage: Optional[Dict[str, Any]] = None

    def chat(self, system_prompt: str, user_prompt: str, **overrides: Any) -> str:
        params = {**self.params, **overrides}
        completion = self.client.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=params["temperature"],
            top_p=params["top_p"],
            repeat_penalty=params["repeat_penalty"],
        )
        self.last_usage = completion.get("usage")
        return completion["choices"][0]["message"]["content"]
