# disclosure-multiagent デモ手順書

> 作成日: 2026-03-02 (cmd_136k_sub1)
> 動作確認済み環境: Python 3.12 / Node.js 20 / WSL2 Ubuntu

---

## 前提条件

| 項目 | バージョン | 確認コマンド |
|------|-----------|------------|
| Python | 3.10以上 | `python3 --version` |
| Node.js | 20以上 | `node --version` |
| pip依存 | requirements_poc.txt | `pip install -r requirements_poc.txt` |
| npm依存 | web/package.json | `cd web && npm install` |

### APIキーについて
- **モックモードあり**（APIキー不要で動作確認可能）
- 本番LLM使用時のみ `ANTHROPIC_API_KEY` が必要

---

## 方法1: Docker で起動（推奨）

Dockerが使える環境では最も簡単。

```bash
# 1. プロジェクトルートへ移動
cd /path/to/disclosure-multiagent

# 2. 環境変数ファイル作成（モックモードはAPIキー不要）
cp .env.example .env

# 3. ビルド＆起動
docker compose up --build

# バックグラウンドで起動する場合
docker compose up -d --build
```

### アクセスURL（Docker）
| サービス | URL |
|---------|-----|
| Web UI | http://localhost:3010 |
| FastAPI | http://localhost:8010 |
| API ドキュメント | http://localhost:8010/docs |

### 停止（Docker）
```bash
docker compose down
```

---

## 方法2: ローカル直接起動（Dockerなし）

### ステップ1: 依存関係インストール

```bash
cd /path/to/disclosure-multiagent

# Python依存
pip install -r requirements_poc.txt

# Node依存
cd web && npm install && cd ..
```

### ステップ2: バックエンド起動

```bash
cd /path/to/disclosure-multiagent

# バックエンドをポート8000で起動（バックグラウンド）
PYTHONPATH=scripts:. uvicorn api.main:app --reload --port 8000 &

# 起動確認
curl http://localhost:8000/api/health
# → {"status":"ok","service":"disclosure-multiagent"}
```

### ステップ3: フロントエンド起動

```bash
cd /path/to/disclosure-multiagent/web

# 開発サーバー起動（ポート3000）
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

### アクセスURL（ローカル）
| サービス | URL |
|---------|-----|
| Web UI | http://localhost:3000 |
| FastAPI | http://localhost:8000 |
| API ドキュメント | http://localhost:8000/docs |

### 停止（ローカル）
```bash
# バックエンド停止
pkill -f "uvicorn api.main:app"

# フロントエンド停止
# Ctrl+C でサーバーを終了
```

---

## 主要機能の操作手順

### 機能1: 有報ギャップ分析（モックモード）

**APIで直接確認する場合:**
```bash
# 分析開始（モックモード: APIキー不要）
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"company_name":"デモ株式会社","use_mock":true}'

# → task_id が返される
# 例: {"task_id":"76f08fd3","status":"queued","message":"パイプライン起動受付完了"}

# 処理状況確認（task_idを置き換えて実行）
curl http://localhost:8000/api/status/76f08fd3

# → M1〜M5ステップの進捗がJSONで返される
# 完了時: {"status":"done","steps":[{"step":1,"status":"done"},...]}
```

**Web UIで操作する場合:**
1. ブラウザで http://localhost:3000 を開く
2. 会社名または証券コードを入力
3. 「分析開始」ボタンをクリック
4. M1〜M5の処理状況がリアルタイムで表示される
5. 完了後、ギャップ分析レポートが表示される

### 機能2: EDINET連携（有報PDF自動取得）

```bash
# EDINET書類検索（会社コード指定）
curl "http://localhost:8000/api/edinet/search?sec_code=7203"

# 特定書類のPDFを取得して分析
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"pdf_doc_id":"S100XXXX","company_name":"トヨタ自動車"}'
```

### 機能3: リアルタイム進捗ストリーム（SSE）

```bash
# SSEでパイプライン進捗をリアルタイム確認
curl -N http://localhost:8000/api/status/{task_id}/stream
```

### 機能4: パイプラインモジュール（M1〜M5）

| モジュール | 処理内容 |
|-----------|---------|
| M1: PDF解析 | 有報PDFからセクション抽出（PyMuPDF/pdfplumber） |
| M2: 法令取得 | 法令マスタYAML読み込み・参照期間算出 |
| M3: ギャップ分析 | 開示義務との差分検出（追加必須/修正推奨/参考） |
| M4: 提案生成 | 松竹梅3水準の改善提案文生成 |
| M5: レポート統合 | Markdownレポート生成 |

---

## API エンドポイント一覧

| メソッド | パス | 説明 |
|---------|-----|------|
| GET | `/api/health` | ヘルスチェック |
| POST | `/api/analyze` | 分析パイプライン開始 |
| GET | `/api/status/{task_id}` | 処理状況取得（ポーリング） |
| GET | `/api/status/{task_id}/stream` | 処理状況取得（SSE） |
| GET | `/api/edinet/search` | EDINET企業検索 |
| GET | `/docs` | Swagger UI |

---

## トラブルシューティング

### バックエンドが起動しない
```bash
# 依存関係を再確認
pip install -r requirements_poc.txt
pip install -r api/requirements.txt

# ポートが使用中の場合
lsof -i :8000
kill -9 <PID>
```

### フロントエンドがAPIに接続できない
```bash
# NEXT_PUBLIC_API_URL を明示的に設定
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

### テスト実行
```bash
cd /path/to/disclosure-multiagent
python3 -m pytest scripts/ -q
# → 272件以上 PASS
```

---

## 動作確認ログ（2026-03-02）

```
$ curl http://localhost:8010/api/health
{"status":"ok","service":"disclosure-multiagent"}

$ curl -X POST http://localhost:8010/api/analyze \
    -H "Content-Type: application/json" \
    -d '{"company_name":"デモ株式会社","use_mock":true}'
{"task_id":"76f08fd3","status":"queued","message":"パイプライン起動受付完了"}

$ curl http://localhost:8010/api/status/76f08fd3
{
  "task_id": "76f08fd3",
  "status": "done",
  "steps": [
    {"step": 1, "name": "M1: PDF解析", "status": "done"},
    {"step": 2, "name": "M2: 法令取得", "status": "done"},
    {"step": 3, "name": "M3: ギャップ分析", "status": "done"},
    {"step": 4, "name": "M4: 提案生成", "status": "done"},
    {"step": 5, "name": "M5: レポート統合", "status": "done"}
  ]
}
```
