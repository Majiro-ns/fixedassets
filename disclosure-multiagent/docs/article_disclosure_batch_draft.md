---
title: "EDINETから有報を一括取得して多年度比較する — M6-M8バッチ処理実装"
emoji: "📊"
type: "tech"
topics: ["python", "edinet", "有価証券報告書", "llm", "バッチ処理"]
published: false
---

## はじめに

「トヨタ自動車の過去3年分の有報を並べて、サステナビリティ開示のどこが変わったか確認したい」——こんな要件に、あなたならどう答えますか。

EDINETを手動で開いて、年度ごとにPDFをダウンロードして、差分をExcelで追う……その作業を何社分も繰り返すのは現実的ではありません。

本記事では、**disclosure-multiagent** の Phase 2 バッチ処理レイヤー（M6〜M8）を解説します。

- **M6**: e-Gov 法令API から法令URLを自動収集し、`source_confirmed` 状態を管理
- **M7**: EDINET API から有報 PDF を日付・会社名・年度で一括取得
- **M8**: 複数年度の有報を比較し、セクションの追加・削除・変更を自動検出

これら3エージェントを組み合わせることで、「EDINETから複数社・複数年度の有報を取得し、開示内容の年次変化を AI で分析する」バッチ処理パイプラインが完成します。

---

## 1. disclosure-multiagent の全体アーキテクチャ

### M1〜M8 エージェント一覧

```
M1: PDFエージェント          有報PDFをテキスト・テーブルに構造化
M2: 法令エージェント          適用法令コンテキストをYAMLから生成
M3: ギャップ分析エージェント   LLMで有報×法令の充足状況を判定
M4: 松竹梅提案エージェント     不足項目の改善文案を3水準で生成
M5: レポートエージェント       分析結果をMarkdown/JSONでエクスポート
────────── Phase 2 ──────────
M6: 法令URL収集エージェント    e-Gov APIで法令URLを自動収集・検証
M7: EDINET クライアント        EDINET APIで有報PDFを一括取得
M8: 多年度比較エージェント     複数年度の有報差分を自動検出
```

