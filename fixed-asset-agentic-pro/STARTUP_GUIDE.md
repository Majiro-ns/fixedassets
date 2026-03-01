# fixed-asset-agentic-pro 起動手順書

## 前提条件
- Node.js 18+ / Python 3.11+
- npm / pip インストール済み

## ステップ1: バックエンド起動（FastAPI）

```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/fixed-asset-ashigaru/
cp .env.example .env   # 初回のみ
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000 --host 0.0.0.0
```

アクセスURL: http://localhost:8000

ヘルスチェック:
```bash
curl http://localhost:8000/health
# → {"ok": true}
```

## ステップ2: フロントエンド起動（Next.js）

```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/fixed-asset-agentic-pro/web/
npm install   # 初回のみ
npm run dev
```

アクセスURL: http://localhost:3000

## ステップ3: Streamlit UI（代替・オプション）

```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/fixed-asset-ashigaru/
pip install -r requirements-ui.txt   # 初回のみ
streamlit run ui/app_minimal.py
```

アクセスURL: http://localhost:8501

## 環境変数（ローカル最小構成）

`.env` に以下を設定（.env.example からコピー）:

| 変数 | 値 | 説明 |
|------|------|------|
| GEMINI_ENABLED | 0 | Gemini APIキー不要 |
| VERTEX_SEARCH_ENABLED | 0 | Discovery Engine不要 |
| CORS_ORIGINS | http://localhost:3000,http://localhost:8501 | CORS許可オリジン |
| FIXED_ASSET_API_KEY | （空） | ローカルは不要 |

## デモデータ

| パス | 内容 |
|------|------|
| `fixed-asset-ashigaru/data/demo/` | JSON分類デモ（demo01〜） |
| `fixed-asset-ashigaru/data/demo_pdf/` | PDF分類デモ |

Streamlit UIではドロップダウンからデモデータを選択可能。

## 実装済み機能（Phase 6完了・247テストPASS）

| 機能 | エンドポイント/場所 | Feature Flag |
|------|---|---|
| JSON分類 | POST /classify | — |
| PDF分類 | POST /classify_pdf | PDF_CLASSIFY_ENABLED=1 |
| CSVインポート教師データ（F-T01） | フロント内 | — |
| PDFインポート教師データ（F-T02） | POST /import_pdf_training | IMPORT_PDF_TRAINING_ENABLED=1 |
| Few-shotプロンプト反映（F-T03） | フロント→API | — |
| 類似事例参照表示（F-T04） | フロント内 | — |
| 継続学習CRUD UI（F-T05） | フロント内 | — |

## 動作確認コマンド

```bash
# JSON分類テスト
curl -X POST http://localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '{
    "opal_json": {
      "invoice_date": "2024-01-01",
      "vendor": "Test Corp",
      "line_items": [
        {"item_description": "server installation", "amount": 5000, "quantity": 1}
      ]
    },
    "policy_path": "policies/company_default.json",
    "answers": {}
  }'
```

## テスト実行

```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/fixed-asset-agentic-pro/web/
npm run lint          # ESLint
npm run build         # ビルド確認
```

```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/fixed-asset-ashigaru/
pytest                # 247テスト
```

---
最終更新: 2026-03-01
