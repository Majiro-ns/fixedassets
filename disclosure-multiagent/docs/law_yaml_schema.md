---
created: 2026-02-27
type: schema-definition
tags: [disclosure-multiagent, 法令YAML, M2, スキーマ]
source: 23_Next_Actions_Detail.md §3, 00_Requirements_Definition.md §7.3
---

# 法令情報 YAML スキーマ定義

> **用途**: M2（法令収集エージェント）が使用する改正・ガイダンス情報の YAML フォーマット
> **方針**: 1改正 = 1エントリ。Git管理。起動時バリデーション付き。

---

## 1. ファイル構成

```
laws/
  human_capital_2024.yaml    # 人的資本・多様性カテゴリ（2024年度対象期間）
  ssbj_2024.yaml             # SSBJ・サステナビリティカテゴリ
  general_disclosure.yaml    # 総会前開示・その他
```

ファイルは **対象期間 × カテゴリ** で分割する。
M2 は `effective_period` を見て対象年度のエントリを絞り込む。

---

## 2. スキーマ定義

### 2.1 ファイルレベル（必須）

| フィールド | 型 | 説明 | 例 |
|------------|----|----|--|
| `version` | string | スキーマバージョン | `"1.0"` |
| `effective_period.from` | date | 対象期間の開始 | `"2024-04-01"` |
| `effective_period.to` | date | 対象期間の終了 | `"2025-03-31"` |
| `amendments` | list | エントリのリスト | — |

### 2.2 エントリレベル（必須フィールド）

| フィールド | 型 | 説明 | 例 |
|------------|----|----|--|
| `id` | string | 一意ID。`{prefix}-{年度}-{連番3桁}` | `"hc-2024-001"` |
| `category` | string | 改正カテゴリ（下記参照） | `"人的資本"` |
| `change_type` | string | 変更種別（下記参照） | `"追加必須"` |
| `effective_from` | date | 施行日または適用開始日 | `"2024-04-01"` |
| `title` | string | 法令・ガイダンスの名称 | `"開示府令改正 人的資本・多様性"` |
| `source` | string | 出典 URL | `"https://www.fsa.go.jp/..."` |
| `summary` | string | 変更内容の要約（1〜3文） | `"平均給与増減率の算出方法を明確化"` |
| `target_sections` | list[string] | 該当する有報セクション | `["人的資本"]` |

### 2.3 エントリレベル（任意フィールド）

| フィールド | 型 | 説明 | 例 |
|------------|----|----|--|
| `required_items` | list[string] | 必須記載項目 | `["平均給与増減率", "算出方法"]` |
| `applicable_markets` | list[string] | 対象上場市場 | `["プライム", "スタンダード"]` |
| `notes` | string | 補足・注意事項 | `"3月決算企業は2024年6月提出より適用"` |
| `deprecated_from` | date | 廃止・上書きされる日 | `"2025-04-01"` |

---

## 3. カテゴリ（category）の値

| 値 | 説明 |
|----|------|
| `人的資本` | 人的資本・多様性開示（開示府令、人的資本可視化指針 等） |
| `SSBJ` | サステナビリティ開示基準（SSBJ、TCFD 等） |
| `総会前開示` | 株主総会前の早期開示要請（取引所ガイドライン 等） |
| `ガバナンス` | コーポレートガバナンス報告書関連 |
| `金商法改正` | 金融商品取引法の改正 |
| `その他` | 上記に該当しないもの |

---

## 4. 変更種別（change_type）の値

| 値 | 説明 |
|----|------|
| `追加必須` | 法令上の新規義務。記載しないと法令違反または開示不備 |
| `修正推奨` | 改正・ガイダンス更新により、既存記載の見直しが強く推奨される |
| `参考` | 任意開示だが、プライム企業ではベストプラクティスとして記載が増えている |

---

## 5. ID 命名規則

```
{prefix}-{4桁年度}-{3桁連番}

prefix:
  hc   → 人的資本（Human Capital）
  sb   → SSBJ
  gm   → 総会前開示（General Meeting）
  gc   → ガバナンス（Governance）
  sc   → 金商法改正（Securities and Exchange Act Change）
  ot   → その他
```

例: `hc-2024-001`, `sb-2024-001`, `gm-2023-001`

---

## 6. サンプル YAML

```yaml
version: "1.0"
effective_period:
  from: "2024-04-01"
  to: "2025-03-31"
amendments:
  - id: "hc-2024-001"
    category: "人的資本"
    change_type: "追加必須"
    effective_from: "2024-04-01"
    title: "開示府令改正 — 人的資本・多様性の記載義務化"
    source: "https://www.fsa.go.jp/news/r4/sonota/20221114-3/20221114-3.html"
    summary: >
      2022年11月改正（2023年1月施行）。有報様式第二号に「人的資本」
      および「多様性」の記載欄が追加され、2024年3月期以降の有報から適用。
      平均給与増減率・女性管理職比率等の定量的開示が必須となった。
    target_sections: ["経営方針", "人的資本"]
    required_items:
      - "人材の確保・育成・定着の方針"
      - "平均給与増減率"
      - "女性管理職比率（連結）"
      - "男性育児休業取得率"
    applicable_markets: ["プライム", "スタンダード", "グロース"]
    notes: "3月決算企業は2024年6月提出の有報から適用"
```

