---
title: "銀行業の有報チェックをAIで自動化する — 業種特化モジュール実装"
emoji: "🏦"
type: "tech"
topics: ["python", "ai", "金融", "銀行", "有価証券報告書"]
published: false
---

## はじめに

「自己資本比率はCET1・Tier1・総自己資本の3本立て、不良債権は4区分で分類、IRRBB（銀行勘定の金利リスク）はEVEとNIIの両面で開示——」

銀行の有価証券報告書には、一般事業会社には存在しない業種固有の開示義務が多数ある。バーゼルIII（第3の柱）・金融再生法・主要行等向け監督指針に基づくこれらのチェック項目を、担当者が手作業で網羅するのは容易ではない。

本記事では、Python製マルチエージェントシステム **disclosure-multiagent** を使って、銀行業の有報開示チェックを自動化する「業種特化モジュール」の実装を解説する。`laws/banking_2025.yaml` に定義した銀行業特化チェック項目（10件）を M2法令収集エージェント（`m2_law_agent.py`）が読み込み、M3ギャップ分析エージェントが `BANKING_KEYWORDS` で有報の関連セクションを自動検出する仕組みだ。

銀行IR担当者・会計士・金融法務エンジニア向けの実装記録として、法令の背景から実コードまでを包括的にカバーする。

---

## 1. 銀行業有報が特殊である理由

### 1-1. 一般事業会社との根本的な違い

有価証券報告書は全上場企業に共通のフォーマットだが、銀行・信託・証券等の金融業種には追加的な開示義務が課されている。その根拠は主に3つだ。

**① バーゼルIII第3の柱（市場規律）**
金融庁告示・銀行法施行規則に基づき、自己資本比率・流動性・レバレッジ比率の開示が義務化されている。プルーデンシャル規制の「見える化」が目的だ。

**② 金融再生法（1998年制定）**
不良債権の実態を社会に示すための法律。与信先を「破綻先」「実質破綻先」「破綻懸念先」「要管理先」の4区分で分類し、残高・保全状況を開示する義務がある。

**③ 主要行等向けの総合的な監督指針（金融庁）**
各種リスク管理体制（信用リスク・金利リスク・オペリスク等）の開示の考え方を示す行政文書。法令ではないが有報審査で参照される実質的な基準だ。

### 1-2. banking_2025.yaml の全体像

`laws/banking_2025.yaml` はこれらの開示要件を10件のエントリとして構造化したファイルだ。

```
banking_2025.yaml — 10件の銀行業特化チェック項目

【第1群】バーゼルIII 第3の柱（bk-2025-001〜005）
├── bk-2025-001: 自己資本比率（CET1/Tier1/総自己資本）        [追加必須]
├── bk-2025-002: リスク加重資産（RWA）内訳                      [追加必須]
├── bk-2025-003: 流動性カバレッジ比率（LCR）                    [追加必須]
├── bk-2025-004: 安定調達比率（NSFR）                           [追加必須]
└── bk-2025-005: レバレッジ比率                                  [追加必須]

【第2群】不良債権・貸倒引当金（bk-2025-006〜007）
├── bk-2025-006: 不良債権残高・4区分分類（金融再生法）           [追加必須]
└── bk-2025-007: 貸倒引当金の計上方針（個別/一般）               [追加必須]

【第3群】信用リスク・金利リスク・ストレステスト（bk-2025-008〜010）
├── bk-2025-008: 信用リスク管理体制                              [修正推奨]
├── bk-2025-009: 金利リスク（IRRBB）管理                         [修正推奨]
└── bk-2025-010: ストレステスト・シナリオ分析                    [修正推奨]
```

`change_type` が「追加必須」の7件は未開示の場合に法令違反リスクがあり、「修正推奨」の3件は開示内容の充実を求めるものだ。

### 1-3. 人的資本・SSBJ との重複課題

銀行・保険等の金融業種は、バーゼルIII開示と並行して、一般上場企業と同じ義務を負っている。

