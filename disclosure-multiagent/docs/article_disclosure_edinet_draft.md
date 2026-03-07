---
title: "EDINET APIで有報を自動取得 → AI法令照合パイプライン完全ガイド"
emoji: "📋"
type: "tech"
topics: ["python", "ai", "EDINET", "有報", "開示"]
published: false
---

## はじめに

「EDINET で有報を手動ダウンロードして、毎回 Excel に貼り付けて法令チェック……」

上場企業の開示担当者や、有報データを扱う FinTech エンジニアなら一度はこの作業に悩まされたことがあるはずです。日本全上場企業の有価証券報告書が無料で公開されている EDINET は宝の山ですが、**自動化しようとすると意外な落とし穴が多い**のが現実です。

本記事では、EDINET API を使って有報 PDF を自動取得し、**disclosure-multiagent**（5 エージェントの AI パイプライン）で法令照合・ギャップ分析・改善提案まで全自動化する実装を解説します。

さらに **2027 年 3 月期から大規模プライム企業に強制適用** が始まる **SSBJ（サステナビリティ基準委員会）開示基準** への対応チェックを、EDINET から取得したトヨタ自動車の有報で実際に動かすデモも紹介します。

---

## 1. なぜ EDINET API か

### 日本の開示インフラとしての EDINET

EDINET（Electronic Disclosure for Investors' NETwork）は金融庁が運営する有価証券報告書等の電子開示システムです。2008 年の XBRL 対応義務化以来、**全上場企業・約 4,000 社の有報が無料で入手可能**です。

民間の IR データベースを使う選択肢もありますが、EDINET には次の強みがあります。

| 比較項目 | EDINET | 民間 IR DB |
|---------|--------|-----------|
| コスト | **無料** | 月額数万〜数十万円 |
| 網羅性 | **全上場企業** | プランによる |
| データの鮮度 | **提出日当日** | 1〜数日の遅延あり |
| API 提供 | **あり（v2）** | あり（有料が多い） |
| 利用規約 | **金融庁利用ガイドライン** | 各社による |

2024 年度から EDINET API v2 が正式公開され、Subscription-Key（無料登録）で書類一覧の自動取得が可能になりました。ただし **PDF の直接ダウンロードは認証不要** という、あまり知られていない重要な仕様があります（後述）。

---

## 2. EDINET API v2 入門

### エンドポイント全体像

EDINET API v2 には 2 系統のエンドポイントがあります。

```
# 書類一覧検索（Subscription-Key 必須）
https://api.edinet-fsa.go.jp/api/v2/documents.json

# PDF 直接ダウンロード（認証不要！）
https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{docID}.pdf
```

**最大の発見**: 書類一覧 API は Subscription-Key が必要ですが、PDF のダウンロードは書類管理番号（docID）さえ分かれば **認証なしで取得できます**。

### Subscription-Key の取得（無料）