---

## 7. 起動時チェックロジック

### 7.1 疑似コード

```
function validate_law_yaml(yaml_data, effective_date):
    # 対象期間内のエントリを取得
    active_entries = [
        e for e in yaml_data.amendments
        if e.effective_from <= effective_date
        and (e.deprecated_from is None or e.deprecated_from > effective_date)
    ]

    # 必須カテゴリの存在確認
    categories = {e.category for e in active_entries}

    if "人的資本" not in categories:
        raise ValidationError("人的資本カテゴリのエントリが1件以上必要です")

    # change_type の値チェック
    valid_types = {"追加必須", "修正推奨", "参考"}
    for entry in active_entries:
        if entry.change_type not in valid_types:
            raise ValidationError(f"不正な change_type: {entry.change_type} (id={entry.id})")

    # 必須フィールドの存在確認
    required_fields = ["id", "category", "change_type", "effective_from",
                       "title", "source", "summary", "target_sections"]
    for entry in active_entries:
        for field in required_fields:
            if not getattr(entry, field, None):
                raise ValidationError(f"必須フィールド欠落: {field} (id={entry.id})")

    return True  # バリデーション成功
```

### 7.2 Python 実装（m2_law_loader.py 向け参考実装）

```python
from __future__ import annotations
import yaml
from datetime import date
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = [
    "id", "category", "change_type", "effective_from",
    "title", "source", "summary", "target_sections",
]
VALID_CHANGE_TYPES = {"追加必須", "修正推奨", "参考"}
REQUIRED_CATEGORIES = {"人的資本"}  # Phase 1 必須。SSBJ は Phase 1 では任意


class LawYamlValidationError(Exception):
    pass


def validate_law_yaml(path: Path, reference_date: date | None = None) -> list[dict[str, Any]]:
    """
    法令 YAML ファイルを読み込み、バリデーションして active エントリを返す。

    Args:
        path: YAML ファイルのパス
        reference_date: 有報の事業年度開始日。None の場合は today()

    Returns:
        有効なエントリのリスト

    Raises:
        LawYamlValidationError: バリデーション失敗時
    """
    if reference_date is None:
        reference_date = date.today()

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    amendments = data.get("amendments", [])

    # 対象期間内のエントリを抽出
    active = []
    for entry in amendments:
        eff = entry.get("effective_from")
        dep = entry.get("deprecated_from")
        if isinstance(eff, str):
            eff = date.fromisoformat(eff)
        if isinstance(dep, str):
            dep = date.fromisoformat(dep)
        if eff <= reference_date and (dep is None or dep > reference_date):
            active.append(entry)

    # 必須フィールドチェック
    for entry in active:
        for field in REQUIRED_FIELDS:
            if not entry.get(field):
                raise LawYamlValidationError(
                    f"必須フィールド欠落: '{field}' (id={entry.get('id', '不明')})"
                )

    # change_type 値チェック
    for entry in active:
        if entry["change_type"] not in VALID_CHANGE_TYPES:
            raise LawYamlValidationError(
                f"不正な change_type: '{entry['change_type']}' (id={entry['id']})"
            )

    # 必須カテゴリの存在確認
    categories = {e["category"] for e in active}
    missing = REQUIRED_CATEGORIES - categories
    if missing:
        raise LawYamlValidationError(
            f"必須カテゴリのエントリが存在しません: {missing}"
        )

    return active


def load_all_laws(laws_dir: Path, reference_date: date | None = None) -> list[dict[str, Any]]:
    """
    laws/ ディレクトリ内の全 YAML を読み込み、統合して返す。
    """
    all_active: list[dict[str, Any]] = []
    for yaml_file in sorted(laws_dir.glob("*.yaml")):
        all_active.extend(validate_law_yaml(yaml_file, reference_date))
    return all_active
```

---

## 8. バリデーションルール一覧

| ルール | 対象 | 内容 |
|--------|------|------|
| V-01 | ファイル | `version` フィールドが存在する |
| V-02 | ファイル | `effective_period.from` / `to` が ISO 8601 形式 |
| V-03 | エントリ | 必須フィールド（§2.2）が全て存在する |
| V-04 | エントリ | `change_type` が定義済みの値である |
| V-05 | エントリ | `effective_from` が ISO 8601 形式 |
| V-06 | 全体 | `人的資本` カテゴリのエントリが 1件以上ある（Phase 1 必須） |
| V-07 | エントリ | `id` が同一ファイル内で重複しない |
| V-08 | エントリ | `target_sections` がリスト型である |

---

## 9. 変更履歴

| 日付 | 変更内容 | 担当 |
|------|----------|------|
| 2026-02-27 | 初版作成 | ashigaru2（cmd_081） |
