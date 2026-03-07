# P9クロスレビューレポート: P9-CR-D-Zenn-01

| 項目 | 内容 |
|---|---|
| レビューID | P9-CR-D-Zenn-01 |
| 対象タスク | D-Zenn-01（足軽6作成） |
| 対象ファイル | docs/article_disclosure_phase1_draft.md（12,351字） |
| レビュー実施 | 足軽8 |
| レビュー日時 | 2026-03-09 |
| 最終判定 | ⚠️ **条件付き承認**（必須修正5件 → 足軽6に差し戻し） |

---

## 総評

記事の構成・法令説明・B→C戦略セクションは優秀。8,000字超・5節構成・frontmatter要件は全て充足。
しかし Section 3「実装詳細」の複数のコードスニペットが実際の実装と乖離しており、読者がコピペした場合にエラーが発生する。必須修正5件の修正後に承認。

---

## CR-5: 文章品質・要件確認（先に確認）

### 字数

```
本文字数: 12,351字（要件 8,000字）✅
```

### frontmatter

```yaml
topics: ["python", "ai", "有報", "開示"]
type: "tech"
published: false
```

✅ 要件通り（topics: ["python", "ai", "有報", "開示"]）

### 5節構成

| 節 | タイトル | 存在 |
|---|---|---|
| 1 | 課題：有報の法令対応コストと人手レビューの限界 | ✅ |
| 2 | アーキテクチャ：M1-M5パイプライン設計 | ✅ |
| 3 | 実装詳細：各エージェントの設計と工夫 | ✅ |
| 4 | デモ結果：トヨタ自動車の有報で7件を検出 | ✅ |
| 5 | B→C戦略：記事マーケティングから受託開発への導線設計 | ✅ |

**CR-5 判定: ✅ PASS**

---

## CR-1: M1-M5パイプラインの説明が実装と一致するか

### パイプライン全体図（Section 2.1）

M1→M2→M3→M4→M5のフロー図は正確 ✅

各エージェントの役割説明:
- M1: PyMuPDF → StructuredReport ✅
- M2: YAML法令DB → LawContext ✅
- M3: キーワードマッチ + LLM文脈判定 → GapAnalysisResult ✅
- M4: 松竹梅提案生成 ✅
- M5: Markdownレポート生成 ✅

### M1: `extract_sections` 関数名（Section 3.1）

記事:
```python
def extract_sections(pdf_path: str) -> StructuredReport:
```

実際の実装: `split_sections_from_text()` + `extract_report()` の構成。`extract_sections` という名前の公開関数は存在しない。
説明的な擬似コードとして提示しているが、「以下のようなコードで実装しています」という文脈で実際のコードと誤解される恐れがある。→ **R1（推奨修正）**: 関数名が実際と異なる旨を注釈するか、実際の関数名に修正する。

### M1: 「13のキーワード」（Section 3.1）

記事: 「13のキーワード（「第一部」「企業情報」「第二部」「財務情報」「人的資本」等）を正規表現でマッチング」

実際の実装: `HEADING_PATTERNS`（8パターンの正規表現）。「13のキーワード」という数値の出典が不明。
→ **R2（推奨修正）**: 「8パターンの正規表現（HEADING_PATTERNS）でセクション見出しを検出」に修正。

### 🟡 M1-UI: `_is_streamlit_running()` の実装場所（Section 3.5）

記事: 「M5: レポート統合エージェント」のコードとして `_is_streamlit_running()` を掲載

実際の実装: `scripts/app.py` に実装（M5である `m5_report_agent.py` には存在しない）

```python
# 実際の場所: scripts/app.py:390
def _is_streamlit_running() -> bool:
    """Streamlitコンテキスト内かどうかを安全に判定"""
    ...
```

→ **R3（推奨修正）**: コードの出典を `scripts/m5_report_agent.py` ではなく `scripts/app.py` と明記する。

**CR-1 判定: ✅ PASS（R1〜R3は推奨修正）**

---

## CR-2: コードスニペット検証

### 🔴 M1（必須修正）: M3コードスニペット — 関数名・型が実装と異なる

**記事の `_keyword_check` 関数（Section 3.3）:**
```python
def _keyword_check(section_text: str, keyword: str) -> bool:
    normalized_text = unicodedata.normalize("NFKC", section_text)
    ...
```