- **人的資本開示**（`human_capital_2024.yaml`）: 女性管理職比率・男性育休取得率・平均給与増減率（2024年3月期以降・全上場企業）
- **SSBJ開示**（`ssbj_2025.yaml`）: GHG排出量・シナリオ分析・移行計画（大規模プライムは2027年3月期から強制）

つまり大手銀行の有報チェックは、**人的資本4件 + SSBJ25件 + 銀行業10件 = 合計39件**をカバーする必要がある。これを人手で毎期チェックするコストは相当高い。

---

## 2. banking_2025.yaml: 銀行業特化YAMLの設計

### 2-1. YAMLスキーマ

`banking_2025.yaml` は他の法令YAMLと同じスキーマを使用する。

```yaml
# laws/banking_2025.yaml（抜粋）
version: "1.0"
effective_period:
  from: "2025-04-01"
  to:   "2026-03-31"

amendments:
  - id: "bk-2025-001"
    category: "銀行業（バーゼルIII）"
    change_type: "追加必須"
    effective_from: "2025-04-01"
    title: "バーゼルIII第3の柱 — 自己資本比率の開示（CET1 / Tier1 / 総自己資本）"
    source: "https://www.fsa.go.jp/news/r5/ginkou/20231020/01.pdf"
    source_confirmed: true
    summary: >
      バーゼルIII第3の柱（市場規律）に基づく自己資本比率の開示要件。
      普通株式等Tier1比率（CET1比率）・Tier1比率・総自己資本比率の各数値を
      連結・単体ベースで開示する。（中略）
    target_sections:
      - "リスク管理の状況"
      - "自己資本の充実の状況"
      - "財務上の主要な指標"
    required_items:
      - "CET1比率（普通株式等Tier1比率）の連結・単体数値"
      - "Tier1比率の連結・単体数値"
      - "総自己資本比率の連結・単体数値"
      - "規制上の最低水準との比較（バッファー充足状況）"
    applicable_markets:
      - "プライム"
      - "スタンダード"
    notes: "地方銀行・信用金庫等の内部格付け手法適用行は開示様式が異なる場合がある"
```

`required_items` フィールドが有報審査の核心だ。M3エージェントはこのリストと有報の文章を照合してギャップを検出する。

### 2-2. 第1群詳解：バーゼルIII第3の柱（5件）

バーゼルIIIは第1の柱（最低所要自己資本）・第2の柱（監督上の検証）・第3の柱（市場規律）の3層構造だ。有報との関連は主に第3の柱——マーケットへの情報開示だ。

| ID | 指標 | 規制最低値 | 主な開示箇所 |
|---|---|---|---|
| bk-2025-001 | CET1比率 / Tier1 / 総自己資本 | 4.5% / 6% / 8% | 自己資本の充実の状況 |
| bk-2025-002 | リスク加重資産（RWA）内訳 | — | 自己資本の充実の状況 |
| bk-2025-003 | 流動性カバレッジ比率（LCR） | 100% | 流動性リスク管理 |
| bk-2025-004 | 安定調達比率（NSFR） | 100% | 流動性リスク管理 |
| bk-2025-005 | レバレッジ比率 | 3% | リスク管理の状況 |

RWA（bk-2025-002）は「信用リスク/市場リスク/オペレーショナルリスクの内訳と算出方法、前期比較および変動要因説明」を要する。内部格付け手法採用行はOVA・OV1テンプレートへの対応も必要で、開示負担が大きい項目だ。

### 2-3. 第2群詳解：不良債権・貸倒引当金（2件）

金融再生法に基づく不良債権の4区分分類は、銀行業有報固有の開示だ。

```
不良債権4区分（bk-2025-006 required_items より）
├── 破綻先債権: 法的・実質的に経営破綻した先
├── 実質破綻先債権: 実質的に経営破綻状態の先（法的整理前）
├── 破綻懸念先債権: 経営破綻の可能性が高い先
└── 要管理先: 3ヶ月以上延滞債権 + 貸出条件緩和債権（要注意先の一部）
```

