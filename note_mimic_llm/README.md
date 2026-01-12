# note_mimic_llm

## Running from PowerShell vs .bat (Important)
- .bat files use %URLS% style variables
- PowerShell does NOT expand %URLS%
- When running run.py directly in PowerShell, always write:
  --urls data/urls/author_x.txt
- Recommended usage for beginners: use the .bat files

## Recommended flow (8GB VRAM)
- 1) Build persona fast (light GPU): `bat\01_build_persona_fast.bat`
- 2) Generate one article on GPU: `bat\02_generate_one_gpu.bat`
- 3) Batch themes on GPU: `bat\03_generate_batch_gpu.bat`
- Heartbeat and phase logs keep printing during long runs; timing summary with `--report-timing`.
- Outputs per run_id: `data/outputs/YYYYMMDD-HHMMSS/` (persona.yaml, fewshot.json, draft_*.md, eval_*.json, logs.txt, success_themes.txt, failed_themes.txt). Compatibility copies still land in `data/outputs/`.
- shared memory is not VRAM; keep GPU settings conservative on 8GB cards.
- Persona phase does not require a theme.
- Long-form: drafts target 3000-4000 Japanese chars; if short, an append-only expand step runs automatically.
- If eval shows low score or structure issues, one auto-revise pass runs to fix headings/paragraph rhythm (can disable with --no-auto-revise).

## GPU acceleration (RTX 4060)
- CUDA wheel install (cu121 example):
  ```
  pip uninstall -y llama-cpp-python
  pip install -U llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
  ```
- Usage options:
  - (A) .bat with env vars
    ```
    set "N_GPU_LAYERS=35"
    set "N_BATCH=512"
    bat\01_build_persona.bat
    ```
  - (B) PowerShell with env vars
    ```
    $env:N_GPU_LAYERS="35"
    $env:N_BATCH="512"
    python run.py ...
    ```
  - (C) CLI overrides
    ```
    python run.py --n-gpu-layers 35 --n-batch 512 ...
    ```

## CLI highlights (phase-specific GPU + observability)
- Persona defaults (8GB-safe): `--persona-n-gpu-layers 30 --persona-n-batch 512`
- Generate defaults (full GPU): `--gen-n-gpu-layers 55 --gen-n-batch 768`
- Phases: `--phase persona|generate|auto` (auto = full pipeline)
- Heartbeat/logging: `--heartbeat-seconds 10`, `--report-timing`
- Wall clock guard: `--max-wall-seconds 1200`
- Run reuse/resume: `--resume-run-id <id>`, `--reuse-persona ...`, `--reuse-fewshot ...`

## Simple SOP (beginner)
0) Prepare files (first time only)
- data\urls\author_x.txt (one URL per line)
- data\themes\themes_x.txt (one theme per line, file must exist)

1) Build persona (not every time)
- Double-click: bat\01_build_persona_fast.bat
- Output: data\personas\persona.yaml

2) Generate one article
- Double-click: bat\02_generate_one_gpu.bat
- Enter theme
- Open latest: data\outputs\<run_id>\draft_0.md

3) Batch generate
- Double-click: bat\03_generate_batch_gpu.bat
- Check:
  - data\outputs\<run_id>\success_themes.txt
  - data\outputs\<run_id>\failed_themes.txt
  - data\outputs\<run_id>\logs.txt

Notes:
- Use .bat files (do not copy into PowerShell).
- Persona phase does not require a theme.

## Long-form generation (3000-4000 chars)
- Default target: 3000-4000 Japanese characters.
- If a draft is shorter than the minimum, an append-only expand step runs (no rewrite; it only adds paragraphs). Each expand saves a new draft file.
- Headings must be Japanese (e.g., はじめに/本論/分析/おわりに); English headings are not allowed.
- Outputs live under `data/outputs/<run_id>/draft_*.md` and `eval_*.json` after expansion.
- If mimic_score is low or checklist fails (改行頻度/見出し), one auto-revise pass runs, then eval is rerun (draft_2.md / eval_2.json, etc.). Use `--no-auto-revise` to disable.
## GPU acceleration (RTX 4060)
- CUDA wheel install (cu121 example):
  ```
  pip uninstall -y llama-cpp-python
  pip install -U llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
  ```
- Usage options:
  - (A) .bat with env vars
    ```
    set "N_GPU_LAYERS=35"
    set "N_BATCH=512"
    bat\01_build_persona.bat
    ```
  - (B) PowerShell with env vars
    ```
    $env:N_GPU_LAYERS="35"
    $env:N_BATCH="512"
    python run.py ...
    ```
  - (C) CLI overrides
    ```
    python run.py --n-gpu-layers 35 --n-batch 512 ...
    ```
