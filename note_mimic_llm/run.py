import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.append(str(SCRIPT_DIR / "src"))

from src.pipeline import run_pipeline, load_urls, preflight_check  # type: ignore  # noqa: E402


DEFAULT_URL_FILE = SCRIPT_DIR / "data/urls/author_x.txt"
DEFAULT_THEME = "note�L���̕��̂�͕킵���V�K�h���t�g"
DEFAULT_SCORE_THRESHOLD = 0.70
DEFAULT_MAX_RETRIES = 2
DEFAULT_MIN_URLS = 3
DEFAULT_MAX_CORPUS_CHARS = 30000
DEFAULT_CORPUS_STRATEGY = "headtail"
DEFAULT_PARAGRAPHS_PER_ARTICLE = 6


def generate_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="note URL�Q���當�̃y���\�i��few-shot���������]�����Đ����܂ł����[�J��LLM�Ŏ��s���܂��B"
    )
    parser.add_argument("--urls", type=Path, default=None, help="URL���X�gtxt�p�X (1�s1URL, #�ŃR�����g)")
    parser.add_argument("--theme", type=str, default=None, help="��������L���e�[�}/����")
    parser.add_argument("--dry-run", action="store_true", help="preflight�̂ݎ��s�i�擾�ELLM�Ȃ��j")
    parser.add_argument("--preflight-only", action="store_true", help="preflight�̂ݎ��s�idry-run�Ɠ��`�j")
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD, help="�͕�X�R�A臒l (0-1 scale)")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES, help="���e���g���C�� (persona+generate loop)")
    parser.add_argument("--min-urls", type=int, default=DEFAULT_MIN_URLS, help="URL�ŏ������̖ڈ� (WARN�̂�)")
    parser.add_argument("--max-corpus-chars", type=int, default=DEFAULT_MAX_CORPUS_CHARS, help="�L���e�L�X�g�̍ő�A�����ihead/tail���o��ɃN���b�v�j")
    parser.add_argument(
        "--corpus-strategy",
        choices=["headtail", "paragraphs"],
        default=DEFAULT_CORPUS_STRATEGY,
        help="�R�[�p�X�\�z����: headtail(�f�t�H���g) or paragraphs(��\�i���X�R�A�����O)",
    )
    parser.add_argument(
        "--paragraphs-per-article",
        type=int,
        default=DEFAULT_PARAGRAPHS_PER_ARTICLE,
        help="paragraphs�헪�ŋL�����Ƃɍ̗p����i����",
    )
    parser.add_argument("--reuse-persona", type=Path, help="����persona.yaml���ė��p���Đ��� (persona�������X�L�b�v)")
    parser.add_argument("--reuse-fewshot", type=Path, help="����fewshot.json���ė��p�i�ȗ����͍Ē��o�j")
    parser.add_argument("--long-form", action="store_true", help="�����������Ƃ��̃q���g��\���i�������e�͓����j")
    parser.add_argument("--n-gpu-layers", type=int, default=None, help="N_GPU_LAYERS override for all phases (compat)")
    parser.add_argument("--n-batch", type=int, default=None, help="N_BATCH override for all phases (compat)")
    parser.add_argument("--persona-n-gpu-layers", type=int, default=30, help="persona phase N_GPU_LAYERS")
    parser.add_argument("--persona-n-batch", type=int, default=512, help="persona phase N_BATCH")
    parser.add_argument("--gen-n-gpu-layers", type=int, default=55, help="generate phase N_GPU_LAYERS")
    parser.add_argument("--gen-n-batch", type=int, default=768, help="generate phase N_BATCH")
    parser.add_argument("--phase", choices=["auto", "persona", "generate"], default="auto", help="pipeline phase to run")
    parser.add_argument("--heartbeat-seconds", type=int, default=10, help="heartbeat interval seconds")
    parser.add_argument("--report-timing", action="store_true", help="report timing summary at end")
    parser.add_argument("--gen-retries", type=int, default=2, help="generate/eval/revise retry attempts on failure")
    parser.add_argument("--gen-fallback-gpu-layers", type=int, default=45, help="fallback N_GPU_LAYERS after failure")
    parser.add_argument("--gen-fallback-batch", type=int, default=512, help="fallback N_BATCH after failure")
    parser.add_argument("--max-wall-seconds", type=int, default=1200, help="max wall clock seconds before abort")
    parser.add_argument("--resume-run-id", type=str, help="resume an existing run_id (generate phase)")
    parser.add_argument("--target-chars-min", type=int, default=3000, help="minimum target characters for long-form output")
    parser.add_argument("--target-chars-max", type=int, default=4000, help="maximum target characters for long-form output")
    parser.add_argument("--expand-retries", type=int, default=1, help="number of append-only expansions when draft is short")
    parser.add_argument("--expand-mode", choices=["append", "revise"], default="append", help="append-only or rewrite expand mode")
    auto_group = parser.add_mutually_exclusive_group()
    auto_group.add_argument("--auto-revise", action="store_true", help="enable auto revise pass when eval is low (default)")
    auto_group.add_argument("--no-auto-revise", action="store_true", help="disable auto revise pass when eval is low")
    args = parser.parse_args()

    url_path = args.urls
    if url_path is None:
        if DEFAULT_URL_FILE.exists():
            print(f"[INFO] --urls not provided; defaulting to {DEFAULT_URL_FILE}")
            url_path = DEFAULT_URL_FILE
        else:
            print("[error] --urls not provided and default URL file is missing.")
            print("Prepare a URL file or pass one explicitly, e.g., --urls data/urls/author_x.txt")
            return 1

    url_arg_str = str(url_path)
    if "%" in url_arg_str:
        print(f"ERROR: URL path looks like an unexpanded batch variable: {url_arg_str}")
        print("If you are using PowerShell, specify the path directly:")
        print("--urls data/urls/author_x.txt")
        print("If you are using .bat, this is OK.")
        return 1

    args.urls = url_path

    # Phase rules
    if args.phase == "generate" and not args.reuse_persona:
        print("[ERROR] --phase generate requires --reuse-persona")
        return 1

    if args.phase == "persona" and args.theme is None:
        args.theme = "(persona_only)"
    elif args.theme is None:
        args.theme = DEFAULT_THEME

    if args.n_gpu_layers is not None:
        os.environ["N_GPU_LAYERS"] = str(args.n_gpu_layers)
    if args.n_batch is not None:
        os.environ["N_BATCH"] = str(args.n_batch)

    # Load URLs unless phase generate only with resume and no URLs needed
    urls: list[str] = []
    if args.phase != "generate" or not args.resume_run_id:
        try:
            urls = load_urls(args.urls)
        except FileNotFoundError as exc:
            print(f"[error] {exc}")
            print("data/urls/author_x.txt ��p�ӂ��Ă��������B")
            return 1

    urls_filtered = urls if urls else []
    preflight_ok = True
    if args.phase != "generate":
        preflight_ok, urls_filtered = preflight_check(
            urls=urls_filtered,
            url_file=args.urls,
            min_urls=args.min_urls,
            n_ctx_hint=None,
            model_path=None,
            reuse_persona=args.reuse_persona,
            reuse_fewshot=args.reuse_fewshot,
        )
    if args.long_form:
        print("[INFO] Long-form hint: use specific, multi-angle themes to encourage depth (e.g., 'The cognitive load of endless AI suggestions' instead of 'about AI').")
    if args.dry_run or args.preflight_only:
        return 0 if preflight_ok else 1
    if not preflight_ok:
        return 1

    persona_settings = {
        "n_gpu_layers": args.n_gpu_layers if args.n_gpu_layers is not None else args.persona_n_gpu_layers,
        "n_batch": args.n_batch if args.n_batch is not None else args.persona_n_batch,
    }
    gen_settings = {
        "n_gpu_layers": args.n_gpu_layers if args.n_gpu_layers is not None else args.gen_n_gpu_layers,
        "n_batch": args.n_batch if args.n_batch is not None else args.gen_n_batch,
    }
    auto_revise = True
    if args.no_auto_revise:
        auto_revise = False
    elif args.auto_revise:
        auto_revise = True

    run_id = args.resume_run_id if args.resume_run_id else generate_run_id()

    try:
        outputs = run_pipeline(
            urls=urls_filtered,
            theme=args.theme,
            url_file=args.urls,
            score_threshold=args.score_threshold,
            max_retries=args.max_retries,
            max_corpus_chars=args.max_corpus_chars,
            min_urls=args.min_urls,
            corpus_strategy=args.corpus_strategy,
            paragraphs_per_article=args.paragraphs_per_article,
            reuse_persona=args.reuse_persona,
            reuse_fewshot=args.reuse_fewshot,
            persona_llm_settings=persona_settings,
            gen_llm_settings=gen_settings,
            phase=args.phase,
            heartbeat_seconds=args.heartbeat_seconds,
            report_timing=args.report_timing,
            gen_retries=args.gen_retries,
            gen_fallback_gpu_layers=args.gen_fallback_gpu_layers,
            gen_fallback_batch=args.gen_fallback_batch,
            max_wall_seconds=args.max_wall_seconds,
            run_id=run_id,
            resume_run_id=args.resume_run_id,
            long_form=args.long_form,
            target_chars_min=args.target_chars_min,
            target_chars_max=args.target_chars_max,
            expand_retries=args.expand_retries,
            expand_mode=args.expand_mode,
            auto_revise=auto_revise,
        )
    except TimeoutError as exc:
        print(f"[ERROR] {exc}")
        return 2
    except Exception as exc:  # pragma: no cover - runtime dependent
        print(f"[ERROR] pipeline failed: {exc}")
        return 1

    print("Pipeline finished. Outputs:")
    for key, value in outputs.items():
        print(f" - {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
