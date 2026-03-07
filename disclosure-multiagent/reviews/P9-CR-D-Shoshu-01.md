# P9クロスレビュー: D-Shoshu-01 招集通知実装

```
レビュアー: 足軽7
対象タスク: D-Shoshu-01（足軽8実装）
対象コミット: 62ae09c / 512e90e / e9c03cd / 2532f77
実施日時: 2026-03-09T15:50:00
thinking_level: standard
```

---

## 総合判定

```
✅ 正式承認（必須修正: 0件）
```

pytest 47 passed / 0 failed を実機確認済み。CR-1〜CR-5 全項目グリーン。

---

## CR-1: laws/shareholder_notice_2025.yaml の正確性

### スキーマ準拠チェック（law_yaml_schema.md 対照）

| 必須フィールド | gm-2025-001〜012 | gc-2025-001〜004 | 判定 |
|---|---|---|---|
| `id` | ✅ 全16件 | ✅ 全4件 | PASS |
| `category` | ✅ "総会前開示" | ✅ "ガバナンス" | PASS |
| `change_type` | ✅ 追加必須/修正推奨 | ✅ 追加必須/修正推奨 | PASS |
| `effective_from` | ✅ 全件日付形式 | ✅ 全件日付形式 | PASS |
| `title` | ✅ 全件 | ✅ 全件 | PASS |
| `source` | ✅ 全件URL形式 | ✅ 全件URL形式 | PASS |
| `summary` | ✅ 全件（>ブロックスカラー） | ✅ 全件 | PASS |
| `target_sections` | ✅ 全件リスト形式 | ✅ 全件リスト形式 | PASS |

**必須16件全件のスキーマ準拠: ✅ PASS**

### ID形式チェック（{prefix}-{年度}-{連番3桁}）

```
gm-2025-001〜012: 12件 ✅（prefix "gm" = general meeting）
gc-2025-001〜004:  4件 ✅（prefix "gc" = governance）
合計: 16件 ✅
```

### 法令根拠の正確性チェック（手計算確認）

| ID | 法令条文 | source URL | 正確性 |
|---|---|---|---|
| gm-2025-001 | 改正会社法第325条の2（電子提供制度）| moj.go.jp/MINJI/minji07_00297.html | ✅ |
| gm-2025-002 | 会社法第299条（発送期限） | 同上 | ✅ |
| gm-2025-003 | CGコード補充原則1-2④ | jpx.co.jp 2021年改訂 | ✅ |
| gm-2025-004 | CGコード補充原則1-2④（電子プラットフォーム）| 同上 | ✅ |
| gm-2025-005 | 会社法施行規則第74条（取締役選任参考書類）| jpx.co.jp | △ ※1 |
| gm-2025-006 | 東証上場規程第436条の2（独立役員）| jpx.co.jp | ✅ |
| gm-2025-007 | 会社法施行規則第82条（役員報酬参考書類）| fsa.go.jp | ✅ |
| gm-2025-008 | 会社法施行規則第76条（監査役選任参考書類）| fsa.go.jp | ✅ |
| gm-2025-009 | 会社法施行規則第85条（定款変更参考書類）| moj.go.jp | ✅ |
| gm-2025-010 | 会社法第305条（株主提案）| jpx.co.jp | ✅ |
| gm-2025-011 | 東証上場規程第415条（議決権行使結果）| jpx.co.jp | △ ※2 |
| gm-2025-012 | 有報改革（役員個別報酬）| fsa.go.jp | ✅ |
| gc-2025-001 | CGコード補充原則4-11①（スキルマトリックス）| jpx.co.jp | ✅ |
| gc-2025-002 | CGコード補充原則4-11③（取締役会評価）| jpx.co.jp | ✅ |
| gc-2025-003 | CGコード原則1-4（政策保有株式）| jpx.co.jp | ✅ |
| gc-2025-004 | サステナビリティ連動報酬 | fsa.go.jp | ✅ |

