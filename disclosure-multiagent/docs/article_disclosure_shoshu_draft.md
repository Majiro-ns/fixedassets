---
title: "AIで株主総会招集通知の法令チェックを自動化する — disclosure-multiagentの書類種別拡張"
emoji: "📋"
type: "tech"
topics: ["python", "ai", "コーポレートガバナンス", "株主総会"]
published: false
---

# AIで株主総会招集通知の法令チェックを自動化する — disclosure-multiagentの書類種別拡張

上場企業の法務・IR担当者であれば、株主総会シーズン前の招集通知作成が毎年の一大作業であることをご存知だろう。CGコードの改訂、会社法の改正、機関投資家の要求水準の高まり——チェック項目は年々増加し、人手によるレビューには限界がある。

本稿では、オープンソースのPythonパイプライン **disclosure-multiagent** が、有価証券報告書（有報）の自動法令チェックに加えて、**株主総会招集通知（招集通知）のチェックにも対応した拡張設計**を解説する。`doc_type="shoshu"` という引数1つで、同じパイプラインが招集通知の16法令項目を自動照合する仕組みだ。

---

## 1. なぜ招集通知の法令チェックが重要か

### 1-1. CGコード2021年改訂が引き上げたハードル

2021年6月に施行された東証コーポレートガバナンス・コード（CGコード）改訂は、プライム上場企業に対して招集通知の内容・タイミングの両面でハードルを引き上げた。

**スキルマトリックスの義務化（補充原則4-11①）**
取締役会全体として必要なスキル・知見と、各取締役のスキルの対応を示す「スキルマトリックス」の開示が義務化された。招集通知の取締役選任議案に掲載する企業が急増している。

**早期発送の要求（補充原則1-2④）**
「少なくとも3週間前（可能な限り4週間前）」の招集通知発送が推奨されている。実務上、4週間前発送はプライム上場企業の実質的な標準となりつつある。

**英語版の提供（補充原則1-2④）**
海外機関投資家向けの英語版招集通知・議決権行使書類の提供も推奨されており、対応遅れが議決権行使反対票につながるケースも出てきた。

### 1-2. 改正会社法の電子提供制度（2023年9月施行）

会社法改正（2023年9月1日施行）により、上場企業には「電子提供制度」が義務化された。これは招集通知の添付書類をウェブサイトに掲載し、株主がオンラインで参照できる仕組みだ。

```
電子提供制度の主なルール（改正会社法 第325条の2〜325条の7）

・電子提供措置期間: 総会の3週間前から総会後3か月間
・ウェブサイトURL: 招集通知本体に記載が必要
・書面請求株主: 書面の送付義務が引き続き残る
・対象書類: 株主総会参考書類・事業報告・計算書類等
```

この制度変更により、チェック項目がさらに増えた。従来の「書面発送」の確認に加えて、「電子提供措置の開始日」「ウェブサイトURLの記載」「書面請求への対応方針の明記」が必要になった。

### 1-3. 人手レビューの限界

上場企業1社あたりの招集通知チェック項目を洗い出すと、次のような規模になる。

| カテゴリ | 主な根拠 | 確認項目数 |
|---------|---------|---------|
| 電子提供制度 | 会社法第325条の2〜 | 3〜5項目 |
| 招集通知発送 | 会社法第299条・CGコード補充原則1-2④ | 2〜3項目 |
| 取締役選任議案 | 会社法施行規則第74条・CGコード補充原則4-11 | 5〜8項目 |
| スキルマトリックス | CGコード補充原則4-11① | 3〜4項目 |
| 役員報酬議案 | 会社法施行規則第82条 | 4〜6項目 |
| サステナビリティ連動報酬 | 2024年有報改革連動 | 3〜4項目 |
| その他 | 監査役選任・定款変更・株主提案等 | 10〜15項目 |

総計で30〜45項目。これを毎年手作業で確認するコストは相当なものだ。さらに法令改正のたびにチェックシートを更新する必要もある。