各区分の残高・担保/保証による保全額・未保全額と、前期比較による不良債権比率（対総与信）の記載が求められる。

貸倒引当金（bk-2025-007）は「個別貸倒引当金（要管理先以下の個別与信先）」と「一般貸倒引当金（正常先・要注意先の損失実績率ベース）」の区分で、計上額・算出方法・引当率の根拠を記載する。IFRS9採用行は予想信用損失（ECL）3ステージ方式の概要説明も必要だ。

### 2-4. 第3群詳解：信用リスク・金利リスク・ストレステスト（3件）

| ID | 内容 | 主な開示ポイント |
|---|---|---|
| bk-2025-008 | 信用リスク管理体制 | 格付け体系・承認権限・大口与信先(自己資本10%超)管理 |
| bk-2025-009 | 金利リスク（IRRBB） | EVE（経済価値）・NII（純金利収益）への金利変動影響額、コア預金モデルの前提 |
| bk-2025-010 | ストレステスト | マクロ経済ストレス下の自己資本比率・流動性耐性の試算結果 |

bk-2025-009のIRRBBは、バーゼルIIIのIRRBB基準（2016年）の国内実施（2020年3月末施行）に対応する。金利変動シナリオとして「パラレルシフト・スティープニング・フラットニング」等を用い、EVE（銀行全体の経済価値への影響）とNII（1年間の純金利収益への影響）をそれぞれ開示する。

---

## 3. M2法令収集エージェント（m2_law_agent.py）の仕組み

### 3-1. マルチYAML読み込み：_load_all_from_dir

`m2_law_agent.py` の最重要機能は `_load_all_from_dir()` だ。`laws/` ディレクトリ配下の全 `*.yaml` を自動検出して読み込み、エントリを結合する。

```python
# m2_law_agent.py — _load_all_from_dir（抜粋）
def _load_all_from_dir(yaml_dir: Path) -> tuple[list[LawEntry], Path]:
    all_entries: list[LawEntry] = []
    last_yaml: Path = yaml_dir  # fallback
    for yaml_path in sorted(yaml_dir.glob("*.yaml")):
        try:
            entries = load_law_entries(yaml_path)
            all_entries.extend(entries)
            last_yaml = yaml_path
        except (ValueError, FileNotFoundError) as e:
            logger.warning("スキップ: %s: %s", yaml_path.name, e)
    return all_entries, last_yaml
```

現在の `laws/` ディレクトリには以下の4ファイルが存在し、合計で数十件のエントリが結合される。

```
laws/
├── banking_2025.yaml          # 銀行業特化 10件（bk-2025-001〜010）
├── human_capital_2024.yaml    # 人的資本 8件（hc-2024-001〜004 + sb-2024-001〜004）
├── shareholder_notice_2025.yaml  # 招集通知 16件（gm-2025-001〜012 + gc-2025-001〜004）
└── ssbj_2025.yaml             # SSBJ 25件（sb-2025-001〜025）
```

この設計のメリットは **新しい業種・法令を追加する際にYAMLファイルを1つ置くだけでよい** ことだ。コードの変更は不要で、次回 `load_law_context()` 実行時に自動的に読み込まれる。

### 3-2. メインAPI: load_law_context の処理フロー

`load_law_context()` は fiscal_year（事業年度）と fiscal_month_end（決算月）からLawContextを生成するメインAPIだ。

```python
# m2_law_agent.py — load_law_context（抜粋）
def load_law_context(
    fiscal_year: int,
    fiscal_month_end: int = 3,
    yaml_path: Optional[Path] = None,
    categories: Optional[list[str]] = None,
) -> LawContext:
    """
    処理フロー:
      1. YAMLファイル読み込み（yaml_path=None → _load_all_from_dir）
      2. 法令参照期間を算出（calc_law_ref_period使用）
      3. 参照期間内エントリをフィルタ（get_applicable_entries）
      4. 重要カテゴリの網羅性チェック（warnings生成）
      5. LawContextとして返す
    """
    # yaml_path=None → laws/ 配下の全YAMLを結合
    if yaml_path is not None:
        all_entries = load_law_entries(yaml_path)
    else:
        all_entries, target_yaml = _load_all_from_dir(LAW_YAML_DIR)

    # 法令参照期間の算出（m3のcalc_law_ref_periodを使用）
    ref_start, ref_end = calc_law_ref_period(fiscal_year, fiscal_month_end)

    # 日付フィルタ + カテゴリフィルタ
    applicable = get_applicable_entries(
        all_entries,
        ref_period=(ref_start, ref_end),
        categories=categories,
    )
    ...
```

