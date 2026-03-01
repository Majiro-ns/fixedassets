# disclosure-multiagent Phase 2 設計書

> 作成日: 2026-02-27
> 担当: ashigaru4 (multi-agent-shogun) / subtask_069a4c
> 前提: Phase 1 完了（M1〜M5・22テスト・実PDF E2E 4社確認済み）
> 参照: 00_Requirements_Definition.md / 10_Research/PDF_PoC_Result.md / gap_analysis_design.md

---

## 1. Phase 2 概要

### 1.1 成功基準（要件定義 9章より）

> **EDINETから取得した有報でレポート出力ができる。12月・6月決算に対応する。**

- M7（EDINET連携）で「手動アップロードなしに有報取得→レポート生成」が完結すること
- M7.5（決算期拡張）で3月決算以外の法令参照期間算出が正しく動作すること

### 1.2 マイルストーン優先順位（要件定義確定）

```
M6 法令半自動取得 → M7 EDINET連携 → M7.5 決算期拡張 → M9 Word連携 → M8 プロファイル保存
```

| マイルストーン | 内容 | 優先度 |
|----------------|------|--------|
| **M6** | 法令情報の半自動取得（金融庁HP等スクレイピング + 手動YAML併用） | High |
| **M7** | EDINET連携（公開有報の直接取得・書類検索API） | High |
| **M7.5** | 決算期拡張（12月・6月決算対応）。法令参照期間分岐ロジック | High |
| **M9** | PDF / HTML エクスポート、Word テンプレート連携 | Medium |
| **M8** | ユーザープロファイル（松竹梅選択履歴等） | Low |

---

## 2. M6: 法令情報の半自動取得

### 2.1 設計方針

**Phase 1 の M2（手動 YAML 管理）を基盤とし、スクレイピング/API で補完するハイブリッド方式。**

```
現状（Phase 1）:
  M2 = human_capital.yaml（手動メンテ）→ ギャップ分析に渡す

Phase 2 M6:
  M2 = human_capital.yaml（手動・マスタ）
      + 自動取得サブモジュール（差分更新）
      → マージ後 YAML → ギャップ分析に渡す
```

### 2.2 対象情報源と取得手段

| 情報源 | 取得手段 | 確認事項 |
|--------|----------|---------|
| **金融庁HP（金商法・開示府令）** | スクレイピング（BeautifulSoup + requests） | 利用規約確認要。構造変更リスクあり |
| **e-Gov（法令API）** | e-Gov API（法令テキスト取得） | 公式 REST API。キー不要で基本利用可 |
| **ASBJ（SSBJ）** | スクレイピング or RSS | 更新頻度は低め。年次確認で十分 |
| **東証（上場規程）** | スクレイピング | 構造変更リスクあり |

### 2.3 実装方針

```python
# scripts/m6_law_fetcher.py（新規作成）

class LawFetcher:
    """
    法令情報の半自動取得モジュール。
    既存 human_capital.yaml をベースに、スクレイピング結果で差分補完する。
    """
    def fetch_fsa_updates(self, period_from: str, period_to: str) -> list[dict]:
        """金融庁 新着情報ページから更新を取得"""
        ...

    def fetch_egov_amendment(self, law_id: str) -> dict:
        """e-Gov API で法令テキストを取得"""
        ...

    def merge_with_yaml(self, existing: list, fetched: list) -> list:
        """
        手動 YAML をマスタとして扱い、自動取得分を差分マージ。
        id が重複する場合は手動 YAML を優先（信頼性重視）。
        """
        ...
```

### 2.4 YAML スキーマ拡張（Phase 2 追加フィールド）

```yaml
# 既存フィールドに以下を追加
- id: "HC_20230131_001"
  # ... 既存フィールド ...
  auto_fetched: false          # 自動取得 or 手動
  last_verified: "2026-02-27"  # 最終確認日
  fetch_source: "manual"       # "manual" | "fsa_scrape" | "egov_api"
  expires_at: null             # 有効期限（指定なし = 永続）
```

### 2.5 複数ソース突合設計

```
[手動 YAML] ←── マスタ（最高信頼度）
[FSA スクレイプ] ──┐
[e-Gov API]    ──┤── 差分チェック → 不一致 → ⚠️ 警告 + 手動確認促進
[ASBJ]         ──┘
```

- 2ソース以上で同じ改正が確認された場合 → `source_confirmed: true` に自動更新
- 1ソースのみ → `source_confirmed: false` のまま（Phase 1 の運用継続）

