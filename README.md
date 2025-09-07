# Fixed Asset Advisor (Hackathon Submission)

- **Demo (Cloud Run)**: <YOUR_CLOUD_RUN_URL>
- **Tagged Release**: https://github.com/Majiro-ns/fixedassets/releases/tag/useful-life-merge
- **Primary Branch**: `hackathon-final`

## Quickstart (Local)
```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r fixed_asset_classifier/requirements.txt
python scripts/generate_golden.py
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest -q tests/test_snapshot.py
```

### What to look at

Input PDF: fixed_asset_classifier/input_pdfs/demo_estimate.pdf

Golden output: tests/golden/demo_estimate.snapshot.json

Useful life resolver: fixed_asset_classifier/useful_life_excel.py + useful_life.xlsx

## Useful Life レイヤー（Excel 連携）

### ワークブック仕様
- ファイル: `useful_life.xlsx`（リポジトリ直下）
- シート:
  - `life_table` … 必須カラム: `category`, `tax_useful_life`, `book_useful_life_default`, `notes`
  - `bias_rules` … 必須カラム: `rule_name`, `kw_include`, `kw_exclude`, `delta_years`, `book_min`, `book_max`
- 既定カテゴリ（例）:
  - PC: book=4, tax=4
  - Server: book=5, tax=5
  - Building附属設備: book=15, tax=15
  - Software: book=5, tax=5

### ローダ（`fixed_asset_classifier/useful_life_excel.py`）
- `UsefulLifeResolver(xlsx_path=...)`
- `resolve(category: str | None, description: str) -> dict`
  - 返却例:
    ```json
    {
      "useful_life": 4,
      "tax_useful_life": 4,
      "basis": "life_table|bias_rules",
      "notes": "…",
      "life_adjustments": []
    }
    ```
- `bias_rules` が存在しない／読み込めない場合でもエラーにせず、空 DataFrame で継続する防御実装あり。

### ワークブック修復（確実な実行手順）
- Windows 環境でコマンド連結やクォート解釈に問題がある場合は、**Python スクリプトを絶対パスで直接実行**する。
- 例：`scripts/generate_golden.py` はそのまま `python C:\…\scripts/generate_golden.py` のように単発で実行。

### テスト
- スナップショット: `python -m pytest -q tests\test_snapshot.py`
- Useful Life の単体: `python -m pytest -q tests\test_useful_life_excel.py`

### 運用 Tips
- `.gitignore` にローカル一時ファイル（`.bat`, `.ps1`, `*.bak*` 等）を追加し、ノイズを抑制。
- コミットメッセージでシェルがクォートを壊す場合は、`.gitmsg` を用いた `git commit -F .gitmsg` 方式を採用.


```