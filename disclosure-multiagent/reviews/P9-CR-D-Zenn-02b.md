# P9 クロスレビュー: disclosure 記事②「EDINETから有報を自動取得して法令照合する」

| 項目 | 内容 |
|---|---|
| **レビュー対象** | `docs/article_disclosure_phase2_draft.md`（640行） |
| **レビュアー** | 足軽2号（cmd_345k_a2b） |
| **実施日** | 2026-03-09 |
| **参照実装** | `scripts/m7_edinet_client.py` / `m6_law_url_collector.py` / `m8_multiyear_agent.py` / `m9_document_exporter.py` |
| **判定** | **Grade B（必須修正3件）** |

---

## CR-1: コードの技術的正確性

### ✅ PASS: M7 fetch_document_list()

記事（L86-101）と実装（m7_edinet_client.py L44-62）を照合した結果、ロジックは完全一致。
エラーメッセージの文言が若干異なる（記事:「必要です。」/ 実装:「必要です。\n環境変数...」）が意味に差異はない。

```python
# 記事・実装とも一致
def fetch_document_list(date: str, doc_type_code: str = "120") -> list[dict]:
    params={"date": date, "type": 2, "Subscription-Key": SUBSCRIPTION_KEY},
    timeout=30,
```

### ✅ PASS: M7 download_pdf()

記事（L118-141）と実装（m7_edinet_client.py L65-88）を照合。
`stream=True` チャンク転送・`time.sleep(1)` サーバー負荷軽減・`validate_doc_id` 事前バリデーションすべて一致。

### ✅ PASS: M7 validate_doc_id()

記事（L149-151）と実装（m7_edinet_client.py L39-41）:

```python
def validate_doc_id(doc_id: str) -> bool:
    return bool(re.fullmatch(r"S[A-Z0-9]{7}", doc_id))
```

完全一致。

### ✅ PASS: M7 search_by_company()

記事（L161-174）と実装（m7_edinet_client.py L91-104）を照合。月次ループ・`time.sleep(0.5)` 等すべて一致。

### ✅ PASS: M6 _get_law_list() / _match()

記事（L216-248）と実装（m6_law_url_collector.py L49-74）を照合。
型ヒント記法の差異のみ（記事: `dict | None` / 実装: `Optional[dict]`）。ロジック完全一致。

### ❌ **FAIL: M8 関数名誤記（_calc_change_rate → _text_change_rate）**

記事（L308）:
```python
def _calc_change_rate(text_a: str, text_b: str) -> float:
```

実装（m8_multiyear_agent.py L93）:
```python
def _text_change_rate(old_text: str, new_text: str) -> float:
```

**差異2点:**
1. 関数名: `_calc_change_rate` → 実際は `_text_change_rate`
2. 引数名: `text_a/text_b` → 実際は `old_text/new_text`
3. 実装には「片方がemptyの場合 → 1.0 を返す」という追加ハンドリングがある（記事に記述なし）

プライベート関数のため直接呼び出し影響は限定的だが、記事の正確性として問題あり。

### ❌ **FAIL: M8 compare_years() シグネチャ不一致（重大）**

記事（L323-333）:
```python
from m8_multiyear_agent import compare_years

diff = compare_years(yearly_2023, yearly_2024)  # ← 2引数
```

実装（m8_multiyear_agent.py L182）:
```python
def compare_years(reports: list[YearlyReport]) -> YearDiff:
```

**実際の引数はリスト1個。記事の呼び出し方では `TypeError` が発生する。**

正しくは:
```python
diff = compare_years([yearly_2023, yearly_2024])  # ← リスト1引数
```

### ❌ **FAIL: M9 export_to_word/export_to_excel シグネチャ不一致（重大）**

記事（L347-354）:
```python
word_path = export_to_word(proposal_set, output_dir="outputs/")
excel_path = export_to_excel(proposal_set, output_dir="outputs/")
```

