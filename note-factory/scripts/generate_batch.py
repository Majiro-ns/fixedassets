import argparse
import csv
import datetime as _dt
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pipeline_policy import parse_pipeline_policy
from runlog import (
    build_step_result,
    compute_run_status,
    lineage_for_new_run,
    lineage_for_rerun,
    new_run_id,
    normalize_mode,
)

@dataclass(frozen=True)
class Persona:
    persona_id: str
    label: str
    role: str
    priority: int
    weight: float
    enabled: bool
    engine: str
    persona_def_file: str
    theme_pool: str
    template_set: str
    output_mode: str
    use_case: str
    forbidden: str
    max_retries: int
    retry_wait_sec: int
    timeout_sec: int
    notes: str


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _persona_folder(root: Path, persona_id: str) -> Path:
    return root / "personas" / persona_id


def _persist_engine_streams(
    run_dir: Path, step_name: str, attempt: int, result: Dict[str, Any]
) -> Dict[str, Any]:
    stdout = result.get("stdout")
    stderr = result.get("stderr")
    stdout_path = None
    stderr_path = None
    if stdout is not None:
        path = run_dir / f"_engine_{step_name}__{attempt}__stdout.txt"
        _write_text(path, str(stdout))
        stdout_path = str(path.relative_to(run_dir)).replace("\\", "/")
    if stderr is not None:
        path = run_dir / f"_engine_{step_name}__{attempt}__stderr.txt"
        _write_text(path, str(stderr))
        stderr_path = str(path.relative_to(run_dir)).replace("\\", "/")
    cleaned = {k: v for k, v in result.items() if k not in ("stdout", "stderr")}
    cleaned["stdout_path"] = stdout_path
    cleaned["stderr_path"] = stderr_path
    return cleaned


def _is_persona_content_file(path: Path) -> bool:
    if path.suffix.lower() not in (".md", ".txt"):
        return False
    parts = {p.lower() for p in path.parts}
    if "overrides" in parts:
        return False
    return True


def _slugify(value: str, max_len: int = 60) -> str:
    value = value.strip().lower()
    value = value.replace("_", "-")
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9\-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    if not value:
        return ""
    return value[:max_len].strip("-") or ""


def _stable_slug_from_theme(theme: str) -> str:
    ascii_slug = _slugify(theme)
    if ascii_slug:
        return ascii_slug
    digest = hashlib.md5(theme.encode("utf-8")).hexdigest()[:10]
    return f"t{digest}"


def _theme_id_from_theme(theme: Dict[str, str]) -> str:
    payload = json.dumps(theme, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _update_content_hashes(run_json: Dict[str, Any], run_dir: Path) -> None:
    hashes: Dict[str, str] = {}
    for name in ("materials.md", "article.md", "REVIEW.md"):
        path = run_dir / name
        if path.exists():
            hashes[name] = _file_sha256(path)
    run_json["content_hashes"] = hashes


def _resolve_experiment_id(run_id: str, parent_experiment_id: Optional[str] = None) -> str:
    env_id = os.environ.get("NOTE_FACTORY_EXPERIMENT_ID", "").strip()
    if env_id:
        return env_id
    if parent_experiment_id:
        return parent_experiment_id
    return run_id

def _parse_int(s: str, default: int) -> int:
    try:
        return int(str(s).strip())
    except Exception:
        return default


def _parse_float(s: str, default: float) -> float:
    try:
        return float(str(s).strip())
    except Exception:
        return default


def _parse_bool01(s: str, default: bool) -> bool:
    v = str(s).strip()
    if v == "1":
        return True
    if v == "0":
        return False
    return default


def load_personas(personas_csv: Path) -> List[Persona]:
    with personas_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        personas: List[Persona] = []
        for row in reader:
            persona_id = (row.get("persona_id") or "").strip()
            if not persona_id:
                continue
            personas.append(
                Persona(
                    persona_id=persona_id,
                    label=(row.get("label") or "").strip(),
                    role=(row.get("役割") or "").strip(),
                    priority=_parse_int(row.get("優先度") or "", 0),
                    weight=_parse_float(row.get("重み") or "", 1.0),
                    enabled=_parse_bool01(row.get("有効") or "", True),
                    engine=(row.get("使用エンジン") or "").strip(),
                    persona_def_file=(row.get("persona定義ファイル") or "").strip(),
                    theme_pool=(row.get("テーマプール") or "").strip(),
                    template_set=(row.get("テンプレセット") or "").strip(),
                    output_mode=(row.get("出力モード") or "").strip(),
                    use_case=(row.get("想定用途") or "").strip(),
                    forbidden=(row.get("禁止事項") or "").strip(),
                    max_retries=_parse_int(row.get("最大リトライ") or "", 0),
                    retry_wait_sec=_parse_int(row.get("リトライ待機秒") or "", 2),
                    timeout_sec=_parse_int(row.get("タイムアウト秒") or "", 180),
                    notes=(row.get("備考") or "").strip(),
                )
            )
    return personas


def _engine_matches(persona_engine: str, requested_engine: str) -> bool:
    persona_engine = persona_engine.strip()
    if not persona_engine:
        return True
    allowed = [e.strip() for e in re.split(r"[|,;/\s]+", persona_engine) if e.strip()]
    return requested_engine in allowed


def _forced_personas_from_env() -> Dict[str, str]:
    raw = os.environ.get("NOTE_FACTORY_FORCE_PERSONA", "").strip()
    mapping: Dict[str, str] = {}
    if not raw:
        return mapping
    for part in re.split(r"[;,]", raw):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            role, persona_id = part.split(":", 1)
        elif "=" in part:
            role, persona_id = part.split("=", 1)
        else:
            continue
        role = role.strip()
        persona_id = persona_id.strip()
        if role and persona_id:
            mapping[role] = persona_id
    return mapping


def choose_persona(
    personas: List[Persona], *, role: str, engine: str, rng: random.Random
) -> Persona:
    candidates = [
        p
        for p in personas
        if p.enabled and p.role == role and _engine_matches(p.engine, engine)
    ]
    if not candidates:
        raise RuntimeError(f"no persona candidates for role={role}, engine={engine}")
    weights = [max(0.0, float(p.priority) * float(p.weight)) for p in candidates]
    if sum(weights) <= 0:
        weights = [1.0 for _ in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def load_theme(theme_csv: Path, rng: random.Random) -> Dict[str, str]:
    override = os.environ.get("NOTE_FACTORY_THEME_OVERRIDE", "").strip()
    if override:
        try:
            data = json.loads(override)
            return {
                "theme": str(data.get("theme") or "").strip(),
                "catchcopy": str(data.get("catchcopy") or "").strip(),
                "paid_flag": str((data.get("paid_flag") or "0")).strip(),
                "tags": str(data.get("tags") or "").strip(),
            }
        except Exception:
            pass
    with theme_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader if (row.get("theme") or "").strip()]
    if not rows:
        raise RuntimeError(f"no themes in {theme_csv}")
    row = rng.choice(rows)
    return {
        "theme": (row.get("theme") or "").strip(),
        "catchcopy": (row.get("catchcopy") or "").strip(),
        "paid_flag": str((row.get("paid_flag") or "0")).strip(),
        "tags": (row.get("tags") or "").strip(),
    }


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def render_template(template_text: str, variables: Dict[str, str]) -> str:
    return template_text.format_map(_SafeFormatDict(variables))


def _load_persona_yaml(root: Path, persona: Persona) -> str:
    rel = persona.persona_def_file.strip()
    path = (root / rel) if rel else (root / "personas" / persona.persona_id)
    if not rel and not path.exists():
        return ""
    if path.is_dir():
        parts: List[str] = []
        for p in sorted(path.rglob("*")):
            if not p.is_file():
                continue
            if not _is_persona_content_file(p):
                continue
            try:
                body = _read_text(p).strip()
            except Exception:
                continue
            if not body:
                continue
            rel_name = str(p.relative_to(path)).replace("\\", "/")
            parts.append(f"---\n# persona_file: {rel_name}\n{body}\n")
        return "\n".join(parts).strip()
    try:
        return _read_text(path)
    except FileNotFoundError:
        return ""


def _collect_persona_def_paths(root: Path, persona: Persona) -> List[Path]:
    rel = persona.persona_def_file.strip()
    path = (root / rel) if rel else (root / "personas" / persona.persona_id)
    if not rel and not path.exists():
        return []
    if path.is_dir():
        return [
            p
            for p in sorted(path.rglob("*"))
            if p.is_file() and _is_persona_content_file(p)
        ]
    if path.is_file():
        return [path]
    return []


def _copy_persona_defs_to_run_dir(root: Path, run_dir: Path, persona: Persona) -> List[str]:
    copied: List[str] = []
    rel_base = (root / persona.persona_def_file.strip()) if persona.persona_def_file.strip() else (root / "personas" / persona.persona_id)
    for src in _collect_persona_def_paths(root, persona):
        base = run_dir / "personas" / persona.persona_id
        try:
            rel_path = src.relative_to(rel_base) if rel_base.is_dir() else Path(src.name)
        except Exception:
            rel_path = Path(src.name)
        dst = base / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(dst.relative_to(run_dir)).replace("\\", "/"))
    return copied