### 2.6 推定実装規模

| ファイル | 行数 | テスト |
|---------|------|--------|
| `scripts/m6_law_fetcher.py` | 200〜300行 | 10〜15件 |
| `scripts/test_m6_law_fetcher.py` | 100〜150行 | — |
| `scripts/m2_law_agent.py` 拡張 | +50〜80行 | 既存テスト更新 |

---

## 3. M7: EDINET連携

### 3.1 現状整理（Phase 1 の知見）

PDF_PoC_Result.md より:
- **直接 PDF ダウンロード（認証不要）**:
  `https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{書類管理番号}.pdf`
- **EDINET API（2024年以降 Subscription-Key 必要）**:
  `api.edinet-fsa.go.jp` — 書類一覧検索・メタデータ取得
- **Phase 1 での取得実績**: company_a〜d 4社分を直接ダウンロードで取得済み

### 3.2 設計方針

**フェーズ分割アプローチ:**

```
M7-1: 直接ダウンロード（書類管理番号入力 → PDF取得）
      ↓ Subscription-Key なしで完結
M7-2: 書類検索 API 連携（企業コード・期間から書類管理番号を自動検索）
      ↓ Subscription-Key 取得が前提
M7-3: 他社比較（複数社のレポートを並列生成・差分表示）
```

### 3.3 M7-1 実装（最小構成）

```python
# scripts/m7_edinet_client.py（新規作成）

import requests
import time
import pathlib

EDINET_DL_BASE = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf"
EDINET_API_BASE = "https://api.edinet-fsa.go.jp/api/v2"

class EdinetClient:
    """
    EDINET連携クライアント。
    Phase 2 M7-1: 書類管理番号からの直接 PDF ダウンロード（認証不要）
    Phase 2 M7-2: 書類一覧 API 連携（Subscription-Key 必要）
    """

    def download_pdf(self, doc_id: str, save_path: pathlib.Path) -> pathlib.Path:
        """
        書類管理番号（例: S100VHUZ）から PDF を直接ダウンロード。
        認証不要。レート制限対策: 1秒ウェイト。

        Args:
            doc_id: EDINET 書類管理番号
            save_path: 保存先パス
        Returns:
            ダウンロードされたPDFのパス
        Raises:
            requests.HTTPError: ダウンロード失敗時
        """
        url = f"{EDINET_DL_BASE}/{doc_id}.pdf"
        time.sleep(1)  # EDINET サーバー負荷軽減（マナー）
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        save_path.write_bytes(resp.content)
        return save_path

    def search_documents(
        self,
        date: str,
        doc_type_code: str = "120",  # 有価証券報告書
        subscription_key: str | None = None,
    ) -> list[dict]:
        """
        書類一覧 API で日付・書類種別を検索（Subscription-Key 必要）。
        未設定の場合は NotImplementedError を発生させる。
        """
        if not subscription_key:
            raise NotImplementedError(
                "EDINET API 書類検索には Subscription-Key が必要です。"
                "EDINET_SUBSCRIPTION_KEY 環境変数を設定してください。"
            )
        ...

    def get_company_docs(
        self,
        edinetcode: str,
        fiscal_year: int,
        subscription_key: str,
    ) -> list[dict]:
        """
        企業コード（EDINETコード）と年度から有報書類一覧を取得。
        """
        ...
```

### 3.4 M7 と既存パイプラインの統合

```
現在（Phase 1）:
  [ユーザー: PDF手動アップロード] → [M1: PDF解析] → ... → [M5: レポート]

Phase 2 M7:
  選択1: [ユーザー: PDF手動アップロード] → [M1] → ...（Phase 1 互換維持）
  選択2: [ユーザー: 書類管理番号入力] → [M7: EDINET取得] → [M1] → ...
  選択3: [ユーザー: 企業コード+年度入力] → [M7: API検索 + DL] → [M1] → ...
```

**Streamlit UI 追加（app.py 拡張）:**

```python
# 入力方式の選択ラジオボタン追加
input_method = st.radio(
    "有報PDFの入力方法",
    ["📂 ファイルアップロード（既存）", "🏢 書類管理番号から取得（EDINET）"]
)

if input_method == "🏢 書類管理番号から取得（EDINET）":
    doc_id = st.text_input("書類管理番号（例: S100VHUZ）")
    if st.button("取得"):
        # M7 で PDF ダウンロード → M1 で解析
        ...
```