実装（m9_document_exporter.py L121-131, L207-218）:
```python
def export_to_word(
    proposal_sets: list[ProposalSet],  # ← リスト（複数）
    output_path: str,                  # ← output_dir ではなく output_path
    company_name: str = "分析対象企業",
    fiscal_year: int = 0,
) -> str:

def export_to_excel(
    proposal_sets: list[ProposalSet],  # ← リスト（複数）
    output_path: str,                  # ← output_dir ではなく output_path
    ...
) -> str:
```

**差異2点:**
1. 第1引数: `proposal_set`（単数）→ 実際は `proposal_sets: list[ProposalSet]`（リスト）
2. キーワード引数名: `output_dir=` → 実際は `output_path=`（ファイルパス直接指定）
3. ファイル名の自動生成機能はなし（記事のコメント `# → outputs/disclosure_proposals_2026-03-09.docx` は誤解を与える）

**実行すると `TypeError: export_to_word() got an unexpected keyword argument 'output_dir'` が発生する。**

---

## CR-2: コード実行可能性

### NameError / ImportError 検査

| コードブロック | 判定 | 備考 |
|---|---|---|
| M7 fetch_document_list（L86） | ✅ PASS | import requests 済み |
| M7 download_pdf（L118） | ✅ PASS | Path・re 等すべて使用可 |
| M6 _match（L237） | ✅ PASS | ET.fromstring 等 import 済み |
| M8 compare_years 利用例（L323） | ❌ **FAIL** | `compare_years(a, b)` → TypeError |
| M9 export_to_word 利用例（L347） | ❌ **FAIL** | `output_dir=` → TypeError |
| E2E統合 run_full_pipeline（L396） | ✅ PASS | `from m7_edinet_client import ...` 等すべて実装済み |
| M7-2設計予定コード（L569） | ⚠️ SKIP | 「実装予定」として明記されているため不問 |
| 実LLM実行コマンド（L588） | ✅ PASS | bash コマンドとして正しい |

**実行可能性 FAIL: 2箇所（M8比較例・M9エクスポート例）**

---

## CR-3: 比較根拠の妥当性

### EDINET エンドポイント情報

| 記事記載 | 実装値 | 判定 |
|---|---|---|
| `api.edinet-fsa.go.jp/api/v2/documents.json` | `EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"` | ✅ |
| `disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{docID}.pdf` | `EDINET_DL_BASE = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf"` | ✅ |
| docTypeCode 120=有報 | MOCK_DOCUMENTS で "120" を使用 | ✅ |
| e-Gov カテゴリ 2=法律・3=政令・4=府令 | `_CATEGORIES = [2, 3, 4]` と一致 | ✅ |

### テスト件数の正確性

記事 L488「207件 全PASS」の内訳検証:

```
29 + 19 + 16 + 41 + 37 + 22 + 13 + 15 + 15 = 207件 ✅
```

計算一致を確認。

### 「EDINET PDF直接DL認証不要」の根拠

記事 L43: 「PDF直接DLは2024年以降も認証不要のまま」

実装（m7_edinet_client.py L77）で実際に認証ヘッダーなしで GET しており、robots.txt 調査結果（L12-14）も文書化済み。根拠あり。ただし将来の仕様変更リスクは記事に免責事項として言及があることを確認（末尾 :::message ブロック L628-635）。**問題なし。**

---

## CR-4: 誤情報検出

| # | 箇所 | 誤情報の内容 | 深刻度 |
|---|---|---|---|
| E1 | L308 | `_calc_change_rate` → 実際の関数名は `_text_change_rate` | 中（プライベート関数だが記事で名前を明記） |
| E2 | L323 | `compare_years(yearly_2023, yearly_2024)` → 実際は `compare_years([yearly_2023, yearly_2024])` | **高（実行するとTypeError）** |
| E3 | L347-354 | `export_to_word(proposal_set, output_dir=...)` → 引数名・型が異なる | **高（実行するとTypeError）** |
| E4 | L311 | `_calc_change_rate` の引数 `text_a/text_b` → 実際は `old_text/new_text` | 低（E1と同根） |
| E5 | L350 `# → outputs/disclosure_proposals_2026-03-09.xlsx` | 実際はファイル名自動生成なし、`output_path` を引数で明示指定する | 低（誤解を与えるコメント） |