**※1**: gm-2025-005 の source は jpx.co.jp（CGコードページ）。会社法施行規則第74条の一次出典は法務省だが、CGコードとの連動文脈でのリンクとして許容範囲。notes欄に「会社法施行規則第74条・74条の3が根拠」と明示されており問題なし。

**※2**: gm-2025-011（議決権行使結果）は **総会後の適時開示事項** であり、招集通知の本来スコープ（総会前）とは異なる。ただし `notes` フィールドに「招集通知本体ではなく総会後の開示」と明記されており、scope外であることを実装者が認識した上での意図的な包含。**差し戻し不要**。

### D-SSBJ-01（ssbj_2025.yaml）との構造一貫性

| 構造要素 | ssbj_2025.yaml | shareholder_notice_2025.yaml | 一致 |
|---|---|---|---|
| version | "1.0" | "1.0" | ✅ |
| effective_period | 2025-04-01〜2026-03-31 | 2025-04-01〜2026-03-31 | ✅ |
| amendments形式 | リスト | リスト | ✅ |
| source_confirmed フィールド | なし | なし | ✅ （両YAMLで一貫）|
| ID形式 | sb-2025-XXX | gm/gc-2025-XXX | ✅ （prefix命名規則準拠）|

**CR-1 判定: ✅ PASS（必須修正なし）**

---

## CR-2: m1_pdf_agent.py の拡張正確性

### SHOSHU_SECTION_KEYWORDS 12件の内容確認

実装（scripts/m1_pdf_agent.py L72-85）を目視カウント：

```python
SHOSHU_SECTION_KEYWORDS = [
    "議案",           # 1
    "取締役選任",     # 2
    "役員報酬",       # 3
    "定款変更",       # 4
    "監査役選任",     # 5
    "株主提案",       # 6
    "報告事項",       # 7
    "決議事項",       # 8
    "議決権",         # 9
    "社外取締役",     # 10
    "スキルマトリックス",  # 11
    "コーポレートガバナンス",  # 12
]
```

**手計算: 12件 ✅**（テスト test_shoshu_keywords_count_is_12 と一致）

12キーワードが shareholder_notice_2025.yaml の対象セクション（議案・取締役選任・役員報酬・スキルマトリックス・CGなど）と整合 ✅

### SHOSHU_HEADING_PATTERNS 8件の内容確認

実装（L88-97）を目視カウント：

| # | パターン | 例 |
|---|---|---|
| 1 | `^第\d+号議案` | 第1号議案 取締役選任の件 |
| 2 | `^【[^】]*議案[^】]*】` | 【取締役選任の件】 |
| 3 | `^報告事項` | 報告事項 |
| 4 | `^決議事項` | 決議事項 |
| 5 | `^株主提案` | 株主提案 |
| 6 | `^[（(]\d+[）)]\s*[\u4e00-\u9fff]` | （1）取締役選任の件 |
| 7 | `^\d+\.\s*[\u4e00-\u9fff]{2,}` | 1. 取締役の選任について |
| 8 | `^【[^】]+】$` | 【表紙】等 |

**手計算: 8件 ✅**（テスト test_shoshu_heading_patterns_count_is_8 と一致）

### doc_type 引数分岐ロジックの確認

```python
# _is_heading_line_for_doc_type (L129-144)
def _is_heading_line_for_doc_type(line: str, doc_type: str = "yuho") -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    patterns = SHOSHU_HEADING_PATTERNS if doc_type == "shoshu" else HEADING_PATTERNS
    return any(p.search(stripped) for p in patterns)
```

- デフォルト `doc_type="yuho"` ✅
- `"shoshu"` → `SHOSHU_HEADING_PATTERNS` 使用 ✅
- それ以外（不正値）→ `HEADING_PATTERNS`（yuhoパターン）にフォールバック ✅（安全な動作）

### _is_heading_line() との関係