実際の実装: `_keyword_check` という関数は存在しない。M3のキーワード判定は `judge_gap` 関数（line 325）の内部で行われる。

**記事の `analyze_gap_with_llm` 関数（Section 3.3）:**
```python
def analyze_gap_with_llm(section_text: str, requirement: str) -> GapVerdict:
    ...
```

実際の実装: `analyze_gap_with_llm` は存在しない。実際の関数名は `judge_gap(section, law_entry, ...)` で引数も異なる。

**`GapVerdict` 型:**
実装には `GapVerdict` 型定義が存在しない。実際は `dict` を返す。

これらは「Section 3.3 M3: ギャップ分析エージェント（幻覚対策4層構造）」内の「第1層」「第2層」の説明コードとして提示されており、読者が実装コードとして試みた場合に `AttributeError: module 'm3_gap_analysis_agent' has no attribute '_keyword_check'` が発生する。

**修正方針**: 実際の関数名（`judge_gap`）を使うか、「※以下は説明用の擬似コードです」と明示する。

### 🔴 M2（必須修正）: `USE_MOCK_LLM` デフォルト値の誤り（Section 3.3）

**記事のコード:**
```python
USE_MOCK_LLM = os.environ.get("USE_MOCK_LLM", "true").lower() == "true"
```

**実際の実装（m3_gap_analysis_agent.py line 551）:**
```python
use_mock = os.environ.get("USE_MOCK_LLM", "").lower() in ("true", "1", "yes")
```

記事のデフォルト `"true"` と実装のデフォルト `""` (false相当) が異なる。
この誤りにより、記事を読んだ読者が「環境変数なしでもモックモードで動く」と誤解する。実際には環境変数未設定時は本番LLMモードとなり、ANTHROPIC_API_KEY がないと失敗する。

**修正方針**: デフォルト値を `""` に修正するか、「本番実行時は `USE_MOCK_LLM=false`（デフォルト）、開発時は `USE_MOCK_LLM=true` と明示的に設定してください」と注記する。

### 🔴 M3（必須修正）: `FEW_SHOT_EXAMPLES` の構造が逆（Section 3.4）

**記事のコード:**
```python
FEW_SHOT_EXAMPLES = {
    "竹": {
        "requirement": "従業員給与等の決定に関する方針",
        "example": ("当社の従業員給与は、...")
    }
}
```

**実際の実装（m4_proposal_agent.py）:**
```python
FEW_SHOT_EXAMPLES = {
    "企業戦略と関連付けた人材戦略": {
        "松": (...),
        "竹": (...),
        "梅": (...),
    },
    "従業員給与等の決定に関する方針": {
        "松": (...),
        "竹": (...),
        "梅": (...),
    },
    ...
}
```

キー順序が全く逆（記事: `{level: {requirement, example}}` / 実装: `{section_name: {level: text}}`）。記事のコードを実行するとキーエラーが発生する。

**修正方針**: 実際の構造を示すか、擬似コードである旨を明示する。

### 🔴 M4（必須修正）: `generate_proposal` のシグネチャ（Section 3.4）

**記事のコード:**
```python
def generate_proposal(gap_item: GapItem, level: ProposalLevel) -> str:
    prompt = _build_few_shot_prompt(gap_item, level, FEW_SHOT_EXAMPLES)
    ...
```

**実際の実装（m4_proposal_agent.py line 537）:**
```python
def generate_proposal(
    section_name: str,
    change_type: str,
    law_summary: str,
    law_id: str,
    level: str,
    system_prompt: Optional[str] = None,
) -> str:
```

引数の型と数が全く異なる（GapItem を渡す設計ではなく、個別フィールドを受け取る）。コピペで `TypeError` が発生する。

**修正方針**: 実際のシグネチャに修正するか、擬似コードであることを明示する。

### generate_report シグネチャ（Section 2.1 図のみ、直接的なコード例なし）

記事ではM5の `generate_report` の直接的なシグネチャ記載なし。OK ✅

### D-Zenn-02で発見した問題との照合（CR-2確認事項）

CR指示書に「generate_report()のシグネチャが実際と一致するか」とあるが、記事内にgenerate_report の呼び出しコードなし → 非該当 ✅

GapSummaryフィールドについて: 記事内に直接的なGapSummary使用コードなし → 非該当 ✅

**CR-2 判定: ⚠️ 必須修正4件（M1〜M4）**

---

## CR-3: トヨタ有報7件の実データ確認

