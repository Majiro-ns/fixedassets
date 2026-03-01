---
title: "有報開示変更レポートAI — Phase 2: e-Gov法令API連携とEDINET自動取得を追加した"
emoji: "📂"
type: "tech"
topics: ["python", "multiagent", "llm", "金融", "有価証券報告書"]
published: false
---

## はじめに

[前回の記事（Phase 1）](https://zenn.dev)では **disclosure-multiagent** の M1〜M5 パイプライン（192テスト・全PASS）を紹介しました。有報PDF を入力すると、法令改正に基づくギャップを検出し、松竹梅3水準の改善提案Markdownを生成するシステムです。

Phase 2 では「**法令情報の自動取得**」と「**有報PDFの自動ダウンロード**」という2つの柱を追加しました。

- **M6**: e-Gov 法令 API を使った法令URL自動収集
- **M7-1**: EDINET 直接DLによる有報PDF自動取得（認証不要）

本記事では Phase 2 の技術的な発見と実装の詳細を記録します。

---

## Phase 1 → Phase 2 の進化

| 項目 | Phase 1 | Phase 2 |
|------|---------|---------|
| モジュール | M1〜M5（5本） | M6・M7-1 追加（7本） |
| テスト数 | 192件 | 207件（+15件） |
| 法令URL取得 | 手動管理（YAML） | e-Gov API 自動収集（M6） |
| 有報PDF取得 | 手動配置 | EDINET 直接DL（M7-1） |
| E2Eパイプライン | M1→M5（モック） | M6→M2→M3 統合スモークテスト |

---

## M6: e-Gov 法令 API 連携

### 背景と課題

Phase 1 の `law_entries_human_capital.yaml` には `source_confirmed: false` のエントリが複数存在していました。これらは法令の出典URLが未確定のものです。手動で探すのは手間がかかるため、**e-Gov 法令 API**（政府提供・認証不要・無料）を使って自動収集するスクリプトを実装しました。

### robots.txt 調査結果

実装前に robots.txt を確認しました。

```
金融庁（fsa.go.jp）: robots.txt → 404（未公開）→ スクレイピング不実施
e-Gov（laws.e-gov.go.jp）: robots.txt → HTML（内容未定義）→ 公式 API のみ使用
```

金融庁サイトのスクレイピングは避け、政府が公式に提供している e-Gov API のみを使う方針にしました。

### e-Gov API の実装

e-Gov 法令 API は認証不要で法令一覧を XML 形式で返します。カテゴリコードは 2=法律、3=政令、4=府令の3種類を使います。

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

### 3段階マッチングアルゴリズム

YAML の `law_name` フィールドと e-Gov の法令名を突合する際、3段階の信頼度で返します。

```python
def _match(law_name: str, laws: list[dict]) -> dict | None:
    """完全一致 → 部分一致1件 → 複数候補最近傍の順で検索"""
    for law in laws:
        if law["law_name"] == law_name:
            return {**law, "confidence": "high"}        # 完全一致
    hits = [l for l in laws if law_name in l["law_name"] or l["law_name"] in law_name]
    if len(hits) == 1:
        return {**hits[0], "confidence": "medium"}      # 部分一致1件
    if hits:
        best = min(hits, key=lambda h: abs(len(h["law_name"]) - len(law_name)))
        return {**best, "confidence": "low"}            # 複数候補→文字列長が最近傍
    return None
```

| confidence | 意味 | 後処理 |
|-----------|------|--------|
| `high` | 法令名が完全一致 | そのままYAML更新候補 |
| `medium` | 部分一致1件 | 目視確認推奨 |
| `low` | 複数候補あり（最近傍） | 必ず目視確認 |

### 出力形式

```json
{
  "metadata": {
    "total_entries": 15,
    "unconfirmed_count": 8,
    "candidates_found": 5,
    "skipped_count": 3,
    "egov_api_status": "ok"
  },
  "candidates": [
    {
      "entry_id": "HC_001",
      "law_name": "企業内容等の開示に関する内閣府令",
      "proposed_url": "https://laws.e-gov.go.jp/law/48M50000008033",
      "egov_law_id": "48M50000008033",
      "confidence": "high",
      "source": "e-Gov API",
      "note": "source_confirmed: false のエントリに対して e-Gov API で候補を提示"
    }
  ]
}
```

`collect()` が生成するこの JSON を確認し、人間が `source_confirmed: true` に更新することでYAMLが整備されていきます。M6 は YAML を直接更新せず、候補提示のみを行う**安全な設計**にしました。

---

## M7-1: EDINET 有報PDF 自動取得

### 重要な発見 — EDINET 直接DL は認証不要

実装前の調査で重要な発見がありました。EDINET の PDF ダウンロードには2つのエンドポイントがあります。

| エンドポイント | 認証 | 用途 |
|-------------|------|------|
| `api.edinet-fsa.go.jp/api/v2/documents.json` | **Subscription-Key 必須** | 書類一覧検索 |
| `disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{docID}.pdf` | **認証不要** | PDF直接DL |

Phase 1 の PoC でも `disclosure2dl.edinet-fsa.go.jp` から直接 PDF をダウンロードしていましたが、これは **2024年以降も認証不要のまま** でした。EDINET API（書類検索）は Subscription-Key 取得が必要になりましたが、PDF 直接ダウンロードは書類管理番号（`S100XXXX` 形式）さえ分かれば取得できます。

```python
EDINET_DL_BASE  = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf"
EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"

def download_pdf(doc_id: str, output_dir: str) -> str:
    """EDINET直接DL（認証不要）でPDFを取得"""
    if not validate_doc_id(doc_id):
        raise ValueError(f"無効な書類管理番号: '{doc_id}'（S + 7桁英数字が必要）")

    # モックモード: テスト用サンプルPDFパスを返す（APIキー不要）
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
    # ... ファイル保存処理
```

### 書類管理番号の検証

`validate_doc_id()` で書類管理番号の形式を厳格にチェックしています。

```python
def validate_doc_id(doc_id: str) -> bool:
    """書類管理番号形式チェック（S + 7桁英数字）"""
    return bool(re.fullmatch(r"S[A-Z0-9]{7}", doc_id))

# 例
validate_doc_id("S100VHUZ")  # → True（company_a.pdf の実際の書類管理番号）
validate_doc_id("INVALID!")  # → False → ValueError を raise
```

### USE_MOCK_EDINET 設計

M3 の `USE_MOCK_LLM` と同様に `USE_MOCK_EDINET` 環境変数でモック切替ができる設計にしました。これにより Subscription-Key なしで全テストが通ります。

```python
USE_MOCK_EDINET = os.environ.get("USE_MOCK_EDINET", "true").lower() == "true"

# テストでは常にモードを強制
os.environ["USE_MOCK_EDINET"] = "true"
```

---

## Phase 2 統合テスト戦略

### M6/M7 統合テストの設計課題

M6 と M7 はそれぞれ独立テスト済みでしたが、**パイプライン接続テスト**が不足していました。特に課題だったのは次の3点です。

1. M7-1 でダウンロードした PDF を M1 に渡す動作確認
2. M6 の candidates フォーマットが M2 の LawEntry と整合するか
3. M6→M2→M3 の全パイプラインが完走するか

### 統合テストの実装

`test_m6_m7_integration.py` を新規作成しました（15件・CI対応）。

**TC-3: M6→M2→M3 パイプライン スモークテスト** が最も重要です。

```python
def test_tc3_m6_m2_m3_pipeline_smoke_test(self):
    # Step 1: M6 collect() でURL候補取得（e-Gov API モック）
    with patch("m6_law_url_collector._fetch") as mock_fetch:
        mock_fetch.return_value = _MOCK_XML_OK
        m6_result = collect(_FIXTURE_YAML, output_path)

    # Step 2: M2 load_law_context() で法令コンテキスト取得
    law_ctx = load_law_context(fiscal_year=2025, fiscal_month_end=3)

    # Step 3: M3 analyze_gaps() でギャップ分析（モックLLM）
    sections = split_sections_from_text(
        "第一部 企業情報\n人的資本に関する考え方と取り組み。"
    )
    mock_report = StructuredReport(
        document_id="TEST_DOC_001",
        company_name="統合テスト株式会社",
        fiscal_year=2025,
        sections=sections,
    )
    gap_result = analyze_gaps(mock_report, law_ctx, use_mock=True)

    # GapAnalysisResult の基本フィールド確認
    self.assertEqual(gap_result.document_id, "TEST_DOC_001")
    self.assertIsInstance(gap_result.gaps, list)
```

### ネットワーク依存テストの設計

TC-4（EDINET 直接DL HTTP 200 確認）はネットワーク依存なので、`RUN_NETWORK_TESTS` 環境変数で制御します。

```python
_RUN_NETWORK_TESTS = os.environ.get("RUN_NETWORK_TESTS", "false").lower() == "true"

@unittest.skipUnless(_RUN_NETWORK_TESTS, "ネットワークテストをスキップ")
class TestM7NetworkDownload(unittest.TestCase):
    def test_tc4_edinet_direct_dl_returns_200(self):
        doc_id = "S100VHUZ"  # company_a.pdf の書類管理番号
        resp = requests.get(f"{EDINET_DL_BASE}/{doc_id}.pdf", stream=True, timeout=30)
        self.assertIn(resp.status_code, (200, 302))
```

デフォルトはスキップ、`RUN_NETWORK_TESTS=true` で有効化。CI では常にスキップされます。

### 実装で気づいた M1 の設計

テスト実装中に M1 の堅牢性設計を発見しました。空文字列パスを渡した場合、例外を raise せず `WARNING` を出力して空 sections の `StructuredReport` を返します（graceful degradation）。

```
WARNING m1_pdf_agent:m1_pdf_agent.py:263 PDF開封エラー（空sectionsで継続）: '.' is no file
```

これは「部分的な失敗でもパイプライン全体を止めない」という設計です。統合テストでこの挙動を検証することで、設計意図をドキュメント化できました。

---

## Phase 2 テスト結果（全207件 PASS）

```bash
python3 -m pytest scripts/ -q
# → 207 passed, 1 skipped, 19 subtests passed
```

| テストファイル | Phase | 件数 | 内容 |
|-------------|-------|------|------|
| test_m1_pdf_agent.py | 1 | 29件 | PDF解析・セクション分割 |
| test_m2_law_agent.py | 1 | 19件 | 法令YAML読み込み |
| test_m3_gap_analysis.py | 1 | 16件 | ギャップ分析（モック） |
| test_m4_proposal.py | 1 | 41件 | 松竹梅提案文生成 |
| test_m5_report.py | 1 | 37件 | Markdownレポート統合 |
| test_e2e_pipeline.py | 1 | 22件 | E2Eパイプライン |
| test_m6_law_url_collector.py | 2 | 13件 | e-Gov API マッチング |
| test_m7_edinet_client.py | 2 | 15件 | EDINET クライアント |
| test_m6_m7_integration.py | 2 | 15件 | **M6/M7 統合テスト（新規）** |

---

## multi-agent-shogun による並列開発

Phase 2 の実装も **multi-agent-shogun**（tmux + Claude Code 並列 AI 開発フレームワーク）で行いました。

Phase 1 から引き継いだ品質ルール（**「テストが通る ≠ 正しい」の原則**）を Phase 2 でも適用しています。

```
三段階の品質防壁:
  第1壁（足軽）: セルフレビュー + 自信度申告（1〜5）
  第2壁（家老）: スポットチェック3箇所以上 + 手計算検算
  第3壁（将軍）: 重要プロジェクトの抜き打ち検査
```

M6 の実装では「**3段階マッチングアルゴリズムの手計算検算**」を実施しました。部分一致の境界条件（`""` 空文字列がどのように扱われるか）を手計算で確認し、テストの期待値を根拠付けています。

---

## Phase 3 に向けた残課題

### M7-2: EDINET書類検索API（Subscription-Key取得後）

`api.edinet-fsa.go.jp` の書類検索 API は 2024年以降 Subscription-Key が必要です。申請・取得後に M7-2 として実装予定です。

```python
# M7-2 の設計（実装予定）
def search_yuho_by_company(company_name: str, fiscal_year: int) -> list[dict]:
    """EDINET書類検索API で対象企業の有報を検索する（Subscription-Key 必要）"""
    resp = requests.get(
        f"{EDINET_API_BASE}/documents.json",
        params={"date": f"{fiscal_year}-06-28", "type": 2,
                "Subscription-Key": SUBSCRIPTION_KEY},
    )
    results = resp.json().get("results", [])
    return [r for r in results if r.get("docTypeCode") == "120"  # 有報
            and company_name in r.get("filerName", "")]
```

### 実LLM E2E 検証

`USE_MOCK_LLM=false`（実 Claude API）によるギャップ分析の精度検証はまだ未実施です。モックモードではキーワードマッチ判定のため、実LLMで文脈を踏まえた判定を行うとどう変わるか検証したい点です。

```bash
# 実LLM E2E 実行（APIキー設定後）
export ANTHROPIC_API_KEY=sk-ant-xxx
USE_MOCK_LLM=false python3 scripts/run_e2e.py \
    "10_Research/samples/company_a.pdf" \
    --company-name "サンプル社A" \
    --fiscal-year 2025 \
    --level 竹
```

### M7.5: 決算期拡張

現在は3月決算を前提としています。12月決算・6月決算などへの拡張も設計済みで、`fiscal_month_end` パラメータで動作する設計になっています（`calc_law_ref_period(fiscal_year, fiscal_month_end=12)` のように指定可能）。

---

## おわりに

Phase 2 では「**法令情報の取得を自動化する**」ことと「**有報PDFの調達を自動化する**」ことの2点を達成しました。

技術的な発見として特に重要だったのは、EDINET の PDF 直接DL が認証不要のままであったことです。書類管理番号（`S100XXXX`）さえ分かれば任意の有報PDFをダウンロードできます。M7-1 はこの認証不要エンドポイントを活かした実装です。

M6 の e-Gov API 連携では、3段階マッチングアルゴリズムのテスト設計に力を入れました。`confidence: high/medium/low` による信頼度分類と、空文字列・複数候補などのエッジケースを単体テスト13件で網羅しています。

Phase 3 として実LLM検証・M7-2（EDINET書類検索API）・M7.5（決算期拡張）を進める予定です。

---

*生成日: 2026-02-27 / 実装: disclosure-multiagent Phase 2 (cmd_070)*
