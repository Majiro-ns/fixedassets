# nencho

年末調整を支援する AI エージェント向けスキルパッケージ。給与所得の年間税額計算から源泉徴収票（Excel/PDF）・CSV 出力までを、エージェントとの対話で進められます。

**SKILL.md オープン標準**に準拠した Agent Skills として提供しているため、Cursor / Claude Code / Windsurf / GitHub Copilot など、スキルに対応した AI コーディングエージェントで利用できます。

## 想定ユーザー

| 対象 | 対応レベル | 備考 |
|------|------------|------|
| 給与所得のみ（会社員） | Full | 年末調整・源泉徴収票作成 |
| 扶養控除・配偶者控除 | Full | 扶養親族の登録・控除計算 |
| 社会保険料控除 | Full | 年間支払額を入力 |
| 生命保険料控除・地震保険料控除 | Full | 一般・個人年金・介護医療・地震 |
| 住宅ローン控除（年末調整で還付） | Full | 初年度以降の控除額計算 |
| 所得金額調整控除 | Full | 一定条件で適用 |
| 中途入退社 | Full | 年末調整要否の判定あり |

## 非対応

| 項目 | 理由・備考 |
|------|------------|
| 退職所得 | 退職所得控除・分離課税は別計算 |
| 株式・FX・不動産所得等 | 年末調整の対象外（確定申告で対応） |
| e-Tax への自動入力 | 計算・書類出力まで。e-Tax 画面操作はユーザーまたは別ツール |

---

## 免責事項

- 本ツールが生成した計算結果・源泉徴収票は、提出前に**必ずご自身で内容を確認**してください。
- 税法の解釈や申告内容に不安がある場合は、**税理士等の専門家に相談**することを推奨します。
- 本ツールの利用によって生じた**いかなる損害についても、開発者は責任を負いません**。
- 税制は毎年改正されます。本ツールは令和7年分（2025年課税年度）等の税制に基づいています。

---

## インストール

### 前提条件

- Python 3.10 以上
- （オプション）Node.js — スキル CLI でインストールする場合

### 方法 1: スキルとしてインストール（推奨）

このリポジトリをスキルパッケージとして追加すると、エージェントが「年末調整」「nencho」などの文脈でスキルを自動的に参照します。

```bash
# スキルのインストール（インストール先エージェントを対話的に選択）
npx skills add Majiro-ns/nencho
```

リポジトリのルートに `skills/` ディレクトリがあることを前提としています。clone 後、作業ディレクトリで上記を実行してください。

### 方法 2: プロジェクト内でそのまま利用

リポジトリを clone し、API または CLI を直接利用します。

```bash
git clone https://github.com/Majiro-ns/nencho.git
cd nencho
pip install -r requirements.txt
```

---

## 使い方

### 作業ディレクトリの準備

年末調整用のデータ（DB・出力ファイル）を置くディレクトリを決め、そのディレクトリで API または CLI を起動します。個人情報が含まれるため、git で管理する場合は `nencho.db` 等を `.gitignore` に追加してください。

### セットアップ

作業ディレクトリでエージェントに「年末調整のセットアップをして」と依頼するか、手動で以下を実行します。

```bash
pip install -r requirements.txt
PYTHONPATH=. uvicorn api.main:app --reload --port 8000
```

健康チェック: `GET http://localhost:8000/api/health`

### メインワークフロー

| スキル | 説明 |
|--------|------|
| **/setup** | 初回セットアップ。作業ディレクトリ・DB・API/CLI 起動方法の案内 |
| **/calculate** | 年末調整の税額計算（単一・一括）。給与所得・控除から所得税・復興特別所得税を算出 |
| **/validate** | 提出前バリデーション。個人・一括の不備チェック |
| **/export** | 源泉徴収票（Excel/PDF）・CSV の出力 |

### 補助スキル

| スキル | 説明 |
|--------|------|
| **/employees** | 従業員の登録・一覧・扶養の管理・CSV/Excel 一括取込 |
| **/capabilities** | 対応範囲・想定ユーザー・既知の制限事項の表示 |

---

## API 概要

| 用途 | メソッド・パス |
|------|----------------|
| 健康チェック | `GET /api/health` |
| 単一計算 | `POST /api/calculate` |
| 従業員一覧 | `POST /api/employees/list` |
| 個人計算 | `POST /api/employees/{id}/calculate` |
| 一括計算 | `POST /api/employees/batch-calculate` |
| 提出前バリデーション（個人） | `POST /api/validation/year-end/{emp_id}` |
| 提出前バリデーション（一括） | `POST /api/validation/year-end/batch` |
| 源泉徴収票 PDF | `POST /api/export/pdf` |
| 源泉徴収票 Excel | `POST /api/export/excel` |
| 年末集計・CSV | `POST /api/reports/year-end/summary` 等 |
| 扶養 CRUD | `GET/POST/DELETE /api/dependents/{emp_id}` |
| セッション | `POST /api/session/create` 等 |

リクエスト body の形式は各ルーターの Pydantic モデルを参照してください。

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/ZENN_PUBLISH_GUIDE.md](docs/ZENN_PUBLISH_GUIDE.md) | **Git と Zenn で公開する手順・記事案** |
| [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) | リリース・公開前のチェックリスト |
| [docs/OSS_READINESS_REVIEW.md](docs/OSS_READINESS_REVIEW.md) | OSS 公開可否のレビュー結果 |
| [docs/OPEN_ISSUES_AND_GAPS.md](docs/OPEN_ISSUES_AND_GAPS.md) | **不足点・課題一覧**（優先度付き） |
| [docs/PRACTICAL_GAPS_AND_QUESTIONS.md](docs/PRACTICAL_GAPS_AND_QUESTIONS.md) | 実務上の不足点・疑問点（詳細） |

## プロジェクト構成

```
nencho/
├── api/                 # FastAPI（main.py + routers）
├── src/                 # コアロジック
│   ├── cli/             # nencho_cli（calculate, employee, backup, import, output）
│   ├── core/calculation/ # 控除・税額計算（allowances, deductions, housing, insurance 等）
│   ├── input/           # 従業員入力フォーム
│   ├── output/          # 源泉徴収票（PDF/Excel）
│   ├── pipeline/        # 年末調整パイプライン（year_end_adjustment, batch_pipeline）
│   └── references/     # 法令参照
├── docs/                # ドキュメント（RELEASE_CHECKLIST, OSS_READINESS_REVIEW 等）
├── skills/              # Agent Skills（SKILL.md オープン標準）
│   ├── setup/
│   ├── calculate/
│   ├── validate/
│   ├── export/
│   ├── employees/
│   └── capabilities/
├── tests/
├── web/                 # Next.js フロント（オプション）
├── requirements.txt
└── README.md
```

---

## 技術スタック

- Python 3.10+
- FastAPI, Pydantic
- SQLite（従業員データ・セッション等）
- openpyxl（Excel）, cryptography（セッション暗号化）

## ライセンス

MIT License（リポジトリの LICENSE ファイルを参照）。

## 参考

- [shinkoku](https://github.com/kazukinagata/shinkoku) — 確定申告自動化 AI エージェントプラグイン（同様の設計思想でスキル化）
- [SKILL.md オープン標準](https://github.com/skill-markdown/skill-markdown) — Agent Skills の共通フォーマット