### law_refs の実装確認

| law_ref | YAML実在 | 内容 |
|---------|---------|------|
| HC_20260220_001 | ✅ | 企業内容等の開示に関する内閣府令改正（2026年2月20日施行） |
| HC_20250421_001 | ✅ | 金融庁「人的資本の開示等に関するWG」好事例集（2025年4月） |

### 必須3件の分類確認

| # | 項目 | 根拠 | YAMLとの整合 |
|---|-----|------|------------|
| 1 | 企業戦略と関連付けた人材戦略 | HC_20260220_001 | ✅ disclosure_items[0]と一致 |
| 2 | 従業員給与等の決定に関する方針 | HC_20260220_001 | ✅ disclosure_items[1]と一致 |
| 3 | 平均年間給与の対前事業年度増減率（連結・単体） | HC_20260220_001 | ✅ disclosure_items[2]と一致 |

### 🟡 R4（推奨修正）: `toyota_2025.pdf` が存在しない

実行コマンド:
```bash
python3 scripts/run_e2e.py \
    "10_Research/samples/toyota_2025.pdf" \
    --company-name "トヨタ自動車" \
    --fiscal-year 2025 \
    --level 竹
```

`10_Research/samples/toyota_2025.pdf` は実際にはリポジトリに存在しない（著作権上の理由で含められないため）。読者がコピペで実行しても `FileNotFoundError` が発生する。

**修正方針**: 「※ toyota_2025.pdf は実際の有報PDFを用意してください（著作権上、リポジトリへの同梱不可）」という注釈を追加する。または `company_a.pdf` 等のモックPDFを使ったコマンド例に変更する。

### テスト件数の確認

記事: 「207件のテストで品質を担保（全PASS確認済み）」

実際（M1〜M5テスト実行）:
```
190 passed, 22 subtests passed in 1.09s
```

記事の「207件」は現在の M1-M5 テスト件数（190件）と一致しない。なお、全テストファイル（M6〜M9含む）での合計は異なる可能性がある。→ **R5（推奨修正）**: テスト件数を実際の数値に更新するか、「M1〜M5テスト：190件+サブテスト22件」と明記する。

**CR-3 判定: ✅ PASS（R4・R5は推奨修正）**

---

## CR-4: 法令情報の正確性

### 「企業内容等の開示に関する内閣府令改正（2026年2月）」の必須3項目

| 記事の記述 | YAMLの disclosure_items | 判定 |
|----------|------------------------|-----|
| 「従業員給与等の決定に関する方針」「平均年間給与の対前事業年度増減率」が新たに必須記載事項 | 「企業戦略と関連付けた人材戦略の記載（必須）」「従業員給与等の決定に関する方針の記載（必須）」「平均年間給与の対前事業年度増減率の記載（必須）: 連結・単体両方で開示」 | ✅ |

### Section 1.1 の法令改正記述

- 「企業内容等の開示に関する内閣府令改正（2026年2月）」: ✅ 正確（2026年2月20日施行）
- 「金融庁「人的資本の開示等に関するWG」好事例集（2025年4月）」: ✅ 正確（HC_20250421_001と一致）

### M2 YAML スニペット（Section 3.2）

記事に示されたYAMLスニペット:
```yaml
- entry_id: HC_20260220_001
  law_name: 企業内容等の開示に関する内閣府令改正（人的資本開示拡充・給与開示）
  effective_date: "2026-02-20"
  fiscal_year_applicable: 2025
  required_items:
    - keyword: "企業戦略と関連付"
      change_type: mandatory_addition
```

実際のYAML（`10_Research/law_entries_human_capital.yaml`）のスキーマ:
- `id`（記事は `entry_id`）
- `effective_from`（記事は `effective_date`）
- `disclosure_items`（記事は `required_items`）

**フィールド名が実装と異なる** — ただし、M2のYAMLスキーマはSection 3.2の説明用スニペットとして示しており、「このYAMLファイルで管理」という構造説明の意図であれば許容範囲と判断できる。

→ **R6（推奨修正）**: 実際のYAMLフィールド名（`id`, `effective_from`, `disclosure_items`）に合わせる。

**CR-4 判定: ✅ PASS（R6は推奨修正）**

---

## 指摘事項サマリー

### 必須修正（5件）

