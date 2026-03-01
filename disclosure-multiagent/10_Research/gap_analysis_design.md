# ギャップ分析エージェント 設計書

> 作成日: 2026-02-27 / 担当: 足軽3（subtask_063a4）
> 対応タスク: MVP 開発チェックリスト Phase 1-M3（M3-1, M3-2, M3-3）
> 参照: 22_MVP_Development_Checklist.md / law_yaml_format_design.md / law_entries_human_capital.yaml

---

## 1. 役割と位置づけ

### 1-1. パイプライン上の位置

```
[有報PDF]
  │
  ▼ M1（PDF解析エージェント）
[構造化JSON]           [法令YAMLエントリ]
  │                         │
  └──────────┬──────────────┘
             ▼
     【M3: ギャップ分析エージェント】    ← 本設計書
             │
             ▼
     [ギャップ分析JSON]
             │
             ▼ M4（松竹梅提案エージェント）
     [松竹梅提案レポート]
```

### 1-2. 役割の定義

**「前期有報テキスト（セクション単位）」×「今期適用される法令要件（YAMLエントリ）」を照合し、
変更が必要な箇所・種別・根拠を構造化して出力する**。

LLMは有報テキストを読んで「法令要件が充足されているか」を判定するが、
**法令の知識は必ずYAMLから与える**（hallucination防止の大原則）。

---

## 2. M3-1: ギャップ分析ロジック設計

### 2-1. 入力仕様

#### 入力A: 構造化有報JSON（M1の出力）

```json
{
  "document_id": "S100VHUZ",
  "company_name": "サンプル株式会社",
  "fiscal_year": 2025,
  "fiscal_month_end": 3,
  "sections": [
    {
      "section_id": "HC-001",
      "heading": "e. 人的資本経営に関する指標",
      "level": 3,
      "text": "当社は人材の確保・育成・定着を重要課題と位置づけており...",
      "tables": [
        {
          "caption": "人的資本関連指標",
          "rows": [["指標", "2023年度", "2024年度"], ["女性管理職比率", "12.3%", "14.1%"]]
        }
      ],
      "parent_section_id": "sustainability-001"
    },
    {
      "section_id": "DIV-001",
      "heading": "f. 多様性に関する指標",
      "level": 3,
      "text": "...",
      "tables": []
    }
  ],
  "extraction_library": "PyMuPDF",
  "extracted_at": "2026-02-27T08:00:00"
}
```

#### 入力B: 適用法令エントリリスト（M2法令収集エージェントの出力）

```json
{
  "fiscal_year": 2025,
  "fiscal_month_end": 3,
  "law_yaml_as_of": "2026-02-27",
  "applicable_entries": [
    {
      "id": "HC_20230131_001",
      "title": "企業内容等の開示に関する内閣府令改正（人的資本・多様性開示の義務化）",
      "category": "金商法・開示府令",
      "change_type": "追加必須",
      "disclosure_items": [
        "人材育成方針の記載（必須）",
        "社内環境整備方針の記載（必須）",
        "女性管理職比率（連結・単体）の開示（必須）",
        "男性育児休業取得率の開示（必須）",
        "男女間賃金格差の開示（必須）"
      ],
      "source": "https://www.fsa.go.jp/news/r4/sonota/20230131/20230131.html",
      "source_confirmed": false,
      "summary": "..."
    }
  ],
  "missing_categories": [],
  "warnings": []
}
```

### 2-2. 出力仕様: ギャップ分析JSON