4つの引数のうち特に重要なのが `categories` だ。

### 3-3. カテゴリフィルタによる業種特化

`categories` を指定することで、特定業種のチェック項目のみを抽出できる。

```python
from m2_law_agent import load_law_context

# 銀行業のみを対象とした法令コンテキスト取得
banking_categories = [
    "銀行業（バーゼルIII）",
    "銀行業（不良債権）",
    "銀行業（信用リスク）",
    "銀行業（金利リスク）",
    "銀行業（ストレステスト）",
]

law_ctx = load_law_context(
    fiscal_year=2025,
    fiscal_month_end=3,
    categories=banking_categories,
)
print(f"適用エントリ: {len(law_ctx.applicable_entries)}件")
# → 適用エントリ: 10件
```

逆に `categories=None` とすれば、banking/人的資本/SSBJ/招集通知の全エントリが結合されてチェックされる。大手銀行の有報チェックでは実質的にこちらがデフォルトだ。

### 3-4. CRITICAL_CATEGORIES と網羅性チェック

`m2_law_agent.py` には重要カテゴリの網羅性チェック機能がある。

```python
# m2_law_agent.py L51
CRITICAL_CATEGORIES = ["人的資本ガイダンス", "金商法・開示府令", "SSBJ"]
```

`load_law_context()` の内部でこのリストに対して「一致するエントリが0件の場合は `warnings` にアラート追加」という処理が走る。

```python
# STEP 4: 重要カテゴリの網羅性チェック
warnings: list[str] = []
for cat in CRITICAL_CATEGORIES:
    if not any(e.category == cat for e in applicable):
        warnings.append(f"⚠️ 重要カテゴリのエントリが0件: {cat}")
```

`banking_2025.yaml` のカテゴリは `"銀行業（バーゼルIII）"` 等だが、`CRITICAL_CATEGORIES` に `"銀行業（バーゼルIII）"` は含まれていないため、銀行業のみでフィルタした場合にアラートが出ることはない。将来的に銀行業を CRITICAL_CATEGORIES に追加する拡張も容易だ。

---

## 4. M3エージェントのBANKING_KEYWORDS: 関連セクション自動判定

### 4-1. BANKING_KEYWORDS の定義

`m3_gap_analysis_agent.py` に、銀行業有報の関連セクションを判定するキーワードリストが定義されている。

```python
# m3_gap_analysis_agent.py L60-72（実装より）

# 銀行業特化関連セクション判定キーワード（バーゼルIII / 不良債権引当）
BANKING_KEYWORDS = [
    "バーゼル", "Basel", "自己資本比率", "CET1", "Tier1", "Tier2",
    "リスク加重資産", "RWA", "LCR", "流動性カバレッジ", "NSFR", "安定調達",
    "レバレッジ比率", "不良債権", "貸倒引当金", "信用リスク", "与信",
    "要管理先", "破綻懸念先", "実質破綻先", "破綻先",
    "金利リスク", "IRRBB", "EVE", "NII", "ストレステスト",
    "流動性リスク", "市場リスク", "オペレーショナルリスク",
    "個別貸倒引当金", "一般貸倒引当金", "集中リスク",
]

# 関連性判定に使用する全キーワード（人的資本 + SSBJ + 銀行業）
ALL_RELEVANCE_KEYWORDS = HUMAN_CAPITAL_KEYWORDS + SSBJ_KEYWORDS + BANKING_KEYWORDS
```