既存の `_is_heading_line(line)` は **そのまま残存**し、後方互換関数として機能。`_is_heading_line_for_doc_type` は新規追加の上位互換関数（L129〜）。

```python
# 既存（後方互換・変更なし）
def _is_heading_line(line: str) -> bool:
    ...
    return any(p.search(stripped) for p in HEADING_PATTERNS)

# 新規（doc_type対応）
def _is_heading_line_for_doc_type(line: str, doc_type: str = "yuho") -> bool:
    ...
    patterns = SHOSHU_HEADING_PATTERNS if doc_type == "shoshu" else HEADING_PATTERNS
    return any(p.search(stripped) for p in patterns)
```

**設計判断: 適切 ✅**。既存関数を変更せず新関数を追加するのは後方互換を最大限保証する。

### 後方互換の検証

`split_sections_from_text` の `doc_type` 引数デフォルト値を確認（L147-151）：

```python
def split_sections_from_text(
    full_text: str,
    max_section_chars: int = MAX_SECTION_CHARS,
    doc_type: str = "yuho",   # ← デフォルト "yuho" ✅
) -> list[SectionData]:
```

引数なしで呼ぶ既存コードは全てデフォルト `"yuho"` が適用 ✅

**CR-2 判定: ✅ PASS（必須修正なし）**

---

## CR-3: api/models/schemas.py の拡張正確性

### DocTypeCode enum の確認

```python
class DocTypeCode(str, Enum):
    """書類種別コード（セマンティック）。EDINETの数値コードとは別物。"""
    yuho = "yuho"     # 有価証券報告書
    shoshu = "shoshu"  # 株主総会招集通知
```

- `str, Enum` 継承で JSON シリアライズ可能 ✅
- docstring に「EDINETの数値コードとは別物」と明記 ✅（後続で重要）

### EdinetDocument.doc_type_code との分離確認

```python
class EdinetDocument(BaseModel):
    doc_type_code: str   # ← EDINETの数値コード（"120"等）のまま str
```

`EdinetDocument.doc_type_code` は EDINET 生の数値コード（"120"=有報）を受け取る `str` 型。`DocTypeCode` enum とは **型レベルで完全分離** ✅。

混同するリスクゼロ（別フィールド名・別型・別モデル）。

### AnalyzeRequest への追加確認

```python
class AnalyzeRequest(BaseModel):
    ...
    doc_type_code: DocTypeCode = DocTypeCode.yuho  # デフォルト yuho
```

- デフォルト `DocTypeCode.yuho` で既存クライアントのリクエストは影響なし ✅
- Pydantic による enum バリデーション（"yuho"/"shoshu" 以外は 422 エラー）✅

**CR-3 判定: ✅ PASS（必須修正なし）**

---

## CR-4: テストの十分性

### TestShoshuDocType 15件の内訳カウント

| # | テストメソッド | カバレッジ |
|---|---|---|
| 1 | `test_shoshu_heading_gian_detected` | 第N号議案パターン（3ケース）|
| 2 | `test_shoshu_heading_hokokujiko_detected` | 報告事項/決議事項/株主提案 |
| 3 | `test_yuho_heading_not_detected_as_shoshu` | 有報パターンが shoshu に非適用 |
| 4 | `test_default_doc_type_is_yuho` | デフォルト引数後方互換 |
| 5 | `test_split_shoshu_text_detects_gian` | split 関数統合テスト |
| 6 | `test_split_shoshu_default_yuho_backward_compat` | デフォルトと yuho 明示が同一結果 |
| 7 | `test_shoshu_text_not_split_with_yuho_pattern` | yuho パターンが shoshu を誤検出しない |
| 8 | `test_get_shoshu_sections_keyword_in_heading` | 見出しキーワード検出 |
| 9 | `test_get_shoshu_sections_keyword_in_body` | 本文200字内キーワード検出 |
| 10 | `test_get_shoshu_sections_empty_report` | 空セクション境界値 |
| 11 | `test_get_shoshu_sections_no_keyword_excluded` | 非対象セクション除外 |
| 12 | `test_all_shoshu_keywords_detectable` | 全12キーワード検出（ループ確認）|
| 13 | `test_shoshu_keywords_count_is_12` | 手計算 CHECK-7b（12件）|
| 14 | `test_shoshu_heading_patterns_count_is_8` | 手計算 CHECK-7b（8件）|
| 15 | `test_shoshu_keywords_all_expected_present` | 12キーワード全列挙確認 |