### 3.5 レート制限対策（要件定義 M7 要件より）

| 対策 | 実装 |
|------|------|
| 1 ダウンロードごとに 1 秒ウェイト | `time.sleep(1)` |
| リトライ（HTTP 429 / 5xx） | 指数バックオフ（1s → 2s → 4s、最大3回） |
| キャッシュ（同じ doc_id は再ダウンロードしない） | ローカルキャッシュディレクトリ管理 |
| 並列ダウンロードしない（Phase 2） | 逐次実行のみ。並列化は Phase 3 で検討 |

### 3.6 推定実装規模

| ファイル | 行数 | テスト |
|---------|------|--------|
| `scripts/m7_edinet_client.py` | 200〜280行 | 12〜18件（モック使用） |
| `scripts/test_m7_edinet_client.py` | 120〜160行 | — |
| `scripts/app.py` 拡張（UI） | +80〜100行 | UI テスト（Streamlit 動作確認） |
| `scripts/run_e2e.py` 拡張 | +30〜50行 | 既存テスト更新 |

---

## 4. M7.5: 決算期拡張

### 4.1 法令参照期間算出ロジック

**要件定義 3.3.1 の仕様:**

| 決算期 | 法令参照期間 | 例（2024年度） |
|--------|------------|----------------|
| 3月決算 | 対象年度の 4/1 〜 翌年 3/31 | 2024/4/1〜2025/3/31 |
| 12月決算 | 対象年度の 1/1 〜 12/31 | 2024/1/1〜2024/12/31 |
| 6月決算 | 対象年度の 7/1 〜 翌年 6/30 | 2024/7/1〜2025/6/30 |

### 4.2 実装箇所

現在（Phase 1）の `m2_law_agent.py` に固定の3月決算ロジックがあると推定。以下を拡張:

```python
def calc_law_reference_period(fiscal_year: int, fiscal_month_end: int) -> tuple[str, str]:
    """
    決算月から法令参照期間（from, to）を算出する。

    Args:
        fiscal_year: 対象年度（例: 2024）
        fiscal_month_end: 決算月（3=3月決算, 12=12月決算, 6=6月決算）

    Returns:
        (period_from, period_to) ISO 形式の日付文字列
    """
    if fiscal_month_end == 3:
        return (f"{fiscal_year}-04-01", f"{fiscal_year + 1}-03-31")
    elif fiscal_month_end == 12:
        return (f"{fiscal_year}-01-01", f"{fiscal_year}-12-31")
    elif fiscal_month_end == 6:
        return (f"{fiscal_year}-07-01", f"{fiscal_year + 1}-06-30")
    else:
        # 汎用: 決算日から1年前〜決算日
        ...
```

### 4.3 UI 変更（app.py）

```python
# 既存の year 入力に決算月選択を追加
fiscal_month_end = st.selectbox(
    "決算月",
    [3, 6, 12],
    format_func=lambda m: f"{m}月決算",
    index=0  # デフォルト: 3月
)
```

### 4.4 推定実装規模

| 変更ファイル | 追加行数 | テスト追加 |
|------------|---------|-----------|
| `scripts/m2_law_agent.py` 拡張 | +30〜50行 | +8〜12件 |
| `scripts/app.py` 拡張 | +20〜30行 | UI確認 |
| `scripts/run_e2e.py` 拡張 | +10〜20行 | +3〜5件 |

---

## 5. M1 との統合方針（Phase 1 資産の活用）

Phase 1 の M1（m1_pdf_agent.py）は PyMuPDF による PDF 解析が完成している。
Phase 2 では**M1 を無改変で利用し、M7（EDINET取得）の出力を M1 の入力として接続**する。

```
Phase 2 追加フロー:
  [M7: EDINET PDF取得] ──(pdf_path)──→ [M1: PDF解析（既存・無改変）]
                                               ↓
                                        [M6: 法令取得（拡張）]
                                               ↓
                                        [M3〜M5: 既存（無改変）]
```

**変更なし（Phase 2 で改変しない）:**
- `scripts/m1_pdf_agent.py`
- `scripts/m3_gap_analysis_agent.py`
- `scripts/m4_proposal_agent.py`
- `scripts/m5_report_agent.py`

---

## 6. 技術的リスクと対処方針