def _read_template(root: Path, template_set: str, filename: str) -> str:
    path = root / "templates" / template_set / filename
    return _read_text(path)


def _read_template_for_persona_step(
    root: Path, persona: Persona, step_name: str, template_set: str, filename: str
) -> Tuple[str, str]:
    """
    Returns (template_text, template_source_path).
    Supports persona overrides:
      - personas/<id>/overrides/<filename>
      - personas/<id>/overrides/<step_name>/<filename>
    """
    persona_dir = _persona_folder(root, persona.persona_id)
    override_candidates = [
        persona_dir / "overrides" / step_name / filename,
        persona_dir / "overrides" / filename,
    ]
    for p in override_candidates:
        if p.exists() and p.is_file():
            text = _read_text(p)
            if "[OVERRIDE TEST]" in text or "OVERRIDE TEST" in text:
                continue
            return text, str(p.relative_to(root)).replace("\\", "/")
    default_path = root / "templates" / template_set / filename
    return _read_text(default_path), str(default_path.relative_to(root)).replace("\\", "/")


def _validate_output_file(output_name: str, path: Path) -> Tuple[bool, Dict[str, Any]]:
    if not path.exists():
        return False, {"reason": "missing", "output": output_name}
    try:
        text = _read_text(path)
    except Exception as e:
        return False, {"reason": "unreadable", "output": output_name, "error": f"{type(e).__name__}: {e}"}

    stripped = text.strip()
    if not stripped:
        return False, {"reason": "empty", "output": output_name}

    if output_name == "tags.csv":
        try:
            rows = list(csv.reader(stripped.splitlines()))
        except Exception as e:
            return False, {"reason": "csv_parse_error", "output": output_name, "error": f"{type(e).__name__}: {e}"}
        if not rows:
            return False, {"reason": "no_rows", "output": output_name}
        header = (rows[0][0] if rows[0] else "").strip().lower()
        if header != "tag":
            return False, {"reason": "missing_header", "output": output_name, "header": header}
        tags = []
        for r in rows[1:]:
            if not r:
                continue
            t = (r[0] or "").strip()
            if t:
                tags.append(t)
        if not tags:
            return False, {"reason": "no_tags", "output": output_name}
        return True, {"reason": "ok", "output": output_name, "tag_count": len(tags)}

    def is_path_line(line: str) -> bool:
        if re.match(r"^[A-Za-z]:\\\\", line):
            return True
        if line.startswith(("/", "./", "../", ".\\")):
            return True
        if re.search(r"[\\\\/]", line) and re.search(r"\\.[A-Za-z0-9]{1,5}(\\s|$)", line):
            return True
        return False

    def has_natural_language(text: str) -> bool:
        total = len(re.findall(r"\S", text))
        if total == 0:
            return False
        letters = len(re.findall(r"[A-Za-z\u3040-\u30ff\u4e00-\u9fff]", text))
        if total < 80:
            return letters > 0
        return (letters / total) >= 0.05

    min_chars = 1
    if output_name == "materials.md":
        min_chars = 120
    elif output_name == "REVIEW.md":
        min_chars = 80
    elif output_name == "article.md":
        min_chars = 400
    elif output_name == "meta.md":
        min_chars = 80
    elif output_name == "banner_prompt.txt":
        min_chars = 10

    if output_name == "article.md":
        lines = [l.strip() for l in stripped.splitlines() if l.strip()]
        if lines and all(is_path_line(l) for l in lines):
            return False, {"reason": "path_only", "output": output_name}
        if not has_natural_language(stripped):
            return False, {"reason": "no_natural_language", "output": output_name}
        if len(stripped) < min_chars:
            return False, {
                "reason": "too_short",
                "output": output_name,
                "chars": len(stripped),
                "min_chars": min_chars,
            }
    else:
        if len(stripped) < min_chars:
            return False, {
                "reason": "too_short",
                "output": output_name,
                "chars": len(stripped),
                "min_chars": min_chars,
            }
    return True, {"reason": "ok", "output": output_name, "chars": len(stripped)}


def _classify_engine_failure(result: Dict[str, Any]) -> str:
    stderr = str(result.get("stderr") or "")
    if "TimeoutExpired" in stderr:
        return "timeout"
    returncode = result.get("returncode")
    if isinstance(returncode, int) and returncode != 0:
        return "engine_error"
    if not result.get("ok"):
        return "format_violation"
    return "unknown"


def _normalize_tags_csv(path: Path, fallback_tags: str) -> None:
    if not path.exists():
        tags = [t.strip() for t in re.split(r"[;,\s]+", fallback_tags) if t.strip()]
        content = "tag\n" + "\n".join(tags[:10]) + ("\n" if tags else "")
        _write_text(path, content)
        return
    txt = _read_text(path).strip()
    if not txt:
        _write_text(path, "tag\n")
        return
    first = txt.splitlines()[0].strip().lower()
    if first != "tag":
        _write_text(path, "tag\n" + txt + ("\n" if not txt.endswith("\n") else ""))


