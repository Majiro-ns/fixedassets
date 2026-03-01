# 法令情報 YAML フォーマット設計書

> 作成日: 2026-02-27 / 担当: 足軽3（subtask_063a3）
> 対応タスク: MVP 開発チェックリスト Phase 1-M2（M2-1, M2-3）
> 参照: 22_MVP_Development_Checklist.md — Phase 1-M2

---

## 1. 設計方針

### 1-1. 基本原則

| 原則 | 内容 |
|------|------|
| **1改正 = 1エントリ** | 同一告示・府令でも複数の変更点がある場合は、変更点ごとに分割してエントリ化 |
| **一次情報必須** | `source` には金融庁・内閣官房・証券取引等監視委員会等の公式URLを記載（推測URL不可） |
| **施行日ベース** | `effective_from` は「適用開始事業年度」ではなく「内閣府令等の施行日」を記載。適用開始時期は `applicable_from_note` で補足 |
| **Git管理** | 各YAMLファイルはGitでバージョン管理。改正追加時はコミットログに告示番号・改正内容を記録 |
| **出典確認義務** | エントリ追加者は必ずURLを実際にアクセス確認してから記載する |

### 1-2. ファイル構成方針

```
10_Research/
├── law_yaml_format_design.md          # 本設計書
├── law_entries_human_capital.yaml     # 人的資本開示 エントリ
├── law_entries_ssbj.yaml              # SSBJ・サステナビリティ開示 エントリ
├── law_entries_corporate_governance.yaml  # コーポレートガバナンス・総会前開示 エントリ
└── law_entries_general.yaml           # 金商法・開示府令（人的資本以外）エントリ
```

**分割基準**: カテゴリ（`category` フィールド）単位でファイルを分ける。
一つの改正が複数カテゴリにまたがる場合は、主要カテゴリのファイルに記載し、他カテゴリのファイルから `see_also` で参照する。

---

## 2. YAMLスキーマ定義

### 2-1. フィールド一覧

```yaml
# =========================================================
# 法令情報エントリ スキーマ
# =========================================================
entries:
  - id: string                   # 必須 ユニークID。形式: {category_abbr}_{YYYYMMDD}_{seq}
                                 # 例: HC_20230131_001

    title: string                # 必須 改正・ガイダンスのタイトル（日本語・短め）
                                 # 例: "人的資本可視化指針の公表"

    law_name: string             # 必須 法令・告示・通達の正式名称
                                 # 例: "企業内容等の開示に関する内閣府令（第17条等改正）"

    category: string             # 必須 下記カテゴリ値のいずれか
                                 # 金商法・開示府令 / 人的資本ガイダンス / SSBJ / 総会前開示

    change_type: string          # 必須 変更種別
                                 # 追加必須 / 修正推奨 / 参考

    effective_from: date         # 必須 施行日（内閣府令等の交付・施行日）
                                 # 形式: YYYY-MM-DD

    applicable_from_note: string # 推奨 実際の有報適用開始時期（事業年度ベース）
                                 # 例: "2023年3月31日以後終了事業年度から適用"

    target_companies: string     # 推奨 対象企業の範囲
                                 # 例: "金商法第24条に基づく有価証券届出書提出会社（約4,000社）"

    summary: string              # 必須 改正・ガイダンスの要点（1〜2文）

    disclosure_items: list       # 任意 具体的な開示義務項目のリスト（箇条書き）

    source: string               # 必須 一次情報URL（金融庁・内閣官房等の公式ページ）
                                 # WebFetch/WebSearchで実際にアクセス確認したURLのみ

    source_confirmed: bool       # 必須 URLの実アクセス確認済みか（true/false）

    see_also: list               # 任意 関連エントリのID一覧

    notes: string                # 任意 実務上の補足・注意点
```

### 2-2. カテゴリ値の定義

| カテゴリ値 | 略称 | 対象 |
|-----------|------|------|
| `金商法・開示府令` | `FIN` | 金融商品取引法・企業内容等の開示に関する内閣府令・関連政令 |
| `人的資本ガイダンス` | `HC` | 内閣官房「人的資本可視化指針」・金融庁ガイダンス等 |
| `SSBJ` | `SSBJ` | サステナビリティ基準委員会（SSBJ）公表基準・関連告示 |
| `総会前開示` | `AGM` | 株主総会前の開示規制・コーポレートガバナンス報告書等 |