| リスク | 深刻度 | 対処方針 |
|--------|--------|---------|
| **EDINET サイト構造変更** | 中 | 直接 PDF DL URL のパターン (`/searchdocument/pdf/{id}.pdf`) は安定。書類一覧 API は公式仕様のため変更リスク低 |
| **EDINET API の Subscription-Key 取得** | 中 | M7-1（直接DL）はキー不要で先行実装可能。M7-2 は Subscription-Key 取得後に実装 |
| **金融庁HP スクレイピング（M6）** | 中 | サイト構造変更で壊れるリスクあり。変更検知の CI テストを追加。フォールバックは手動 YAML のみ |
| **e-Gov API の仕様変更** | 低 | 公式 REST API。廃止時はスクレイピングに切り替え |
| **法令 YAML の手動メンテ遅延** | 中 | 自動取得で補完するが、品質保証は手動。重要改正はアラートで通知 |
| **M6 自動取得の hallucination** | 高 | 自動取得はメタデータ（タイトル・URL・施行日）のみ。要約文はLLMで生成禁止。手動 YAML が最終権威 |
| **Phase 1 互換性の破壊** | 低 | M1〜M5 は無改変。M2・run_e2e.py は後方互換 API を維持 |

---

## 7. 推定実装規模（Phase 2 全体）

| カテゴリ | ファイル | 新規行数 | テスト件数 |
|---------|---------|---------|-----------|
| **M6** | m6_law_fetcher.py（新規） | 250 | 15 |
| **M6** | test_m6_law_fetcher.py（新規） | 130 | — |
| **M7** | m7_edinet_client.py（新規） | 240 | 15 |
| **M7** | test_m7_edinet_client.py（新規） | 140 | — |
| **M7.5** | m2_law_agent.py 拡張 | +60 | +10 |
| **UI** | app.py 拡張（入力方式選択・決算月） | +120 | 手動確認 |
| **E2E** | run_e2e.py 拡張（EDINET入力対応） | +50 | +5 |
| **合計** | 7ファイル変更 | **990行** | **45件** |

---

## 8. 着手順序（推奨）

```
Sprint 1（1〜2週）:
  1. calc_law_reference_period() 実装（M7.5 先行）
     → 単体テスト10件 → 既存テスト回帰確認
  2. EdinetClient.download_pdf() 実装（M7-1）
     → モックテスト → 実 EDINET で手動確認

Sprint 2（2〜3週）:
  3. LawFetcher.fetch_fsa_updates() 実装（M6）
     → スクレイピング PoC → テスト追加
  4. app.py に入力方式選択・決算月プルダウン追加（UI拡張）

Sprint 3（1〜2週）:
  5. E2E テスト更新（EDINET入力フロー確認）
  6. Subscription-Key 取得後に書類一覧 API 実装（M7-2）
```

---

## 9. Phase 2 完了の定義（Success Criteria 具体化）

| 条件 | 検証方法 |
|------|---------|
| **EDINET の書類管理番号を入力してレポートが生成できる** | company_a の書類管理番号（S100VHUZ）から DL → レポート生成を E2E で確認 |
| **12月決算の法令参照期間が正しく算出される** | `calc_law_reference_period(2024, 12)` → `("2024-01-01", "2024-12-31")` のテストPASS |
| **6月決算の法令参照期間が正しく算出される** | `calc_law_reference_period(2024, 6)` → `("2024-07-01", "2025-06-30")` のテストPASS |
| **Phase 1 の既存 22 テストが全 PASS 維持** | `USE_MOCK_LLM=true pytest scripts/test_e2e_pipeline.py` → 22 passed |
| **M6 自動取得が 1 件以上の法令エントリを取得できる** | 金融庁 HP の最新情報から 1 件以上取得・YAML 生成確認 |

---

## 10. 関連ドキュメント

- `00_Requirements_Definition.md` — Phase 2 要件定義（§9.2, §3.3.1, §7.1, §7.3）
- `10_Research/PDF_PoC_Result.md` — EDINET URL・ライブラリ選定結果
- `10_Research/gap_analysis_design.md` — M3 設計書（Phase 2 への影響範囲確認用）
- `10_Research/law_yaml_format_design.md` — 法令 YAML スキーマ（M6 の拡張ベース）
- `10_Research/EDINET_サンプル取得手順.md` — EDINET 手動取得手順（M7-1 のベース）
- `skills/e2e-pipeline-runner.md` — E2E パイプラインスキル設計書
