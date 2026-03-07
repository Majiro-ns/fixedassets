# Git と Zenn で公開する手順・記事案

nencho を GitHub に push し、Zenn で記事を公開するまでの手順と、Zenn 用の記事本文案です。

---

# 第一部：手順

## 1. Git でリポジトリを用意する

### パターン A: nencho を単体リポジトリとして公開する場合（推奨）

スキルは「リポジトリのルートに `skills/` がある」前提のため、nencho 単体で 1 リポにすると `npx skills add Majiro-ns/nencho` がそのまま使えます。

1. **GitHub で新規リポジトリを作成**
   - https://github.com/new
   - リポジトリ名: `nencho`（任意）
   - Public、README は追加しなくてよい（既に nencho 側にある）

2. **ローカルで nencho だけを新リポのルートにする**
   ```powershell
   # 例: 親リポの外に nencho 用の作業用フォルダを作る
   cd C:\Users\owner\Desktop\llama3_wallthinker
   xcopy /E /I nencho nencho-standalone
   cd nencho-standalone
   ```
   または、既に `nencho` フォルダで作業している場合は、その中で以下を実行。

3. **git 初期化（まだの場合）とリモート追加**
   ```powershell
   cd c:\Users\owner\Desktop\llama3_wallthinker\nencho
   git init
   git remote add origin https://github.com/Majiro-ns/nencho.git
   ```

4. **コミットして push**
   ```powershell
   git add .
   git status   # .gitignore で除外されているか確認
   git commit -m "chore: initial release as OSS (nencho)"
   git branch -M main
   git push -u origin main
   ```

5. **README の URL を実際のリポに合わせる**
   - README の「clone」「npx skills add」の説明で、リポジトリ所有者を `Majiro-ns` に設定済み。

### パターン B: 親リポ（llama3_wallthinker）のまま push する場合

- 親リポのルートで `git add nencho/` してコミット・push 即可。
- スキルとして使う場合は「リポ全体の URL + サブパス」がスキル CLI でどう扱われるか要確認。単体リポ（パターン A）の方がスキル利用は簡単です。

---

## 2. Zenn で公開する手順

### 2.1 Zenn と GitHub を連携する

1. https://zenn.dev にログイン（GitHub アカウントでサインアップ可）
2. **設定** → **連携** → **GitHub リポジトリを連携**
3. 記事用のリポジトリを選択（例: `yourname/nencho` または 別の `yourname/zenn` など）
   - 「Zenn の記事を GitHub のリポで管理する」場合は、通常は **zenn 用リポ** を 1 つ作り、その中に `articles/` を置く運用が多いです。
   - **今回のように「nencho リポの中に記事を置く」** ことも可能: nencho リポを連携し、そのリポ内に `articles/` を作成する（後述）。

### 2.2 記事の管理方法（2 通り）

**方法 1: Zenn の「GitHub と連携した記事」として書く**

- 連携したリポに `articles/` フォルダを作り、その中に `slug.md` のようなマークダウンを push すると Zenn に反映されます。
- 例: `nencho` リポを連携している場合  
  `nencho/articles/nencho-oss-release.md` を作成し、Zenn のフォーマット（frontmatter 付き）で書く。

**方法 2: Zenn の「クラウドで直接執筆」**

- Zenn のダッシュボードで「新規記事」を作成し、本文は Zenn 上だけで編集。Git には載せない。
- 手軽だが、原稿のバージョン管理は Zenn 上のみ。

以下は **方法 1** を前提に、リポ内に記事用ファイルを置く場合の流れです。

### 2.3 記事ファイルをリポに追加して公開する

1. **連携リポのルートに `articles` ディレクトリを作成**（Zenn の仕様に従う）
   ```text
   nencho/
   ├── articles/           # Zenn 用
   │   └── nencho-oss-release.md
   ├── api/
   ├── skills/
   └── ...
   ```

2. **記事のマークダウンファイルを作成**
   - ファイル名: スラッグになる（例: `nencho-oss-release.md` → URL は `zenn.dev/.../articles/nencho-oss-release`）
   - 先頭に YAML frontmatter が必要:
   ```yaml
   ---
   title: "年末調整をエージェントと一緒にやる Agent Skill「nencho」を OSS にした"
   emoji: "🧾"
   type: "tech"
   topics: ["python", "oss", "AI", "年末調整", "Agent"]
   published: true
   ---
   ```

3. **本文を書く（下記「第二部：記事案」をコピーして編集）**

4. **push する**
   ```powershell
   git add articles/nencho-oss-release.md
   git commit -m "docs: add Zenn article for nencho OSS release"
   git push
   ```

5. **Zenn で確認**
   - 連携設定により、push 後に Zenn の「記事」一覧に表示され、公開設定にしていれば公開されます。下書きにしたい場合は frontmatter で `published: false` にします。

### 2.4 Zenn で「記事を GitHub と連携」していない場合

- Zenn の「新規記事」でクラウド執筆を選び、**第二部の記事案**をコピペして Zenn 上で編集・公開しても構いません。その場合は Git には記事ファイルは残りません。

---

# 第二部：Zenn 用記事本文案

以下をそのまま Zenn の記事本文にコピーし、**リポジトリ URL** と **あなたの環境に合わせた部分**だけ差し替えて使ってください。

---