### 2-3. change_type の使い分け

| 値 | 意味 | 有報への影響 |
|----|------|-------------|
| `追加必須` | 法令上の義務的記載要件として新設された項目 | 未記載の場合、法令違反または当局指摘リスクがある |
| `修正推奨` | 法令要件ではないが、実務上または当局推奨として対応が強く期待される項目 | ベストプラクティスとして対応が望ましい |
| `参考` | ガイドライン・指針等での参考情報。義務・推奨ではない | 将来的な義務化に向けた準備として参照 |

---

## 3. YAMLファイル例

```yaml
# law_entries_human_capital.yaml
# 人的資本開示 法令・ガイダンス エントリ
# Last Updated: 2026-02-27
# Maintained by: disclosure-multiagent project

entries:
  - id: HC_20220830_001
    title: 人的資本可視化指針の公表
    law_name: 人的資本可視化指針（内閣官房 非財務情報可視化研究会）
    category: 人的資本ガイダンス
    change_type: 参考
    effective_from: 2022-08-30
    applicable_from_note: "指針公表日（義務ではない。2023年3月期有報から参考として活用推奨）"
    target_companies: "有価証券報告書提出会社（任意適用）"
    summary: >
      内閣官房非財務情報可視化研究会が「人的資本可視化指針」を公表。
      7つの視点・19の開示項目を示したガイダンス。義務ではないが有報開示の基礎資料。
    disclosure_items:
      - "7視点: 人材育成/エンゲージメント/流動性/多様性・包摂/健康・安全/労働慣行/コンプライアンス・倫理"
      - "19項目（詳細は指針本文参照）"
    source: https://www.cas.go.jp/jp/houdou/pdf/20220830shiryou1.pdf
    source_confirmed: true
    see_also: [HC_20230131_001]

  - id: HC_20230131_001
    title: 企業内容等の開示に関する内閣府令改正（人的資本・多様性開示義務化）
    law_name: 企業内容等の開示に関する内閣府令等の一部を改正する内閣府令（令和5年内閣府令第3号）
    category: 金商法・開示府令
    change_type: 追加必須
    effective_from: 2023-01-31
    applicable_from_note: "2023年3月31日以後に終了する事業年度に係る有価証券報告書から適用"
    target_companies: "金融商品取引法第24条に基づく有価証券報告書提出会社（大手約4,000社）"
    summary: >
      有価証券報告書に人的資本・多様性に関する記載事項が新設・義務化された。
      サステナビリティ情報欄の新設、人材育成方針・社内環境整備方針・指標・目標の開示が必須となった。
    disclosure_items:
      - "サステナビリティ情報欄の新設（様式第19号 第二部第2「事業の状況」内）"
      - "人材育成方針の記載（必須）"
      - "社内環境整備方針の記載（必須）"
      - "女性管理職比率（連結・単体）の開示（必須）"
      - "男性育児休業取得率の開示（必須）"
      - "男女間賃金格差の開示（必須）"
      - "指標・目標の開示（人材戦略と関連付けた指標は選択制）"
    source: https://www.fsa.go.jp/news/r4/sonota/20230131/20230131.html
    source_confirmed: false
    notes: "source URLは金融庁報道発表ページ推定。WebFetchで本文確認が必要。"
    see_also: [HC_20220830_001, HC_20260220_001]
```

---

## 4. 法令収集エージェント設計（M2-3）

### 4-1. 役割

**対象年度・決算期を指定 → 関連する法令改正エントリを返す** YAML読み込み型のエージェント。
Phase 1 では静的YAMLを読み込むのみ（スクレイピング・自動取得はPhase 2以降）。

### 4-2. 入力・出力