---

## 2. disclosure-multiagentの書類種別拡張アーキテクチャ

### 2-1. 全体パイプラインのおさらい

```
招集通知PDF
    │
    ▼ M1: m1_pdf_agent.py（doc_type="shoshu"）
    │   PDF解析 → セクション分割（招集通知パターンで）
    │   → StructuredReport
    │
    ▼ M2: m2_law_context_agent.py
    │   shareholder_notice_2025.yaml を参照
    │   → LawContext（16項目のチェックリスト）
    │
    ▼ M3: m3_gap_analysis_agent.py
    │   各セクションと法令要件を照合
    │   → GapAnalysisResult（充足/不足/未記載）
    │
    ▼ M4: m4_proposal_agent.py
    │   ギャップに対する松竹梅改善提案を生成
    │   → ProposalResult
    │
    ▼ M5: m5_report_agent.py
        最終レポートを出力
        → disclosure_report.md / PDF
```

有報パイプラインと同じM1〜M5の構成だが、`doc_type="shoshu"` を指定することで、各モジュールが招集通知向けの処理に切り替わる。

### 2-2. `doc_type` 引数による分岐設計

最大の設計ポイントは **`doc_type` 引数の導入** だ。`m1_pdf_agent.py` の主要関数は以下のシグネチャを持つ。

```python
def split_sections_from_text(
    full_text: str,
    max_section_chars: int = MAX_SECTION_CHARS,
    doc_type: str = "yuho",   # ← ここがキー
) -> list[SectionData]:
    ...
```

内部では見出しパターンの切り替えだけを行う。シンプルだが効果的な設計だ。

```python
def _is_heading_line_for_doc_type(line: str, doc_type: str = "yuho") -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    # doc_type に応じてパターンを切り替えるだけ
    patterns = SHOSHU_HEADING_PATTERNS if doc_type == "shoshu" else HEADING_PATTERNS
    return any(p.search(stripped) for p in patterns)
```

元の `_is_heading_line()` 関数は **一切変更していない**。新関数 `_is_heading_line_for_doc_type()` を追加し、有報処理は従来通りの関数を呼び出す。これが後方互換性の核心だ。

### 2-3. DocTypeCode enum の設計判断

`api/models/schemas.py` では、書類種別コードを `DocTypeCode` enum として定義している。

```python
class DocTypeCode(str, Enum):
    """書類種別コード（セマンティック）。EDINETの数値コードとは別物。"""
    yuho = "yuho"      # 有価証券報告書
    shoshu = "shoshu"  # 株主総会招集通知
```

重要なのは **「EDINETの数値コードとは別物」** という設計方針だ。

EDINETでは書類種別を数値で管理している（有報は "120"、招集通知は "030" 等）。これをそのまま使うと、API利用者が数値の意味を調べる手間が生じる。そこで人間が読みやすいセマンティックなコード（"yuho"/"shoshu"）を別途定義し、EDINET数値コードとの変換はライブラリ内部で処理する設計にした。

```python
class EdinetDocument(BaseModel):
    doc_type_code: str     # EDINET数値コード ("120", "030" 等)
    ...

class AnalyzeRequest(BaseModel):
    doc_type_code: DocTypeCode = DocTypeCode.yuho  # セマンティックコード
    ...
```

`EdinetDocument.doc_type_code` は `str`（EDINETの数値）、`AnalyzeRequest.doc_type_code` は `DocTypeCode`（セマンティック）と、型レベルで分離されている。

### 2-4. 後方互換設計の3原則

招集通知対応の実装は、以下の3原則で後方互換を保証している。

**原則1: デフォルト引数は "yuho"**
`doc_type="yuho"` がデフォルトなので、既存の有報処理コードは引数を追加せずそのまま動く。

**原則2: 既存関数は変更しない**
`_is_heading_line()` は一切変更せず、新関数 `_is_heading_line_for_doc_type()` を追加した。