3カテゴリのキーワードを統合した `ALL_RELEVANCE_KEYWORDS` が、有報の各セクションが「チェック対象の関連セクションか否か」を判定するために使われる。

### 4-2. is_relevant_section による関連セクション判定

```python
# m3_gap_analysis_agent.py — is_relevant_section（概念コード）
def is_relevant_section(section: SectionData) -> bool:
    """
    有報のセクションが法令チェック対象かどうかを判定する。
    見出し + 本文冒頭200文字でキーワードマッチング。
    """
    combined = section.heading + section.text[:200]
    return any(kw in combined for kw in ALL_RELEVANCE_KEYWORDS)
```

例えば有報の「リスク管理の状況 > 信用リスク管理」セクションは、見出しに「信用リスク」が含まれるため `BANKING_KEYWORDS` にマッチし、チェック対象として抽出される。

逆に「連結財務諸表注記 > 固定資産の減価償却方法」のようなセクションはいずれのキーワードにもマッチしないため、スキップされる。

### 4-3. 銀行業キーワードの設計思想

BANKING_KEYWORDS を観察すると3つの設計方針が見える。

**英語略語 + 日本語名称の両方を登録**
`"LCR"` と `"流動性カバレッジ"` のように、同じ概念の英略語と日本語を両方登録する。有報によって「LCR」と書く企業と「流動性カバレッジ比率」と書く企業が混在するためだ。

**特定度の高いキーワードを優先**
`"Tier1"` は銀行文書以外ではほぼ登場しない特定度の高い単語だ。こういったキーワードを登録することで、非銀行業の有報で誤検出するリスクを下げている。

**不良債権4区分を全て登録**
`"要管理先"` `"破綻懸念先"` `"実質破綻先"` `"破綻先"` を個別登録。4区分のうち1つでも記載があればセクションを抽出できる。

---

## 5. 実装コード全体: 銀行業有報の一括チェック

### 5-1. 銀行業特化チェックの実行

以下は banking_2025.yaml の全10件を対象に、有報とのギャップを分析する実装例だ。

```python
from pathlib import Path
from m2_law_agent import load_law_context
from m3_gap_analysis_agent import analyze_gaps, StructuredReport

# STEP 1: 銀行業カテゴリのみでLawContext生成
banking_categories = [
    "銀行業（バーゼルIII）",
    "銀行業（不良債権）",
    "銀行業（信用リスク）",
    "銀行業（金利リスク）",
    "銀行業（ストレステスト）",
]

law_ctx = load_law_context(
    fiscal_year=2025,
    fiscal_month_end=3,
    categories=banking_categories,
)
print(f"銀行業エントリ: {len(law_ctx.applicable_entries)}件")
# → 銀行業エントリ: 10件

# STEP 2: 有報を StructuredReport として読み込む（M1エージェント担当）
# （本デモでは省略 — 実際は M1: m1_pdf_agent.py でPDFを解析）
demo_report = StructuredReport(
    company="○○銀行株式会社",
    fiscal_year="2025年3月期",
    sections=[],  # M1出力をここに渡す
)

# STEP 3: M3 ギャップ分析
gap_result = analyze_gaps(demo_report, law_ctx)
print(f"ギャップ件数: {gap_result.summary.total_gaps}")
print(f"  追加必須: {gap_result.summary.by_change_type.get('追加必須', 0)}件")
print(f"  修正推奨: {gap_result.summary.by_change_type.get('修正推奨', 0)}件")
```

### 5-2. 全カテゴリ一括チェック（大手銀行向け）

`categories=None` にすると、人的資本・SSBJ・銀行業を一括チェックする。

```python
# 大手銀行向け: 全カテゴリ（banking + 人的資本 + SSBJ + 招集通知）
law_ctx_all = load_law_context(
    fiscal_year=2025,
    fiscal_month_end=3,
    # categories=None → laws/ 配下の全YAMLが対象
)
print(f"全カテゴリエントリ数: {len(law_ctx_all.applicable_entries)}件")
# → 全カテゴリエントリ数: 59件（banking 10 + 人的資本 8 + SSBJ 25 + 招集通知 16）

# 警告確認
for w in law_ctx_all.warnings:
    print(w)
```