```json
{
  "document_id": "S100VHUZ",
  "fiscal_year": 2025,
  "gap_analysis_version": "1.0",
  "analyzed_at": "2026-02-27T09:00:00",
  "law_yaml_as_of": "2026-02-27",
  "summary": {
    "total_gaps": 3,
    "by_change_type": {
      "追加必須": 2,
      "修正推奨": 1,
      "参考": 0
    }
  },
  "gaps": [
    {
      "gap_id": "GAP-001",
      "section_id": "HC-001",
      "section_heading": "e. 人的資本経営に関する指標",
      "change_type": "追加必須",
      "has_gap": true,
      "gap_description": "男性育児休業取得率の記載が見当たらない。",
      "disclosure_item": "男性育児休業取得率の開示（必須）",
      "reference_law_id": "HC_20230131_001",
      "reference_law_title": "企業内容等の開示に関する内閣府令改正（人的資本・多様性開示の義務化）",
      "reference_url": "https://www.fsa.go.jp/news/r4/sonota/20230131/20230131.html",
      "source_confirmed": false,
      "source_warning": "⚠️ このURLは実アクセス未確認（source_confirmed: false）。参照前に確認を推奨。",
      "evidence_hint": "テキスト内に「育児休業」「育休」のキーワードなし。",
      "llm_reasoning": "有報テキスト中に男性育児休業取得率を示す数値・記述が確認できない。",
      "confidence": "high"
    },
    {
      "gap_id": "GAP-002",
      "section_id": "HC-001",
      "change_type": "追加必須",
      "has_gap": false,
      "gap_description": null,
      "disclosure_item": "女性管理職比率（連結・単体）の開示（必須）",
      "reference_law_id": "HC_20230131_001",
      "evidence_hint": "テーブル内に「女性管理職比率 14.1%」の記載あり。",
      "llm_reasoning": "有報テキストのテーブル行から女性管理職比率（連結）を確認。単体値も要確認だが連結値は記載済み。",
      "confidence": "medium"
    }
  ],
  "no_gap_items": [
    {
      "disclosure_item": "人材育成方針の記載（必須）",
      "reference_law_id": "HC_20230131_001",
      "evidence_hint": "第3段落に「人材育成方針として...」の記載あり。"
    }
  ],
  "metadata": {
    "llm_model": "claude-haiku-4-5-20251001",
    "sections_analyzed": 2,
    "entries_checked": 1
  }
}
```

### 2-3. 処理フロー

```
STEP 1: 入力検証
  ├── 構造化有報JSON: document_id / sections の存在確認
  ├── 適用法令エントリ: applicable_entries が空でないことを確認
  └── 空の場合 → エラー終了（エラーコード: GAP_ERR_001）

STEP 2: エントリ×セクション のマトリクス生成
  ├── 各法令エントリの disclosure_items ごとに確認タスクを生成
  ├── セクションは「人的資本」「サステナビリティ」「従業員の状況」に関連するものを優先対象
  └── 1エントリの disclosure_items が複数ある場合 → 各項目を独立して判定

STEP 3: LLM判定（disclosure_item × section のペアごと）
  ├── システムプロンプト: ドメイン知識・制約を付与（詳細は M3-2 参照）
  ├── ユーザープロンプト: セクションテキスト + 確認すべき disclosure_item
  ├── 出力形式: JSON（has_gap / reason / evidence_hint）
  └── 1ペアあたり 1 API 呼び出し（Haiku推奨: コスト最小化）

STEP 4: 根拠URL付与（M3-3）
  ├── 各ギャップ結果に reference_url（YAMLの source フィールド）を付与
  └── source_confirmed: false の場合 → source_warning フィールドに警告文を付与

STEP 5: 出力JSON生成
  ├── summary（合計ギャップ数・change_type別内訳）を集計
  ├── gaps / no_gap_items に分類して格納
  └── law_yaml_as_of をメタデータに記録（レポートの透明性確保）
```

### 2-4. エラーハンドリング

| エラーコード | 発生条件 | 処理方針 |
|-------------|----------|---------|
| `GAP_ERR_001` | 構造化有報JSONが空またはsectionsが0件 | 処理中断。エラーメッセージ: 「有報テキストの抽出に失敗しました。M1エージェントの出力を確認してください。」 |
| `GAP_ERR_002` | 適用法令エントリが0件 | 警告付きで継続。「⚠️ 適用法令エントリが0件です。対象年度・決算月の設定を確認してください。」 |
| `GAP_ERR_003` | LLM APIがエラーレスポンス（タイムアウト・レート制限） | 最大3回リトライ。3回失敗後は当該ペアを `has_gap: null, confidence: "error"` として記録し、次のペアへ継続 |
| `GAP_ERR_004` | LLM出力がJSONパース不可 | 出力テキストを `llm_raw_output` に保存し、当該ペアは `has_gap: null, confidence: "parse_error"` として記録 |
| `GAP_ERR_005` | YAMLエントリに `disclosure_items` が未定義 | そのエントリはスキップ。ログに記録: 「スキップ: {entry_id} (disclosure_items なし)」 |