**原則3: 既存テストが全件PASS**
後方互換テスト（32件）が全件PASSすることで、デグレードがないことを自動確認できる。

---

## 3. 招集通知チェック項目（shareholder_notice_2025.yaml）

### 3-1. 16項目の全体像

チェック項目は `laws/shareholder_notice_2025.yaml` に定義されている。**総会前開示（gm）12件** と **ガバナンス（gc）4件** の合計16件だ。

```yaml
# laws/shareholder_notice_2025.yaml の構造
version: "1.0"
effective_period:
  from: "2025-04-01"
  to: "2026-03-31"
amendments:
  - id: "gm-2025-001"   # gm = general meeting（総会前開示）
    category: "総会前開示"
    change_type: "追加必須"
    ...
  - id: "gc-2025-001"   # gc = governance（ガバナンス）
    category: "ガバナンス"
    ...
```

### 3-2. 総会前開示カテゴリ（gm）12件の解説

| ID | タイトル | 法令根拠 | change_type |
|----|---------|---------|------------|
| gm-2025-001 | 電子提供制度の導入 | 会社法第325条の2 | 追加必須 |
| gm-2025-002 | 招集通知の発送期限（3週間前） | 会社法第299条 | 追加必須 |
| gm-2025-003 | 招集通知の早期開示（任意） | CGコード補充原則1-2④ | 修正推奨 |
| gm-2025-004 | 議決権電子行使プラットフォーム | CGコード補充原則1-2④ | 修正推奨 |
| gm-2025-005 | 取締役選任議案の記載要件 | 会社法施行規則第74条 | 追加必須 |
| gm-2025-006 | 社外取締役の独立性基準の開示 | CGコード原則4-9 | 追加必須 |
| gm-2025-007 | 役員報酬改定議案の記載要件 | 会社法施行規則第82条 | 追加必須 |
| gm-2025-008 | 監査役選任議案の記載要件 | 会社法施行規則第76条 | 追加必須 |
| gm-2025-009 | 定款変更議案の記載要件 | 会社法施行規則第85条 | 追加必須 |
| gm-2025-010 | 株主提案への対応記載 | 会社法第305条 | 修正推奨 |
| gm-2025-011 | 議決権行使結果の開示 | 上場規程第415条 | 修正推奨 |
| gm-2025-012 | 役員個別報酬の開示（1億円以上） | 有価証券報告書改革 | 修正推奨 |

特に注目すべきは **gm-2025-001（電子提供制度）** と **gm-2025-002（発送期限）** だ。2023年9月施行の改正会社法により義務化されたため、`change_type: "追加必須"` として最高優先度でチェックされる。

### 3-3. ガバナンスカテゴリ（gc）4件の解説

| ID | タイトル | 対象市場 | 特記事項 |
|----|---------|---------|---------|
| gc-2025-001 | スキルマトリックス | プライム（義務） | 2021年CGコード改訂で義務化 |
| gc-2025-002 | 取締役会評価の開示 | プライム・スタンダード | 外部評価採用の有無も確認 |
| gc-2025-003 | 政策保有株式の方針 | プライム・スタンダード | 有報との整合確認が必要 |
| gc-2025-004 | サステナビリティ連動型役員報酬 | プライム | SSBJ対応との連携項目 |

**gc-2025-004（サステナビリティ連動型役員報酬）** は、SSBJ（サステナビリティ基準委員会）対応と連携した項目だ。CO2削減・女性管理職比率・エンゲージメントスコア等のKPIを役員報酬に連動させる企業が増えており、招集通知でのKPI設定根拠・達成状況の開示が機関投資家から求められている。

### 3-4. スキーマの構造（law_yaml_schema.md 準拠）

各エントリーは以下のスキーマに従って定義されている。

