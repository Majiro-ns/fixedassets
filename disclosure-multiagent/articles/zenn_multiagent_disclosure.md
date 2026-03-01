---
title: "マルチエージェントで有報の開示変更レポートを自動生成するシステムを作った"
emoji: "📋"
type: "tech"
topics: ["python", "multiagent", "llm", "金融", "有価証券報告書"]
published: false
---

## はじめに

有価証券報告書（有報）の開示内容は、毎年度の法令改正に合わせて更新が必要です。しかし「どの記載を変えるか」「どう書けばいいか」を追跡するのは、担当者にとって地道な作業です。

そこで、Claude（Anthropic）を活用したマルチエージェントシステム **disclosure-multiagent** を作りました。有報PDF を入力すると、翌期に必要な変更箇所と提案文を自動生成します。さらに開発基盤として **multi-agent-shogun**（tmux + Claude Code による並列AI開発フレームワーク）を活用し、複数の「AI足軽」が並行して実装を進める実験も行いました。

---

## 背景・課題

### 有報開示変更対応の現状

上場企業は毎年、内閣府令改正に合わせて有報の記載内容を見直す必要があります。特に近年は **人的資本開示** の強化が続いており、以下のような新規記載が求められています。

- 企業戦略と連動した人材戦略の開示（必須）
- 従業員給与の決定方針・賃上げ方針（必須）
- 平均年間給与の対前年増減率（連結・単体両方）
- 男女間賃金格差の開示

これらを「昨年の有報を見ながら、法令改正情報と照らし合わせて、抜け漏れを探す」作業は、ツールがなければ非常に手間がかかります。

### LLMで解決できること

LLMは「既存の有報テキスト × 法令改正情報 → ギャップを発見し、改善提案を生成」するタスクが得意です。Claude を使えば、法律文書の読み解きと自然な日本語での提案文生成の両方が期待できます。

---

## システム概要

5つのエージェント（M1〜M5）がパイプラインを形成します。

```
有報PDF
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│ M1: PDF解析エージェント                                    │
│   PyMuPDF でテキスト抽出 → StructuredReport（セクション分割） │
└────────────────────┬────────────────────────────────────┘
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
┌──────────────────┐   ┌──────────────────┐
│ M2: 法令取得      │   │  (M1出力を保持)   │
│   YAML → LawContext│   └──────────────────┘
└────────┬─────────┘
         │ StructuredReport + LawContext
         ▼
┌─────────────────────────────────────────────────────────┐
│ M3: ギャップ分析エージェント                               │
│   (有報セクション × 法令エントリ) → GapAnalysisResult      │
│   USE_MOCK_LLM=true でAPIキー不要テストが可能              │
└────────────────────┬────────────────────────────────────┘
                     │ GapItem（has_gap=True のもの）
                     ▼
┌─────────────────────────────────────────────────────────┐
│ M4: 松竹梅提案エージェント                                 │
│   GapItem × 3レベル → ProposalSet                        │
└────────────────────┬────────────────────────────────────┘
                     │ ProposalSet リスト
                     ▼
┌─────────────────────────────────────────────────────────┐
│ M5: レポート統合エージェント                               │
│   全出力 → Markdown レポート                              │
└─────────────────────────────────────────────────────────┘
                     │
                     ▼
          開示変更レポート（.md）
```

---

## 各モジュール解説

### M1: PDF解析エージェント（PyMuPDF）

有報PDFからテキストを抽出し、セクション単位に分割します。

```python
# 有報の見出しパターンを正規表現でマッチ
HEADING_PATTERNS = [
    re.compile(r'^第[一二三四五六七八九十\d]+部'),   # 「第一部」
    re.compile(r'^[（(]\d+[）)]\s*[\u4e00-\u9fff]'), # 「（1）人的資本」
    re.compile(r'^\d+\.\s*[\u4e00-\u9fff]{2,}'),     # 「1. 人材戦略」
    # ... 計8パターン
]

# 人的資本関連セクションのみを抽出
JINJI_SECTION_KEYWORDS = ["人的資本", "人材戦略", "従業員の状況", "ダイバーシティ", ...]
```

出力は `StructuredReport`（データクラス）で、セクションリスト・会社名・事業年度などを持ちます。PyMuPDF が未インストールの環境でも `--test` フラグで動作確認できる設計にしました。

### M2: 法令取得エージェント（YAMLベース）