---

## 6. B→C戦略: 銀行・地銀への受託展開

### 6-1. 銀行業有報チェックの市場規模

日本の銀行業は有報開示において特殊な難しさを抱えており、これが受託展開の商機になる。

**対象機関の規模感**
- 大手行（メガバンク3グループ）: プライム市場、有報の分量が一般企業の2〜3倍
- 地方銀行（62行 + 第二地銀38行）: 地域金融機関でも全員プライム/スタンダード上場
- 信用金庫・信用組合: 開示府令の対象外だが、銀行法施行規則ベースで同等の開示義務

合計100行超の全上場銀行が `banking_2025.yaml` の10件と、人的資本・SSBJ（合計39件）のチェック対象となる。

### 6-2. 銀行業特化の受託展開シナリオ

disclosure-multiagent の銀行業特化モジュールを商用展開する場合、以下のシナリオが想定される。

**ターゲット①: 大手行（メガバンク）**

内部のコンプライアンス・IR部門が有報審査を行うが、バーゼルIII開示の複雑さ（OVA/OV1テンプレート・IRRBB開示等）により専門ツールへのニーズがある。提供価値は「ギャップ検出の自動化」よりも「開示の充実度スコアリング（松竹梅）」だ。

```python
# 大手行向け: 追加必須 + 修正推奨の両方を高精度でチェック
law_ctx = load_law_context(
    fiscal_year=2025,
    fiscal_month_end=3,
    categories=None,  # 全カテゴリ（banking + 人的資本 + SSBJ）
)
# M4提案エージェントで松（ベストプラクティス）水準の開示文案を自動生成
```

**ターゲット②: 地方銀行**

62行の地方銀行はIT・法務リソースが限られており、毎期の有報チェックを外部委託したいニーズが強い。`categories` で銀行業に絞ったチェックをSaaS提供するシナリオが現実的だ。

```python
# 地方銀行向け: 銀行業 + 人的資本のみ（SSBJ対応は任意適用段階）
banking_categories = [
    "銀行業（バーゼルIII）",
    "銀行業（不良債権）",
    "銀行業（信用リスク）",
    "銀行業（金利リスク）",
    "銀行業（ストレステスト）",
    "人的資本",
]
law_ctx = load_law_context(
    fiscal_year=2025,
    fiscal_month_end=3,
    categories=banking_categories,
)
# → 12件に絞り込み（銀行業10件 + 人的資本2件）
```

**ターゲット③: 監査法人・会計士事務所**

有報の監査プロセスに disclosure-multiagent を組み込むことで、銀行業クライアントの開示チェックを効率化する。監査調書の補助ツールとしての位置づけだ。

### 6-3. 地銀向けカスタマイズ: 業種内の差異対応

地方銀行内にも開示要件の差異がある。

| 銀行種別 | 国際統一基準行 | 国内基準行 |
|---|---|---|
| LCR開示（bk-2025-003） | 必須（国際業務あり） | 不要 |
| NSFR開示（bk-2025-004） | 必須（2021年3月〜） | 不要 |
| レバレッジ比率（bk-2025-005） | 必須 | 2023年3月〜適用拡大 |

`banking_2025.yaml` の `applicable_markets` や `notes` フィールドにこの差異情報が記録されており、M2の `get_applicable_entries()` でフィルタリングできる設計になっている。将来的に `applicable_institution_type: ["国際統一基準行"]` のような追加フィールドを YAML に加えれば、銀行種別による絞り込みにも対応できる。

### 6-4. fiscal_year による複数年度対応

`load_law_context()` の `fiscal_year` 引数は `calc_law_ref_period()` を使って法令参照期間を計算し、`effective_from` フィールドと照合してフィルタリングする。