```yaml
- id: "gm-2025-005"
  category: "総会前開示"          # gm or gc
  change_type: "追加必須"          # 追加必須/修正推奨/廃止
  effective_from: "2021-06-11"    # 施行日
  title: "取締役選任議案の記載要件 — ..."
  source: "https://www.jpx.co.jp/..."  # 根拠URL
  summary: >                        # 300〜500字の詳細説明
    ...
  target_sections:                  # 照合対象のセクション名
    - "議案（取締役選任の件）"
    - "株主総会参考書類"
  required_items:                   # チェック必須項目リスト
    - "候補者氏名・生年月日・略歴"
    - "重要な兼職の状況"
    ...
  applicable_markets:               # 適用市場
    - "プライム"
    - "スタンダード"
  notes: "..."                      # 補足メモ
```

`target_sections` フィールドが重要だ。M1で分割されたセクション名と照合することで、どのセクションに何が書かれているべきかを特定できる。

---

## 4. 実装コード

### 4-1. SHOSHU_SECTION_KEYWORDS — 招集通知セクション検出

```python
# scripts/m1_pdf_agent.py

SHOSHU_SECTION_KEYWORDS: list[str] = [
    "議案",
    "取締役選任",
    "役員報酬",
    "定款変更",
    "監査役選任",
    "株主提案",
    "報告事項",
    "決議事項",
    "議決権",
    "社外取締役",
    "スキルマトリックス",
    "コーポレートガバナンス",
]
```

12件のキーワードは、招集通知の典型的なセクション名を網羅している。有報の `HUMAN_CAPITAL_KEYWORDS`（スキーマの人的資本関連）と同様の設計思想で、セクション本文の先頭200文字も検索対象に含める。

### 4-2. SHOSHU_HEADING_PATTERNS — 見出し行の判定

```python
SHOSHU_HEADING_PATTERNS: list[re.Pattern] = [
    re.compile(r'^第\d+号議案'),              # 「第1号議案 取締役選任の件」
    re.compile(r'^【[^】]*議案[^】]*】'),      # 「【取締役選任の件】」
    re.compile(r'^報告事項'),                  # 「報告事項」
    re.compile(r'^決議事項'),                  # 「決議事項」
    re.compile(r'^株主提案'),                  # 「株主提案」
    re.compile(r'^[（(]\d+[）)]\s*[\u4e00-\u9fff]'),  # 「（1）取締役選任の件」
    re.compile(r'^\d+\.\s*[\u4e00-\u9fff]{2,}'),       # 「1. 取締役の選任について」
    re.compile(r'^【[^】]+】$'),               # 「【表紙】」等の汎用パターン
]
```

8つのパターンが招集通知の構造に対応している。`第\d+号議案` は最も典型的な書式で、100%の招集通知に含まれる。`[\u4e00-\u9fff]`（CJK統合漢字のUnicode範囲）を使って、漢字で始まるセクション名を確実にキャッチする。

### 4-3. get_shoshu_sections() — 関連セクションの抽出

```python
def get_shoshu_sections(report: StructuredReport) -> list[SectionData]:
    """
    StructuredReportから招集通知関連セクションのみを抽出する。
    SHOSHU_SECTION_KEYWORDS が見出しまたは本文（先頭200文字）に
    含まれるセクションを返す。
    """
    relevant = []
    for section in report.sections:
        heading = section.heading
        body_head = section.text[:200]  # 本文先頭200文字のみ検索
        combined = heading + body_head
        if any(kw in combined for kw in SHOSHU_SECTION_KEYWORDS):
            relevant.append(section)
    return relevant
```

本文先頭200文字のみを検索するのは、長い本文を全文スキャンするコストを避けるためだ。見出し行にキーワードが含まれない場合（例：「第3号議案」のみのケース）でも、本文冒頭の「役員報酬改定の件」でキャッチできる。

### 4-4. 招集通知PDFの解析実行例

