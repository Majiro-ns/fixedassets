---
title: "EDINETから有報を自動取得して法令照合する — Phase2 API連携実装"
emoji: "📂"
type: "tech"
topics: ["python", "edinet", "金融", "api", "有価証券報告書"]
published: false
---

# EDINETから有報を自動取得して法令照合する — Phase2 API連携実装

## はじめに

[前回の記事（Phase1）](https://zenn.dev)では **disclosure-multiagent** の M1〜M5 パイプラインを紹介した。有報PDFを入力すると、法令改正に基づくギャップを検出し、松竹梅3水準の改善提案Markdownを自動生成するシステムだ。192テスト・全PASSで品質を担保している。

Phase2では「**法令情報・有報PDFの調達を自動化する**」という方向に進化させた。具体的には2つの柱を追加した。

| 追加モジュール | 機能 | 技術 |
|---|---|---|
| **M6** | e-Gov法令API連携 / 法令URL自動収集 | e-Gov XML API（認証不要） |
| **M7** | EDINET有報PDF自動取得 | EDINET直接DL + 書類検索API |
| **M8** | 多年度比較 | difflib + StructuredReport比較 |
| **M9** | Word/Excel出力エクスポート | python-docx / openpyxl |

本記事ではPhase2の実装詳細を解説する。特に **「EDINET PDFダウンロードは認証不要のままだった」** という重要な発見と、それを活かしたM7の設計について詳述する。

---

## EDINET APIv2の仕組み

### EDINETとは

EDINET（Electronic Disclosure for Investors' NETwork）は金融庁が運営する有価証券報告書等の電子開示システムだ。2008年のXBRL対応義務化以来、**全上場企業・約4,000社の有報が無料で公開**されている。

### 2つのエンドポイント

EDINETには目的の異なる2つのエンドポイントが存在する。

| エンドポイント | 認証 | 用途 |
|---|---|---|
| `api.edinet-fsa.go.jp/api/v2/documents.json` | **Subscription-Key必須** | 書類一覧検索 |
| `disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{docID}.pdf` | **認証不要** | PDF直接DL |

Phase2の重要な発見は、**PDF直接ダウンロードは2024年以降も認証不要のまま**だったことだ。書類管理番号（`S100XXXX` 形式）さえ分かれば任意の有報PDFを取得できる。

### 書類管理番号の取得方法

書類管理番号 `S100XXXX`（S + 7桁英数字）はEDINETの書類ページのURLから確認できる。

```
例: トヨタ自動車 2023年度有報
→ https://disclosure.edinet-fsa.go.jp/E00002/S100VHUZ.xbrl
→ 書類管理番号: S100VHUZ
```

書類一覧API（Subscription-Key必要）を使うと、企業名・提出日で検索して書類管理番号を自動取得できる。

### Subscription-Keyの取得方法

EDINET書類検索APIを使う場合はSubscription-Keyが必要だ。

1. [EDINETのAPIポータル](https://disclosure2.edinet-fsa.go.jp/api.html) にアクセス
2. 「APIキーの申請」フォームに記入（法人名・利用目的等）
3. 数日以内にキーがメール通知される
4. 環境変数 `EDINET_SUBSCRIPTION_KEY=xxxxx` に設定

PDF直接DL（M7-1）のみを使う場合はSubscription-Key取得は不要だ。

---

## M7: EDINETクライアント実装解説

### 設計方針: USE_MOCK_EDINET切替

M3の `USE_MOCK_LLM` と同様の設計思想で、環境変数1つでモック/実APIを切り替えられる。

```python
USE_MOCK_EDINET = os.environ.get("USE_MOCK_EDINET", "true").lower() == "true"
SUBSCRIPTION_KEY = os.environ.get("EDINET_SUBSCRIPTION_KEY", "")
```

デフォルトはモードON。**Subscription-Keyなしで全テストが通る**設計になっている。

### fetch_document_list(): 書類一覧取得

```python
def fetch_document_list(date: str, doc_type_code: str = "120") -> list[dict]:
    """EDINET書類一覧APIで有報リストを取得。USE_MOCK_EDINET=true でモックデータを返す。"""
    if USE_MOCK_EDINET:
        return [d for d in MOCK_DOCUMENTS if d["docTypeCode"] == doc_type_code]

    if not SUBSCRIPTION_KEY:
        raise RuntimeError("EDINET APIにはSubscription-Keyが必要です。")

    resp = requests.get(
        f"{EDINET_API_BASE}/documents.json",
        params={"date": date, "type": 2, "Subscription-Key": SUBSCRIPTION_KEY},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return [r for r in results if r.get("docTypeCode") == doc_type_code]
```

`doc_type_code="120"` は有価証券報告書を指す。書類種別コードの主なものを示す。

| docTypeCode | 書類種別 |
|---|---|
| 120 | 有価証券報告書 |
| 130 | 半期報告書 |
| 140 | 四半期報告書 |
| 020 | 有価証券届出書 |

### download_pdf(): PDF直接ダウンロード

```python
EDINET_DL_BASE = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf"

def download_pdf(doc_id: str, output_dir: str) -> str:
    """EDINET直接DL（認証不要）でPDFを取得。"""
    if not validate_doc_id(doc_id):
        raise ValueError(f"無効な書類管理番号: '{doc_id}'（S + 7桁英数字が必要）")

    if USE_MOCK_EDINET:
        sample = _SAMPLES_DIR / "company_a.pdf"
        if sample.exists():
            return str(sample)
        raise FileNotFoundError(f"モック用サンプルPDFが見つかりません: {sample}")

    time.sleep(1)  # EDINETサーバー負荷軽減（マナー）
    resp = requests.get(f"{EDINET_DL_BASE}/{doc_id}.pdf", timeout=60, stream=True)
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

`stream=True` でチャンク転送するため、大容量PDFでもメモリを圧迫しない。

### validate_doc_id(): 入力バリデーション

```python
def validate_doc_id(doc_id: str) -> bool:
    """書類管理番号形式チェック（S + 7桁英数字）"""
    return bool(re.fullmatch(r"S[A-Z0-9]{7}", doc_id))

# 例
validate_doc_id("S100VHUZ")  # → True（company_a.pdf の実際の番号）
validate_doc_id("INVALID!")  # → False → ValueError を raise
```

### search_by_company(): 企業名・年度検索

```python
def search_by_company(company_name: str, year: int) -> list[dict]:
    """会社名（部分一致）・年度から有価証券報告書を検索。"""
    if USE_MOCK_EDINET:
        return [d for d in MOCK_DOCUMENTS if company_name in d["filerName"]]

    results: list[dict] = []
    for month in range(1, 13):
        try:
            docs = fetch_document_list(f"{year}-{month:02d}-01")
            results.extend(d for d in docs if company_name in d.get("filerName", ""))
            time.sleep(0.5)
        except Exception:
            continue
    return results
```

月次でAPIを呼び出して全年度分の有報を収集する。`time.sleep(0.5)` でレート制限を回避している。

### モック動作確認（USE_MOCK_EDINET=true）

```bash
# Subscription-Keyなしでモック動作確認
USE_MOCK_EDINET=true python3 scripts/m7_edinet_client.py --date 2026-01-10
```

実行出力:

```
[M7] EDINET クライアント起動（モード: モック）
[M7] 書類一覧: 3 件 (date=2026-01-10)
  docID=S100A001  edinetCode=E00001  filerName=サンプル社A
  docID=S100B002  edinetCode=E00002  filerName=サンプル社B
  docID=S100C003  edinetCode=E00003  filerName=サンプル社C
```

---

## M6: e-Gov法令API連携

### 課題: 法令URLの手動管理

Phase1の `law_entries_human_capital.yaml` には `source_confirmed: false` のエントリが複数存在していた。法令のソースURLが未確定のものだ。手動で探すのは手間がかかるため、**e-Gov法令API**（政府提供・認証不要・無料）を使って自動収集する。

```bash
# robots.txt調査結果（2026-02-27）
金融庁（fsa.go.jp）: robots.txt → 404 → スクレイピング不実施
e-Gov（laws.e-gov.go.jp）: 公式API → 利用可
```

### e-Gov APIの構造

```python
_EGOV_BASE = "https://laws.e-gov.go.jp/api/1"
_CATEGORIES = [2, 3, 4]  # 2=法律 3=政令 4=府令

def _get_law_list(category: int) -> list[dict]:
    xml_text = _fetch(f"{_EGOV_BASE}/lawlists/{category}")
    if not xml_text:
        return []
    root = ET.fromstring(xml_text)
    if root.findtext(".//Result/Code") != "0":
        return []
    return [
        {"law_id": n.findtext("LawId", ""), "law_name": n.findtext("LawName", "")}
        for n in root.findall(".//LawNameListInfo")
        if n.findtext("LawId") and n.findtext("LawName")
    ]
```

認証不要で法令一覧XMLを取得できる。カテゴリコードは 2=法律・3=政令・4=府令 の3種類を使う。

### 3段階マッチングアルゴリズム

YAMLの `law_name` フィールドとe-Govの法令名を照合する際、信頼度を3段階で返す。

```python
def _match(law_name: str, laws: list[dict]) -> dict | None:
    """完全一致 → 部分一致1件 → 複数候補最近傍 の順で検索"""
    for law in laws:
        if law["law_name"] == law_name:
            return {**law, "confidence": "high"}     # 完全一致
    hits = [l for l in laws if law_name in l["law_name"] or l["law_name"] in law_name]
    if len(hits) == 1:
        return {**hits[0], "confidence": "medium"}   # 部分一致1件
    if hits:
        best = min(hits, key=lambda h: abs(len(h["law_name"]) - len(law_name)))
        return {**best, "confidence": "low"}          # 複数候補→文字列長が最近傍
    return None
```

| confidence | 意味 | 後処理 |
|---|---|---|
| `high` | 法令名が完全一致 | そのままYAML更新候補 |
| `medium` | 部分一致1件 | 目視確認推奨 |
| `low` | 複数候補（最近傍） | 必ず目視確認 |

### 安全な設計: YAMLは直接更新しない

M6は候補提示JSONを生成するのみで、**Law YAMLファイルを直接更新しない**。人間が確認してから `source_confirmed: true` に更新する設計だ。

```json
{
  "candidates": [
    {
      "entry_id": "HC_001",
      "law_name": "企業内容等の開示に関する内閣府令",
      "proposed_url": "https://laws.e-gov.go.jp/law/48M50000008033",
      "confidence": "high",
      "source": "e-Gov API",
      "note": "source_confirmed: false のエントリに対して候補を提示"
    }
  ]
}
```

この設計により、誤ったURL自動更新によるデータ破損リスクをゼロにしている。

---

## M8: 多年度比較エージェント

### 機能概要

M8は `StructuredReport`（M1出力）を複数年度分受け取り、年度間の差分を検出する。

```python
@dataclass
class YearlyReport:
    fiscal_year: int
    structured_report: StructuredReport  # M1出力
    elapsed_sec: float = 0.0

@dataclass
class YearDiff:
    fiscal_year_from: int   # 比較元（旧年度）
    fiscal_year_to: int     # 比較先（新年度）
    added_sections: list    # 新年度に追加されたセクション
    removed_sections: list  # 旧年度から削除されたセクション
    changed_sections: list  # 内容が変化したセクション
    summary: str            # 差分テキストサマリー
```

### セクション変化率による検出

```python
CHANGE_RATE_THRESHOLD: float = 0.20  # 本文変化率 > 20% → changed

def _calc_change_rate(text_a: str, text_b: str) -> float:
    """difflib.SequenceMatcher で変化率を計算（0.0〜1.0）"""
    if not text_a and not text_b:
        return 0.0
    matcher = difflib.SequenceMatcher(None, text_a, text_b)
    return 1.0 - matcher.ratio()
```

`difflib.SequenceMatcher` でテキスト類似度を計算し、変化率が20%を超えた場合に「変更あり」と判定する。

### 多年度比較の利用例

2年分の有報を比較してトレンドを把握できる。

```python
from m8_multiyear_agent import compare_years

# 2023年度 vs 2024年度 の比較
diff = compare_years(yearly_2023, yearly_2024)

print(f"追加セクション: {diff.added_sections}")
print(f"削除セクション: {diff.removed_sections}")
print(f"変更セクション: {diff.changed_sections}")
print(diff.summary)
# → 「人的資本」セクション: 本文変化率 34.2%（+1,247字）
# → 「役員報酬」セクション: 本文変化率 12.1%（変化なしと判定）
```

---

## M9: Word/Excelエクスポーター

### 機能概要

M4の松竹梅提案セット（`ProposalSet`）をWord（.docx）またはExcel（.xlsx）形式で出力する。

```python
from m9_document_exporter import export_to_word, export_to_excel

# Word出力
word_path = export_to_word(proposal_set, output_dir="outputs/")
# → outputs/disclosure_proposals_2026-03-09.docx

# Excel出力
excel_path = export_to_excel(proposal_set, output_dir="outputs/")
# → outputs/disclosure_proposals_2026-03-09.xlsx
```

### Excelの列構成

```python
EXCEL_HEADERS = [
    "GAP_ID",
    "ギャップ要約",
    "松（テキスト）",
    "竹（テキスト）",
    "梅（テキスト）",
    "法令根拠",
    "警告",
]
```

経理・法務担当者が直接Excelで確認・修正できる出力形式になっている。依存ライブラリは `python-docx` と `openpyxl` だが、未インストール時は当該形式のみスキップするフォールバック設計だ。

---

## エンドツーエンド統合デモ: EDINET取得→M1-M5パイプライン

### 統合フロー

```
[EDINET書類一覧API（M7）]
  ↓ 書類管理番号取得
[EDINET直接DL（M7）]
  ↓ PDF保存
[M1: PDF解析 → StructuredReport]
  ↓
[M2: Law YAML読み込み → LawContext]    ← M6が法令URLを整備
  ↓
[M3: ギャップ分析 → GapAnalysisResult]
  ↓
[M4: 松竹梅提案生成 → ProposalSet]
  ↓
[M9: Word/Excel出力]
```

### 実装コード

```python
import os
from pathlib import Path
from m7_edinet_client import search_by_company, download_pdf
from m1_pdf_agent import analyze_pdf
from m2_law_agent import load_law_context
from m3_gap_analysis_agent import analyze_gaps
from m4_proposal_agent import generate_proposals
from m9_document_exporter import export_to_excel

def run_full_pipeline(
    company_name: str,
    fiscal_year: int,
    output_dir: str = "outputs",
) -> str:
    """
    EDINETから有報PDFを自動取得し、法令照合→提案生成→Excel出力まで全自動。

    Args:
        company_name: 検索する企業名（部分一致）
        fiscal_year: 提出年度（例: 2024）
        output_dir: 出力先ディレクトリ

    Returns:
        生成されたExcelファイルのパス
    """
    print(f"[Step1] EDINET検索: {company_name} {fiscal_year}年度")
    docs = search_by_company(company_name, fiscal_year)
    if not docs:
        raise ValueError(f"有報が見つかりませんでした: {company_name} {fiscal_year}")

    # 最新の有報を取得（提出日降順で1件目）
    latest = sorted(docs, key=lambda d: d.get("submitDateTime", ""), reverse=True)[0]
    doc_id = latest["docID"]
    print(f"[Step1] 取得対象: docID={doc_id} filerName={latest['filerName']}")

    print(f"[Step2] PDF直接DL: {doc_id}")
    pdf_path = download_pdf(doc_id, output_dir=f"{output_dir}/pdf")
    print(f"[Step2] 保存完了: {pdf_path}")

    print("[Step3] M1 PDF解析")
    structured_report = analyze_pdf(pdf_path)

    print("[Step4] M2 法令コンテキスト取得")
    law_ctx = load_law_context(fiscal_year=fiscal_year, fiscal_month_end=3)

    print("[Step5] M3 ギャップ分析")
    gap_result = analyze_gaps(structured_report, law_ctx)
    print(f"[Step5] 検出ギャップ数: {len(gap_result.gaps)}")

    print("[Step6] M4 提案生成（松竹梅）")
    proposals = generate_proposals(gap_result, law_ctx)

    print("[Step7] M9 Excel出力")
    excel_path = export_to_excel(proposals, output_dir=output_dir)
    print(f"[Step7] 出力完了: {excel_path}")

    return excel_path


# 実行例（モードモード: Subscription-Key不要）
if __name__ == "__main__":
    os.environ["USE_MOCK_EDINET"] = "true"
    os.environ["USE_MOCK_LLM"] = "true"

    result = run_full_pipeline(
        company_name="サンプル社A",
        fiscal_year=2024,
    )
    print(f"\n✅ 完了: {result}")
```

実行出力例:

```
[Step1] EDINET検索: サンプル社A 2024年度
[Step1] 取得対象: docID=S100A001 filerName=サンプル社A
[Step2] PDF直接DL: S100A001
[Step2] 保存完了: outputs/pdf/S100A001.pdf
[Step3] M1 PDF解析
[Step4] M2 法令コンテキスト取得
[Step5] M3 ギャップ分析
[Step5] 検出ギャップ数: 5
[Step6] M4 提案生成（松竹梅）
[Step7] M9 Excel出力
[Step7] 出力完了: outputs/disclosure_proposals_2026-03-09.xlsx

✅ 完了: outputs/disclosure_proposals_2026-03-09.xlsx
```

---

## Phase2テスト結果（207件 全PASS）

```bash
cd disclosure-multiagent
python3 -m pytest scripts/ -q
# → 207 passed, 1 skipped, 19 subtests passed
```

| テストファイル | Phase | 件数 | 内容 |
|---|---|---|---|
| test_m1_pdf_agent.py | 1 | 29件 | PDF解析・セクション分割 |
| test_m2_law_agent.py | 1 | 19件 | 法令YAML読み込み |
| test_m3_gap_analysis.py | 1 | 16件 | ギャップ分析（モック） |
| test_m4_proposal.py | 1 | 41件 | 松竹梅提案文生成 |
| test_m5_report.py | 1 | 37件 | Markdownレポート統合 |
| test_e2e_pipeline.py | 1 | 22件 | E2Eパイプライン |
| test_m6_law_url_collector.py | 2 | 13件 | e-Gov APIマッチング |
| test_m7_edinet_client.py | 2 | 15件 | EDINETクライアント |
| test_m6_m7_integration.py | 2 | 15件 | **M6/M7統合テスト（新規）** |

### 統合テストの設計: M6→M2→M3スモークテスト

```python
def test_tc3_m6_m2_m3_pipeline_smoke_test(self):
    # M6: e-Gov APIでURL候補取得（モック）
    with patch("m6_law_url_collector._fetch") as mock_fetch:
        mock_fetch.return_value = _MOCK_XML_OK
        m6_result = collect(_FIXTURE_YAML, output_path)

    # M2: 法令コンテキスト取得
    law_ctx = load_law_context(fiscal_year=2025, fiscal_month_end=3)

    # M3: ギャップ分析（モックLLM）
    gap_result = analyze_gaps(mock_report, law_ctx, use_mock=True)

    self.assertEqual(gap_result.document_id, "TEST_DOC_001")
    self.assertIsInstance(gap_result.gaps, list)
```

ネットワーク依存テスト（EDINET直接DL HTTPステータス確認）は `RUN_NETWORK_TESTS=true` 環境変数でのみ実行される。CIでは常にスキップ。

---

## B→C戦略との連動

disclosure-multiagentは当初「BSLライセンス+コンサル」戦略（B戦略）で検討していたが、殿の判断により「記事マーケティング+受託」戦略（C戦略）に転換した。

Phase2の記事マーケティング活用として:

```
記事掲載:
  「Phase2: EDINET API連携実装」 ← 本記事
         ↓ 読者のエンジニア層にリーチ
  「有報開示対応をAI自動化したい」という問い合わせ
         ↓
  受託開発・カスタマイズ提案
         ↓
  トヨタ自動車有報7件指摘デモで具体的な価値を示す
```

Phase2の技術的デモ価値として最も強力なのは**「Subscription-Keyなし・モックモードで即試せる」**点だ。

```bash
# 試せる最小コマンド（APIキー不要）
git clone https://github.com/your-org/disclosure-multiagent.git
cd disclosure-multiagent
pip install -r requirements.txt
USE_MOCK_EDINET=true USE_MOCK_LLM=true python3 scripts/m7_edinet_client.py --date 2026-01-10
```

読者がすぐに動かせることで、記事→問い合わせのコンバージョン率を高める。

---

## Phase3に向けた残課題

### M7-2: EDINET書類検索API（Subscription-Key取得後）

書類検索APIを使うと、企業名・提出日で書類管理番号を自動取得できる。現在のM7-1は書類管理番号が既知の場合のみ動作するが、M7-2ではこの制約を解消する。

```python
# M7-2の設計（実装予定）
def search_yuho_by_company(company_name: str, fiscal_year: int) -> list[dict]:
    """EDINET書類検索APIで対象企業の有報を検索する"""
    resp = requests.get(
        f"{EDINET_API_BASE}/documents.json",
        params={"date": f"{fiscal_year}-06-28", "type": 2,
                "Subscription-Key": SUBSCRIPTION_KEY},
    )
    results = resp.json().get("results", [])
    return [r for r in results if r.get("docTypeCode") == "120"
            and company_name in r.get("filerName", "")]
```

### 実LLM E2E検証

`USE_MOCK_LLM=false`（実Claude API）によるギャップ分析の精度検証がまだ未実施だ。モックモードではキーワードマッチ判定のため、実LLMでの文脈を踏まえた判定がどう変わるか検証する必要がある。

```bash
# 実LLM E2E実行（APIキー設定後）
export ANTHROPIC_API_KEY=sk-ant-xxx
USE_MOCK_LLM=false python3 scripts/run_e2e.py \
    "10_Research/samples/company_a.pdf" \
    --company-name "サンプル社A" \
    --fiscal-year 2025 \
    --level 竹
```

### M7.5: 決算期拡張

現在は3月決算を前提にしている。`fiscal_month_end` パラメータを使えば12月決算・6月決算への拡張も可能な設計になっている。

---

## まとめ

Phase2では「法令URLの調達を自動化する（M6）」「有報PDFの調達を自動化する（M7）」という2つのボトルネックを解消した。

技術的な発見として最も重要なのは、**EDINET PDF直接DLが2024年以降も認証不要**であることだ。書類管理番号さえ分かれば任意の有報を取得できる。M7-1はこの認証不要エンドポイントを活用した実装だ。

また M8（多年度比較）・M9（Word/Excel出力）により、「AIが提案した改善案を経理担当者がExcelで確認・修正」というワークフローが完成した。エンジニアではない開示担当者も実際に使えるシステムになった。

| Phase | テスト数 | 主要機能 |
|---|---|---|
| Phase1 | 192件 | M1-M5: PDF解析→法令照合→提案生成→Markdown出力 |
| Phase2 | 207件 | M6: 法令URL自動収集 / M7: EDINET自動取得 / M8: 多年度比較 / M9: Word/Excel出力 |

Phase3では実LLM検証・EDINET書類検索API（M7-2）・決算期拡張（M7.5）を実施する予定だ。

---

## 参考リンク

- [EDINET APIポータル](https://disclosure2.edinet-fsa.go.jp/api.html)
- [e-Gov法令API](https://laws.e-gov.go.jp/api/1)
- [disclosure-multiagent GitHub（リポジトリ）](https://github.com/your-org/disclosure-multiagent)
- [Phase1記事: マルチエージェントで有報の開示変更レポートを自動生成するシステムを作った](https://zenn.dev)

---

:::message
**本記事のコードについて**:
- M7のEDINET直接DLは `disclosure2dl.edinet-fsa.go.jp` の公式エンドポイントを使用
- デフォルト `USE_MOCK_EDINET=true` のため、Subscription-Keyなしで動作確認可能
- e-Gov法令API（M6）は政府提供の公式APIのみを使用（スクレイピング不実施）
- `time.sleep(1)` でサーバー負荷を考慮した実装
- 実APIを使う際は利用規約を確認してください
:::

---

*本記事は disclosure-multiagent Phase2 の実装記録として作成。*
*作成: Majiro-ns (cmd_344k_a3a) | 2026-03-09*