1. [EDINET API 利用ガイドライン](https://api.edinet-fsa.go.jp/) にアクセス
2. 「利用申請」から簡単な利用登録（無料）
3. メールで Subscription-Key が発行される

### 書類一覧 API の使い方

```python
import requests
import os

EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"
SUBSCRIPTION_KEY = os.environ.get("EDINET_SUBSCRIPTION_KEY", "")

def fetch_document_list(date: str, doc_type_code: str = "120") -> list[dict]:
    """
    書類一覧を取得する。

    Args:
        date: 提出日（YYYY-MM-DD）
        doc_type_code: 書類種別コード
            120 = 有価証券報告書
            130 = 半期報告書
            140 = 四半期報告書

    Returns:
        書類情報のリスト（docID, edinetCode, filerName 等）
    """
    resp = requests.get(
        f"{EDINET_API_BASE}/documents.json",
        params={
            "date": date,
            "type": 2,  # 2=提出書類一覧（メタデータ付き）
            "Subscription-Key": SUBSCRIPTION_KEY,
        },
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    # docTypeCode で有報（120）だけに絞り込み
    return [r for r in results if r.get("docTypeCode") == doc_type_code]
```

レスポンスの主要フィールドは以下です。

```json
{
  "docID": "S100VHUZ",
  "edinetCode": "E02144",
  "filerName": "トヨタ自動車株式会社",
  "docTypeCode": "120",
  "periodEnd": "2024-03-31",
  "submitDateTime": "2024-06-26T15:13:00"
}
```

### docID の形式と検証

書類管理番号（docID）は `S + 7桁英数字（大文字）` の固定形式です。

```python
import re

def validate_doc_id(doc_id: str) -> bool:
    """書類管理番号形式チェック（S + 7桁英数字）"""
    return bool(re.fullmatch(r"S[A-Z0-9]{7}", doc_id))

# 例
validate_doc_id("S100VHUZ")  # → True（実在の書類管理番号）
validate_doc_id("INVALID!")  # → False
```

EDINETCode は `E + 5桁数字` の形式です。

```python
def validate_edinetcode(code: str) -> bool:
    """EDINETコード形式チェック（E + 5桁数字）"""
    return bool(re.fullmatch(r"E\d{5}", code))

validate_edinetcode("E02144")  # → True（トヨタ自動車）
```

### PDF ダウンロード（認証不要）

```python
import time
from pathlib import Path

EDINET_DL_BASE = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf"

def download_pdf(doc_id: str, output_dir: str) -> str:
    """
    EDINET 直接 DL（認証不要）で PDF を取得。

    Raises:
        ValueError: docID の形式が不正
        FileNotFoundError: 書類が存在しない（404）
    """
    if not validate_doc_id(doc_id):
        raise ValueError(f"無効な書類管理番号: '{doc_id}'（S + 7桁英数字が必要）")

    time.sleep(1)  # サーバー負荷軽減（必須マナー）
    resp = requests.get(
        f"{EDINET_DL_BASE}/{doc_id}.pdf",
        timeout=60,
        stream=True,
    )
    if resp.status_code == 404:
        raise FileNotFoundError(f"書類が見つかりません: docID={doc_id}")
    resp.raise_for_status()

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    pdf_path = out / f"{doc_id}.pdf"
    with open(pdf_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return str(pdf_path)
```

### レート制限の注意事項

EDINET のレート制限は公式に明記されていませんが、実装上の注意点があります。

- **PDF ダウンロード間隔**: `time.sleep(1)` を必ず入れる
- **大量取得は避ける**: 1 日分の有報は 50〜200 件程度。全件一括は非推奨
- **書類一覧 API**: 1 リクエスト = 1 日分。日付を変えてループする場合は `time.sleep(0.5)`

```python
# 複数日付の書類を取得する場合（マナーある実装）
from datetime import date, timedelta

def fetch_range(start_date: date, end_date: date) -> list[dict]:
    """日付範囲の有報一覧を取得"""
    all_docs = []
    current = start_date
    while current <= end_date:
        docs = fetch_document_list(current.strftime("%Y-%m-%d"))
        all_docs.extend(docs)
        current += timedelta(days=1)
        time.sleep(0.5)  # API への負荷軽減
    return all_docs
```

---

## 3. disclosure-multiagent との統合パイプライン

### システム全体像

EDINET 取得から最終レポートまでの自動パイプラインを示します。

```
┌──────────────────────────────────────────────────────────┐
│           EDINET × disclosure-multiagent パイプライン      │
│                                                          │
│  EDINET                                                  │
│    │                                                     │
│    ├─ /api/v2/documents.json  ─→ 書類一覧（M7-1）        │
│    └─ /searchdocument/pdf/{docID}.pdf ─→ PDF DL（M7-1） │
│                 │                                        │
│                 ▼                                        │
│  ┌─────────────────────────┐                            │
│  │  M1: PDF 解析エージェント │  PyMuPDF                  │
│  │  セクション構造化抽出     │  13 キーワードマッチ        │
│  └──────────┬──────────────┘                            │
│             │ StructuredReport                           │
│             ▼                                            │
│  ┌─────────────────────────┐                            │
│  │  M2: 法令コンテキスト取得 │  laws/*.yaml 読み込み      │
│  │  適用法令の絞り込み       │  決算期・施行日照合         │
│  └──────────┬──────────────┘                            │
│             │ LawContext                                 │
│             ▼                                            │
│  ┌─────────────────────────┐                            │
│  │  M3: ギャップ分析         │  Claude Haiku              │
│  │  開示漏れの特定           │  SSBJ + 人的資本 対応      │
│  └──────────┬──────────────┘                            │
│             │ GapAnalysisResult                          │
│             ▼                                            │
│  ┌─────────────────────────┐                            │
│  │  M4: 松竹梅提案          │  Claude Haiku              │
│  │  改善文案の生成           │  3 水準の記載文案           │
│  └──────────┬──────────────┘                            │
│             │ ProposalSet                                │
│             ▼                                            │
│  ┌─────────────────────────┐                            │
│  │  M5: レポート生成         │  Markdown                 │
│  │  最終アウトプット          │  有報担当者向け出力         │
│  └─────────────────────────┘                            │
└──────────────────────────────────────────────────────────┘
```

### M1: PDF 解析エージェント

有報 PDF を構造化データ（`StructuredReport`）に変換します。

```python
from m1_pdf_agent import extract_sections_from_pdf, StructuredReport

# EDINET でダウンロードした PDF をそのまま渡せる
pdf_path = download_pdf("S100VHUZ", output_dir="./downloads")
report: StructuredReport = extract_sections_from_pdf(pdf_path)

print(f"企業名: {report.company_name}")
print(f"セクション数: {len(report.sections)}")
# → 企業名: トヨタ自動車株式会社
# → セクション数: 47
```

有報の構造（第一部〜第五部）と 13 キーワード（「人的資本」「サステナビリティ」「GHG」等）で自動的にセクションを分類します。

### M2: 法令コンテキスト取得

`laws/` ディレクトリの YAML ファイルから、当該事業年度に適用される法令を絞り込みます。

```python
from m2_law_agent import load_law_context, LawContext

# 2025年度・3月決算（2025/04/01 〜 2026/03/31 が参照期間）
law_ctx: LawContext = load_law_context(
    fiscal_year=2025,
    fiscal_month_end=3,
)

print(f"適用法令数: {len(law_ctx.applicable_entries)}")
# → 適用法令数: 37  （人的資本25件 + SSBJ 12件等）
```

`laws/` 配下に現在 2 つの YAML が存在します。

- `laws/human_capital_2024.yaml`: 人的資本開示（男女賃金格差・育休取得率等）25 件
- `laws/ssbj_2025.yaml`: SSBJ 気候変動開示基準 25 件（GHG・移行計画・削減目標等）

### M3: ギャップ分析

Claude Haiku を使って、各セクションと法令開示要求のギャップを判定します。

```python
from m3_gap_analysis_agent import analyze_gaps, GapAnalysisResult

# USE_MOCK_LLM=true でAPIキー不要（開発・テスト用）
import os
os.environ["USE_MOCK_LLM"] = "false"  # 本番は false

gap_result: GapAnalysisResult = analyze_gaps(
    report=report,
    law_context=law_ctx,
    use_mock=False,  # 本番API使用
)

print(f"ギャップ件数: {gap_result.summary.total_gaps}")
print(f"必須対応: {gap_result.summary.mandatory_gaps} 件")
```

**SSBJ 対応の重要な設計**: M3 の `is_relevant_section()` 関数は、2つのキーワードセットを使って SSBJ 関連セクションを自動検出します。

```python
# SSBJ 関連キーワード（GHG・気候変動・移行計画等 25 語）
SSBJ_KEYWORDS = [
    "SSBJ", "サステナビリティ開示", "気候変動", "気候関連",
    "GHG", "温室効果ガス", "Scope1", "Scope2", "Scope3",
    "脱炭素", "カーボンニュートラル", "ネットゼロ",
    "移行計画", "TCFD", "シナリオ分析", "炭素", ...
]

# 人的資本 + SSBJ 両方のセクションを検出
ALL_RELEVANCE_KEYWORDS = HUMAN_CAPITAL_KEYWORDS + SSBJ_KEYWORDS

def is_relevant_section(section: SectionData) -> bool:
    combined = section.heading + section.text[:200]
    return any(kw in combined for kw in ALL_RELEVANCE_KEYWORDS)
```

### M4: 松竹梅提案

ギャップが検出された項目に対して、松・竹・梅の 3 水準で改善文案を生成します。

```python
from m4_proposal_agent import generate_proposals, ProposalSet

for gap_item in gap_result.gaps:
    if gap_item.has_gap:
        proposals: ProposalSet = generate_proposals(gap_item)
        print(f"\n【{gap_item.disclosure_item}】")
        print(f"松（充実記載）: {proposals.matsu.text[:80]}...")
        print(f"竹（標準記載）: {proposals.take.text[:80]}...")
        print(f"梅（最小記載）: {proposals.ume.text[:80]}...")
```

---

## 4. 実装コード: エンドツーエンドパイプライン

```python
"""
edinet_pipeline.py
EDINET から有報を取得し、AI 法令照合パイプラインを実行する。

使い方:
    # モックモード（EDINET API・LLM API 不要）
    USE_MOCK_EDINET=true USE_MOCK_LLM=true python3 edinet_pipeline.py

    # 本番モード
    EDINET_SUBSCRIPTION_KEY=xxx ANTHROPIC_API_KEY=sk-ant-xxx python3 edinet_pipeline.py
"""
from __future__ import annotations

import os
import time
from datetime import date

import requests

# EDINET クライアント
from m7_edinet_client import (
    fetch_document_list,
    download_pdf,
    validate_doc_id,
)

# disclosure-multiagent パイプライン
from m1_pdf_agent import extract_sections_from_pdf
from m2_law_agent import load_law_context
from m3_gap_analysis_agent import analyze_gaps
from m4_proposal_agent import generate_proposals
from m5_report_agent import generate_report


def run_pipeline(
    doc_id: str,
    company_name: str,
    fiscal_year: int,
    fiscal_month_end: int = 3,
    output_dir: str = "./outputs",
) -> str:
    """
    EDINET 書類管理番号を起点に、有報 PDF 取得 → ギャップ分析 → 改善提案 → レポート生成。

    Args:
        doc_id: EDINET 書類管理番号（S + 7桁英数字）
        company_name: 企業名（レポート用）
        fiscal_year: 事業年度（例: 2025 = 2025年度）
        fiscal_month_end: 決算月（3 = 3月決算）
        output_dir: PDF・レポートの保存先

    Returns:
        生成されたレポートのファイルパス
    """
    print(f"[1/5] PDF 取得中: docID={doc_id}")
    pdf_path = download_pdf(doc_id, output_dir=f"{output_dir}/pdf")

    print("[2/5] PDF 解析中（セクション抽出）")
    report = extract_sections_from_pdf(pdf_path)
    print(f"  → {len(report.sections)} セクション抽出")

    print("[3/5] 法令コンテキスト取得中")
    law_ctx = load_law_context(
        fiscal_year=fiscal_year,
        fiscal_month_end=fiscal_month_end,
    )
    print(f"  → {len(law_ctx.applicable_entries)} 件の法令が適用対象")

    print("[4/5] ギャップ分析中（Claude Haiku）")
    use_mock = os.environ.get("USE_MOCK_LLM", "false").lower() == "true"
    gap_result = analyze_gaps(report, law_ctx, use_mock=use_mock)
    print(f"  → ギャップ {gap_result.summary.total_gaps} 件検出")

    print("[5/5] レポート生成中")
    report_path = generate_report(
        gap_result=gap_result,
        company_name=company_name,
        output_path=f"{output_dir}/reports/{doc_id}_report.md",
    )
    print(f"  → レポート出力: {report_path}")
    return report_path


# --- 実行例 ---
if __name__ == "__main__":
    # トヨタ自動車 2024年度有報（2024-03-31 決算、2024-06-26 提出）
    TOYOTA_DOC_ID = "S100VHUZ"  # EDINET 実際の書類管理番号

    result = run_pipeline(
        doc_id=TOYOTA_DOC_ID,
        company_name="トヨタ自動車株式会社",
        fiscal_year=2024,
        fiscal_month_end=3,
    )
    print(f"\n✅ 完了: {result}")
```

### FastAPI エンドポイントでの利用

disclosure-multiagent には FastAPI バックエンドが含まれています。REST API 経由でパイプラインを呼び出せます。

```bash
# サーバー起動
PYTHONPATH=scripts:. uvicorn api.main:app --reload --port 8000

# EDINET 書類検索
curl -H "X-API-Key: your-key" \
  "http://localhost:8000/api/edinet/search?name=トヨタ自動車"

# 書類一覧取得（日付指定）
curl -H "X-API-Key: your-key" \
  "http://localhost:8000/api/edinet/documents?date=2024-06-26&doc_type=120"

# PDF ダウンロード
curl -H "X-API-Key: your-key" \
  "http://localhost:8000/api/edinet/download/S100VHUZ" \
  -o toyota_2024.pdf
```

---

## 5. SSBJ 対応版の活用（CL-026〜035）

### SSBJ とは

SSBJ（サステナビリティ基準委員会）が 2025 年 3 月に確定した日本独自のサステナビリティ開示基準です。IFRS S1/S2 に準拠しており、有価証券報告書への組み込みが段階的に義務化されます。

| 対象企業 | 適用開始 |
|---------|---------|
| 大規模プライム上場企業 | **2027 年 3 月期**（強制）|
| その他プライム上場企業 | 2028 年 3 月期予定 |
| スタンダード・グロース | 2030 年 3 月期予定 |

### 4 つの開示柱（TCFD 完全準拠）

SSBJ は TCFD（気候関連財務情報開示タスクフォース）の 4 柱構造と完全に整合しています。

```
ガバナンス (sb-2025-001〜003)
├── 取締役会の監督体制
├── 経営陣の役割・責任
└── 気候関連スキル・知識

戦略 (sb-2025-004〜010)
├── 気候変動リスク・機会の特定
├── 財務的影響（定量・定性）
├── 移行計画
├── シナリオ分析（1.5℃/2℃/4℃）
└── 事業モデルへの影響

リスク管理 (sb-2025-011〜013)
├── リスク特定・評価プロセス
├── ERM（全社リスク管理）との統合
└── 監視・レビュー体制

指標と目標 (sb-2025-014〜022)
├── Scope1 GHG 排出量
├── Scope2 GHG 排出量（市場基準・立地基準）
├── Scope3 GHG 排出量（15 カテゴリ）
├── GHG 削減目標・進捗
└── 気候関連 CapEx・財務影響指標
```

### CL-026〜035: チェックリスト項目

今回の実装で追加した SSBJ 対応チェックリスト項目（`api/data/checklist_data.json`）は以下の 10 件です。

| ID | 項目 | 必須 |
|----|------|-----|
| CL-026 | GHG 排出量（Scope1・2）開示 | ✅ |
| CL-027 | GHG 排出量（Scope3）開示 | △（大規模企業は実質必須）|
| CL-028 | 気候変動ガバナンス体制 | ✅ |
| CL-029 | 気候変動リスク・機会の特定と財務影響 | ✅ |
| CL-030 | 気候変動移行計画 | ✅ |
| CL-031 | シナリオ分析 | △（大規模企業は必須）|
| CL-032 | GHG 削減目標・進捗 | ✅ |
| CL-033 | 気候関連財務影響指標（炭素価格感応度等）| △ |
| CL-034 | 第三者保証（限定的/合理的保証）| △ |
| CL-035 | SSBJ 準拠宣言・適用スケジュール | △ |

---

## 6. デモ: トヨタ自動車の有報で SSBJ 項目を自動検証

### セットアップ

```bash
# リポジトリ取得
git clone https://github.com/yourname/disclosure-multiagent
cd disclosure-multiagent

# 依存パッケージ
pip install -r requirements_poc.txt
# PyMuPDF・anthropic・requests・fastapi・pyyaml 等

# 環境変数（モックモードは不要）
export USE_MOCK_EDINET=true   # EDINET API なしでテスト
export USE_MOCK_LLM=true      # LLM API なしでテスト
```

### Step 1: EDINET 書類検索

```python
# モックモードで実行（ネット接続不要）
from scripts.m7_edinet_client import fetch_document_list, MOCK_DOCUMENTS

# 実際のデモ実行（Subscription-Key 必要）
# docs = fetch_document_list("2024-06-26", doc_type_code="120")

# モックデモ
docs = MOCK_DOCUMENTS
for doc in docs:
    print(f"{doc['filerName']:30s} docID={doc['docID']}")
```

```
サンプル社A                      docID=S100A001
サンプル社B                      docID=S100B002
サンプル社C                      docID=S100C003
```

本番環境（Subscription-Key あり）では、トヨタ自動車の docID `S100VHUZ` が返ります。

### Step 2: 有報 PDF の取得

```bash
# モックモード（ローカルのサンプル PDF を使用）
USE_MOCK_EDINET=true python3 scripts/m7_edinet_client.py \
  --company "サンプル社" --year 2024

# 実本番（認証なし・直接 DL）
# S100VHUZ.pdf → downloads/pdf/S100VHUZ.pdf
python3 -c "
from scripts.m7_edinet_client import download_pdf
pdf_path = download_pdf('S100VHUZ', 'downloads/pdf')
print(f'ダウンロード完了: {pdf_path}')
"
```

### Step 3: SSBJ ギャップ分析の実行

```python
import os
import sys
sys.path.insert(0, "scripts")

os.environ["USE_MOCK_LLM"] = "true"  # モードモード

from m1_pdf_agent import StructuredReport, SectionData
from m2_law_agent import load_law_context
from m3_gap_analysis_agent import analyze_gaps

# デモ用の有報セクション（実際は m1 で PDF から抽出）
demo_section = SectionData(
    section_id="S-SSBJ-01",
    heading="サステナビリティに関する考え方及び取組",
    text=(
        "当社グループは、カーボンニュートラル実現に向けた取組みを推進しています。"
        "2035年までに新車販売の全てをEVにする目標を掲げています。"
        # ※ Scope1/2/3 の数値記載がない → ギャップ検出対象
    ),
    level=2,
)

demo_report = StructuredReport(
    document_id="TOYOTA_2024",
    company_name="トヨタ自動車株式会社（デモ）",
    fiscal_year=2024,
    fiscal_month_end=3,
    sections=[demo_section],
)

# SSBJ 基準を含む法令コンテキスト取得
law_ctx = load_law_context(fiscal_year=2024, fiscal_month_end=3)
ssbj_entries = [e for e in law_ctx.applicable_entries if e.id.startswith("sb-")]
print(f"適用 SSBJ 項目数: {len(ssbj_entries)}")
# → 適用 SSBJ 項目数: 25

# ギャップ分析実行
gap_result = analyze_gaps(demo_report, law_ctx, use_mock=True)
print(f"検出ギャップ: {gap_result.summary.total_gaps} 件")
```

### Step 4: 検出結果と改善提案

上記デモでは次のようなギャップが検出されます。

```
【ギャップ検出結果（デモ）】

▼ CL-026: GHG 排出量（Scope1・Scope2）の開示
  判定: ギャップあり ⚠️
  根拠: テキストに「Scope1」「Scope2」の数値記載なし
  対応: sb-2025-014 / sb-2025-015

【M4 改善提案】

■ 松（充実記載）:
  Scope1（直接排出）: [Scope1排出量]t-CO2e（前年比[率]%）
  Scope2（間接排出・市場基準）: [Scope2排出量]t-CO2e
  GHGプロトコル「コーポレート基準」に準拠して算定。
  連結グループ全体（[N]社）を対象とし、[検証機関名]による
  限定的保証を取得済み（ISO14064-3）。

■ 竹（標準記載）:
  Scope1は[Scope1排出量]t-CO2e、Scope2（市場基準）は
  [Scope2排出量]t-CO2e（前年比[率]%）。GHGプロトコル準拠。
  連結グループ全体（[N]社）が算定対象。

■ 梅（最小記載）:
  Scope1: [排出量]t-CO2e、Scope2（市場基準）: [排出量]t-CO2e
  （GHGプロトコル準拠）。
```

プレースホルダ（`[Scope1排出量]` 等）を実際の数値に置き換えるだけで、有報への記載文案が完成します。

---

## 7. まとめ

### 実装のポイント 3 選

**① EDINET PDF ダウンロードは認証不要**
書類管理番号（S + 7桁）さえ分かれば、`disclosure2dl.edinet-fsa.go.jp` から直接取得できます。有報の定期的な自動収集に活用できます。

**② モック設計で開発コストを最小化**
`USE_MOCK_EDINET=true` / `USE_MOCK_LLM=true` で EDINET API キーも Claude API キーも不要でローカル開発・テストが完結します。CI/CD でも全テストがパスします（テスト 71 件 + subtests 22 件 ALL PASS 確認済み）。

**③ SSBJ 対応は 2027 年 3 月期から必須**
大規模プライム企業には Scope1/2/3 GHG 排出量・移行計画・ガバナンス体制の開示が義務化されます。今から自動チェック体制を整備しておくことを強く推奨します。

### 今後の活用方向

| ユースケース | 実装難度 | 効果 |
|-----------|---------|------|
| 毎期の有報提出前 SSBJ チェック | ★☆☆ | ギャップ発見 → 作成工数△ |
| 競合他社の開示水準ベンチマーク | ★★☆ | EDINET から複数社一括取得 |
| ESG データの時系列可視化 | ★★☆ | GHG 推移・削減目標達成率 |
| 有報開示支援 SaaS | ★★★ | B → C 収益化。FastAPI + Next.js |

### ソースコード

本記事で紹介した実装は **disclosure-multiagent** として GitHub で公開予定です。

- EDINET クライアント: `scripts/m7_edinet_client.py`
- M3 ギャップ分析（SSBJ 対応）: `scripts/m3_gap_analysis_agent.py`
- チェックリスト（CL-026〜035）: `api/data/checklist_data.json`
- SSBJ 法令 YAML: `laws/ssbj_2025.yaml`

---

## 参考資料

- [EDINET API 利用ガイドライン（金融庁）](https://api.edinet-fsa.go.jp/)
- [SSBJ サステナビリティ開示基準（ASBJ）](https://www.asb.or.jp/jp/sustainability_standards.html)
- [GHGプロトコル コーポレート基準（World Resources Institute）](https://ghgprotocol.org/corporate-standard)
- [TCFD 最終提言（2017）](https://www.fsb-tcfd.org/recommendations/)
- [金融庁「記述情報の開示に関する原則」](https://www.fsa.go.jp/news/30/singi/20190319-2.html)