```python
from scripts.m1_pdf_agent import (
    extract_text_from_pdf,
    split_sections_from_text,
    get_shoshu_sections,
    StructuredReport,
)

# 招集通知PDFのパス
pdf_path = "sample_shoshu_2025.pdf"

# PDFテキスト抽出
full_text = extract_text_from_pdf(pdf_path)

# 招集通知モードでセクション分割
sections = split_sections_from_text(full_text, doc_type="shoshu")

# StructuredReportを組み立て
report = StructuredReport(
    document_id="SHOSHU-2025-SAMPLE",
    company_name="サンプル株式会社",
    fiscal_year=2025,
    fiscal_month_end=3,
    sections=sections,
)

# 招集通知関連セクションのみ抽出
shoshu_sections = get_shoshu_sections(report)

for s in shoshu_sections:
    print(f"[{s.section_id}] {s.heading}")
    print(f"  本文: {s.text[:80]}...")
    print()
```

出力例:
```
[SEC-001] 報告事項
  本文: 第190期（2024年4月1日〜2025年3月31日）事業報告の内容...

[SEC-002] 決議事項
  本文: 第1号議案 取締役選任の件...

[SEC-003] 第1号議案 取締役選任の件
  本文: 取締役候補者を以下のとおり選任いたしたいと存じます...

[SEC-004] 第2号議案 役員報酬改定の件
  本文: 取締役報酬の額の改定をお諮りいたします...
```

---

## 5. M2〜M5パイプラインによる法令照合・ギャップ分析・改善提案

### 5-1. FastAPI エンドポイントから招集通知を解析

```python
import httpx

# 招集通知の解析リクエスト
response = httpx.post(
    "http://localhost:8000/analyze",
    json={
        "edinet_code": "E02144",        # 例: トヨタ自動車
        "fiscal_year": 2025,
        "doc_type_code": "shoshu",      # ← 招集通知モード
        "use_mock": True,               # 開発時はモック
    }
)
result = response.json()
```

`doc_type_code: "shoshu"` を指定するだけで、M1〜M5が全て招集通知向けの処理に切り替わる。

### 5-2. M3ギャップ分析の出力例

以下は、プライム上場企業の招集通知を解析した際の M3 ギャップ分析出力例だ。

```json
{
  "gap_analysis": [
    {
      "law_id": "gc-2025-001",
      "title": "スキルマトリックスの招集通知への記載",
      "status": "充足",
      "matched_sections": ["第1号議案 取締役選任の件"],
      "evidence": "スキルマトリックス（取締役会スキル一覧）が掲載されています",
      "confidence": 0.92
    },
    {
      "law_id": "gm-2025-001",
      "title": "電子提供制度の導入",
      "status": "不足",
      "matched_sections": ["招集通知発送方法"],
      "evidence": "電子提供措置の開始日の記載が見当たりません",
      "confidence": 0.85,
      "missing_items": [
        "電子提供措置開始日（総会3週間前）",
        "ウェブサイトURL（会社法所定事項の掲載先）"
      ]
    },
    {
      "law_id": "gc-2025-004",
      "title": "サステナビリティ連動型役員報酬",
      "status": "未記載",
      "matched_sections": [],
      "evidence": "サステナビリティ連動KPIに関する記載が確認できませんでした",
      "confidence": 0.78
    }
  ]
}
```

### 5-3. M4松竹梅提案の出力サンプル

M4では、ギャップに対して「松（理想）」「竹（標準）」「梅（最低限）」の3水準で改善提案を生成する。

**gm-2025-001（電子提供措置）の不足に対する提案:**

```
【梅（最低限）】
招集通知の「電子提供措置」欄に以下を追記してください:
「当社は、本招集通知について、改正会社法に基づく電子提供措置を実施します。
電子提供措置の開始日は○年○月○日（株主総会の3週間前）です。
電子提供措置に係る事項は、当社ウェブサイト（https://example.com/ir）に
掲載いたします。」

【竹（標準）】
上記に加え、書面交付請求への対応方針も記載する:
「書面による提供を希望される株主様は、○年○月○日までに
ご請求ください（行使基準日現在の株主名簿に記録された住所へ郵送します）。」

【松（理想）】
電子提供措置URL・書面請求期限・QRコードでのアクセス案内を記載し、
同内容を英語版でも提供する（プライム上場企業の対機関投資家標準）。
スマートフォン対応ページとして電子提供ページを整備し、
議決権行使URLと一体化した UX を提供する。
```