```python
# 2024年3月期（銀行業の一部 + 人的資本）
ctx_2024 = load_law_context(fiscal_year=2024, fiscal_month_end=3)
# → hc-2024-001〜004（人的資本）が対象
# → banking_2025.yaml のエントリは effective_from="2025-04-01" のため除外

# 2025年3月期（banking_2025.yaml が対象に含まれる）
ctx_2025 = load_law_context(fiscal_year=2025, fiscal_month_end=3)
# → banking_2025.yaml 全10件が対象
```

この動的フィルタリングにより、**同じコードで複数年度・複数クライアントの有報チェックに対応**できる。地銀向け受託サービスとして、毎期の決算確定後に自動バッチ実行する運用が実現可能だ。

---

## 7. まとめ：disclosure-multiagent の業種特化設計

### 7-1. 実装のポイント整理

本記事で解説した銀行業対応の核心は3点だ。

**① laws/ ディレクトリの YAML 追加だけで業種拡張**

`banking_2025.yaml` を `laws/` に置いただけで、`_load_all_from_dir()` が自動読み込みする。M2・M3のコードに変更不要。将来の証券業・保険業・地方銀行固有要件にも同じパターンで対応できる。

**② BANKING_KEYWORDS による業種特化セクション検出**

M3の `BANKING_KEYWORDS`（32語）が「CET1」「IRRBB」「破綻懸念先」等の銀行固有キーワードを登録。有報の全セクションを高速スキャンして関連箇所を自動抽出する。人的資本・SSBJ・銀行業の3カテゴリを `ALL_RELEVANCE_KEYWORDS` で統合しているため、大手銀行の有報でも一度の解析で全カテゴリのギャップを検出できる。

**③ categories 引数による業種絞り込み**

`load_law_context(categories=["銀行業（バーゼルIII）", ...])` と指定することで、銀行業専用モードで動作する。スタンダード上場の地方銀行に SSBJチェックが不要な場合などに有用だ。

### 7-2. 対応チェック項目の全体像（2025年3月期時点）

| カテゴリ | 件数 | 法的性質 | 追加必須件数 |
|---|---|---|---|
| 銀行業（バーゼルIII） | 5件 | 追加必須 | 5件 |
| 銀行業（不良債権/引当） | 2件 | 追加必須 | 2件 |
| 銀行業（信用/金利/ストレス） | 3件 | 修正推奨 | 0件 |
| 人的資本（開示府令） | 2件 | 追加必須 | 2件 |
| 人的資本（ガイドライン） | 2件 | 修正推奨 | 0件 |
| SSBJ（確定基準） | 25件 | 追加必須 | 10件 |
| **合計** | **39件** | | **19件（追加必須）** |

大手プライム銀行は2027年3月期までに39件全てに対応する必要がある。disclosure-multiagent はこの複雑なチェックを M2（法令収集）→ M3（ギャップ分析）→ M4（松竹梅提案）→ M5（レポート出力）のパイプラインで自動化する。

### 7-3. 今後の拡張方向

現在の業種特化対応は銀行業のみだが、以下の拡張が想定される。

```
laws/
├── banking_2025.yaml        ✅ 実装済み（10件）
├── insurance_2025.yaml      （予定: ソルベンシーII等）
├── securities_2025.yaml     （予定: 金商法500条対応等）
└── real_estate_2025.yaml    （予定: 不動産特化KPI等）
```

各ファイルを `laws/` に追加するだけで、`_load_all_from_dir()` が自動的に読み込む。M3の KEYWORDS定数（`INSURANCE_KEYWORDS` 等）を追加すれば関連セクション判定も業種特化できる。

disclosure-multiagent の設計は「法令の追加を YAML 追加のみで完結させる」というオープンクローズド原則を貫いている。銀行業有報の複雑な開示要件も、この設計によって低コストで自動チェック体制を構築できる。

---

*筆者: Majiro-ns / disclosure-multiagent プロジェクト*
*参照: laws/banking_2025.yaml / laws/human_capital_2024.yaml / scripts/m2_law_agent.py*