| ID | 種別 | 重大度 | 内容 | 場所 |
|---|---|---|---|---|
| M1 | **必須修正** | 🔴 高 | `_keyword_check`・`analyze_gap_with_llm`・`GapVerdict` が実装に存在しない | Section 3.3 M3コード |
| M2 | **必須修正** | 🔴 高 | `USE_MOCK_LLM` デフォルト `"true"` → 実装は `""` (false)。誤動作の原因 | Section 3.3 M3コード |
| M3 | **必須修正** | 🔴 高 | `FEW_SHOT_EXAMPLES` 構造が実装と逆（キーと値の順序が異なる） | Section 3.4 M4コード |
| M4 | **必須修正** | 🔴 高 | `generate_proposal(gap_item, level)` → 実装は5引数（section_name, change_type, law_summary, law_id, level） | Section 3.4 M4コード |
| M5 | **必須修正** | 🟡 中 | `toyota_2025.pdf` が存在しない → コピペ実行時 FileNotFoundError | Section 4.1 実行コマンド |

### 推奨修正（6件）

| ID | 種別 | 内容 |
|---|---|---|
| R1 | 推奨 | `extract_sections` → 実際の関数名は存在しない（注釈または修正） |
| R2 | 推奨 | 「13のキーワード」→ HEADING_PATTERNSは8パターン |
| R3 | 推奨 | `_is_streamlit_running()` はM5ではなく `scripts/app.py` |
| R4 | 推奨 | `toyota_2025.pdf` 未同梱の注釈追加 |
| R5 | 推奨 | テスト件数「207件」→ M1-M5実績は190+22件 |
| R6 | 推奨 | YAMLスニペットのフィールド名を実際と一致させる |

---

## 修正指示（足軽6への差し戻し）

### M1修正: M3コードスニペットの扱い

Section 3.3 の「第1層: キーワードマッチによる一次フィルタ」と「第2層: LLMによる文脈判定」のコードを以下のいずれかに修正:

**選択肢A（擬似コード宣言）**: 「※以下は設計概念を示す擬似コードです」を冒頭に追記し、実際の実装は `judge_gap()` 関数を参照するよう案内。

**選択肢B（実際のコードに差し替え）**: `judge_gap(section, law_entry, ...)` の実際のシグネチャを使用したコードに差し替え。

### M2修正: USE_MOCK_LLM デフォルト値

```python
# 修正前
USE_MOCK_LLM = os.environ.get("USE_MOCK_LLM", "true").lower() == "true"

# 修正後（実装と一致）
use_mock = os.environ.get("USE_MOCK_LLM", "").lower() in ("true", "1", "yes")
# または注釈追加: ※ USE_MOCK_LLM は明示的に "true" と設定してください（デフォルトは本番モード）
```

### M3修正: FEW_SHOT_EXAMPLES 構造

```python
# 修正: 実際の構造に合わせる
FEW_SHOT_EXAMPLES = {
    "従業員給与等の決定に関する方針": {
        "松": ("当社の給与水準は..."),
        "竹": ("当社の従業員給与は..."),
        "梅": "当社の従業員給与は...",
    }
}
```

または「※以下は説明用の簡略版です。実際の構造は `scripts/m4_proposal_agent.py` の `FEW_SHOT_EXAMPLES` を参照」と注記。

### M4修正: generate_proposal シグネチャ

```python
# 修正: 実際のシグネチャに合わせる
def generate_proposal(
    section_name: str,   # "従業員給与等の決定に関する方針"
    change_type: str,    # "追加必須" / "修正推奨"
    law_summary: str,    # 法令変更の概要
    law_id: str,         # "HC_20260220_001"
    level: str,          # "松" / "竹" / "梅"
) -> str:
```

### M5修正: Toyota サンプルPDF

Section 4.1 実行コマンドに注釈追加:
```bash
# ※ toyota_2025.pdf はトヨタ自動車の公開有報PDFをご自身で用意してください
# （著作権上の理由でリポジトリへの同梱不可）
# サンプルPDFで試す場合: 10_Research/samples/ に任意の有報PDFを配置してください
```

---

## 最終判定

```
⚠️ 条件付き承認
必須修正5件（M1〜M5）修正後、足軽6が再コミット → 再CR不要で承認
```

記事の法令情報（CR-4）・全体構成・B2C戦略（CR-5）は優秀。
実装コードのスニペット修正のみで Zenn 公開可能水準に到達する。

---

*レビュー実施: 足軽8 / 2026-03-09*