---

## 6. テスト設計（TestShoshuDocType パターン）

### 6-1. テストクラスの全体構成

`scripts/test_m1_pdf_agent.py` に追加した `TestShoshuDocType` クラスは15件のテストで構成される。

```python
class TestShoshuDocType(unittest.TestCase):
    """
    TEST 7: 招集通知（shoshu）書類種別対応テスト

    手計算検証（CHECK-7b）:
      SHOSHU_SECTION_KEYWORDS: 12件
      SHOSHU_HEADING_PATTERNS: 8件
    """
```

テストは4つのグループに分類されている。

**グループ 7-1: `_is_heading_line_for_doc_type` の判定テスト（4件）**
```python
def test_shoshu_heading_gian_detected(self):
    """「第N号議案」が shoshu 見出しとして認識される"""
    self.assertTrue(
        _is_heading_line_for_doc_type("第1号議案 取締役選任の件", "shoshu")
    )

def test_default_doc_type_is_yuho(self):
    """デフォルト引数（yuho）では shoshu 専用パターンは検出されない"""
    # 有報パターンは認識される
    self.assertTrue(_is_heading_line_for_doc_type("第一部 企業情報"))
    # shoshu 専用パターンはデフォルトでは認識されない
    self.assertFalse(
        _is_heading_line_for_doc_type("第1号議案 取締役選任の件")
    )
```

**グループ 7-2: `split_sections_from_text` の分割テスト（4件）**
```python
def test_split_shoshu_default_yuho_backward_compat(self):
    """デフォルト引数と doc_type='yuho' の結果が完全一致（後方互換保証）"""
    mock_yuho = "第一部 企業情報\n企業情報\n\n第二部 保証会社情報\n情報\n"
    sections_default = split_sections_from_text(mock_yuho)
    sections_yuho = split_sections_from_text(mock_yuho, doc_type="yuho")
    self.assertEqual(
        [s.heading for s in sections_default],
        [s.heading for s in sections_yuho],
    )
```

**グループ 7-3: `get_shoshu_sections` のフィルタテスト（3件）**

**グループ 7-4: 定数の手計算検証（4件）**
```python
def test_total_keyword_count_is_12(self):
    """SHOSHU_SECTION_KEYWORDS は手計算で12件"""
    self.assertEqual(len(SHOSHU_SECTION_KEYWORDS), 12)

def test_heading_patterns_count_is_8(self):
    """SHOSHU_HEADING_PATTERNS は手計算で8件"""
    self.assertEqual(len(SHOSHU_HEADING_PATTERNS), 8)
```

### 6-2. 後方互換テストの重要性

新しい機能を追加するとき、**既存機能が壊れていないことの証明** が最重要だ。本実装では既存テスト32件が後方互換を保証するテストスイートとして機能している。

```bash
# テスト全件実行（47件全PASS が要件）
python -m pytest scripts/test_m1_pdf_agent.py -v

# 出力例:
# test_m1_pdf_agent.py::TestShoshuDocType::test_shoshu_heading_gian_detected PASSED
# test_m1_pdf_agent.py::TestShoshuDocType::test_default_doc_type_is_yuho PASSED
# ...
# 47 passed in 0.23s
```

### 6-3. キーワード手計算検証の意義

`test_total_keyword_count_is_12` のような「定数のカウント検証」は、一見すると意味のないテストに見える。しかし実際には重要な役割がある。

**意図せぬ追加・削除を防ぐ**: 誰かがキーワードをコピペで重複追加したり、リファクタリング中に誤って削除したりしたとき、テストが即座に失敗する。