---

## 3. M3-2: LLM連携プロンプト設計

### 3-1. 設計方針

| 方針 | 内容 |
|------|------|
| **モデル選定** | `claude-haiku-4-5-20251001`（推奨）。Haikuは低コスト・高速。disclosure_item 1件の判定は複雑でないためHaikuで十分 |
| **1呼び出し = 1判定** | disclosure_item 1件 × section 1件のペアを1 API呼び出しで判定。バッチ化すると精度が落ちるため分離 |
| **hallucination対策** | システムプロンプトで「YAMLエントリ以外の法令への言及を禁止」を明示。出力JSONのフィールドをenumで制約 |
| **セクションのチャンク** | テキストが4000文字超の場合、先頭2000文字+末尾1000文字を使用。テーブルはテキスト化して含める |

### 3-2. システムプロンプト

```text
あなたは日本の有価証券報告書の開示コンプライアンス専門家です。
以下の役割と制約に従って、有報テキストの法令要件充足状況を判定してください。

## 役割
有価証券報告書の特定のセクションテキストを読み、
指定された法令開示項目が記載されているかどうかを判定する。

## 制約（必ず守ること）
1. 判定は「提供された法令開示項目の要件のみ」に基づいて行う。
   YAMLエントリとして提供されていない法令・ガイドラインへの言及は禁止する。
2. 推測や一般的な「あるべき開示」の観点から余分な指摘を追加しない。
3. 出力は必ず指定のJSONフォーマットで返す。フォーマット外の文章を追加しない。
4. 有報テキストに明示的な記載がない場合は has_gap: true とする。
   「おそらく記載があるはず」という推測で has_gap: false としない。
5. 確信度（confidence）は "high"/"medium"/"low" のいずれかで答える。
   テキストに明確な記載あり → high
   類似の記載があるが完全ではない → medium
   テキストが断片的で判断しづらい → low

## 有報の構造について
様式第19号の主要セクション:
- 第二部第2「事業の状況」: 経営方針・サステナビリティ・人的資本・多様性
- 第二部第5「従業員の状況」: 従業員数・平均年齢・平均給与・女性管理職比率等
人的資本の開示は「事業の状況」と「従業員の状況」の両方に分散している場合がある。
```

### 3-3. ユーザープロンプト（テンプレート）

```text
## 判定対象

### 有報セクション情報
- セクションID: {section_id}
- 見出し: {section_heading}
- テキスト（先頭2000文字）:
"""
{section_text}
"""
{テーブル情報（存在する場合）:
テーブル「{caption}」:
{rows のCSV表現}
}

### 確認すべき法令開示項目
- 項目: {disclosure_item}
- 法令根拠: {law_entry.title}
- 変更種別: {law_entry.change_type}（追加必須/修正推奨/参考のいずれか）

## 出力フォーマット（JSONのみ返すこと）
{
  "has_gap": true または false,
  "gap_description": "ギャップがある場合の説明（日本語・1〜2文）。ない場合はnull",
  "evidence_hint": "判定の根拠となるテキストの引用や観察（日本語・1文）",
  "confidence": "high" または "medium" または "low"
}
```

### 3-4. Claude API 実装例（擬似コード）

```python
import anthropic
import json
from dataclasses import dataclass

client = anthropic.Anthropic()

SYSTEM_PROMPT = """..."""  # 3-2 のシステムプロンプト

def judge_gap(
    section: dict,
    disclosure_item: str,
    law_entry: dict,
) -> dict:
    """
    1つの disclosure_item × section ペアのギャップを判定する。

    Returns:
        {"has_gap": bool, "gap_description": str|None,
         "evidence_hint": str, "confidence": str}
    """
    # セクションテキストのチャンク処理（4000文字超の場合）
    text = section["text"]
    if len(text) > 4000:
        text = text[:2000] + "\n...[中略]...\n" + text[-1000:]

    # テーブルをテキスト化
    table_text = ""
    for table in section.get("tables", []):
        caption = table.get("caption", "テーブル")
        rows_csv = "\n".join(",".join(row) for row in table.get("rows", []))
        table_text += f'\nテーブル「{caption}」:\n{rows_csv}\n'

    user_prompt = f"""## 判定対象

### 有報セクション情報
- セクションID: {section['section_id']}
- 見出し: {section['heading']}
- テキスト:
\"\"\"{text}\"\"\"
{table_text}

### 確認すべき法令開示項目
- 項目: {disclosure_item}
- 法令根拠: {law_entry['title']}
- 変更種別: {law_entry['change_type']}

## 出力フォーマット（JSONのみ返すこと）
{{
  "has_gap": true または false,
  "gap_description": "ギャップの説明（ない場合はnull）",
  "evidence_hint": "判定根拠の一文",
  "confidence": "high" または "medium" または "low"
}}"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    # JSONパース（エラー時はフォールバック）
    try:
        result = json.loads(response.content[0].text)
    except json.JSONDecodeError:
        result = {
            "has_gap": None,
            "gap_description": None,
            "evidence_hint": "LLM出力のJSONパースに失敗",
            "confidence": "parse_error",
        }

    return result
```