```markdown
---
title: "年末調整をエージェントと一緒にやる Agent Skill「nencho」を OSS にした"
emoji: "🧾"
type: "tech"
topics: ["python", "oss", "AI", "年末調整", "Agent", "Cursor"]
published: true
---

年末調整、毎年忘れがちで面倒ですよね。控除の種類も多く、源泉徴収票の作成まで手間がかかります。確定申告を自動化する [shinkoku](https://github.com/kazukinagata/shinkoku) が OSS で話題になっていますが、**年末調整**も同じようにエージェントに任せたい——そんな思いで、年末調整を支援する Agent Skill「nencho」をスキル化し、OSS として公開しました。

## 作った動機

給与所得者や小規模法人では、年末調整は毎年必ず発生する作業です。一方で、年に1回しかやらないため手順を忘れがちで、控除の入力や税額計算に時間がかかります。確定申告向けの shinkoku が、スキル分離と SKILL.md オープン標準でエージェントと協調する設計になっているのを見て、**年末調整も同じ思想でスキル化すれば、エージェントと対話しながら計算から源泉徴収票出力まで進められる**と考え、nencho を整備しました。

## nencho でできること

書類の準備から計算・源泉徴収票の出力まで、エージェントとの対話で進められます。スラッシュコマンド（スキル）で各ステップを呼び出せます。

### メインワークフロー

| スキル | 説明 |
|--------|------|
| /setup | 初回セットアップ。作業ディレクトリ・DB・API/CLI 起動方法の案内 |
| /calculate | 年末調整の税額計算（単一・一括）。給与所得・控除から所得税・復興特別所得税を算出 |
| /validate | 提出前バリデーション。個人・一括の不備チェック |
| /export | 源泉徴収票（Excel/PDF）・CSV の出力 |

### 補助スキル

| スキル | 説明 |
|--------|------|
| /employees | 従業員の登録・一覧・扶養の管理・CSV/Excel 一括取込 |
| /capabilities | 対応範囲・想定ユーザー・既知の制限事項の表示 |

計算は **API**（`POST /api/calculate` 等）と **CLI**（`python -m src.cli.nencho_cli calculate`）の両方から利用でき、スキルがその手順を案内します。

## 対象ユーザー

| 対象 | 対応レベル | 備考 |
|------|------------|------|
| 給与所得のみ（会社員） | Full | 年末調整・源泉徴収票作成 |
| 扶養控除・配偶者控除 | Full | 扶養親族の登録・控除計算 |
| 社会保険料控除 | Full | 年間支払額を入力 |
| 生命保険料・地震保険料控除 | Full | 一般・個人年金・介護医療・地震 |
| 住宅ローン控除（年末調整で還付） | Full | 初年度以降の控除額計算 |
| 所得金額調整控除 | Full | 一定条件で適用 |
| 中途入退社 | Full | 年末調整要否の判定あり |

## 非対応項目

| 項目 | 理由・備考 |
|------|------------|
| 退職所得 | 退職所得控除・分離課税は別計算 |
| 株式・FX・不動産所得等 | 年末調整の対象外（確定申告で対応） |
| e-Tax への自動入力 | 計算・書類出力まで。e-Tax 画面操作はユーザーまたは別ツール |

分離課税や事業所得は確定申告（shinkoku）の領域です。年末調整は「給与所得の年間税額」に特化しています。

## 対応エージェント

SKILL.md オープン標準に準拠しているため、**Cursor** / **Claude Code** / **Windsurf** / **GitHub Copilot** など、スキルに対応した AI コーディングエージェントで利用できます。

### インストール

スキルとして追加する場合:

```bash
npx skills add Majiro-ns/nencho
```

リポジトリを clone して API/CLI を直接使う場合:

```bash
git clone https://github.com/Majiro-ns/nencho.git
cd nencho
pip install -r requirements.txt
```

### 起動例

```bash
# API（プロジェクトルートで）
PYTHONPATH=. uvicorn api.main:app --reload --port 8000
# 健康チェック: GET http://localhost:8000/api/health

# CLI（対話で1人分を計算）
PYTHONPATH=. python -m src.cli.nencho_cli calculate
```

作業ディレクトリに DB が作成され、個人情報を含むため `.gitignore` に `nencho.db` 等を追加することを推奨します。

## 実務上の注意・免責

- **令和7年分（2025年課税年度）** を正式対応としています。令和8年分は税制次第で対応予定です。
- 本ツールが生成した計算結果・源泉徴収票は、提出前に**必ずご自身で内容を確認**してください。
- 税法の解釈や申告内容に不安がある場合は、**税理士等の専門家に相談**することを推奨します。
- 本ツールの利用によって生じた**いかなる損害についても、開発者は責任を負いません**。

## 今後の予定

- 令和8年分の税制対応
- バリデーション項目の拡充
- サンプルデータ・ドキュメントの整備

## おわりに

自分自身の年末調整や社内の試算に使いながら、エージェントと対話で進められる体験を多くの人に届けたいと思い、OSS にしました。フィードバックやコントリビュートを歓迎しています。興味のある方はぜひリポジトリを覗いてみてください。

- **nencho**: https://github.com/Majiro-ns/nencho
- **shinkoku**（確定申告）: https://github.com/kazukinagata/shinkoku
- **SKILL.md オープン標準**: Agent Skills の共通フォーマット
```

---

# 第三部：公開前の最終確認

- [x] README のリポジトリ URL を実際の `https://github.com/Majiro-ns/nencho` にしている
- [x] 記事内の `https://github.com/Majiro-ns/nencho` を実際の URL に設定済み
- [ ] 免責・「提出前に必ず確認」の記述が記事に含まれている
- [ ] Zenn の frontmatter の `published` を、公開するなら `true`、下書きなら `false` にしている

以上で、Git でリポジトリを用意し、Zenn で記事を公開する手順と、そのまま使える記事案が揃います。必要に応じて「作った動機」や「今後の予定」を自分の言葉に差し替えてください。