**ドキュメントとしての役割**: テストコードのコメントに手計算リストが記載されているため、「なぜ12件なのか」が一目でわかる。

```python
# テストコードのコメント = 仕様ドキュメント
"""
SHOSHU_SECTION_KEYWORDS:
  1. "議案"               6. "株主提案"
  2. "取締役選任"         7. "報告事項"
  3. "役員報酬"           8. "決議事項"
  4. "定款変更"           9. "議決権"
  5. "監査役選任"        10. "社外取締役"
                         11. "スキルマトリックス"
                         12. "コーポレートガバナンス"
合計: 12件
"""
```

---

## 7. まとめ

### 本実装で実現したこと

| 機能 | 詳細 |
|------|------|
| 書類種別拡張 | `doc_type="shoshu"` 1つで招集通知解析モードに切替 |
| 法令チェック | CGコード2021・改正会社法2023に対応した16項目 |
| 後方互換 | 有報（yuho）処理への影響ゼロ（テスト32件で保証） |
| 松竹梅提案 | 電子提供制度・スキルマトリックス等の不足箇所を自動提案 |
| テスト設計 | 手計算検証を含む15件のシナリオテスト |

### 対応市場別の活用ポイント

| 市場 | 特に重要な項目 | 理由 |
|------|-------------|------|
| プライム | gc-2025-001（スキルマトリックス）・gc-2025-004（SSBJ連動報酬） | CGコード義務項目・機関投資家要求 |
| スタンダード | gm-2025-001（電子提供）・gm-2025-002（発送期限） | 法定義務であり漏れが許されない |
| グロース | gm-2025-005（取締役選任）・gm-2025-009（定款変更） | 新興企業でも会社法準拠は必須 |

### 次のステップ

**e-Gov法令API連携**
現在は法令テキストをYAMLに静的定義しているが、[e-Gov法令API](https://laws.e-gov.go.jp/api/1/lawtext) と連携することで、会社法・会社法施行規則の最新条文を動的に取得し、YAMLの自動更新が可能になる。

**英語版招集通知の対応**
CGコード補充原則1-2④はプライム上場企業への英語版招集通知提供を推奨している。英語テキストへの対応（ENGLISH_SHOSHU_SECTION_KEYWORDS等）は次期バージョンの実装候補だ。

**機械学習モデルによるスコアリング**
現在のルールベース照合に加え、招集通知の記載品質をスコアリングする機械学習モデルを組み合わせることで、「法令準拠はしているが説明が不十分」なケースも検出できる。

**招集通知の時系列比較**
前年の招集通知と比較して、「今年から削除された開示項目」「新たに追加すべきCGコード項目」を自動でフラグ付けする機能も計画中だ。

---

## ソースコード

disclosure-multiagent の主要ファイル構成:

```
disclosure-multiagent/
├── laws/
│   ├── shareholder_notice_2025.yaml  # 招集通知チェックリスト（16件）
│   ├── human_capital_2024.yaml       # 人的資本（有報用）
│   └── ssbj_2025.yaml               # SSBJ気候変動開示（有報用）
├── scripts/
│   ├── m1_pdf_agent.py              # PDF解析（doc_type="shoshu"対応）
│   ├── m2_law_context_agent.py      # 法令コンテキスト生成
│   ├── m3_gap_analysis_agent.py     # ギャップ分析
│   ├── m4_proposal_agent.py         # 松竹梅提案生成
│   └── test_m1_pdf_agent.py         # テスト（47件）
└── api/
    └── models/schemas.py            # DocTypeCode enum
```

招集通知の法令チェック自動化は、年1回の総会対応を効率化するだけでなく、機関投資家との対話品質を高める基盤にもなる。SSBJ対応（2027年3月期〜義務化）との連携も含め、コーポレートガバナンスの高度化に向けた投資として位置付けていただきたい。