### 3-5. Hallucination対策チェックリスト

| 対策 | 実装方法 |
|------|---------|
| **法令参照をYAML限定に制約** | システムプロンプトで「YAMLエントリ以外の法令への言及禁止」を明示 |
| **出力フィールドの制約** | `has_gap` はboolのみ、`confidence` は enum の3値のみ許容。パース失敗を検知 |
| **推測禁止** | 「明示的な記載がない場合はhas_gap: true」とシステムプロンプトで指示 |
| **根拠引用の義務化** | `evidence_hint` に必ず有報テキストの観察・引用を含めさせる |
| **レポートへのYAML更新日明示** | `law_yaml_as_of` を全出力に含め、法令情報の鮮度を透明化 |
| **source_confirmed: false の警告** | 根拠URLの信頼性をユーザーに明示（詳細は M3-3 参照） |

---

## 4. M3-3: 根拠明示設計

### 4-1. 設計方針

**「ギャップの根拠は必ずYAMLエントリの `source` URL から引用する」**。
LLMが独自に法令URLを生成することを禁止し、hallucination由来の誤ったURL掲載を防ぐ。

### 4-2. 根拠URLの付与ロジック

```python
def attach_reference_url(gap_result: dict, law_entry: dict) -> dict:
    """
    ギャップ判定結果に法令根拠URLを付与する。
    source_confirmed: false の場合は警告を追加する。
    """
    gap_result["reference_law_id"] = law_entry["id"]
    gap_result["reference_law_title"] = law_entry["title"]
    gap_result["reference_url"] = law_entry["source"]
    gap_result["source_confirmed"] = law_entry.get("source_confirmed", False)

    if not law_entry.get("source_confirmed", False):
        gap_result["source_warning"] = (
            f"⚠️ このURLは実アクセス未確認（source_confirmed: false）。"
            f"参照前にURLの有効性を確認することを推奨します。"
        )
    else:
        gap_result["source_warning"] = None

    return gap_result
```

### 4-3. レポートへの根拠引用形式

ギャップ分析レポート（M5で生成するMarkdown）における根拠引用の表示形式：

```markdown
#### GAP-001: 男性育児休業取得率の記載なし

| 項目 | 内容 |
|------|------|
| セクション | e. 人的資本経営に関する指標 |
| 変更種別 | 🔴 追加必須 |
| 根拠 | 企業内容等の開示に関する内閣府令改正（令和5年内閣府令第3号） |
| 参照URL | https://www.fsa.go.jp/news/r4/sonota/20230131/20230131.html ⚠️ URL未確認 |
| 説明 | 男性育児休業取得率の記載が見当たらない。 |
| 根拠テキスト | 「育児休業」「育休」のキーワードなし。 |
| 確信度 | 高 |

**法令YAML取得日**: 2026-02-27
```

**⚠️ URL未確認ラベルの表示条件**:
- `source_confirmed: false` のエントリ由来の場合に `⚠️ URL未確認` を表示
- 参照URLの脚注に「このURLは自動生成・推定URLを含む場合があります」を追加

### 4-4. source_confirmed: false エントリの取り扱いポリシー