---

## CR-5: publishグレード判定

### グレード: **B**（必須修正3件完了後 A）

**理由:**

- 記事全体の構成・説明の正確性は高い
- EDINET/e-Gov API の仕様説明・設計方針・テスト説明は正確
- ただし M8 compare_years と M9 export 関数の **使用例コードが実行するとTypeError** になる致命的な誤りが2件ある
- 読者がコードをコピペして動かした場合に即エラーになるため、publish前の必須修正が必要

---

## 必須修正リスト（publish前に対応必須）

### M1: M8 compare_years 引数修正（**必須・高優先**）

**対象行: L323-333**

```python
# 修正前（TypeError が発生する）
diff = compare_years(yearly_2023, yearly_2024)

# 修正後
diff = compare_years([yearly_2023, yearly_2024])
```

### M2: M9 export_to_word/export_to_excel シグネチャ修正（**必須・高優先**）

**対象行: L345-354**

```python
# 修正前（TypeError が発生する）
from m9_document_exporter import export_to_word, export_to_excel

# Word出力
word_path = export_to_word(proposal_set, output_dir="outputs/")
# → outputs/disclosure_proposals_2026-03-09.docx

# Excel出力
excel_path = export_to_excel(proposal_set, output_dir="outputs/")
# → outputs/disclosure_proposals_2026-03-09.xlsx
```

```python
# 修正後（実際のシグネチャに合わせる）
from m9_document_exporter import export_to_word, export_to_excel

# Word出力
word_path = export_to_word(
    proposal_sets=[proposal_set],         # ← リスト
    output_path="outputs/report.docx",    # ← output_path（ファイルパス直接指定）
)

# Excel出力
excel_path = export_to_excel(
    proposal_sets=[proposal_set],         # ← リスト
    output_path="outputs/report.xlsx",    # ← output_path（ファイルパス直接指定）
)
```

### M3: _calc_change_rate → _text_change_rate 関数名修正（**必須・中優先**）

**対象行: L308**

```python
# 修正前
def _calc_change_rate(text_a: str, text_b: str) -> float:

# 修正後（実際の関数名に合わせる）
def _text_change_rate(old_text: str, new_text: str) -> float:
    """difflib.SequenceMatcher で変化率を計算（0.0〜1.0）
    ※ 片方が空の場合は 1.0（完全変化）を返す。
    """
    if not old_text and not new_text:
        return 0.0
    if not old_text or not new_text:  # 片方が空 → 完全変化
        return 1.0
    matcher = difflib.SequenceMatcher(None, old_text, new_text)
    return 1.0 - matcher.ratio()
```

---

## 推奨修正（必須ではない）

| # | 箇所 | 内容 |
|---|---|---|
| R1 | L350コメント | `# → outputs/disclosure_proposals_2026-03-09.docx` → `# ファイル名は output_path で指定した値` に修正（自動生成と誤解させない） |
| R2 | L104 docTypeCode表 | 現状で正確。変更不要 |

---

## まとめ

| CR項目 | 結果 |
|---|---|
| CR-1 コード技術的正確性 | **FAIL**（E1〜E3: 関数名誤記・引数型不一致） |
| CR-2 コード実行可能性 | **FAIL**（M8/M9コード例が TypeError） |
| CR-3 比較根拠の妥当性 | **PASS**（EDINET/e-Gov仕様・テスト件数すべて正確） |
| CR-4 誤情報検出 | **FAIL**（E1-E5: うち高深刻度2件） |
| CR-5 publishグレード | **B**（必須修正M1〜M3完了後 → A） |

**必須修正3件（M1: compare_years引数, M2: export引数名, M3: 関数名）を適用後、Grade A としてpublish可能。**

---

*レビュアー: 足軽2号 / cmd_345k_a2b / 2026-03-09*
