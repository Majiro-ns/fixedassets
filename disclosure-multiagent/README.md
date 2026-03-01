# disclosure-multiagent

有価証券報告書（有報）の開示情報ギャップ分析 AI エージェント。
人的資本開示等の法令改正に対し、有報PDF を自動解析してギャップを検出し、松竹梅3水準の改善提案文を生成する。
**モックモードを搭載しており、APIキーなしで動作確認可能。**

---

## Docker で起動（推奨）

```bash
# 1. 環境変数ファイルを作成
cp .env.example .env
# 必要に応じて ANTHROPIC_API_KEY を設定（モックモードは不要）

# 2. 起動
docker compose up --build

# バックグラウンドで起動する場合
docker compose up -d --build
```

起動後のアクセス先：
- Web UI: http://localhost:3010
- FastAPI (API): http://localhost:8010
- API ドキュメント: http://localhost:8010/docs

停止：
```bash
docker compose down
```

---

## アーキテクチャ

```
有報PDF → [M1: PDF解析] → [M2: 法令取得] → [M3: ギャップ分析]
                                                     ↓
                              Markdownレポート ← [M5: レポート統合] ← [M4: 松竹梅提案]
                                                                              ↓
                                                               [M9: Word/Excel出力]

[M6: 法令URL収集] ──→ M2/M3 へフィードバック
[M7: EDINET連携] ──→ 有報PDF 自動取得 → M1 へ
[M8: 複数年度比較] ← M1出力を複数年度分入力
```

### モジュール一覧

| モジュール | 役割 | テスト件数 | 状態 |
|-----------|------|-----------|------|
| m1_pdf_agent.py | PDF解析・セクション抽出（PyMuPDF/pdfplumber） | 29件 | ✅ Phase 1 |
| m2_law_agent.py | 法令マスタYAML読み込み・参照期間算出 | 19件 | ✅ Phase 1 |
| m3_gap_analysis_agent.py | ギャップ分析（追加必須/修正推奨/参考） | 16件 | ✅ Phase 1 |
| m4_proposal_agent.py | 松竹梅3水準の提案文生成 | 41件 | ✅ Phase 1 |
| m5_report_agent.py | Markdownレポート統合 | 37件 | ✅ Phase 1 |
| m6_law_url_collector.py | 法令URL自動収集（金融庁HP / e-Gov API） | 13件 | ✅ Phase 2 |
| m7_edinet_client.py | EDINET連携・有報PDF自動取得 | 15件 | ✅ Phase 2 |
| m8_multiyear_agent.py | 複数年度比較（YearDiff・トレンド検出） | 15件 | ✅ Phase 2 |
| m9_document_exporter.py | Word/Excel出力（python-docx/openpyxl） | 8件 | ✅ Phase 2 |

**総テスト数: 256件（全PASS確認済み / 1件スキップ）**
※ E2E統合テスト（test_e2e_pipeline.py・test_e2e_batch.py・test_e2e_smoke.py・test_e2e_phase2.py）を含む

---

## セットアップ

```bash
pip install -r requirements_poc.txt

# 実LLM使用時のみ（モックモードは不要）
export ANTHROPIC_API_KEY=sk-ant-xxx
```

---

## クイックスタート（モックモード・APIキー不要）

```bash
cd scripts/

# E2Eパイプライン実行（モックLLM）
USE_MOCK_LLM=true python3 run_e2e.py \
    ../10_Research/samples/company_a.pdf \
    --company-name "サンプル社A" \
    --fiscal-year 2025 \
    --level 竹

# → reports/ に Markdownレポートが生成される
```

---

## 実LLMモード

```bash
cd scripts/

# API疎通確認
python3 check_real_api.py

# E2Eパイプライン実行（実LLM）
USE_MOCK_LLM=false python3 run_e2e.py \
    ../10_Research/samples/company_a.pdf \
    --company-name "サンプル社A" \
    --fiscal-year 2025 \
    --level 竹
```

---

## Streamlit UI

```bash
cd scripts/
streamlit run app.py
# → http://localhost:8501 でブラウザUIが起動
```

PDFをアップロードすると M1〜M5 フルパイプラインが実行される。
PDFなしでデモデータを使用した動作確認も可能。

---

## Phase 2 機能の使い方

### M8: 複数年度比較

```python
import sys
sys.path.insert(0, "scripts/")

from m8_multiyear_agent import YearlyReport, compare_years
from m1_pdf_agent import extract_report

# 2年分の有報を読み込む
report_2024 = extract_report("path/to/yuho_2024.pdf", fiscal_year=2024)
report_2025 = extract_report("path/to/yuho_2025.pdf", fiscal_year=2025)

yr_2024 = YearlyReport(fiscal_year=2024, structured_report=report_2024)
yr_2025 = YearlyReport(fiscal_year=2025, structured_report=report_2025)

# 差分検出（最新2年度を自動選択）
diff = compare_years([yr_2024, yr_2025])

print(diff.summary)
# 例: "2024年度 → 2025年度: 追加: 2件, 変更: 3件"
print(f"追加セクション: {[s.heading for s in diff.added_sections]}")
print(f"削除セクション: {[s.heading for s in diff.removed_sections]}")
print(f"変更セクション: {[s.heading for s in diff.changed_sections]}")
# 変化率 > 20% のセクションが changed として検出される
```

### M9: Word/Excel出力

```python
import sys
sys.path.insert(0, "scripts/")

from m9_document_exporter import export_documents
from m4_proposal_agent import generate_proposals

# M4 で生成した提案セットを Word/Excel に出力
proposal_sets = [generate_proposals(gap) for gap in gap_result.gaps if gap.has_gap]

result = export_documents(
    proposal_sets=proposal_sets,
    word_path="output/report.docx",
    excel_path="output/report.xlsx",
    company_name="株式会社サンプル",
    fiscal_year=2025,
)

print(f"Word: {result.word_path}")
print(f"Excel: {result.excel_path}")
print(f"提案数: {result.proposal_count}件")
```

---

## Phase 2 ロードマップ

| マイルストーン | 内容 | 状態 |
|-------------|------|------|
| M6 | 法令URL自動収集（金融庁HP / e-Gov API） | ✅ 完了（m6_law_url_collector.py） |
| M7-1 | EDINET有報PDF直接ダウンロード（認証不要） | ✅ 完了（m7_edinet_client.py） |
| M7-2 | EDINET書類検索API（Subscription-Key取得後） | ⏸ 保留（Subscription-Key未取得） |
| M8 | 複数年度比較・トレンド検出（YearlyReport/YearDiff/compare_years） | ✅ 完了（m8_multiyear_agent.py） |
| M9 | Word/Excel出力テンプレート差し込み（python-docx/openpyxl） | ✅ 完了（m9_document_exporter.py） |
| 実LLM E2E検証 | `ANTHROPIC_API_KEY` 設定後に方式B確認予定（方式Aで2社E2E完走確認済み） | 方式A完了 |

---

## 制限事項

- **モックモード**: 全機能動作確認済み（APIキー不要）
- **実LLMモード**: `ANTHROPIC_API_KEY` の設定が必要（現時点未設定）
- **EDINET API**: Subscription-Key が必要（M7-2）。直接DLは認証不要
- **M8変化率閾値**: 本文変化率 > 20%（CHANGE_RATE_THRESHOLD = 0.20）でセクション変更を検出
- **M9 Word出力**: python-docx 1.0.0 以上が必要（`pip install python-docx`）
- 本ツールはPoCであり、税務・法律上の判断には必ず専門家の確認を要する