| 状況 | 対応 |
|------|------|
| **ギャップ分析での使用** | 許可。ただし全ての出力箇所に `source_warning` を付与 |
| **松竹梅提案での使用** | 許可。提案文内で根拠URLを表示する際に「⚠️ 要確認」ラベルを付与 |
| **最終レポートでの表示** | `source_confirmed: false` のURLには視覚的な警告（⚠️アイコン＋注釈）を必ず表示 |
| **修正対応** | `source_confirmed: false` のエントリを解消するには、実装者がURLをWebFetchで確認し `source_confirmed: true` に更新する |

---

## 5. セクションマッピング設計

### 5-1. 人的資本関連セクションの特定

有報テキストの `section_heading` から人的資本関連セクションを特定するためのキーワードパターン：

```python
HUMAN_CAPITAL_KEYWORDS = [
    "人的資本", "人材", "人材戦略", "人材育成", "従業員",
    "ダイバーシティ", "多様性", "育児休業", "育休",
    "サステナビリティ", "ESG", "社会",
    "給与", "賃金", "報酬",
]

SUSTAINABILITY_SECTION_PATTERNS = [
    r"サステナビリティ",
    r"人的資本",
    r"従業員の状況",
    r"ESG",
    r"ダイバーシティ",
    r"多様性",
]
```

### 5-2. 法令エントリとセクションの対応表（初期定義）

| 法令エントリID | 優先確認セクション（キーワード） | 理由 |
|---------------|-------------------------------|------|
| `HC_20230131_001` | 人的資本, サステナビリティ, 従業員の状況 | 人材育成方針・多様性指標は複数セクションに分散 |
| `HC_20260220_001` | 人的資本, 人材戦略, 従業員の状況 | 企業戦略との連携・給与開示は人的資本セクションが主 |
| `HC_20220830_001` | 人的資本, サステナビリティ | 任意ガイドラインのため参考チェックのみ |

---

## 6. コスト・性能設計

### 6-1. API コスト見積もり

| パラメータ | 値 |
|-----------|----|
| 使用モデル | claude-haiku-4-5-20251001 |
| 1判定あたりの入力トークン推定 | 約1,500トークン（セクションテキスト2000文字 + システムプロンプト + 設問） |
| 1判定あたりの出力トークン推定 | 約200トークン |
| disclosure_items 数（HC_20230131_001） | 6項目 |
| 分析対象セクション数（目安） | 3〜5セクション |
| 1有報あたりの推定API呼び出し数 | 6項目 × 4セクション = 24回 |
| Haiku 料金（2025年時点参考） | 入力 $0.80/MTok, 出力 $4.00/MTok |
| 1有報あたりの推定コスト | 約 $0.04（4セント） |

### 6-2. 処理時間

| フェーズ | 推定時間 |
|---------|---------|
| YAML読み込み | < 1秒 |
| LLM判定（24回 × 約2秒/回） | 約50秒（並列化で短縮可能） |
| 出力JSON生成 | < 1秒 |
| **合計** | **約60秒** |

**並列化オプション**: Pythonの `asyncio` + `anthropic` の非同期APIを使用することで
24回の API 呼び出しを並列実行し、10〜15秒に短縮可能（Phase 1は逐次実行で十分）。

---

## 7. テスト設計（参考）

### 7-1. 単体テスト項目

| テストケース | 期待動作 |
|------------|---------|
| `has_gap: true` の正例（記載なし） | 女性管理職比率が全く記載されていないセクション → has_gap: true |
| `has_gap: false` の正例（記載あり） | 女性管理職比率が明示されているセクション → has_gap: false |
| テキストが空のセクション | GAP_ERR_001 相当の警告を付与 |
| `disclosure_items` が空のエントリ | GAP_ERR_005 でスキップ |
| LLM出力がJSONでない | GAP_ERR_004: `confidence: "parse_error"` で継続 |
| `source_confirmed: false` のエントリ | `source_warning` フィールドが付与される |

### 7-2. 統合テスト

- **前提**: samples/ の4社分の構造化JSONと law_entries_human_capital.yaml を使用
- **確認項目**: 全ギャップ結果に `reference_url` が付与されること / `law_yaml_as_of` が出力に含まれること
- **サンプル**: company_a.pdf（人的資本記載充実）→ ギャップが少ないことを確認

---

## 8. 変更履歴

| 日付 | 変更内容 | 担当 |
|------|---------|------|
| 2026-02-27 | 初版作成（M3-1〜M3-3 全設計） | 足軽3 subtask_063a4 |
