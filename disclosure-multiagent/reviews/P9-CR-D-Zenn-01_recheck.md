# P9-CR-D-Zenn-01 再CR: Phase1 記事（article_disclosure_phase1_draft.md）修正確認

**レビュアー**: 足軽8
**対象**: `docs/article_disclosure_phase1_draft.md`（修正者: 足軽7）
**実施日**: 2026-03-09
**元CR**: reviews/P9-CR-D-Zenn-01.md（⚠️条件付き承認・必須修正5件）

---

## 総合判定

**✅ 正式承認（M1〜M5全件解消・再CR不要）**

---

## 必須修正5件の解消確認

### M1: `_keyword_check` / `analyze_gap_with_llm` / `GapVerdict` — 擬似コード注記

**元指摘**: 実装に存在しない関数名がコードブロックに記載されており、コピペでエラーが発生する

**修正確認**:

```markdown
# Section 3.3（記事 L163）
> ※ 以下は設計概念を示す擬似コードです。実際のキーワード判定は `judge_gap()` 関数
>（`scripts/m3_gap_analysis_agent.py`）の内部処理として実装されており、`_keyword_check`
> という名前の独立した公開関数は存在しません。

# Section 3.3（記事 L180）
> ※ 以下は設計概念を示す擬似コードです。実際のLLM判定は `judge_gap()` 関数
>（`scripts/m3_gap_analysis_agent.py` L325）に統合されており、`analyze_gap_with_llm`
> という独立した関数は存在しません。

# 実装シグネチャも明示（記事 L184）
# 実装シグネチャ: judge_gap(section, disclosure_item, law_entry, client, use_mock=False)
```

「擬似コード」注記 + 実際の関数名（`judge_gap()`）参照 ✅

**判定: ✅ 解消**

---

### M2: `USE_MOCK_LLM` デフォルト値 `"true"` → `""`（本番モード）

**元指摘**: 記事は `"true"` がデフォルトと示唆、実装は `""` でデフォルト本番モード

**修正確認**:

```python
# 記事 L185
use_mock = os.environ.get("USE_MOCK_LLM", "").lower() in ("true", "1", "yes")
```

```
# 記事 L190（解説文）
`USE_MOCK_LLM`環境変数は**デフォルト未設定（本番モード）**です。テスト時は`USE_MOCK_LLM=true`を
明示設定することでAPIキーなしで全207件のテストが通ります。
```

- `os.environ.get("USE_MOCK_LLM", "")`: デフォルト空文字 → `false` 相当 ✅
- 「デフォルト未設定（本番モード）」の明示説明 ✅

**判定: ✅ 解消**

---

### M3: `FEW_SHOT_EXAMPLES` 構造の修正

**元指摘**: 記事が `{level: {requirement, example}}` 構造、実装は `{section_name: {level: text}}` 構造

**修正確認**:

```python
# 記事 L211-229
FEW_SHOT_EXAMPLES = {
    "従業員給与等の決定に関する方針": {   # ← section_name をキー
        "松": "...",                       # ← {level: text} 構造
        "竹": "...",
        "梅": "...",
    },
    "GHG排出量（Scope1・Scope2）の開示": {
        "松": "...",
        ...
    },
    # （以下、各セクション名に対する松竹梅の例文が続く）
}
```

`{section_name: {level: text}}` の正しい構造に修正済み ✅

**判定: ✅ 解消**

---

### M4: `generate_proposal()` シグネチャ修正

**元指摘**: 記事が `generate_proposal(gap_item, level)` の2引数、実装は5引数（section_name, change_type, law_summary, law_id, level）

**修正確認**:

```python
# 記事 L232-238
def generate_proposal(
    section_name: str,
    change_type: str,
    law_summary: str,
    law_id: str,
    level: str,
    system_prompt: Optional[str] = None,
) -> str:
```

実装と一致する5引数（+ オプション `system_prompt`）シグネチャに修正済み ✅

**判定: ✅ 解消**

---

### M5: `toyota_2025.pdf` → プレースホルダ + 注釈追加

**元指摘**: リポに含まれない `toyota_2025.pdf` を直接パス指定、FileNotFoundErrorが発生

**修正確認**:

```bash
# 記事 L288-296
# ※ 有報PDFは各自でご用意ください（本リポジトリには含まれていません）
# EDINETから取得した有報PDF等を任意のパスに配置して指定してください
python3 scripts/run_e2e.py \
    "/path/to/your/annual_report.pdf" \
    --company-name "トヨタ自動車" \
    --fiscal-year 2025 \
    --level 竹
```

- `toyota_2025.pdf` → `/path/to/your/annual_report.pdf`（プレースホルダ）✅
- 「本リポジトリには含まれていません」注釈追加 ✅

**判定: ✅ 解消**

---

## 推奨修正の残存確認（修正不要・参考）

| ID | 内容 | 状況 |
|----|------|------|
| R1 | `extract_sections()` への注釈 | 未対応（L108）。推奨のため再修正不要 |
| R2 | 「13のキーワード」→ HEADING_PATTERNSは8パターン | 未対応（L128）。推奨のため再修正不要 |
| R3 | `_is_streamlit_running()` は `scripts/app.py` に実装 | 未対応（L265）。推奨のため再修正不要 |
| R4 | toyota_2025.pdf 未同梱注記 | M5修正に含まれ解消済み ✅ |
| R5 | テスト件数「207件」→「293件+25subtests」へ更新 | 未対応（L46/L443）。推奨のため再修正不要 |
| R6 | YAMLフィールド名を実装と一致 | 未対応（L134〜）。推奨のため再修正不要 |

R1〜R3・R5〜R6は推奨修正のため再修正不要。R4はM5対応に含まれ解消済み。

---

## 知見共有

- **擬似コード注記パターン**: 設計概念を説明するコードブロックに「※ 以下は設計概念を示す擬似コードです。実際の実装は `xxx()` 関数...」という注記を追加する方式は、コピペエラーを防ぎつつ概念説明を維持する優れたパターン
- **環境変数デフォルト値の明示**: コードスニペット内の `get("KEY", "")` に加えて、直後の文章で「デフォルト未設定（本番モード）」と明示することで読者の誤解を防止できる

*再CR: 足軽8 / P9-CR-D-Zenn-01_recheck / 2026-03-09*
