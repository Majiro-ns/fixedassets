# laws/ — 法令マスタ YAML ディレクトリ

`m2_law_agent.py` が自動読み込みする法令チェック項目ファイルを配置するディレクトリ。

起動時に `laws/*.yaml` を全件読み込む（`LAW_YAML_DIR` 環境変数で変更可能）。

---

## ファイル一覧

| ファイル名 | カテゴリ | 対象期間 | 件数 | ID プレフィックス |
|-----------|---------|---------|------|-----------------|
| `human_capital_2024.yaml` | 人的資本・多様性 / SSBJ 2024 | 2024年度 | 8件 | `hc-2024-xxx`（4件）、`sb-2024-xxx`（4件） |
| `ssbj_2025.yaml` | SSBJ（サステナビリティ開示基準）| 2025年度 | 25件 | `sb-2025-001〜025` |
| `shareholder_notice_2025.yaml` | 総会前開示・ガバナンス（招集通知） | 2025年度 | 16件 | `gm-2025-xxx`（12件）、`gc-2025-xxx`（4件） |
| **合計** | — | — | **49件** | — |

---

## ID 命名規則

```
{カテゴリ}-{年度}-{連番3桁}
例: hc-2024-001 / sb-2025-010 / gm-2025-005
```

| プレフィックス | カテゴリ |
|-------------|---------|
| `hc-` | 人的資本（Human Capital） |
| `sb-` | SSBJ（Sustainability Disclosure Standards Board Japan） |
| `gm-` | 総会前開示（General Meeting disclosure） |
| `gc-` | ガバナンス（Governance Compliance） |

---

## YAML スキーマ

```yaml
version: "1.0"
effective_period:
  from: "YYYY-MM-DD"
  to: "YYYY-MM-DD"

amendments:
  - id: "xx-YYYY-001"
    title: "チェック項目タイトル"
    category: "カテゴリ名"
    required_items:
      - "確認項目1"
      - "確認項目2"
    reference:
      law: "根拠法令名"
      article: "条項"
```

スキーマの詳細仕様は [`docs/law_yaml_schema.md`](../docs/law_yaml_schema.md) を参照。

---

## 新規 YAML の追加手順

1. 上記命名規則に従ってファイルを作成する（例: `laws/climate_2026.yaml`）
2. `laws/` ディレクトリに配置する
3. アプリを再起動すると自動読み込みされる（設定変更不要）
4. `python3 -m pytest scripts/test_m2_law_agent.py` で読み込み確認

> **注意**: `amendments` または `entries` キーのどちらでも読み込み可能（旧形式との互換）。
> フィールド名は `required_items` または `disclosure_items` のいずれかを使用。
