# CHANGELOG

## [Unreleased]

---

## [Phase 2 後半] — 2026-03-07〜2026-03-09

### D-LAW-DIR-fix（commit 78fbfb8）
**m2 LAW_YAML_DIR を `laws/` に修正 + amendments スキーマ対応**

- `m2_law_agent.py`: `LAW_YAML_DIR` のデフォルトを `10_Research/` → `laws/` に変更
- `_load_all_from_dir()` 関数追加: `laws/` 配下の全 `*.yaml` を一括読み込み
- `amendments` / `entries` 両スキーマに対応（旧 YAML との後方互換）
- `disclosure_items` / `required_items` フィールド名フォールバック追加
- テスト追加: `TestLawsDirectoryLoading` 7件（合計 26件）

### D-Zenn-03-fix（commit 0dde91a）
**FastAPI エンドポイント URL 修正 + doc_type 引き渡し修正**

- `docs/article_disclosure_shoshu_draft.md`: `/analyze` → `/api/analyze`（`APIRouter(prefix="/api")` に合わせて修正）
- `api/routers/analyze.py`: `doc_type=request.doc_type_code.value` を `run_pipeline_async` 呼び出しに追加
- `api/services/pipeline.py`: `run_pipeline_async` に `doc_type: str = "yuho"` パラメータ追加、`extract_report` への引き渡し追加

---

## [Phase 2 中盤] — 2026-03-07

### D-SSBJ-01（commit 60608de）
**SSBJ（サステナビリティ開示基準）対応**

- `laws/ssbj_2025.yaml` 新規作成: SSBJ 基準チェック項目 25件（sb-2025-001〜025）
- `laws/human_capital_2024.yaml` 追加: 人的資本（hc-2024-xxx × 4）+ SSBJ 2024 年（sb-2024-xxx × 4）= 8件
- `m2_law_agent.py` / `m3_gap_analysis_agent.py` 等の SSBJ 対応修正
- `docs/article_disclosure_ssbj_draft.md` 作成（16,340字）

### D-Shoshu-01（commits 62ae09c〜f4ca3b0）
**株主総会招集通知（招集通知）対応**

- `laws/shareholder_notice_2025.yaml` 新規作成: 招集通知チェック項目 16件（gm-2025-xxx × 12 + gc-2025-xxx × 4）
- `scripts/m1_pdf_agent.py`:
  - `SHOSHU_SECTION_KEYWORDS` 12項目追加
  - `SHOSHU_HEADING_PATTERNS` 8パターン追加
  - `split_sections_from_text(..., doc_type: str = "yuho", ...)` 対応
  - `get_shoshu_sections()` 追加
- `api/models/schemas.py`: `DocTypeCode(str, Enum)` 追加（`yuho` / `shoshu`）、`AnalyzeRequest.doc_type_code` フィールド追加
- テスト追加: `TestShoshuDocType` 15件（m1 合計 47件）
- P9 クロスレビュー完了（commit f4ca3b0 ✅正式承認）

---

## [Phase 2 前半] — 2026-02 以前

### Phase 2 完成（M6〜M9）
- `m6_law_url_collector.py`: 法令 URL 自動収集（金融庁 HP / e-Gov API）
- `m7_edinet_client.py`: EDINET 連携・有報 PDF 自動取得
- `m8_multiyear_agent.py`: 複数年度比較（YearDiff / YearlyReport / compare_years）
- `m9_document_exporter.py`: Word / Excel 出力（python-docx / openpyxl）

---

## [Phase 1] — 初期実装

### Phase 1 完成（M1〜M5）
- `m1_pdf_agent.py`: PDF 解析・セクション抽出（PyMuPDF / pdfplumber）
- `m2_law_agent.py`: 法令マスタ YAML 読み込み・参照期間算出
- `m3_gap_analysis_agent.py`: ギャップ分析（追加必須 / 修正推奨 / 参考）
- `m4_proposal_agent.py`: 松竹梅 3 水準の提案文生成
- `m5_report_agent.py`: Markdown レポート統合
- FastAPI + Streamlit UI 実装
- Docker Compose 対応