```
入力:
  - target_fiscal_year: int      # 対象年度（例: 2025 = 2025年度申告の有報）
  - fiscal_month_end: int        # 決算月（Phase 1は3月固定）
  - categories: list[str]        # フィルタするカテゴリ（省略時は全カテゴリ）

出力:
  - applicable_entries: list     # 対象期間内に施行されたエントリ一覧
  - missing_categories: list     # 重要カテゴリで1件もエントリがない場合の警告
  - law_yaml_as_of: date         # YAMLの最終更新日（レポートに明示するため）
```

### 4-3. ロジック概要

```python
# 法令収集エージェント ロジック概要（擬似コード）

def collect_applicable_laws(
    target_fiscal_year: int,
    fiscal_month_end: int = 3,
    categories: list[str] | None = None,
) -> LawCollectionResult:
    """
    対象年度・決算期に適用される法令改正エントリを収集する。

    法令参照期間:
      - 3月決算の場合: (target_fiscal_year-1)/4/1 〜 target_fiscal_year/3/31
      - 例: 2025年度（2025年3月期）= 2024/4/1 〜 2025/3/31

    エントリ収集基準:
      - effective_from が法令参照期間内のエントリを対象とする
      - ただし applicable_from_note で「〜以後終了事業年度」と記載がある場合は
        その開始日が法令参照期間の終了日（3/31）以前であるものも含める
    """

    # Step 1: 全YAMLエントリを読み込み
    entries = load_all_law_yamls(LAW_YAML_DIR)

    # Step 2: 法令参照期間の算出
    period_start = date(target_fiscal_year - 1, fiscal_month_end + 1, 1)
    period_end = date(target_fiscal_year, fiscal_month_end, 31)

    # Step 3: 日付フィルタ
    applicable = [
        e for e in entries
        if period_start <= e.effective_from <= period_end
    ]

    # Step 4: カテゴリフィルタ（指定がある場合のみ）
    if categories:
        applicable = [e for e in applicable if e.category in categories]

    # Step 5: 重要カテゴリの網羅性チェック（警告生成）
    CRITICAL_CATEGORIES = ["人的資本ガイダンス", "金商法・開示府令", "SSBJ"]
    missing = [
        cat for cat in CRITICAL_CATEGORIES
        if not any(e.category == cat for e in applicable)
    ]
    if missing:
        warnings.append(f"⚠️ 重要カテゴリのエントリが0件: {missing}")

    return LawCollectionResult(
        applicable_entries=applicable,
        missing_categories=missing,
        law_yaml_as_of=get_yaml_last_modified(),
    )
```

### 4-4. 実装上の注意点

| 注意点 | 内容 |
|--------|------|
| **法令参照期間の定義** | 3月決算: 前年4/1〜当年3/31。12月決算(Phase 2): 前年1/1〜当年12/31 |
| **hallucination対策** | YAMLに登録されていないエントリへの言及を禁止。LLMへの渡し方でも明示 |
| **YAML更新日の透明性** | レポートには必ず `法令YAML取得日: YYYY-MM-DD` を明示（22_MVP_Development_Checklist M5-2参照） |
| **重要カテゴリ警告** | 人的資本ガイダンス・金商法・SSBJの3カテゴリに1件もヒットしない場合は必ず警告 |

---

## 5. Git管理方針

### 5-1. ファイル配置

```
10_Research/
├── law_entries_*.yaml     # 改正エントリ（カテゴリ別）
└── law_yaml_format_design.md  # 本設計書

# Git管理対象: 全yamlファイル
# .gitignore 対象外（機密情報なし・全て公開情報）
```

### 5-2. コミットログ規則

```
feat(law-yaml): 人的資本開示 2026年2月改正を追加

- HC_20260220_001: 企業戦略と人材戦略の連携・給与開示義務化（2026年3月期から）
- HC_20260220_002: SSBJ基準適用（時価総額3兆円以上、2027年3月期から）

Ref: https://www.fsa.go.jp/...（金融庁報道発表URL）
```

---

## 6. 変更履歴

| 日付 | 変更内容 | 担当 |
|------|---------|------|
| 2026-02-27 | 初版作成（M2-1 法令YAMLフォーマット設計 + M2-3 法令収集エージェント設計） | 足軽3 subtask_063a3 |