**手計算: 15件 ✅**

### 後方互換テストの確認

| テスト | 確認内容 |
|---|---|
| `test_default_doc_type_is_yuho` | `_is_heading_line_for_doc_type` のデフォルトが yuho |
| `test_split_shoshu_default_yuho_backward_compat` | `split_sections_from_text` デフォルト=yuho 明示と同一 |

後方互換 ✅

### 手計算検証の存在確認

- `test_shoshu_keywords_count_is_12`: 12件の手計算一覧付き ✅
- `test_shoshu_heading_patterns_count_is_8`: 8パターンのコメント一覧付き ✅
- `test_shoshu_keywords_all_expected_present`: 全12キーワードの expected list と照合 ✅

**CR-4 判定: ✅ PASS（必須修正なし）**

---

## CR-5: 全体動作確認

### pytest 実行結果

```
$ cd disclosure-multiagent/scripts && python3 -m pytest test_m1_pdf_agent.py -v

platform linux -- Python 3.12.3, pytest-9.0.2
collected 47 items

test_m1_pdf_agent.py ...............................................  [100%]

============================== 47 passed in 0.23s ==============================
```

**47 passed ✅ 完全再現確認**

（既存32件 + TestShoshuDocType 15件 = 47件 ✅）

---

## 軽微観察事項（差し戻し不要）

以下は必須修正ではなく、知識共有目的で記録する。

### O-1: gm-2025-011 のスコープ（周知済み）

`gm-2025-011`（議決権行使結果 TDnet 開示）は厳密には招集通知「後」の開示事項。ただし `notes` フィールドに「招集通知本体ではなく総会後の開示」と明記済み。エントリの包含は意図的。**対応不要**。

### O-2: 不正な doc_type 値の未テスト

`_is_heading_line_for_doc_type("text", "invalid")` の場合、`else HEADING_PATTERNS` にフォールバックする動作は安全だが、明示的テストが存在しない。現時点では実用上問題なし。将来的に他の doc_type（例: "kikan_hokoku"）を追加する際に考慮。

### O-3: SHOSHU_HEADING_PATTERNS[8] の汎用性

パターン8 `^【[^】]+】$`（全体が【〜】で囲まれた行）は招集通知に限らず一般的すぎる可能性がある。現在は shoshu 専用パターンなので問題は生じないが、将来的に別書類種別が追加された場合に誤検出の可能性。

---

## CR総括

| CR項目 | 検査内容 | 結果 |
|---|---|---|
| CR-1 | shareholder_notice_2025.yaml スキーマ準拠・法令根拠 | ✅ PASS |
| CR-2 | m1 SHOSHU_KEYWORDS/PATTERNS・doc_type分岐・後方互換 | ✅ PASS |
| CR-3 | schemas.py DocTypeCode分離・AnalyzeRequest追加 | ✅ PASS |
| CR-4 | TestShoshuDocType 15件・手計算・後方互換テスト | ✅ PASS |
| CR-5 | pytest 47 passed 実機再現確認 | ✅ PASS |

```
■ 総合判定: ✅ 正式承認
■ 必須修正: 0件
■ 推奨修正: 0件
■ 軽微観察: 3件（O-1/O-2/O-3）
■ pytest: 47 passed in 0.23s（完全再現）
■ 信頼度: 5/5
```

---

*レビュアー: 足軽7 / 2026-03-09T16:00:00*