def _run_engine(
    *,
    engine: str,
    prompt_text: str,
    output_path: Path,
    timeout_sec: int,
    used_prompt_path: Path,
    cwd: Path,
    fallback_context: Dict[str, str],
) -> Dict[str, Any]:
    used_prompt_path.parent.mkdir(parents=True, exist_ok=True)
    used_prompt_path.write_text(prompt_text, encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()

    def resolve_engine_argv(engine_name: str, engine_args: List[str]) -> Optional[List[str]]:
        base = shutil.which(engine_name)
        if base:
            return [base, *engine_args]
        if os.name == "nt":
            for ext in (".cmd", ".exe", ".bat"):
                p = shutil.which(engine_name + ext)
                if p:
                    return [p, *engine_args]
            ps1 = shutil.which(engine_name + ".ps1")
            if ps1:
                return [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    ps1,
                    *engine_args,
                ]
        return None

    def offline_write(text: str, reason: str) -> Dict[str, Any]:
        output_path.write_text(text, encoding="utf-8")
        return {
            "cmd": None,
            "returncode": None,
            "stdout": "",
            "stderr": reason,
            "elapsed_sec": round(time.time() - started, 3),
            "ok": True,
            "engine_mode": "offline_fallback",
        }

    def offline_generate() -> Dict[str, Any]:
        theme = (fallback_context.get("theme") or "").strip()
        catchcopy = (fallback_context.get("catchcopy") or "").strip()
        paid_flag = (fallback_context.get("paid_flag") or "0").strip()
        tags_raw = (fallback_context.get("tags") or "").strip()
        tags = [t.strip() for t in re.split(r"[;,\s]+", tags_raw) if t.strip()]
        if not tags:
            tags = ["note", "学び", "習慣"]

        name = output_path.name
        if name == "materials.md":
            text = (
                f"# 素材: {theme}\n\n"
                "## フック案\n"
                f"- 「{catchcopy}」は本当？ 今日から検証できる方法\n"
                f"- いまの不調は才能不足じゃない。「{theme}」の仕組みの話\n"
                f"- 5分で変わる。{theme}の“入口”だけやってみる\n\n"
                "## タイトル案\n"
                f"- {theme}の最短ルート\n"
                f"- {theme}: まずは1つだけ\n"
                f"- {catchcopy}\n"
                f"- {theme}をラクにするチェックリスト\n"
                f"- 「時間がない/続かない」をほどく{theme}\n\n"
                "## 冒頭一文\n"
                f"- {catchcopy}。\n"
                f"- 「{theme}」を変えると、日々の負担が下がります。\n"
                f"- {theme}は気合ではなく設計です。\n\n"
                "## 主要論点\n"
                "- 原因は1つに絞らず、再現性のある要素に分解する\n"
                "- まず“負荷”を下げ、次に“回復”を増やす\n"
                "- 計測できる指標を置く（主観/時間/頻度）\n"
                "- 失敗パターンを先に潰す（過剰・断念・反動）\n"
                "- 継続のコツは最小単位と環境設計\n\n"
                "## 具体例/比喩\n"
                "- スマホの省電力モード: まず消耗を減らす\n"
                "- 筋トレの漸進性: いきなり最大負荷にしない\n"
                "- 交差点の信号: 切替コストを減らすと流れが良くなる\n"
            )
            return offline_write(text, "offline_fallback: engine executable not found")

        if name == "REVIEW.md":
            text = (
                f"# REVIEW: {theme}\n\n"
                "## 弱点\n"
                "- 根拠の提示が薄い箇所がある（出典/体験談の区別を明確に）\n"
                "- 専門用語が続くと読み手が脱落しやすい（比喩か要約を追加）\n\n"
                "## 冗長\n"
                "- 同じ主張の言い換えが連続する箇所は1回に圧縮\n\n"
                "## 飛躍\n"
                "- 手段→結果の因果が強すぎる表現がある（「可能性が高い」等に緩める）\n\n"
                "## 危険表現\n"
                "- 医療/健康の断定は避け、必要なら受診推奨を入れる\n\n"
                "## 改善提案\n"
                "- 冒頭で「この記事で得られるもの」を3点に固定\n"
                "- 具体策は『今日/今週/来月』の3段にする\n"
            )
            return offline_write(text, "offline_fallback: engine executable not found")

        if name == "banner_prompt.txt":
            text = (
                f"{theme} / {catchcopy}\n"
                "ミニマルなフラットデザイン、落ち着いた配色、抽象アイコン、16:9、文字は短い見出し1つ"
            )
            return offline_write(text, "offline_fallback: engine executable not found")

        if name == "tags.csv":
            extra = ["生産性", "健康", "思考法", "セルフケア", "デスクワーク"]
            merged: List[str] = []
            for t in tags + extra:
                if t not in merged:
                    merged.append(t)
            text = "tag\n" + "\n".join(merged[:10]) + "\n"
            return offline_write(text, "offline_fallback: engine executable not found")

        if name == "meta.md":
            text = (
                "## title\n"
                f"{theme}\n\n"
                "## description\n"
                f"{catchcopy}を手がかりに、原因の分解と具体策をまとめます。\n\n"
                "## target_reader\n"
                "- 忙しくて整える時間が取れない人\n"
                "- 仕組みで改善したい人\n\n"
                "## key_takeaways\n"
                "- 原因を分解すると手が打てる\n"
                "- 最小単位から始めると続く\n"
                "- 反動を防ぐ仕組みが必要\n\n"
                "## paid\n"
                f"{paid_flag}\n"
            )
            return offline_write(text, "offline_fallback: engine executable not found")

        paid = paid_flag == "1"
        free = (
            f"# {theme}\n\n"
            f"{catchcopy}\n\n"
            "## この記事で得られるもの\n"
            "- 何が起きているか（仕組み）\n"
            "- 今日からできる具体策\n"
            "- 続けるための設計\n\n"
            "## 結論\n"
            f"{theme}は気合ではなく、負荷の設計と回復の積み上げで改善しやすくなります。\n\n"
            "## 背景/仕組み\n"
            "- まず「負荷（消耗）」と「回復（補給）」に分けて考える\n"
            "- 悪化要因は“足し算”より“切替”で増えることがある\n\n"
            "## 具体策（今日から）\n"
            "1. いま一番つらい場面を1つだけ特定する\n"
            "2. その直前に入る“切替”を1つ減らす\n"
            "3. 5分の回復ルーチンを固定する\n\n"
            "## ありがちな失敗と回避\n"
            "- いきなり全部変える → 1つだけ変える\n"
            "- 根性で続ける → 環境で続ける\n\n"
            "## まとめ\n"
            "- 分解して一撃で効く点を探す\n"
            "- 最小単位で回す\n"
            "- 反動が出ない設計にする\n"
        )
        paid_part = ""
        if paid:
            paid_part = (
                "\n\n※以下、有料部分\n\n"
                "## 有料: 深掘り（設計のテンプレ）\n"
                "### 1) 負荷の棚卸し（3カテゴリ）\n"
                "- 物理: 姿勢/視線/睡眠など\n"
                "- 認知: 注意の切替/意思決定/通知\n"
                "- 感情: 不安/焦り/自己否定\n\n"
                "### 2) 週次で回す最小KPI\n"
                "- 週に何回できたか（頻度）\n"
                "- 1回の最小時間（継続の下限）\n"
                "- 主観スコア（0〜10）\n\n"
                "### 3) 続かない原因の先回り\n"
                "- 予定が崩れた時の“代替案”を1つ作っておく\n"
                "- 例外日でもゼロにしない（30秒ルール）\n"
            )
        return offline_write(free + paid_part + "\n", "offline_fallback: engine executable not found")

    if engine == "codex":
        cmd = resolve_engine_argv(
            "codex",
            [
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--output-last-message",
                str(output_path),
                "-",
            ],
        )
        if cmd is None:
            return offline_generate()
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            input=prompt_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        ok = proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-4000:],
            "elapsed_sec": round(time.time() - started, 3),
            "ok": ok,
        }

    if engine == "gemini":
        cmd = resolve_engine_argv("gemini", ["-p", prompt_text])
        if cmd is None:
            return offline_generate()
        try:
            with output_path.open("w", encoding="utf-8", newline="\n") as out:
                proc = subprocess.run(
                    cmd,
                    cwd=str(cwd),
                    stdout=out,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_sec,
                )
        except Exception as e:
            return {
                "cmd": cmd,
                "returncode": None,
                "stdout": "",
                "stderr": f"{type(e).__name__}: {e}",
                "elapsed_sec": round(time.time() - started, 3),
                "ok": False,
            }
        ok = proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": "",
            "stderr": (proc.stderr or "")[-4000:],
            "elapsed_sec": round(time.time() - started, 3),
            "ok": ok,
        }

    raise ValueError(f"unknown engine: {engine}")


