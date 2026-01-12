from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .fetch_note import fetch_and_extract
from .llm_local import DEFAULT_MODEL_PATH, LocalLLM

ROOT_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = Path(__file__).parent / "prompts"
DATA_DIR = ROOT_DIR / "data"


def ensure_data_dirs(base_dir: Path = DATA_DIR) -> Dict[str, Path]:
    paths = {
        "raw_html": base_dir / "raw_html",
        "corpus": base_dir / "corpus",
        "personas": base_dir / "personas",
        "fewshot": base_dir / "fewshot",
        "outputs": base_dir / "outputs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def load_urls(url_file: Path) -> List[str]:
    if not url_file.exists():
        raise FileNotFoundError(f"URL file not found: {url_file}")

    urls: List[str] = []
    seen = set()
    for raw_line in url_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            continue
        seen.add(line)
        urls.append(line)
    return urls


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()
    cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()
    return cleaned


def strip_json_wrappers(text: str) -> str:
    cleaned = strip_code_fences(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return cleaned


def parse_json_with_llm_retry(raw: str, llm: LocalLLM, kind: str) -> Dict[str, Any]:
    cleaned = strip_json_wrappers(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        repair_prompt = f"Fix the following text into strict JSON for {kind}. Return JSON only (no code fences, no explanation).\n\n{cleaned}"
        fixed = llm.chat(
            system_prompt="Return strict JSON only. No markdown, no comments.",
            user_prompt=repair_prompt,
        )
        fixed_clean = strip_json_wrappers(fixed)
        try:
            return json.loads(fixed_clean)
        except json.JSONDecodeError as exc:
            raise ValueError(f"[error] JSON parse failed for {kind}: {exc}") from exc


def read_texts(paths: Iterable[Path]) -> List[str]:
    texts: List[str] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            texts.append(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[warn] failed to read {path}: {exc}")
            texts.append("")
    return texts


def clip_articles_headtail(texts: List[str], max_corpus_chars: int, head_chars: int = 2000, tail_chars: int = 800) -> Tuple[str, bool]:
    chunks: List[str] = []
    for text in texts:
        if len(text) <= head_chars + tail_chars:
            chunks.append(text)
        else:
            head = text[:head_chars]
            tail = text[-tail_chars:]
            chunks.append(head + "\n...\n" + tail)
    combined = "\n\n---\n\n".join(chunks)
    clipped = combined[:max_corpus_chars]
    was_clipped = len(combined) > len(clipped)
    return clipped, was_clipped


def _score_paragraph(paragraph: str) -> float:
    text = paragraph.strip()
    length = len(text)
    score = 0.0
    if 120 <= length <= 800:
        score += 3.0
    elif length < 80:
        score -= 1.0
    elif length > 1200:
        score -= 1.0

    punct = len(re.findall(r"[.!?,]", text))
    score += min(punct / max(1, length) * 400, 2.0)

    connectors = 0
    score += min(connectors * 0.5, 2.0)

    questions = text.count("?")
    score += min(questions * 0.4, 1.5)

    assertive = 0
    score += min(assertive * 0.3, 1.5)

    if re.match(r"^https?://", text) or len(re.findall(r"[#@]{3,}", text)) > 0:
        score -= 2.0

    return score


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    return bool(re.search(r"(\\)|\\])$", stripped) or stripped.endswith((": ", "...", "#"))


def build_corpus_paragraphs(texts: List[str], max_corpus_chars: int, paragraphs_per_article: int) -> Tuple[str, bool, int]:
    selected: List[str] = []
    for text in texts:
        paragraphs = re.split(r"\n\s*\n+", text.strip())
        scored: List[Tuple[float, str]] = []
        prev_heading = False
        for para in paragraphs:
            lines = para.splitlines()
            if lines and _is_heading(lines[0]):
                prev_heading = True
                continue
            score = _score_paragraph(para)
            if prev_heading:
                score += 1.5
                prev_heading = False
            scored.append((score, para))
        if not scored:
            continue
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [p for _, p in scored[:paragraphs_per_article]]
        selected.extend(top)
    combined = "\n\n---\n\n".join(selected)
    clipped = combined[:max_corpus_chars]
    was_clipped = len(combined) > len(clipped)
    return clipped, was_clipped, len(selected)


def ensure_writing_scope_block(persona_text: str) -> str:
    if "writing_scope:" in persona_text:
        return persona_text
    block = (
        "\nwriting_scope:\n"
        "  supports_long_form: true\n"
        "  recommended_structure:\n"
        "    - introduction\n"
        "    - development\n"
        "    - analysis\n"
        "    - conclusion\n"
        "  notes: |\n"
        "    Persona is extracted from clipped corpus.\n"
        "    Clipping does not limit final article length.\n"
    )
    return persona_text.rstrip() + block + "\n"


def preflight_check(
    urls: List[str],
    url_file: Path,
    min_urls: int = 3,
    n_ctx_hint: int | None = None,
    model_path: Path | None = None,
    reuse_persona: Path | None = None,
    reuse_fewshot: Path | None = None,
) -> Tuple[bool, List[str]]:
    ok = True
    valid_urls: List[str] = []

    if not url_file.exists():
        print(f"[ERROR] URL file missing: {url_file}")
        return False, []

    for u in urls:
        if not u.startswith(("http://", "https://")) or " " in u:
            print(f"[WARN] invalid URL skipped: {u}")
            ok = False if len(urls) == 1 else ok
            continue
        valid_urls.append(u)

    unique_urls = list(dict.fromkeys(valid_urls))
    if len(unique_urls) == 0:
        print("[ERROR] No valid URLs found after filtering.")
        return False, []
    if len(unique_urls) != len(valid_urls):
        print(f"[OK] duplicates removed: {len(valid_urls)} -> {len(unique_urls)}")
    if len(unique_urls) < min_urls:
        print(f"[WARN] urls < {min_urls}: persona may be unstable (count={len(unique_urls)})")

    try:
        ensure_data_dirs()
        print("[OK] output dirs ready")
    except Exception as exc:
        print(f"[ERROR] failed to prepare output dirs: {exc}")
        return False, []

    model_check = model_path or DEFAULT_MODEL_PATH
    if not Path(model_check).exists():
        print(f"[ERROR] model not found: {model_check}")
        return False, []
    print(f"[OK] model: {model_check}")

    if reuse_persona:
        if not Path(reuse_persona).exists():
            print(f"[ERROR] reuse-persona not found: {reuse_persona}")
            return False, []
        print(f"[OK] reuse-persona: {reuse_persona}")
    if reuse_fewshot:
        if not Path(reuse_fewshot).exists():
            print(f"[ERROR] reuse-fewshot not found: {reuse_fewshot}")
            return False, []
        print(f"[OK] reuse-fewshot: {reuse_fewshot}")

    try:
        import llama_cpp  # type: ignore  # noqa: F401
    except Exception as exc:  # pragma: no cover - env dependent
        print(f"[ERROR] llama_cpp import failed: {exc}")
        return False, []
    print(f"[OK] urls loaded: {len(unique_urls)} (unique)")

    if n_ctx_hint is not None and n_ctx_hint < 2048:
        print("[WARN] n_ctx is small; generation may truncate")

    if ok:
        print("[OK] preflight passed")
    return ok, unique_urls


class Heartbeat:
    def __init__(self, interval: int, phase_getter: callable, logger: callable, start_time: float) -> None:
        self.interval = max(1, interval)
        self.phase_getter = phase_getter
        self.logger = logger
        self.start_time = start_time
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval):
            phase = self.phase_getter()
            elapsed = int(time.time() - self.start_time)
            self.logger(f"working... (elapsed={elapsed}s, phase={phase})")


def _log_line(log_file: Path, level: str, phase: str, message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] [phase={phase}] {message}"
    print(line)
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _write_and_mirror(content: str, run_file: Path, compat_file: Path) -> None:
    run_file.parent.mkdir(parents=True, exist_ok=True)
    run_file.write_text(content, encoding="utf-8")
    compat_file.write_text(content, encoding="utf-8")


def _check_wall(start_time: float, limit: int) -> bool:
    return (time.time() - start_time) > limit


def run_pipeline(
    urls: List[str],
    theme: str,
    url_file: Path | None = None,
    model_path: Path | str = DEFAULT_MODEL_PATH,
    score_threshold: float = 0.70,
    max_retries: int = 2,
    max_corpus_chars: int = 30000,
    min_urls: int = 3,
    corpus_strategy: str = "headtail",
    paragraphs_per_article: int = 6,
    reuse_persona: Path | None = None,
    reuse_fewshot: Path | None = None,
    persona_llm_settings: Dict[str, Any] | None = None,
    gen_llm_settings: Dict[str, Any] | None = None,
    phase: str = "auto",
    heartbeat_seconds: int = 10,
    report_timing: bool = False,
    gen_retries: int = 2,
    gen_fallback_gpu_layers: int = 45,
    gen_fallback_batch: int = 512,
    max_wall_seconds: int = 1200,
    run_id: str | None = None,
    resume_run_id: str | None = None,
    long_form: bool = False,
    target_chars_min: int = 3000,
    target_chars_max: int = 4000,
    expand_retries: int = 1,
    expand_mode: str = "append",
    auto_revise: bool = True,
) -> Dict[str, Path]:
    paths = ensure_data_dirs(DATA_DIR)
    run_identifier = resume_run_id or run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = paths["outputs"] / run_identifier
    log_file = run_dir / "logs.txt"
    success_file = run_dir / "success_themes.txt"
    failed_file = run_dir / "failed_themes.txt"

    current_phase = {"name": "persona"}

    def log(level: str, phase_name: str, message: str) -> None:
        _log_line(log_file, level, phase_name, message)

    def get_phase() -> str:
        return current_phase["name"]

    start_time = time.time()
    heartbeat = Heartbeat(heartbeat_seconds, get_phase, lambda msg: log("INFO", get_phase(), msg), start_time)
    heartbeat.start()
    outputs: Dict[str, Path] = {"run_dir": run_dir}
    persona_elapsed = 0
    generate_elapsed = 0
    eval_elapsed = 0
    revise_elapsed = 0

    def set_phase(name: str) -> None:
        current_phase["name"] = name

    def timing(label: str, start: float) -> None:
        if report_timing:
            elapsed = int(time.time() - start)
            log("INFO", get_phase(), f"timing: {label} elapsed={elapsed}s")

    def append_line(file_path: Path, text: str) -> None:
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def wall_guard(point: str) -> None:
        if _check_wall(start_time, max_wall_seconds):
            log("ERROR", get_phase(), f"max wall clock exceeded at {point}")
            raise TimeoutError(f"Max wall clock exceeded at {point}")

    persona_text = ""
    persona_path = paths["personas"] / "persona.yaml"
    fewshot_text = ""
    fewshot_path = paths["fewshot"] / "fewshot.json"
    articles_blob = ""
    source_urls_text = ""

    try:
        wall_guard("start")
        if phase != "generate":
            set_phase("persona")
            log("INFO", "persona", f"phase start: persona run_id={run_identifier}")
            for u in urls:
                if "note.com" not in u:
                    log("WARN", "persona", f"Non-note domain URL detected: {u}")
            corpus_paths = fetch_and_extract(urls, paths["raw_html"], paths["corpus"])
            article_texts = read_texts(corpus_paths)
            if len(urls) < min_urls:
                log("WARN", "persona", f"URL count low: {len(urls)} (<{min_urls})")
            if corpus_strategy == "paragraphs":
                articles_blob, clipped, picked = build_corpus_paragraphs(
                    article_texts, max_corpus_chars=max_corpus_chars, paragraphs_per_article=paragraphs_per_article
                )
                log("INFO", "persona", f"corpus strategy=paragraphs, selected_paragraphs={picked}")
            else:
                articles_blob, clipped = clip_articles_headtail(article_texts, max_corpus_chars=max_corpus_chars)
                log("INFO", "persona", "corpus strategy=headtail")
            if clipped:
                log("WARN", "persona", f"articles_text clipped at {max_corpus_chars} chars")
            source_urls_text = "\n".join(urls)

            persona_start = time.time()
            if reuse_persona:
                persona_path = Path(reuse_persona)
                persona_text = persona_path.read_text(encoding="utf-8")
                persona_text = ensure_writing_scope_block(persona_text)
                persona_path.write_text(persona_text, encoding="utf-8")
                log("INFO", "persona", f"persona reused from {persona_path}")
            else:
                persona_llm = LocalLLM(model_path=model_path, **(persona_llm_settings or {}))
                persona_prompt = (
                    load_prompt("persona_summarize")
                    .replace("{{articles_text}}", articles_blob)
                    .replace("{{source_urls}}", source_urls_text)
                )
                persona_text = persona_llm.chat(
                system_prompt="Persona summarizer returning YAML."
                    user_prompt=persona_prompt,
                )
                persona_text = ensure_writing_scope_block(persona_text)
                _write_and_mirror(persona_text.strip() + "\n", run_dir / "persona.yaml", persona_path)
                log("INFO", "persona", f"persona written to {run_dir / 'persona.yaml'}")
            timing("persona", persona_start)
            persona_elapsed = int(time.time() - persona_start)
            outputs["persona"] = persona_path

            if phase == "persona":
                log("INFO", "persona", f"phase end: persona run_id={run_identifier}")
                return outputs
        else:
            set_phase("generate")
            log("INFO", "generate", f"phase start: generate(run-resume) run_id={run_identifier}")
            if reuse_persona:
                persona_path = Path(reuse_persona)
                persona_text = ensure_writing_scope_block(persona_path.read_text(encoding="utf-8"))
            else:
                log("ERROR", "generate", "generate phase requires --reuse-persona")
                raise ValueError("generate phase requires persona")
            source_urls_text = ""
            articles_blob = ""

        wall_guard("before fewshot")

        if reuse_fewshot:
            fewshot_path = Path(reuse_fewshot)
            fewshot_text = fewshot_path.read_text(encoding="utf-8")
            fewshot_json = json.loads(fewshot_text)
            log("INFO", "generate", f"fewshot reused from {fewshot_path}")
        elif phase == "generate":
            log("WARN", "generate", "generate phase without reuse-fewshot: proceeding without snippets")
            fewshot_json = {"snippets": []}
            fewshot_text = json.dumps(fewshot_json, ensure_ascii=False, indent=2)
        else:
            fewshot_llm = LocalLLM(model_path=model_path, **(persona_llm_settings or {}))
            fewshot_prompt = (
                load_prompt("fewshot_select")
                .replace("{{persona_yaml}}", persona_text)
                .replace("{{articles_text}}", articles_blob)
                .replace("{{source_urls}}", source_urls_text)
            )
            fewshot_raw = fewshot_llm.chat(
            system_prompt="Fewshot selector returning JSON snippets."
                user_prompt=fewshot_prompt,
            )
            fewshot_json = parse_json_with_llm_retry(fewshot_raw, llm=fewshot_llm, kind="fewshot")
            if "snippets" not in fewshot_json:
                fewshot_json["snippets"] = []
            fewshot_text = json.dumps(fewshot_json, ensure_ascii=False, indent=2)
            _write_and_mirror(fewshot_text + "\n", run_dir / "fewshot.json", fewshot_path)
            log("INFO", "generate", f"fewshot written to {run_dir / 'fewshot.json'}")
        outputs["fewshot"] = fewshot_path

        wall_guard("before generate loop")
        generate_start = time.time()
        draft_template = load_prompt("generate")
        eval_template = load_prompt("eval")
        revise_template = load_prompt("revise")
        expand_template = load_prompt("expand")

        def make_llm(settings: Dict[str, Any]) -> LocalLLM:
            return LocalLLM(model_path=model_path, **settings)

        def save_output(name: str, content: str) -> Path:
            run_target = run_dir / name
            compat_target = paths["outputs"] / name
            _write_and_mirror(content.strip() + "\n", run_target, compat_target)
            return run_target

        def evaluate_text(current_llm: LocalLLM, draft_text: str, retry_index: int) -> Dict[str, Any]:
            nonlocal eval_elapsed
            eval_start = time.time()
            eval_prompt = (
                eval_template.replace("{{persona_yaml}}", persona_text)
                .replace("{{fewshot_json}}", fewshot_text)
                .replace("{{draft_text}}", draft_text)
            )
            eval_raw = current_llm.chat(
            system_prompt="Style consistency evaluator returning strict JSON."
                user_prompt=eval_prompt,
            )
            eval_json_local = parse_json_with_llm_retry(eval_raw, llm=current_llm, kind="eval")
            if "mimic_score" not in eval_json_local:
                eval_json_local["mimic_score"] = 0
            checklist = eval_json_local.get("checklist") or []
            failed_items = [c for c in checklist if isinstance(c, dict) and c.get("pass") is False]
            failed_items = [c for c in checklist if isinstance(c, dict) and c.get("pass") is False]
            prioritized = [f"Fix first: {c.get('item','unknown')}" for c in failed_items]
            if not isinstance(existing_fixes, list):
                existing_fixes = [str(existing_fixes)]
            if prioritized:
                eval_json_local["fix_instructions"] = prioritized + existing_fixes
            else:
                eval_json_local["fix_instructions"] = existing_fixes
            eval_path = save_output(f"eval_{retry_index}.json", json.dumps(eval_json_local, ensure_ascii=False, indent=2))
            outputs[f"eval_{retry_index}"] = eval_path
            eval_elapsed += int(time.time() - eval_start)
            return eval_json_local

        def generate_text(current_llm: LocalLLM, retry_index: int, last_eval: Dict[str, Any], last_draft_text: str) -> str:
            nonlocal revise_elapsed
            draft_prompt = (
                draft_template.replace("{{persona_yaml}}", persona_text)
                .replace("{{fewshot_json}}", fewshot_text)
                .replace("{{theme}}", theme)
            )
            if retry_index > 0 and last_eval.get("fix_instructions"):
                revise_start = time.time()
                fix_items = last_eval.get("fix_instructions") or []
                if not isinstance(fix_items, (list, tuple)):
                    fix_items = [str(fix_items)]
                fixes = "\n".join(f"- {inst}" for inst in fix_items)
                revise_prompt = (
                    revise_template.replace("{{persona_yaml}}", persona_text)
                    .replace("{{fewshot_json}}", fewshot_text)
                    .replace("{{draft_text}}", last_draft_text)
                    .replace("{{fix_instructions}}", fixes)
                    .replace("{{theme}}", theme)
                    .replace("{{eval_json}}", json.dumps(last_eval, ensure_ascii=False))
                    .replace("{{target_chars_min}}", str(target_chars_min))
                    .replace("{{target_chars_max}}", str(target_chars_max))
                log("INFO", "generate", f"auto revise triggered: {
.join(triggers)}")
                revised = current_llm.chat(
                    system_prompt="Follow the fix instructions and persona style strictly. Rewrite in Japanese with the same content.",
                    user_prompt=revise_prompt,
                )
                revise_elapsed += int(time.time() - revise_start)
                return revised
            return current_llm.chat(
                system_prompt="Write a new Japanese article that strictly follows the given persona and fewshot style.",
                user_prompt=draft_prompt,
            )

        def maybe_expand(current_llm: LocalLLM, draft_text: str, draft_index: int) -> Tuple[str, int]:
            char_count = len(draft_text)
            log("INFO", "generate", f"char_count={char_count} target={target_chars_min}-{target_chars_max}")
                    system_prompt="Structure-focused rewriter: improve headings, rhythm, reduce repetition; keep meaning."
            expanded_index = draft_index
            for expand_try in range(max(expand_retries, 0)):
                if char_count >= target_chars_min:
                    break
                wall_guard(f"expand attempt {expand_try}")
                expand_prompt = (
                    expand_template.replace("{{persona_yaml}}", persona_text)
                    .replace("{{theme}}", theme)
                    .replace("{{current_draft}}", expanded_text)
                    .replace("{{target_chars_min}}", str(target_chars_min))
                    .replace("{{target_chars_max}}", str(target_chars_max))
                )
                expanded_raw = current_llm.chat(
                    system_prompt="Append-only Japanese writer who keeps persona style. Do not rewrite existing text.",
                    user_prompt=expand_prompt,
                )
                addition = expanded_raw.strip()
                if not addition:
                    log("WARN", "generate", "expand returned empty; skipping append")
                    continue
                if expand_mode == "append":
                    expanded_text = expanded_text.rstrip() + "\n\n" + addition
                else:
                    expanded_text = addition
                expanded_index += 1
                new_path = save_output(f"draft_{expanded_index}.md", expanded_text)
                outputs[f"draft_{expanded_index}"] = new_path
                char_count = len(expanded_text)
                log("INFO", "generate", f"expanded draft_{expanded_index} char_count={char_count}")
            if char_count < target_chars_min:
                log("WARN", "generate", f"draft below target after expand attempts (len={char_count})")
            return expanded_text, expanded_index

        attempt_settings = [
            gen_llm_settings or {},
            {"n_gpu_layers": gen_fallback_gpu_layers, "n_batch": gen_fallback_batch},
            {"n_gpu_layers": 30, "n_batch": 256},
        ]

        success = False
        last_eval: Dict[str, Any] = {}
        last_draft_text = ""
        last_gen_llm: LocalLLM | None = None
        last_draft_index = 0

        for retry_counter in range(max(gen_retries, 0) + 1):
            wall_guard(f"generate attempt {retry_counter}")
            settings_idx = min(retry_counter, len(attempt_settings) - 1)
            current_settings = attempt_settings[settings_idx]
            try:
                gen_llm = make_llm(current_settings)
                last_gen_llm = gen_llm
                last_draft_text = generate_text(gen_llm, retry_counter, last_eval, last_draft_text)
                draft_index = retry_counter
                draft_path = save_output(f"draft_{draft_index}.md", last_draft_text)
                outputs[f"draft_{draft_index}"] = draft_path
                last_draft_text, draft_index = maybe_expand(gen_llm, last_draft_text, draft_index)
                last_draft_index = draft_index
                last_eval = evaluate_text(gen_llm, last_draft_text, draft_index)
                if last_eval.get("mimic_score", 0) < score_threshold:
                    log("WARN", "generate", f"mimic_score below threshold ({last_eval.get('mimic_score',0)} < {score_threshold}), regenerating once.")
                    last_draft_text = generate_text(gen_llm, retry_counter + 100, last_eval, last_draft_text)
                    draft_index = retry_counter + 100
                    draft_path = save_output(f"draft_{draft_index}.md", last_draft_text)
                    outputs[f"draft_{draft_index}"] = draft_path
                    last_draft_text, draft_index = maybe_expand(gen_llm, last_draft_text, draft_index)
                    last_draft_index = draft_index
                    last_eval = evaluate_text(gen_llm, last_draft_text, draft_index)
                if last_eval.get("mimic_score", 0) >= score_threshold:
                    success = True
                    break
            except Exception as exc:  # pragma: no cover - runtime
                log("ERROR", "generate", f"generate attempt failed (retry={retry_counter}, settings_idx={settings_idx}): {exc}")

        if auto_revise and last_eval:
            checklist = last_eval.get("checklist") or []
            def _has_fail(keyword: str) -> bool:
                for c in checklist:
                    if isinstance(c, dict) and c.get("pass") is False and keyword in str(c.get("item", "")):
                        return True
                return False
            triggers = []
            score_val = last_eval.get("mimic_score", 0)
            if score_val < score_threshold:
                triggers.append("score")
            if _has_fail("linebreak"):
                triggers.append("linebreak")
            if _has_fail("heading") or _has_fail("structure"):
                triggers.append("heading/structure")
            if triggers and last_gen_llm:
                log("INFO", "generate", f"auto revise triggered: {', '.join(triggers)}")
                draft_index = last_draft_index + 1
                fix_items = last_eval.get("fix_instructions") or []
                if not isinstance(fix_items, (list, tuple)):
                    fix_items = [str(fix_items)]
                fixes = "\n".join(f"- {inst}" for inst in fix_items)
                revise_prompt = (
                    revise_template.replace("{{persona_yaml}}", persona_text)
                    .replace("{{fewshot_json}}", fewshot_text)
                    .replace("{{draft_text}}", last_draft_text)
                    .replace("{{fix_instructions}}", fixes)
                    .replace("{{theme}}", theme)
                    .replace("{{eval_json}}", json.dumps(last_eval, ensure_ascii=False))
                    .replace("{{target_chars_min}}", str(target_chars_min))
                    .replace("{{target_chars_max}}", str(target_chars_max))
                )
                revised_text = last_gen_llm.chat(
                    system_prompt="Structure-focused Japanese rewriter. Improve headings, rhythm, reduce repetition without changing meaning.",
                    user_prompt=revise_prompt,
                )
                last_draft_text = revised_text
                draft_path = save_output(f"draft_{draft_index}.md", last_draft_text)
                outputs[f"draft_{draft_index}"] = draft_path
                last_draft_index = draft_index
                if len(last_draft_text) < target_chars_min and expand_retries > 0:
                    last_draft_text, last_draft_index = maybe_expand(last_gen_llm, last_draft_text, last_draft_index)
                last_eval = evaluate_text(last_gen_llm, last_draft_text, last_draft_index)
                score_val = last_eval.get("mimic_score", 0)
                if score_val >= score_threshold:
                    success = True
        if success:
            append_line(success_file, theme)
            log("INFO", "generate", f"generation success for theme='{theme}'")
        else:
            append_line(failed_file, theme)
            log("ERROR", "generate", f"generation failed after retries for theme='{theme}'")

        generate_elapsed = int(time.time() - generate_start)
        elapsed_all = int(time.time() - start_time)
        log("INFO", "generate", f"phase end: generate run_id={run_identifier}, elapsed={elapsed_all}s, outputs_dir={run_dir}")
        if report_timing:
            log(
                "INFO",
                "summary",
                f"total={elapsed_all}s persona={persona_elapsed}s generate={generate_elapsed}s eval={eval_elapsed}s revise={revise_elapsed}s",
            )
        if not success:
            raise RuntimeError("generation failed after retries")
        return outputs
    finally:
        heartbeat.stop()