本記事が対象とするのは M6〜M8 の「バッチ処理レイヤー」です。M1〜M5 の基本パイプラインは [記事①](https://zenn.dev/) を参照してください。

### なぜ Phase 2 が必要か

M1〜M5 は「1社1年度」の有報を処理する設計です。しかし実務では以下の課題があります。

1. **法令 URL の鮮度**: YAML に記載した法令参照URLが変更・廃止される可能性がある
2. **毎年の一括処理**: 決算期（3〜6月）に集中する有報提出を自動で捌く必要がある
3. **年次比較の需要**: 前年対比でどの開示項目が追加・変更されたかを把握したい

M6〜M8 はこれら3つの課題をそれぞれ解決するために設計されました。

---

## 2. M7: EDINET 有報 PDF 自動取得クライアント

### 2-1. EDINET API の2系統

M7 が使用する EDINET のエンドポイントは2種類です。

| 種別 | URL | 認証 |
|------|-----|------|
| 書類一覧 API | `https://api.edinet-fsa.go.jp/api/v2/documents.json` | **Subscription-Key 必要** |
| PDF 直接 DL | `https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{docID}.pdf` | **認証不要** |

書類一覧 API は日付・書類種別（docTypeCode）でフィルタリングできます。有価証券報告書の docTypeCode は **120** です。PDF のダウンロード自体は認証不要なので、docID さえ取得できれば APIキーなしでPDFを入手できます。

### 2-2. EDINET の入力バリデーション

```python
# scripts/m7_edinet_client.py より

def validate_edinetcode(code: str) -> bool:
    """EDINETコード形式チェック（E + 5桁数字）"""
    return bool(re.fullmatch(r"E\d{5}", code))


def validate_doc_id(doc_id: str) -> bool:
    """書類管理番号形式チェック（S + 7桁英数字）"""
    return bool(re.fullmatch(r"S[A-Z0-9]{7}", doc_id))
```

**EDINETコード**: `E00001` 形式（E + 5桁数字）。金融庁が各提出者に付与する識別子です。

**書類管理番号**: `S100A001` 形式（S + 7桁英数字）。書類1件ごとに付与されます。docID とも呼ばれます。

不正な形式が渡された場合は `ValueError` を早期に返す設計で、後続のAPIコールをムダにしません。

### 2-3. 書類一覧取得

```python
def fetch_document_list(date: str, doc_type_code: str = "120") -> list[dict]:
    """EDINET 書類一覧APIで有報リストを取得。USE_MOCK_EDINET=true でモックを返す。"""
    if USE_MOCK_EDINET:
        return [d for d in MOCK_DOCUMENTS if d["docTypeCode"] == doc_type_code]

    if not SUBSCRIPTION_KEY:
        raise RuntimeError(
            "EDINET API には Subscription-Key が必要です。"
            "環境変数 EDINET_SUBSCRIPTION_KEY を設定してください。"
        )

    resp = requests.get(
        f"{EDINET_API_BASE}/documents.json",
        params={"date": date, "type": 2, "Subscription-Key": SUBSCRIPTION_KEY},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return [r for r in results if r.get("docTypeCode") == doc_type_code]
```

`type=2` で提出書類の詳細情報を取得します（`type=1` はメタデータのみ）。取得結果を `docTypeCode == "120"`（有価証券報告書）でフィルタリングすることで、その日に提出された有報の一覧が得られます。

### 2-4. PDF ダウンロード

```python
def download_pdf(doc_id: str, output_dir: str) -> str:
    """EDINET直接DL（認証不要）でPDFを取得。"""
    if not validate_doc_id(doc_id):
        raise ValueError(f"無効な書類管理番号: '{doc_id}'（S + 7桁英数字が必要）")

    if USE_MOCK_EDINET:
        sample = _SAMPLES_DIR / "company_a.pdf"
        if sample.exists():
            return str(sample)
        raise FileNotFoundError(f"モック用サンプルPDFが見つかりません: {sample}")

    time.sleep(1)  # EDINET サーバー負荷軽減（マナー）
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

`stream=True` で大きなPDFも安全にダウンロードします。`chunk_size=8192`（8KB）でメモリ効率よく書き込みます。また `time.sleep(1)` でサーバー負荷を軽減しています。これは EDINET の利用規約でも推奨されているマナーです。

### 2-5. 会社名・年度での検索

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

「トヨタ自動車」を検索する場合、1〜12月の書類一覧を順に取得して `filerName` を部分一致でフィルタリングします。`time.sleep(0.5)` で月次APIコール間にインターバルを設けています。

### 2-6. 開発時の使い方

```bash
# モックモード（APIキー不要）
USE_MOCK_EDINET=true python3 scripts/m7_edinet_client.py --date 2026-01-10

# 実API（Subscription-Key 必要）
EDINET_SUBSCRIPTION_KEY=your-key python3 scripts/m7_edinet_client.py --date 2026-01-10

# 会社名+年度で検索
python3 scripts/m7_edinet_client.py --company トヨタ自動車 --year 2025
```

`USE_MOCK_EDINET=true`（デフォルト）の場合、実APIを叩かずにモックデータで動作します。開発・テスト時はAPIキー取得前にロジックを開発できます。

---

## 3. M6: 法令 URL 自動収集（e-Gov API 連携）

### 3-1. なぜ法令URLの管理が必要か

disclosure-multiagent の `laws/` ディレクトリには法令YAMLが格納されています。各エントリには `source`（法令参照URL）と `source_confirmed`（URLの有効性確認フラグ）があります。

```yaml
# laws/ssbj_2025.yaml の例
- id: sb-2025-001
  title: "SSBJ確定基準 S1 第13項 — ガバナンス開示"
  source: "https://www.ssb.or.jp/..."
  source_confirmed: false  # ← 未確認URLが存在する
```

法令URLは金融庁・内閣府・e-Govなど複数の政府サイトに分散しており、手動管理は困難です。M6 はこの課題を e-Gov 法令API で解決します。

### 3-2. robots.txt 調査と e-Gov API の選択

```python
# scripts/m6_law_url_collector.py
_ROBOTS_SUMMARY = (
    "fsa.go.jp: robots.txt→404。利用規約確認要、スクレイピング不実施。"
    " laws.e-gov.go.jp: robots.txt→HTML(未公開)。公式API(/api/1/)は政府提供のため利用可。"
)
```

実装前に robots.txt の調査を実施しました（2026-02-27）。

| サイト | robots.txt | 対応 |
|--------|-----------|------|
| `fsa.go.jp` | 404（未公開） | スクレイピング不実施・利用規約確認要 |
| `laws.e-gov.go.jp` | HTML（未公開） | **公式 API（/api/1/）のみ使用** |

`laws.e-gov.go.jp` は政府が提供する公式 API を持っており、認証不要で法令一覧を取得できます。このAPIを利用してスクレイピングを避けた適切な実装となっています。

### 3-3. e-Gov 法令リスト取得

```python
_EGOV_BASE = "https://laws.e-gov.go.jp/api/1"
_CATEGORIES = [2, 3, 4]  # 2=法律 3=政令 4=府令


def _get_law_list(category: int) -> list[dict]:
    """e-Gov API GET /api/1/lawlists/{category} で法令一覧を取得"""
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

カテゴリは **2（法律）・3（政令）・4（府令）** の3種を取得します。レスポンスはXML形式で、`Result/Code == "0"` が成功を示します。有価証券報告書関連の法令は主に「府令（カテゴリ4）」に含まれます。

### 3-4. 法令名マッチング（完全一致→部分一致の優先度）

```python
def _match(law_name: str, laws: list[dict]) -> Optional[dict]:
    """法令名で完全一致→部分一致の順で検索"""
    for law in laws:
        if law["law_name"] == law_name:
            return {**law, "confidence": "high"}
    hits = [l for l in laws if law_name in l["law_name"] or l["law_name"] in law_name]
    if len(hits) == 1:
        return {**hits[0], "confidence": "medium"}
    if hits:
        best = min(hits, key=lambda h: abs(len(h["law_name"]) - len(law_name)))
        return {**best, "confidence": "low"}
    return None
```

マッチング戦略には confidence レベルを設定しています。

| パターン | confidence | 意味 |
|---------|-----------|------|
| 完全一致 | `high` | YAML の law_name と e-Gov 法令名が完全に一致 |
| 部分一致（1件） | `medium` | どちらかが他方を包含する形で1件のみ一致 |
| 部分一致（複数） | `low` | 複数候補あり・文字数が最も近いものを採用 |
| 一致なし | — | スキップ（`skipped` に記録） |

`confidence: "high"` のみを自動適用し、`"medium"` 以下は人手確認が推奨されます。

### 3-5. 収集フロー

```python
def collect(yaml_path: Path, output_path: Path) -> dict:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    unconfirmed = [e for e in entries if not e.get("source_confirmed", False)]

    # e-Gov API で全カテゴリの法令リストを取得
    all_laws: list[dict] = []
    for cat in _CATEGORIES:
        laws = _get_law_list(cat)
        all_laws.extend(laws)

    # 各 source_confirmed:false エントリにURLを提案
    candidates, skipped = [], []
    for e in unconfirmed:
        m = _match(e.get("law_name", ""), all_laws)
        if m:
            candidates.append({
                "entry_id": e["id"],
                "proposed_url": _EGOV_URL.format(law_id=m["law_id"]),
                "confidence": m["confidence"],
                "note": "手動 YAML が最終権威。適用前に人手確認必須。",
            })
        else:
            skipped.append({"entry_id": e["id"], "reason": "e-Gov に一致なし"})

    # 結果をJSONで出力（YAMLは更新しない）
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result
```

**重要な設計思想**: M6 は YAML ファイルを**直接更新しません**。出力は `law_url_candidates.json` の「提案」であり、担当者が内容を確認してから YAML に反映する運用です。誤ったURLが法令照合に混入するリスクを最小化しています。

### 3-6. 実行例

```bash
# デフォルト（laws/law_entries_human_capital.yaml を対象）
python3 scripts/m6_law_url_collector.py

# 出力例
# 全エントリ: 12 / source_confirmed:false = 5 件
# e-Gov API 法令リスト取得中...
#   category=2: 847 件
#   category=3: 2,103 件
#   category=4: 1,456 件
#   ✅ HC_20230131_001: high → https://laws.e-gov.go.jp/law/405M60400040065
#   ✅ HC_20260220_001: medium → https://laws.e-gov.go.jp/law/406M60400040006
#   ⚠️  SSBJ_2025_001: 一致なし（スキップ）
```

---

## 4. M8: 複数年度比較エージェント

### 4-1. 設計の背景

F-08「複数年度の比較」要件は、有報の年次変化を把握するために設計されました。特に SSBJ 開示基準が段階的に強化される 2025〜2028 年の移行期間において、「前年から何が追加されたか」を自動検出する機能は実務で高い需要があります。

### 4-2. データクラス設計

```python
# scripts/m8_multiyear_agent.py より

@dataclass
class YearlyReport:
    """1年度分の有報データ（M1出力ラッパー）"""
    fiscal_year: int                       # 例: 2024
    structured_report: StructuredReport   # M1出力
    elapsed_sec: float = 0.0              # M1処理時間（秒）


@dataclass
class YearDiff:
    """2年度間の差分結果"""
    fiscal_year_from: int                  # 比較元（旧年度）
    fiscal_year_to: int                    # 比較先（新年度）
    added_sections: list[SectionData]      # 新規追加セクション
    removed_sections: list[SectionData]   # 削除されたセクション
    changed_sections: list[SectionData]   # 内容変化セクション（新年度版）
    summary: str                           # 差分テキストサマリー
```

`YearlyReport` は M1 の出力（`StructuredReport`）をラップするだけのシンプルな構造です。M1〜M5 の改変禁止制約（READ-ONLY参照のみ）の中で、既存モジュールを再利用する設計になっています。

### 4-3. 変化率計算（difflib.SequenceMatcher）

```python
CHANGE_RATE_THRESHOLD: float = 0.20  # 20% 超で「変更」判定


def _text_change_rate(old_text: str, new_text: str) -> float:
    """
    2つのテキストの変化率を計算（0.0〜1.0）
    変化率 = 1.0 - SequenceMatcher.ratio()

    手計算検証:
        old="abc", new="abc"    → ratio=1.0 → 変化率=0.0（変化なし）
        old="abc", new="xyz"    → ratio=0.0 → 変化率=1.0（全変化）
        old="abc", new="abcdef" → ratio=6/9=0.667 → 変化率=0.333（変化あり）
    """
    if not old_text and not new_text:
        return 0.0
    if not old_text or not new_text:
        return 1.0
    ratio = difflib.SequenceMatcher(None, old_text, new_text).ratio()
    return 1.0 - ratio
```

`difflib.SequenceMatcher` は Python 標準ライブラリで追加依存ゼロです。`ratio()` は「最長共通部分列」ベースの一致率（0.0〜1.0）を返します。変化率 = 1.0 - ratio で、**20% 以上の変化が検出されたセクションを「変更あり」と判定**します。

> 📝 **設計のポイント**: 閾値 20% は要件定義書 §3.2 F-08 で明示されています。軽微な表現修正（誤字修正等）で誤検知しない一方、開示内容の実質的な変更を捕捉できる値として設定されています。

### 4-4. セクション差分検出アルゴリズム

```python
def detect_section_changes(
    old: StructuredReport,
    new: StructuredReport,
) -> dict[str, list[SectionData]]:
    """
    アルゴリズム:
    1. 旧・新年度のセクションを見出し（heading）でインデックス化
    2. 追加 = 新年度のみに存在する heading のセクション
    3. 削除 = 旧年度のみに存在する heading のセクション
    4. 変更 = 両年度に存在し、変化率 > 20% のセクション
    """
    # heading でインデックス化（重複時は最初のものを使用）
    old_by_heading = {sec.heading: sec for sec in old.sections}
    new_by_heading = {sec.heading: sec for sec in new.sections}

    old_headings = set(old_by_heading.keys())
    new_headings = set(new_by_heading.keys())

    # 追加: 新年度のみに存在
    added = [new_by_heading[h] for h in sorted(new_headings - old_headings)]

    # 削除: 旧年度のみに存在
    removed = [old_by_heading[h] for h in sorted(old_headings - new_headings)]

    # 変更: 共通見出しで変化率 > CHANGE_RATE_THRESHOLD
    changed = []
    for heading in sorted(old_headings & new_headings):
        rate = _text_change_rate(
            old_by_heading[heading].text,
            new_by_heading[heading].text,
        )
        if rate > CHANGE_RATE_THRESHOLD:
            changed.append(new_by_heading[heading])  # 新年度版を格納

    return {"added": added, "removed": removed, "changed": changed}
```

**手計算検証例**:
```
old.sections = [A（人的資本）, B（ガバナンス）, C（リスク管理）]
new.sections = [A（人的資本）, B（ガバナンス）, D（Scope3開示）]

追加: {D（Scope3開示）}  ← SSBJ対応で新設
削除: {C（リスク管理）}  ← 章立て変更で統合
共通: {A, B}

A の本文変化率 = 35% > 20% → changed に追加  ← 人材戦略の記載を拡充
B の本文変化率 = 5%  ≤ 20% → 変化なし         ← 小修正のみ
```

このアルゴリズムにより、SSBJ 対応で新設されたセクション・統廃合されたセクション・記載が大幅に拡充されたセクションを自動検出できます。

### 4-5. 複数年度の比較

```python
def compare_years(reports: list[YearlyReport]) -> YearDiff:
    """
    複数年度レポートの最新2年度間の差分を返す。

    手計算検証:
        reports = [2022, 2023, 2024] → 2023→2024 を比較 ✓
        reports = [2023, 2024]       → 2023→2024 を比較 ✓
    """
    if len(reports) < 2:
        raise ValueError(f"最低2件の YearlyReport が必要（受取: {len(reports)}件）")

    # 会計年度で昇順ソート → 末尾2件を比較
    sorted_reports = sorted(reports, key=lambda r: r.fiscal_year)
    old_report = sorted_reports[-2]
    new_report = sorted_reports[-1]

    changes = detect_section_changes(
        old_report.structured_report,
        new_report.structured_report,
    )

    # サマリー生成
    parts = []
    if changes["added"]:
        parts.append(f"追加: {len(changes['added'])}件")
    if changes["removed"]:
        parts.append(f"削除: {len(changes['removed'])}件")
    if changes["changed"]:
        parts.append(f"変更: {len(changes['changed'])}件")

    summary = (
        f"{old_report.fiscal_year}年度 → {new_report.fiscal_year}年度: "
        + (", ".join(parts) or "差分なし")
    )

    return YearDiff(
        fiscal_year_from=old_report.fiscal_year,
        fiscal_year_to=new_report.fiscal_year,
        added_sections=changes["added"],
        removed_sections=changes["removed"],
        changed_sections=changes["changed"],
        summary=summary,
    )
```

`sorted(reports, key=lambda r: r.fiscal_year)` により、年度が不順に渡された場合も正しく処理されます。3年度以上の入力では**最新2年度（末尾2件）**のみを比較します。

---

## 5. E2E バッチ処理デモ

### 5-1. トヨタ有報3年度比較（モックモード）

```python
import os
import sys
sys.path.insert(0, "scripts")

os.environ["USE_MOCK_EDINET"] = "true"
os.environ["USE_MOCK_LLM"] = "true"

from m3_gap_analysis_agent import StructuredReport, SectionData
from m7_edinet_client import fetch_document_list, download_pdf
from m8_multiyear_agent import YearlyReport, compare_years

# ─── Step 1: EDINET から書類一覧を取得 ───
# モックモードでは MOCK_DOCUMENTS を返す
docs_2024 = fetch_document_list("2024-06-28")
docs_2023 = fetch_document_list("2023-06-30")
docs_2022 = fetch_document_list("2022-06-29")

print(f"書類件数: 2024年={len(docs_2024)}件, 2023年={len(docs_2023)}件, 2022年={len(docs_2022)}件")
# → 書類件数: 2024年=3件, 2023年=3件, 2022年=3件

# ─── Step 2: PDF ダウンロード（モック: サンプルPDF使用）───
for doc in docs_2024[:1]:
    pdf_path = download_pdf(doc["docID"], output_dir="downloads/toyota")
    print(f"DL: {doc['filerName']} → {pdf_path}")

# ─── Step 3: 3年度の StructuredReport を構築（実際は M1 が抽出）───
# デモ用のダミーセクションデータ
def make_report(year: int, sections_data: list[tuple[str, str]]) -> StructuredReport:
    sections = [
        SectionData(section_id=f"{year}-{i}", heading=h, text=t, level=2)
        for i, (h, t) in enumerate(sections_data)
    ]
    return StructuredReport(
        document_id=f"TOYOTA_{year}",
        company_name="トヨタ自動車株式会社",
        fiscal_year=year,
        fiscal_month_end=3,
        sections=sections,
    )

# 2022年度: SSBJ対応前（人的資本開示 + 旧形式ガバナンス）
report_2022 = make_report(2022, [
    ("人的資本に関する方針", "当社は人材を最重要の経営資源と位置付けています。"),
    ("コーポレートガバナンス", "取締役会は年4回以上開催します。"),
    ("リスク管理", "経営リスクは取締役会で定期的に審議されます。"),
])

# 2023年度: 人的資本開示義務化対応（内閣府令改正）
report_2023 = make_report(2023, [
    ("人的資本に関する方針", "当社は人材を最重要の経営資源と位置付け、女性管理職比率14.1%を目標に設定しています。男性育児休業取得率42.3%（2023年度実績）。"),
    ("コーポレートガバナンス", "取締役会は年4回以上開催します。"),
    ("サステナビリティに関する考え方及び取組", "脱炭素への取組：2050年カーボンニュートラルを目指します。"),
])

# 2024年度: SSBJ先行適用対応（GHG開示追加）
report_2024 = make_report(2024, [
    ("人的資本に関する方針", "当社は人材を最重要の経営資源と位置付け、女性管理職比率14.1%（2024年度実績）、男性育児休業取得率47.2%（2024年度実績）を達成しました。"),
    ("コーポレートガバナンス", "取締役会は年4回以上開催します。サステナビリティ委員会（四半期開催）を設置し、気候関連リスク・機会を監督しています。"),
    ("サステナビリティに関する考え方及び取組", "Scope1: 2,450万t-CO2e、Scope2（市場基準）: 320万t-CO2e（2024年度実績）。GHGプロトコル準拠。2035年EV100%化を目標とする移行計画を策定しました。"),
    ("Scope3 GHG排出量の開示", "Scope3 合計: 4億8,200万t-CO2e（カテゴリ11「製品の使用」が全体の83%を占める）。"),
])

# ─── Step 4: M8 多年度比較 ───
yearly_reports = [
    YearlyReport(fiscal_year=2022, structured_report=report_2022),
    YearlyReport(fiscal_year=2023, structured_report=report_2023),
    YearlyReport(fiscal_year=2024, structured_report=report_2024),
]

diff = compare_years(yearly_reports)
print(f"\n[M8] 差分サマリー: {diff.summary}")

print(f"\n追加セクション ({len(diff.added_sections)}件):")
for sec in diff.added_sections:
    print(f"  + {sec.heading}")

print(f"\n変更セクション ({len(diff.changed_sections)}件):")
for sec in diff.changed_sections:
    print(f"  ~ {sec.heading}")
```

**実行結果（期待値）**:

```
書類件数: 2024年=3件, 2023年=3件, 2022年=3件
DL: サンプル社A → 10_Research/samples/company_a.pdf

[M8] 差分サマリー: 2023年度 → 2024年度: 追加: 1件, 変更: 2件

追加セクション (1件):
  + Scope3 GHG排出量の開示

変更セクション (2件):
  ~ コーポレートガバナンス  （サステナビリティ委員会の記載が追加）
  ~ サステナビリティに関する考え方及び取組  （Scope1/2数値・移行計画が追加）
```

2023→2024 の比較で、「Scope3 GHG排出量の開示」が**新規追加**され、「ガバナンス」と「サステナビリティ」の記載が**大幅に拡充**されたことが自動検出されました。

---

## 6. EDINET Subscription Key の取得方法

EDINET の書類一覧 API を使用するには Subscription-Key の取得が必要です。

1. [EDINET API接続仕様書](https://api.edinet-fsa.go.jp/) にアクセス
2. 「EDINET APIの利用申請」から申請フォームへ
3. 利用目的（研究・システム開発等）を記入して申請
4. 審査後にAPIキーが発行（通常数営業日）

取得後は環境変数に設定します。

```bash
export EDINET_SUBSCRIPTION_KEY="your-api-key-here"

# 動作確認
python3 scripts/m7_edinet_client.py --date 2026-03-01
```

> ⚠️ **APIキーの取扱い**: `.env` ファイルに記載し、`.gitignore` に追加してください。GitHubにPushしないよう注意が必要です。

---

## 7. テスト構成（pytest 71件 PASS）

M6〜M8 には対応するテストファイルが整備されています。

```
scripts/
├── test_m6_law_url_collector.py   # M6 法令URL収集テスト
├── test_m6_m7_integration.py      # M6×M7 統合テスト
├── test_m7_edinet_client.py       # M7 EDINETクライアントテスト
├── test_m8_multiyear.py           # M8 多年度比較テスト
└── test_e2e_batch.py              # E2E バッチテスト
```

主なテスト項目：

| テストファイル | カバー範囲 |
|-------------|----------|
| test_m7_edinet_client.py | validate_edinetcode / validate_doc_id / fetch_document_list(モック) / download_pdf(モック・404) |
| test_m8_multiyear.py | _text_change_rate 手計算検証 / detect_section_changes(追加・削除・変更) / compare_years(2件・3件) |
| test_m6_m7_integration.py | M6収集後のURLを M7 に渡すエンドツーエンドフロー |

```bash
# M6〜M8 のテストのみ実行
pytest scripts/test_m6*.py scripts/test_m7*.py scripts/test_m8*.py -v

# 全テスト実行（71件 PASS）
pytest scripts/ -v --tb=short
```

---

## 8. M6-M8 の組み合わせ活用パターン

### パターン A: 決算シーズンの一括取得

```python
# 3〜6月の有報提出ラッシュに対応するバッチ処理
import asyncio
from datetime import date, timedelta

async def batch_fetch_reports(start_date: date, end_date: date):
    current = start_date
    all_docs = []
    while current <= end_date:
        docs = fetch_document_list(current.strftime("%Y-%m-%d"))
        all_docs.extend(docs)
        current += timedelta(days=1)
        await asyncio.sleep(1)  # EDINET負荷軽減
    return all_docs

# 2026年3月〜6月の全有報を取得
reports = asyncio.run(batch_fetch_reports(
    date(2026, 3, 1), date(2026, 6, 30)
))
print(f"取得件数: {len(reports)}件")
```

### パターン B: SSBJギャップの年次トレンド分析

M8 の差分検出と M3 のギャップ分析を組み合わせることで、「前年はギャップがあったが今年は解消された項目」を自動追跡できます。

```python
# 2023→2024→2025 のSSBJギャップ推移を追跡
from m3_gap_analysis_agent import analyze_gaps
from m2_law_agent import load_law_context
from m8_multiyear_agent import compare_years

law_ctx = load_law_context(fiscal_year=2025, fiscal_month_end=3)
yearly_reports = [...]  # M7で取得した3年分の有報

# まず変更セクションを検出
diff = compare_years(yearly_reports)

# 変更セクションのみをギャップ分析（コスト削減）
from m3_gap_analysis_agent import StructuredReport
changed_report = StructuredReport(
    document_id="CHANGED_ONLY",
    company_name="sample",
    fiscal_year=2025,
    fiscal_month_end=3,
    sections=diff.changed_sections,  # 変更セクションのみ
)
gap_result = analyze_gaps(changed_report, law_ctx, use_mock=False)
print(f"変更セクションの新規ギャップ: {gap_result.summary.total_gaps}件")
```

変更があったセクションのみをギャップ分析することで、**LLM の API コストを大幅に削減**できます。

---

## 9. まとめ・次回予告

本記事では disclosure-multiagent の Phase 2 バッチ処理レイヤー（M6〜M8）を解説しました。

| エージェント | 実装のポイント |
|------------|-------------|
| **M6** | e-Gov 法令API（認証不要・robots.txt 調査済み）で法令URL を自動収集。confidence 3段階で人手確認の優先度付け |
| **M7** | EDINET 書類一覧API + PDF 直接DL（認証不要）の2系統。USE_MOCK_EDINET でAPIキーなし開発可能 |
| **M8** | difflib.SequenceMatcher で変化率を算出。閾値20%でセクションの追加・削除・変更を自動検出 |

### 実務への応用ポイント

- **EDINET Subscription-Key は無料**で取得できる。申請して本番APIへ移行する価値がある
- **M8 の変更検出 + M3 のギャップ分析**の組み合わせで、変更箇所のみをAI分析するコスト効率の高い処理が実現できる
- **モックモード**（`USE_MOCK_EDINET=true`・`USE_MOCK_LLM=true`）により、APIキーなしでE2Eフローを開発・テストできる

### 次回記事予告

次回は **M9: ドキュメントエクスポートエージェント** と **FastAPI による REST API 公開** を解説します。`/api/checklist` エンドポイントから SSBJ チェックリストを取得し、フロントエンドと連携する実装を紹介します。

---

*本記事で使用したコードは [disclosure-multiagent](https://github.com/) で公開予定です（SSBJ記事シリーズ④）。*