def _parse_minimal_yaml(text: str) -> Any:
    """
    最小YAMLパーサ:
    - 2スペースインデント
    - mapping: key: value / key:
    - list: - value / - key: value / - key:
    - 文字列はクオート無しを前提（必要なら "..." も許容）
    """

    def parse_scalar(s: str) -> Any:
        s = s.strip()
        if not s:
            return ""
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        if s in ("true", "True"):
            return True
        if s in ("false", "False"):
            return False
        return s

    lines = []
    for raw in text.splitlines():
        raw = raw.rstrip()
        if not raw or raw.lstrip().startswith("#"):
            continue
        lines.append(raw)

    idx = 0

    def current_indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def parse_block(expected_indent: int) -> Any:
        nonlocal idx
        mapping: Dict[str, Any] = {}
        sequence: List[Any] = []
        mode: Optional[str] = None  # "map" or "seq"

        while idx < len(lines):
            line = lines[idx]
            indent = current_indent(line)
            if indent < expected_indent:
                break
            if indent > expected_indent:
                raise ValueError(f"invalid indent at line: {line}")

            stripped = line.strip()
            if stripped.startswith("- "):
                if mode is None:
                    mode = "seq"
                if mode != "seq":
                    raise ValueError(f"mixed sequence and mapping at line: {line}")
                item = stripped[2:].strip()
                idx += 1
                if not item:
                    sequence.append(parse_block(expected_indent + 2))
                    continue
                if ":" in item:
                    key, rest = item.split(":", 1)
                    key = key.strip()
                    rest = rest.strip()
                    if rest:
                        sequence.append({key: parse_scalar(rest)})
                    else:
                        sequence.append({key: parse_block(expected_indent + 2)})
                else:
                    sequence.append(parse_scalar(item))
                continue

            if mode is None:
                mode = "map"
            if mode != "map":
                raise ValueError(f"mixed mapping and sequence at line: {line}")

            if ":" not in stripped:
                raise ValueError(f"expected key: value at line: {line}")
            key, rest = stripped.split(":", 1)
            key = key.strip()
            rest = rest.strip()
            idx += 1
            if rest:
                mapping[key] = parse_scalar(rest)
            else:
                mapping[key] = parse_block(expected_indent + 2)
        return sequence if mode == "seq" else mapping

    doc = parse_block(0)
    return doc


def _load_pipeline(root: Path, pipeline_name: str) -> Dict[str, Any]:
    cfg_path = root / "config" / "pipeline.yml"
    data = _parse_minimal_yaml(_read_text(cfg_path))
    if not isinstance(data, dict) or pipeline_name not in data:
        raise RuntimeError(f"pipeline not found: {pipeline_name}")
    pipeline = data[pipeline_name]
    if not isinstance(pipeline, dict):
        raise RuntimeError(f"invalid pipeline: {pipeline_name}")
    steps = pipeline.get("steps")
    if not isinstance(steps, list) or not steps:
        raise RuntimeError(f"pipeline has no steps: {pipeline_name}")
    normalized_steps: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            raise RuntimeError(f"invalid step: {step}")
        if len(step) == 1:
            (k, v), = step.items()
            if isinstance(v, dict):
                normalized_steps.append({"name": str(k), **v})
                continue
        normalized_steps.append(step)
    pipeline["steps"] = normalized_steps
    pipeline["name"] = pipeline_name
    return pipeline