法令情報は YAMLファイルで管理します。将来的にはスクレイピングも想定していますが、Phase 1 では手動で整備した `human_capital.yaml` を使います。

```yaml
# human_capital.yaml（抜粋イメージ）
entries:
  - id: HC_20260220_001
    title: "企業内容等の開示に関する内閣府令改正（人的資本開示拡充・給与開示）"
    effective_from: "2026-02-20"
    change_type: "追加必須"
    disclosure_items:
      - "企業戦略と関連付けた人材戦略の記載（必須）: 経営戦略との連動を明示すること"
      - "従業員給与等の決定に関する方針の記載（必須）: 賃上げに関する方針を含む"
      - "平均年間給与の対前事業年度増減率の記載（必須）: 連結・単体両方で開示"
```

`load_law_context()` は決算月・年度から適用法令を絞り込み、`LawContext` を返します。

### M3: ギャップ分析エージェント

M3 は本システムの核心です。「有報のセクション」と「法令の開示項目」を掛け合わせ、記載漏れ（ギャップ）を判定します。

#### USE_MOCK_LLM によるテスト設計

実際の Claude API を呼ぶとコストがかかります。そこで `USE_MOCK_LLM` 環境変数でモック切替ができる設計にしました。

```python
def analyze_gaps(report, law_context, use_mock=None):
    if use_mock is None:
        use_mock = os.environ.get("USE_MOCK_LLM", "").lower() in ("true", "1")

    for entry in law_context.applicable_entries:
        for disclosure_item in entry.disclosure_items:
            for section in relevant_sections:
                result = judge_gap(section, disclosure_item, entry,
                                   client=client, use_mock=use_mock)
```

モック時は `_mock_judge_response()` がキーワードマッチで `has_gap` を返します。実LLM時は Claude API を呼び、文脈を理解した判定を行います。

#### モックモードの設計上の限界

モックでは「disclosure_item のキーワードが section.text に含まれるか」だけで判定するため、PDFの内容が薄い場合は全ギャップが同じ `section_heading` に集中することがあります（これは仕様の限界であり、実LLMモードでは発生しません）。

### M4: 松竹梅提案エージェント

ギャップが見つかった項目について、3段階の提案文を生成します。

| レベル | 対象読者 | 記載スタイル |
|--------|---------|-------------|
| 松 | 充実開示を目指す企業 | KPI・数値目標・ガバナンス体制を含む詳細記載 |
| 竹 | 標準的な実務対応 | 必須項目を過不足なく満たす実務的な記載 |
| 梅 | 最小限対応 | 法令義務の最小限を満たす簡潔な記載 |

```python
# 竹レベルの提案文（実際の出力例）
"""
当社は、事業成長を支える人材基盤の強化を経営の最重要課題と位置付けています。
中期経営計画（2024〜2026年度）において、デジタル・技術領域を中心とした
専門人材の確保・育成を重点施策とし、採用・リスキリング・リテンションの
三方向から対応しています。
"""
```

### M5: レポート統合エージェント

M1〜M4 の出力を受け取り、Markdown レポートに統合します。

```python
def generate_report(structured_report, law_context, gap_result,
                    proposal_set, level) -> str:
    # 必須5セクションを生成
    # 1. 変更箇所サマリ（テーブル）
    # 2. セクション別の変更提案（各ギャップの提案文）
    # 3. 未変更項目（充足確認済み）
    # 4. 参照した法令一覧
    # 5. 免責事項詳細
```

#### pipeline_mock() による E2E テスト

実PDFや実APIキーなしで E2E を確認できる `pipeline_mock()` を実装しました。

```python
# APIキー不要でE2Eパイプライン全体を確認
from m5_report_agent import pipeline_mock
report_md = pipeline_mock(company_name="テスト株式会社", fiscal_year=2025, level="竹")
print(report_md[:500])
```

テストファイル `test_e2e_pipeline.py` では `pipeline_mock()` を使った 22 件のテストが全て `USE_MOCK_LLM=true` 環境で通るようにしました。

---

## E2E実証

実有報（121ページ、サンプル社A）を `company_a.pdf` として投入し、動作確認を行いました。

```bash
cd scripts/
USE_MOCK_LLM=true python3 run_e2e.py \
    "../10_Research/samples/company_a.pdf" \
    --company-name "サンプル社A" \
    --fiscal-year 2025 \
    --level 竹
```

生成されたレポートの構造（抜粋）:

```markdown
# 開示変更レポート — サンプル社A 有価証券報告書

- 法令参照期間: 2025/04/01 〜 2026/03/31
- 提案レベル: 竹（スタンダード実務向け）

## 1. 変更箇所サマリ

| 変更種別 | 件数 |
|----------|------|
| 追加必須 | 3    |
| 修正推奨 | 4    |
| 合計     | 7    |

## 2. セクション別の変更提案

### 2.1. （該当セクション名）

- 変更種別: 追加必須
- 対象項目: 企業戦略と関連付けた人材戦略の記載（必須）

#### 竹レベルの提案文

当社は、事業成長を支える人材基盤の強化を…（以下略）
```

`run_e2e.py` のパイプラインは M1→M2→M3→M4→M5 を順に呼び出し、`reports/` ディレクトリに Markdown ファイルとして保存します。`--stdout` フラグで標準出力にも表示できます。

---

## Streamlit UI

`app.py` として Streamlit の簡易 UI も実装しました。

```bash
cd scripts/
streamlit run app.py
```

PDFをアップロードすると M1→M5 が順に実行され、進捗バーとともにレポートが生成されます。PDFなしでも「デモモード」（`pipeline_mock()` を使用）で動作を確認できます。

### `_is_streamlit_running()` ガード

Streamlit アプリは `python3 -c "import app"` のようなインポートチェック時に `st.set_page_config()` が実行されると例外を起こします。これを防ぐため、以下のガードを実装しました。

```python
def _is_streamlit_running() -> bool:
    """Streamlit のアクティブセッション内で実行されているか確認する"""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False

if _is_streamlit_running():
    main()
```

`streamlit run app.py` では `get_script_run_ctx()` が非 None を返し、`python3 -c "import app"` では `None` を返します。これにより CI でのインポートチェックと実際の Streamlit 起動の両方に対応できます。

---

## マルチエージェント開発基盤（multi-agent-shogun）

disclosure-multiagent の開発自体も、**multi-agent-shogun** という自作フレームワークで行いました。

### 構成

```
将軍（SHOGUN）
  ├── 家老壱 → 足軽2・3・4
  └── 家老弐 → 足軽6・7・8
```

各ペインは tmux の異なる pane で動作する Claude Code インスタンスです。YAML ファイルを通信媒体として使い、タスクの割り当て・進捗報告・クロスレビューを行います。

```
queue/tasks/ashigaru3.yaml   # 足軽3へのタスク指示
queue/reports/ashigaru3_report.yaml  # 足軽3からの完了報告
```

### P9: クロスレビュー常態化

「テストが通る ≠ 正しい」という教訓から、実装完了後に別の足軽がクロスレビューを行うルール（P9）を制定しました。今回も run_e2e.py の `use_mock=True` ハードコード問題を足軽3のクロスレビューで発見し、環境変数制御へ修正しました。

---

## 課題・今後

### Phase 1 の限界

1. **モックモードの section_heading 問題**: `USE_MOCK_LLM=true` では全ギャップが同一 `section_heading` になることがある。実LLMモードでは発生しないが、テストでの可視化が不十分。

2. **法令YAMLの手動管理**: Phase 1 では `human_capital.yaml` を手動で整備。Phase 2 では法令情報の自動収集（スクレイピング/公式API）を検討。

3. **PDF品質依存**: 有報の PDF は企業によって構造が大きく異なる。見出しパターンの網羅性がカバレッジに直結する。

### Phase 2 の予定

- 実 Claude API による精度向上（`USE_MOCK_LLM=false` モード）
- 法令情報の自動取得・定期更新
- EDINETとの連携（有報PDFの自動ダウンロード）
- section_heading の多様性検証テスト追加

---

## おわりに

有報開示変更対応という「地道だが重要な作業」を LLM で自動化する試みを Phase 1 として実装しました。

特に気に入っているのは `USE_MOCK_LLM` 設計です。LLM を使うシステムは「本番APIを叩かないとテストできない」問題が生じがちですが、モック切替設計を最初から組み込むことで、CI でも E2E テストが通る構成を実現できました。

また、multi-agent-shogun による並列 AI 開発は、M1〜M5 の実装を短期間で進める上で有効でした。クロスレビューのルール化（P9）も含め、AI エージェントを品質を保ちながら運用するための知見が蓄積されつつあります。

コードは整理でき次第 GitHub に公開予定です。

---

*生成日: 2026-02-27 / 実装: disclosure-multiagent Phase 1 (cmd_063)*
