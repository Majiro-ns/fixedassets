# fixed-asset-agentic-pro

見積書の固定資産判定AIシステム — フロントエンド（Next.js）リポジトリ

---

## アーキテクチャ

```
fixed-asset-agentic-pro/   ← このリポジトリ（Next.js フロントエンド）
│  web/                    ← Next.js アプリ (port 3000)
│
fixed-asset-ashigaru/      ← 兄弟ディレクトリ（Python FastAPI バックエンド）
   api/                    ← FastAPI アプリ (port 8000)
   ui/                     ← Streamlit UI (port 8501, オプション)
```

```
ブラウザ (port 3000)
    │
    │ HTTP/REST
    ▼
Next.js フロントエンド
(fixed-asset-agentic-pro/web/)
    │
    │ HTTP API
    ▼
FastAPI バックエンド (port 8000)
(fixed-asset-ashigaru/)
    │
    │ Gemini API（GEMINI_ENABLED=1 の場合）
    ▼
Google Gemini / Vertex AI
```

---

## 動作モード

| モード | 設定 | 説明 |
|--------|------|------|
| **Phase 1（単体）** | `USE_MULTI_AGENT=false` | 単一 Gemini エージェントで判定。APIキー不要で動作確認可能 |
| **Phase 2+（マルチエージェント）** | `USE_MULTI_AGENT=true` | Tax エージェント + Practice エージェントが合議して判定 |

---

## 同時起動手順（ローカル開発）

### 前提条件
- Node.js 18+
- Python 3.11+
- npm / pip インストール済み

### ステップ 1: バックエンド起動（FastAPI）

```bash
cd ../fixed-asset-ashigaru

# 初回のみ: 環境変数ファイルをコピー
cp .env.example .env

# 依存関係インストール（初回のみ）
pip install -r requirements.txt

# サーバー起動
uvicorn api.main:app --reload --port 8000 --host 0.0.0.0
```

ヘルスチェック:

```bash
curl http://localhost:8000/health
# → {"ok": true}
```

### ステップ 2: フロントエンド起動（Next.js）

別ターミナルで実行:

```bash
cd web

# 初回のみ: 依存関係インストール
cp .env.example .env.local   # 環境変数ファイルをコピー
npm install

# 開発サーバー起動
npm run dev
```

ブラウザで http://localhost:3000 にアクセス

### ステップ 3: Streamlit UI（オプション）

```bash
cd ../fixed-asset-ashigaru

# 初回のみ
pip install -r requirements-ui.txt

streamlit run ui/app_minimal.py
# → http://localhost:8501
```

### Windows ワンクリック起動

```
1_start_backend.bat   ← バックエンド（FastAPI）
2_start_frontend.bat  ← フロントエンド（Next.js）
3_start_streamlit.bat ← Streamlit UI（オプション）
```

---

## 環境変数一覧

### フロントエンド（`web/.env.local`）

`web/.env.example` をコピーして設定:

```bash
cp web/.env.example web/.env.local
```

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | FastAPI バックエンドの URL |
| `NEXT_PUBLIC_USE_MULTI_AGENT` | `false` | Phase 2 マルチエージェント有効化（クライアント側） |
| `NEXT_PUBLIC_PDF_TRAINING_ENABLED` | `1` | PDF教師データ取込機能 |
| `USE_MULTI_AGENT` | `false` | Phase 2 マルチエージェント有効化（サーバー側 route.ts） |
| `PARALLEL_AGENTS` | `true` | エージェント並列実行 |
| `AUDIT_TRAIL_ENABLED` | `true` | 判定履歴の記録 |

### バックエンド（`../fixed-asset-ashigaru/.env`）

`../fixed-asset-ashigaru/.env.example` をコピーして設定:

```bash
cp ../fixed-asset-ashigaru/.env.example ../fixed-asset-ashigaru/.env
```

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `GEMINI_ENABLED` | `0` | Gemini API 有効化（0=無効でもルールベース判定動作） |
| `GEMINI_API_KEY` | （空） | Google AI Studio の API キー |
| `GOOGLE_CLOUD_PROJECT` | （空） | Vertex AI 経由の場合のプロジェクト ID |
| `VERTEX_SEARCH_ENABLED` | `0` | Vertex AI Search（法令引用）有効化 |
| `CORS_ORIGINS` | `http://localhost:3000,...` | CORS 許可オリジン（カンマ区切り） |
| `FIXED_ASSET_API_KEY` | （空） | API 認証キー（ローカルは空で可） |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | フロントエンドへ返す API URL |

> **ローカル最小構成**: `GEMINI_ENABLED=0` / `VERTEX_SEARCH_ENABLED=0` のままで動作確認可能（API キー不要）

---

## テスト

```bash
# フロントエンドテスト（480件）
cd web
npm run test

# フロントエンドリント
npm run lint

# フロントエンドビルド確認
npm run build
```

```bash
# バックエンドテスト
cd ../fixed-asset-ashigaru
pytest
```

---

## 詳細ドキュメント

| ファイル | 内容 |
|----------|------|
| `STARTUP_GUIDE.md` | 詳細起動手順・デモシナリオ・動作確認コマンド |
| `../fixed-asset-ashigaru/README.md` | バックエンド詳細・API 仕様・デプロイ手順 |
| `../fixed-asset-ashigaru/DEMO_JP.md` | デモ手順書（日本語） |

---

## プロジェクト構成

```
fixed-asset-agentic-pro/
├── README.md              ← このファイル
├── STARTUP_GUIDE.md       ← 詳細起動手順・デモシナリオ
├── web/                   ← Next.js フロントエンド
│   ├── src/               ← ソースコード
│   ├── .env.example       ← 環境変数テンプレート
│   └── package.json
├── 1_start_backend.bat    ← Windows: バックエンド起動
├── 2_start_frontend.bat   ← Windows: フロントエンド起動
└── 3_start_streamlit.bat  ← Windows: Streamlit UI 起動
```