def _unique_run_dir(base: Path) -> Path:
    if not base.exists():
        return base
    for i in range(2, 9999):
        candidate = Path(str(base) + f"_{i}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find unique run dir for: {base}")


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _zip_run_dir(run_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(run_dir.rglob("*")):
            if p.is_dir():
                continue
            if p.name == zip_path.name:
                continue
            zf.write(p, arcname=str(p.relative_to(run_dir)))


def _step_prompt_kind_for_output(output_name: str) -> str:
    if output_name == "banner_prompt.txt":
        return "prompt_banner.txt"
    if output_name == "tags.csv":
        return "prompt_tags.txt"
    if output_name == "meta.md":
        return "prompt_meta.txt"
    if output_name.endswith(".md"):
        return "prompt_article.txt"
    return "prompt_article.txt"


def _run_step(
    *,
    root: Path,
    run_dir: Path,
    engine: str,
    persona: Persona,
    theme: Dict[str, str],
    step_name: str,
    output_name: str,
    inputs: List[str],
    rng: random.Random,
) -> Tuple[bool, Dict[str, Any]]:
    input_materials = _read_text(run_dir / "materials.md") if (run_dir / "materials.md").exists() else ""
    input_review = _read_text(run_dir / "REVIEW.md") if (run_dir / "REVIEW.md").exists() else ""
    input_article = _read_text(run_dir / "article.md") if (run_dir / "article.md").exists() else ""
    persona_yaml = _load_persona_yaml(root, persona)

    template_name = _step_prompt_kind_for_output(output_name)
    template_text, template_source = _read_template_for_persona_step(
        root, persona, step_name, persona.template_set, template_name
    )

    variables = {
        "persona_id": persona.persona_id,
        "role": persona.role,
        "theme": theme["theme"],
        "catchcopy": theme["catchcopy"],
        "paid_flag": theme["paid_flag"],
        "tags": theme["tags"],
        "persona_yaml": persona_yaml,
        "run_date": _dt.date.today().isoformat(),
        "input_materials": input_materials,
        "input_review": input_review,
        "input_article": input_article,
    }

    prompt_text = render_template(template_text, variables)
    out_path = run_dir / output_name
    used_prompt_path = run_dir / f"_used_{step_name}__{template_name}"

    try:
        persona_defs = _copy_persona_defs_to_run_dir(root, run_dir, persona)
    except Exception:
        persona_defs = []

    max_attempts = 1 + max(0, persona.max_retries)
    last_result: Dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        try:
            result = _run_engine(
                engine=engine,
                prompt_text=prompt_text,
                output_path=out_path,
                timeout_sec=max(1, persona.timeout_sec),
                used_prompt_path=used_prompt_path,
                cwd=root,
                fallback_context={
                    "theme": theme["theme"],
                    "catchcopy": theme["catchcopy"],
                    "paid_flag": theme["paid_flag"],
                    "tags": theme["tags"],
                },
            )
        except subprocess.TimeoutExpired as e:
            result = {
                "cmd": getattr(e, "cmd", None),
                "returncode": None,
                "stdout": "",
                "stderr": f"TimeoutExpired: {e}",
                "elapsed_sec": persona.timeout_sec,
                "ok": False,
            }
        cleaned = _persist_engine_streams(run_dir, step_name, attempt, result)
        last_result = {
            **cleaned,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "persona_defs": persona_defs,
            "template": template_name,
            "template_source": template_source,
        }
        if result.get("ok"):
            try:
                override_prefix = f"personas/{persona.persona_id}/overrides/"
                if template_source.replace("\\", "/").startswith(override_prefix):
                    src = root / Path(template_source)
                    dst = run_dir / template_source
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    last_result["template_copied_to_run_dir"] = str(dst.relative_to(run_dir)).replace("\\", "/")
            except Exception:
                pass
            if output_name == "tags.csv":
                _normalize_tags_csv(out_path, theme.get("tags", ""))
            ok_quality, quality = _validate_output_file(output_name, out_path)
            last_result["quality"] = quality
            if not ok_quality:
                last_result["ok"] = False
                last_result["failure_reason"] = "format_violation"
            else:
                last_result["failure_reason"] = ""
            try:
                dst = run_dir / "persona_outputs" / persona.persona_id / f"{step_name}__{out_path.name}"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(out_path, dst)
                last_result["persona_output"] = str(dst.relative_to(run_dir)).replace("\\", "/")
            except Exception:
                pass
            if ok_quality:
                return True, last_result
        else:
            last_result["failure_reason"] = _classify_engine_failure(result)
        if attempt < max_attempts:
            time.sleep(max(0, persona.retry_wait_sec))
    return False, last_result


def _generate_derivatives(
    *,
    root: Path,
    run_dir: Path,
    engine: str,
    persona: Persona,
    theme: Dict[str, str],
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    def build_entry(step_name: str, output_name: str, ok: bool, r: Dict[str, Any]) -> Dict[str, Any]:
        retries = max(0, int(r.get("attempt", 1)) - 1)
        failure_reason = None if ok else str(r.get("failure_reason") or "unknown")
        return {
            "name": step_name,
            "role": persona.role,
            "persona_id": persona.persona_id,
            "inputs": ["article.md"],
            "output": output_name,
            "ok": ok,
            "engine_result": r,
            **build_step_result(
                step_name=step_name,
                status="success" if ok else "failed",
                failure_reason=failure_reason,
                error_message=None,
                retries=retries,
                duration_ms=None,
            ),
        }

    ok1, r1 = _run_step(
        root=root,
        run_dir=run_dir,
        engine=engine,
        persona=persona,
        theme=theme,
        step_name="banner",
        output_name="banner_prompt.txt",
        inputs=["article.md"],
        rng=random.Random(),
    )
    results.append(build_entry("banner", "banner_prompt.txt", ok1, r1))

    ok2, r2 = _run_step(
        root=root,
        run_dir=run_dir,
        engine=engine,
        persona=persona,
        theme=theme,
        step_name="tags",
        output_name="tags.csv",
        inputs=["article.md"],
        rng=random.Random(),
    )
    results.append(build_entry("tags", "tags.csv", ok2, r2))

    ok3, r3 = _run_step(
        root=root,
        run_dir=run_dir,
        engine=engine,
        persona=persona,
        theme=theme,
        step_name="meta",
        output_name="meta.md",
        inputs=["article.md"],
        rng=random.Random(),
    )
    results.append(build_entry("meta", "meta.md", ok3, r3))

    return results


def _run_single(
    *,
    root: Path,
    personas: List[Persona],
    engine: str,
    rng: random.Random,
    persona_id: Optional[str],
    auto: bool,
    skip_on_failure: bool,
    seed: int,
) -> Tuple[Path, bool]:
    if persona_id:
        persona = next((p for p in personas if p.persona_id == persona_id), None)
        if persona is None:
            raise RuntimeError(f"persona_id not found: {persona_id}")
    elif auto:
        persona = choose_persona(personas, role="integrator", engine=engine, rng=rng)
    else:
        raise RuntimeError("either --persona_id or --auto is required for single mode")

    theme_path = root / "themes" / f"{persona.theme_pool}.csv"
    theme = load_theme(theme_path, rng)

    run_date = _dt.date.today().isoformat()
    slug = _stable_slug_from_theme(theme["theme"])
    base_dir = root / "runs" / run_date / f"{persona.persona_id}__{slug}"
    run_dir = _unique_run_dir(base_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    output_mode = (persona.output_mode or "").strip().lower()
    if output_mode in ("materials", "material", "materials.md"):
        main_output = "materials.md"
        main_step_name = "idea"
    elif output_mode in ("review", "critic", "review.md", "reviewer"):
        main_output = "REVIEW.md"
        main_step_name = "review"
    else:
        main_output = "article.md"
        main_step_name = "article"

    mode_raw = "auto" if auto else "single"
    mode_normalized, mode_legacy = normalize_mode(mode_raw)
    run_id = new_run_id()
    theme_id = _theme_id_from_theme(theme)
    experiment_id = _resolve_experiment_id(run_id)
    run_json: Dict[str, Any] = {
        "run_id": run_id,
        "ts": _now_iso(),
        "mode": mode_normalized,
        "engine": engine,
        "seed": seed,
        "persona": persona.persona_id,
        "theme": theme,
        "theme_id": theme_id,
        "experiment_id": experiment_id,
        "rerun_command": " ".join(
            [
                "python",
                "scripts/generate_batch.py",
                "--engine",
                engine,
                "--seed",
                str(seed),
                *(
                    ["--persona_id", persona.persona_id]
                    if persona_id
                    else (["--auto"] if auto else ["--persona_id", persona.persona_id])
                ),
                "--n",
                "1",
            ]
        ),
        "steps": [],
    }
    run_json["mode_legacy"] = mode_legacy
    run_json.update(lineage_for_new_run(run_id))

    started = time.time()
    ok_article, result_article = _run_step(
        root=root,
        run_dir=run_dir,
        engine=engine,
        persona=persona,
        theme=theme,
        step_name=main_step_name,
        output_name=main_output,
        inputs=[],
        rng=rng,
    )
    duration_ms = int((time.time() - started) * 1000)
    retries = max(0, int(result_article.get("attempt", 1)) - 1)
    failure_reason = None if ok_article else str(result_article.get("failure_reason") or "unknown")
    error_message = None
    run_json["steps"].append(
        {
            "name": main_step_name,
            "role": persona.role,
            "persona_id": persona.persona_id,
            "output": main_output,
            "ok": ok_article,
            "engine_result": result_article,
            **build_step_result(
                step_name=main_step_name,
                status="success" if ok_article else "failed",
                failure_reason=failure_reason,
                error_message=error_message,
                retries=retries,
                duration_ms=duration_ms,
            ),
        }
    )

    if not ok_article and skip_on_failure:
        run_json["run_status"] = "failed"
        _write_text(run_dir / "SKIP.json", json.dumps({"reason": "article_failed"}, ensure_ascii=False, indent=2))
        _update_content_hashes(run_json, run_dir)
        _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
        _append_jsonl(
            root / "logs" / "runs.jsonl",
            {"ts": run_json["ts"], "status": "skipped", "mode": "single", "run_dir": str(run_dir)},
        )
        return run_dir, False
    if not ok_article:
        run_json["run_status"] = "failed"
        _update_content_hashes(run_json, run_dir)
        _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
        return run_dir, False

    if main_output == "article.md":
        deriv = _generate_derivatives(root=root, run_dir=run_dir, engine=engine, persona=persona, theme=theme)
        run_json["derivatives"] = deriv
    run_json["run_status"] = "success"
    _update_content_hashes(run_json, run_dir)
    _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
    _zip_run_dir(run_dir, run_dir / "bundle.zip")

    _append_jsonl(
        root / "logs" / "runs.jsonl",
        {
            "ts": run_json["ts"],
            "status": "ok",
            "mode": "single",
            "engine": engine,
            "run_dir": str(run_dir),
            "persona": persona.persona_id,
            "theme": theme.get("theme"),
        },
    )
    return run_dir, run_json.get("run_status") != "failed"


def _run_pipeline(
    *,
    root: Path,
    personas: List[Persona],
    pipeline_name: str,
    engine: str,
    rng: random.Random,
    auto: bool,
    skip_on_failure: bool,
    seed: int,
) -> Tuple[Path, bool]:
    pipeline = _load_pipeline(root, pipeline_name)
    steps: List[Dict[str, Any]] = pipeline["steps"]
    policy = parse_pipeline_policy(pipeline)

    selected_personas: Dict[str, Persona] = {}
    forced_personas = _forced_personas_from_env()
    first_persona: Optional[Persona] = None
    for step in steps:
        role = str(step.get("role") or "").strip()
        if not role:
            raise RuntimeError(f"step missing role: {step}")
        if auto:
            forced_id = forced_personas.get(role)
            if forced_id:
                persona = next((p for p in personas if p.persona_id == forced_id), None)
                if persona is None:
                    raise RuntimeError(f"forced persona_id not found: {forced_id}")
                if persona.role != role:
                    raise RuntimeError(
                        f"forced persona role mismatch: {forced_id} role={persona.role} expected={role}"
                    )
            else:
                persona = choose_persona(personas, role=role, engine=engine, rng=rng)
        else:
            raise RuntimeError("--pipeline requires --auto (persona selection per step)")
        selected_personas[str(step.get("name") or role)] = persona
        if first_persona is None:
            first_persona = persona
    if first_persona is None:
        raise RuntimeError("pipeline has no steps")

    theme_path = root / "themes" / f"{first_persona.theme_pool}.csv"
    theme = load_theme(theme_path, rng)

    run_date = _dt.date.today().isoformat()
    slug = _stable_slug_from_theme(theme["theme"])
    base_dir = root / "runs" / run_date / f"{pipeline_name}__{slug}"
    run_dir = _unique_run_dir(base_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    mode_normalized, mode_legacy = normalize_mode("pipeline")
    run_id = new_run_id()
    theme_id = _theme_id_from_theme(theme)
    experiment_id = _resolve_experiment_id(run_id)
    run_json: Dict[str, Any] = {
        "run_id": run_id,
        "ts": _now_iso(),
        "mode": mode_normalized,
        "pipeline": pipeline_name,
        "engine": engine,
        "seed": seed,
        "theme": theme,
        "theme_id": theme_id,
        "experiment_id": experiment_id,
        "selected_personas": {k: v.persona_id for k, v in selected_personas.items()},
        "required_steps": sorted(policy.required_steps),
        "optional_steps": sorted(policy.optional_steps),
        "on_step_failure": policy.on_step_failure,
        "rerun_command": " ".join(
            [
                "python",
                "scripts/generate_batch.py",
                "--engine",
                engine,
                "--seed",
                str(seed),
                "--pipeline",
                pipeline_name,
                "--auto",
                "--n",
                "1",
            ]
        ),
        "steps": [],
    }
    run_json["mode_legacy"] = mode_legacy
    run_json.update(lineage_for_new_run(run_id))

    stop_triggered = False
    skip_rest = False
    last_integrator: Optional[Persona] = None
    for step in steps:
        step_name = str(step.get("name") or "").strip() or "step"
        role = str(step.get("role") or "").strip()
        output_name = str(step.get("output") or "").strip()
        inputs = step.get("inputs") or []
        if isinstance(inputs, list):
            inputs_list = [str(x).strip() for x in inputs if str(x).strip()]
        else:
            inputs_list = []

        persona = selected_personas.get(step_name) or choose_persona(personas, role=role, engine=engine, rng=rng)
        if role == "integrator":
            last_integrator = persona

        if skip_rest:
            run_json["steps"].append(
                {
                    "name": step_name,
                    "role": role,
                    "persona_id": persona.persona_id,
                    "inputs": inputs_list,
                    "output": output_name,
                    "ok": False,
                    "engine_result": None,
                    **build_step_result(
                        step_name=step_name,
                        status="skipped",
                        failure_reason="skip_rest",
                        error_message=None,
                        retries=0,
                        duration_ms=None,
                    ),
                }
            )
            continue

        retries = 0
        total_ms = 0
        final_action = "continue"
        while True:
            started = time.time()
            ok, engine_result = _run_step(
                root=root,
                run_dir=run_dir,
                engine=engine,
                persona=persona,
                theme=theme,
                step_name=step_name,
                output_name=output_name,
                inputs=inputs_list,
                rng=rng,
            )
            total_ms += int((time.time() - started) * 1000)

            failure_reason = None if ok else str(engine_result.get("failure_reason") or "unknown")
            error_message = None

            if ok:
                status = "success"
                break

            rule = policy.failure_rule(step_name, failure_reason)
            if rule.action == "retry" and retries < rule.max_retry:
                retries += 1
                continue
            if rule.action == "retry":
                final_action = policy.action_after_retry(step_name)
            else:
                final_action = rule.action
            status = "failed"
            break

        run_json["steps"].append(
            {
                "name": step_name,
                "role": role,
                "persona_id": persona.persona_id,
                "inputs": inputs_list,
                "output": output_name,
                "ok": ok,
                "engine_result": engine_result,
                **build_step_result(
                    step_name=step_name,
                    status=status,
                    failure_reason=failure_reason if status != "success" else None,
                    error_message=error_message if status != "success" else None,
                    retries=retries,
                    duration_ms=total_ms,
                ),
            }
        )

        if status == "failed" and policy.is_required(step_name):
            if final_action == "stop":
                stop_triggered = True
                break
            if final_action == "skip_rest":
                skip_rest = True

        run_json["run_status"] = compute_run_status(run_json["steps"], required_steps, stop_triggered)

    if stop_triggered:
        if skip_on_failure:
            _write_text(
                run_dir / "SKIP.json",
                json.dumps(
                    {"ts": run_json["ts"], "reason": "step_failed", "failed_step": run_json["steps"][-1]},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            _update_content_hashes(run_json, run_dir)
            _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
            _append_jsonl(
                root / "logs" / "runs.jsonl",
                {
                    "ts": run_json["ts"],
                    "status": "skipped",
                    "mode": "pipeline",
                    "pipeline": pipeline_name,
                    "engine": engine,
                    "run_dir": str(run_dir),
                },
            )
            return run_dir, False
        _update_content_hashes(run_json, run_dir)
        _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
        return run_dir, False

    if (run_dir / "article.md").exists() and last_integrator is not None and not stop_triggered:
        run_json["derivatives"] = _generate_derivatives(
            root=root, run_dir=run_dir, engine=engine, persona=last_integrator, theme=theme
        )

    _update_content_hashes(run_json, run_dir)
    _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
    _zip_run_dir(run_dir, run_dir / "bundle.zip")

    _append_jsonl(
        root / "logs" / "runs.jsonl",
        {
            "ts": run_json["ts"],
            "status": run_json.get("run_status", "ok"),
            "mode": "pipeline",
            "pipeline": pipeline_name,
            "engine": engine,
            "run_dir": str(run_dir),
            "theme": theme.get("theme"),
            "personas": run_json.get("selected_personas", {}),
        },
    )
    return run_dir, True


def _resolve_existing_run_dir(root: Path, run_dir_arg: str) -> Path:
    p = Path(run_dir_arg)
    if not p.is_absolute():
        p = (root / p).resolve()
    if not p.exists() or not p.is_dir():
        raise RuntimeError(f"rerun dir not found: {p}")
    run_json_path = p / "run.json"
    if not run_json_path.exists():
        raise RuntimeError(f"run.json not found in rerun dir: {p}")
    try:
        p.relative_to(root)
    except Exception:
        raise RuntimeError(f"rerun dir must be under project root: {p}")
    return p


def _run_rerun(
    *,
    root: Path,
    personas: List[Persona],
    rerun_dir: Path,
    skip_on_failure: bool,
) -> Tuple[Path, bool]:
    prev = json.loads(_read_text(rerun_dir / "run.json"))
    if not prev.get("run_id"):
        prev_run_id = new_run_id()
        prev["run_id"] = prev_run_id
        prev.setdefault("origin_run_id", prev_run_id)
        _write_text(rerun_dir / "run.json", json.dumps(prev, ensure_ascii=False, indent=2))
    mode = str(prev.get("mode") or "").strip()
    engine = str(prev.get("engine") or "").strip()
    if engine not in ("codex", "gemini"):
        raise RuntimeError(f"invalid engine in run.json: {engine}")
    seed = int(prev.get("seed") or 0)
    theme = prev.get("theme")
    if not isinstance(theme, dict) or not str(theme.get("theme") or "").strip():
        raise RuntimeError("invalid theme in run.json")

    run_date = _dt.date.today().isoformat()
    slug = _stable_slug_from_theme(str(theme.get("theme") or ""))
    rerun_of_rel = str(rerun_dir.relative_to(root)).replace("\\", "/")
    rerun_cmd = " ".join(["python", "scripts/generate_batch.py", "--rerun", rerun_of_rel])

    if mode in ("single", "rerun_single"):
        persona_id = str(prev.get("persona") or "").strip()
        if not persona_id:
            raise RuntimeError("missing persona in run.json")
        persona = next((p for p in personas if p.persona_id == persona_id), None)
        if persona is None:
            raise RuntimeError(f"persona_id not found: {persona_id}")

        steps = prev.get("steps") or []
        if not isinstance(steps, list) or not steps or not isinstance(steps[0], dict):
            raise RuntimeError("run.json has no steps")
        first_step: Dict[str, Any] = steps[0]
        main_step_name = str(first_step.get("name") or "").strip() or "article"
        main_output = str(first_step.get("output") or "").strip() or "article.md"

        base_dir = root / "runs" / run_date / f"{persona.persona_id}__{slug}__rerun"
        run_dir = _unique_run_dir(base_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        run_id = new_run_id()
        parent_experiment_id = str(prev.get("experiment_id") or "") or None
        theme_id = str(prev.get("theme_id") or "") or _theme_id_from_theme(theme)
        experiment_id = _resolve_experiment_id(run_id, parent_experiment_id)
        run_json: Dict[str, Any] = {
            "run_id": run_id,
            "ts": _now_iso(),
            "mode": "rerun",
            "mode_legacy": "rerun_single",
            "engine": engine,
            "seed": seed,
            "persona": persona.persona_id,
            "theme": theme,
            "theme_id": theme_id,
            "experiment_id": experiment_id,
            "rerun_command": rerun_cmd,
            "steps": [],
        }
        run_json.update(lineage_for_rerun(prev, rerun_of_rel))

        rng = random.Random(seed)
        started = time.time()
        ok_main, result_main = _run_step(
            root=root,
            run_dir=run_dir,
            engine=engine,
            persona=persona,
            theme=theme,
            step_name=main_step_name,
            output_name=main_output,
            inputs=[],
            rng=rng,
        )
        duration_ms = int((time.time() - started) * 1000)
        retries = max(0, int(result_main.get("attempt", 1)) - 1)
        failure_reason = None if ok_main else str(result_main.get("failure_reason") or "unknown")
        error_message = None
        run_json["steps"].append(
            {
                "name": main_step_name,
                "role": persona.role,
                "persona_id": persona.persona_id,
                "output": main_output,
                "ok": ok_main,
                "engine_result": result_main,
                **build_step_result(
                    step_name=main_step_name,
                    status="success" if ok_main else "failed",
                    failure_reason=failure_reason,
                    error_message=error_message,
                    retries=retries,
                    duration_ms=duration_ms,
                ),
            }
        )

        if not ok_main and skip_on_failure:
            run_json["run_status"] = "failed"
            _write_text(
                run_dir / "SKIP.json",
                json.dumps(
                    {"ts": run_json["ts"], "reason": "step_failed", "failed_step": run_json["steps"][-1]},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            _update_content_hashes(run_json, run_dir)
            _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
            _append_jsonl(
                root / "logs" / "runs.jsonl",
                {"ts": run_json["ts"], "status": "skipped", "mode": "rerun_single", "run_dir": str(run_dir)},
            )
            return run_dir, False
        if not ok_main:
            run_json["run_status"] = "failed"
            _update_content_hashes(run_json, run_dir)
            _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
            return run_dir, False

        if main_output == "article.md":
            run_json["derivatives"] = _generate_derivatives(
                root=root, run_dir=run_dir, engine=engine, persona=persona, theme=theme
            )

        run_json["run_status"] = "success"
        _update_content_hashes(run_json, run_dir)
        _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
        _zip_run_dir(run_dir, run_dir / "bundle.zip")
        _append_jsonl(
            root / "logs" / "runs.jsonl",
            {
                "ts": run_json["ts"],
                "status": run_json.get("run_status", "ok"),
                "mode": "rerun_single",
                "engine": engine,
                "run_dir": str(run_dir),
                "persona": persona.persona_id,
                "theme": str(theme.get("theme") or ""),
            },
        )
        return run_dir, True

    if mode in ("pipeline", "rerun_pipeline"):
        steps = prev.get("steps") or []
        if not isinstance(steps, list) or not steps:
            raise RuntimeError("run.json has no steps")
        pipeline_name = str(prev.get("pipeline") or "").strip() or "pipeline"

        base_dir = root / "runs" / run_date / f"{pipeline_name}__{slug}__rerun"
        run_dir = _unique_run_dir(base_dir)
        run_dir.mkdir(parents=True, exist_ok=True)

        run_id = new_run_id()
        parent_experiment_id = str(prev.get("experiment_id") or "") or None
        theme_id = str(prev.get("theme_id") or "") or _theme_id_from_theme(theme)
        experiment_id = _resolve_experiment_id(run_id, parent_experiment_id)
        run_json: Dict[str, Any] = {
            "run_id": run_id,
            "ts": _now_iso(),
            "mode": "rerun",
            "mode_legacy": "rerun_pipeline",
            "pipeline": pipeline_name,
            "engine": engine,
            "seed": seed,
            "theme": theme,
            "theme_id": theme_id,
            "experiment_id": experiment_id,
            "selected_personas": {},
            "rerun_command": rerun_cmd,
            "steps": [],
        }
        run_json.update(lineage_for_rerun(prev, rerun_of_rel))

        rng = random.Random(seed)
        stop_triggered = False
        skip_rest = False
        last_integrator: Optional[Persona] = None
        required_steps = set()
        prev_required = prev.get("required_steps")
        if isinstance(prev_required, list):
            required_steps = {str(x).strip() for x in prev_required if str(x).strip()}

        for step in steps:
            if not isinstance(step, dict):
                raise RuntimeError(f"invalid step in run.json: {step}")
            step_name = str(step.get("name") or "").strip() or "step"
            role = str(step.get("role") or "").strip()
            output_name = str(step.get("output") or "").strip()
            inputs_val = step.get("inputs")
            inputs_list = [str(x).strip() for x in inputs_val if str(x).strip()] if isinstance(inputs_val, list) else []
            persona_id = str(step.get("persona_id") or "").strip()
            if not persona_id:
                raise RuntimeError(f"missing persona_id in step: {step_name}")
            persona = next((p for p in personas if p.persona_id == persona_id), None)
            if persona is None:
                raise RuntimeError(f"persona_id not found: {persona_id}")
            run_json["selected_personas"][step_name] = persona.persona_id
            if role == "integrator":
                last_integrator = persona

            if skip_rest:
                run_json["steps"].append(
                    {
                        "name": step_name,
                        "role": role,
                        "persona_id": persona.persona_id,
                        "inputs": inputs_list,
                        "output": output_name,
                        "ok": False,
                        "engine_result": None,
                        **build_step_result(
                            step_name=step_name,
                            status="skipped",
                            failure_reason="skip_rest",
                            error_message=None,
                            retries=0,
                            duration_ms=None,
                        ),
                    }
                )
                continue

            retries = 0
            total_ms = 0
            while True:
                started = time.time()
                ok, engine_result = _run_step(
                    root=root,
                    run_dir=run_dir,
                    engine=engine,
                    persona=persona,
                    theme=theme,
                    step_name=step_name,
                    output_name=output_name,
                    inputs=inputs_list,
                    rng=rng,
                )
                total_ms += int((time.time() - started) * 1000)
                failure_reason = None if ok else str(engine_result.get("failure_reason") or "unknown")
                error_message = None
                if ok:
                    status = "success"
                    break
                status = "failed"
                break

            run_json["steps"].append(
                {
                    "name": step_name,
                    "role": role,
                    "persona_id": persona.persona_id,
                    "inputs": inputs_list,
                    "output": output_name,
                    "ok": ok,
                    "engine_result": engine_result,
                    **build_step_result(
                        step_name=step_name,
                        status=status,
                        failure_reason=failure_reason if status != "success" else None,
                        error_message=error_message if status != "success" else None,
                        retries=retries,
                        duration_ms=total_ms,
                    ),
                }
            )
            if status == "failed" and step_name in required_steps:
                stop_triggered = True
                break

        run_json["run_status"] = compute_run_status(
            run_json["steps"], required_steps, stop_triggered
        )

        if stop_triggered:
            if skip_on_failure:
                _write_text(
                    run_dir / "SKIP.json",
                    json.dumps(
                        {"ts": run_json["ts"], "reason": "step_failed", "failed_step": run_json["steps"][-1]},
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                _update_content_hashes(run_json, run_dir)
                _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
                _append_jsonl(
                    root / "logs" / "runs.jsonl",
                    {
                        "ts": run_json["ts"],
                        "status": "skipped",
                        "mode": "rerun_pipeline",
                        "pipeline": pipeline_name,
                        "engine": engine,
                        "run_dir": str(run_dir),
                    },
                )
                return run_dir, False
            _update_content_hashes(run_json, run_dir)
            _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
            return run_dir, False

        # Generate derivatives only if article.md is valid
        article_path = run_dir / "article.md" # Re-define article_path here as it was removed in previous step
        if article_path.exists() and os.path.getsize(article_path) > 0 and last_integrator is not None:
            run_json["derivatives"] = _generate_derivatives(
                root=root, run_dir=run_dir, engine=engine, persona=last_integrator, theme=theme
            )

        _update_content_hashes(run_json, run_dir)
        _write_text(run_dir / "run.json", json.dumps(run_json, ensure_ascii=False, indent=2))
        _zip_run_dir(run_dir, run_dir / "bundle.zip")
        _append_jsonl(
            root / "logs" / "runs.jsonl",
            {
                "ts": run_json["ts"],
                "status": run_json.get("run_status", "ok"),
                "mode": "rerun_pipeline",
                "pipeline": pipeline_name,
                "engine": engine,
                "run_dir": str(run_dir),
                "theme": str(theme.get("theme") or ""),
                "personas": run_json.get("selected_personas", {}),
            },
        )
        return run_dir, run_json.get("run_status") != "failed"

    raise RuntimeError(f"unsupported rerun mode in run.json: {mode}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona_id", default=None)
    parser.add_argument("--auto", action="store_true", help="persona自動選定（role一致）")
    parser.add_argument("--pipeline", default=None, help="config/pipeline.yml のパイプライン名")
    parser.add_argument("--n", type=int, default=1, help="連続生成回数")
    parser.add_argument("--engine", default=None, choices=["codex", "gemini"])
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--skip_on_failure", action="store_true", default=True)
    parser.add_argument("--no-skip_on_failure", dest="skip_on_failure", action="store_false")
    parser.add_argument("--rerun", default=None, help="existing run_dir based rerun (fixed theme/personas)")
    args = parser.parse_args(argv)

    root = _project_root()
    if args.rerun:
        personas_csv = root / "config" / "personas.csv"
        personas = load_personas(personas_csv)
        rerun_dir = _resolve_existing_run_dir(root, str(args.rerun))
        run_dir, ok = _run_rerun(
            root=root, personas=personas, rerun_dir=rerun_dir, skip_on_failure=args.skip_on_failure
        )
        print(str(run_dir))
        return 0 if ok else 2

    if not args.engine:
        raise SystemExit("--engine is required unless --rerun is used")
    personas_csv = root / "config" / "personas.csv"
    personas = load_personas(personas_csv)
    seed = int(args.seed) if args.seed is not None else int(time.time())
    rng = random.Random(seed)

    last_run_dir: Optional[Path] = None
    ok_any = False

    for _ in range(max(1, int(args.n))):
        if args.pipeline:
            run_dir, ok = _run_pipeline(
                root=root,
                personas=personas,
                pipeline_name=args.pipeline,
                engine=str(args.engine),
                rng=rng,
                auto=args.auto,
                skip_on_failure=args.skip_on_failure,
                seed=seed,
            )
        else:
            run_dir, ok = _run_single(
                root=root,
                personas=personas,
                engine=str(args.engine),
                rng=rng,
                persona_id=args.persona_id,
                auto=args.auto,
                skip_on_failure=args.skip_on_failure,
                seed=seed,
            )
        last_run_dir = run_dir
        ok_any = ok_any or ok

    if last_run_dir is not None:
        print(str(last_run_dir))
    return 0 if ok_any else 2


if __name__ == "__main__":
    raise SystemExit(main())
