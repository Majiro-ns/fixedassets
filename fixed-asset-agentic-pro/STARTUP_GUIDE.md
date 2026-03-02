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

## 実装済み機能（Phase 3完了・267テスト[backend] + 578テスト[frontend] PASS）

| 機能 | エンドポイント/場所 | Feature Flag |
|------|---|---|
| JSON分類 | POST /classify | — |
| PDF分類（v1） | POST /classify_pdf | PDF_CLASSIFY_ENABLED=1 |
| PDF分類（v2マルチエージェント） | POST /api/v2/classify_pdf | — |
| リース分類 | POST /classify_lease | — |
| 減価償却計算 | POST /calculate_depreciation | — |
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

## デモシナリオ（殿向け・APIキー不要）

### 前提条件
- Python 3.11+ / Node.js 18+
- APIキー不要（GEMINI_ENABLED=0、VERTEX_SEARCH_ENABLED=0 がデフォルト）

### 起動手順（2コマンド）

**ターミナル1: バックエンド**
```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/fixed-asset-ashigaru/
cp .env.example .env && uvicorn api.main:app --reload --port 8000
```

**ターミナル2: フロントエンド**
```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/fixed-asset-agentic-pro/web/
npm run dev
```

→ http://localhost:3000 にアクセス

### デモシナリオ（所要時間: 約5分）

1. **PDFアップロード**
   - `fixed-asset-ashigaru/data/demo_pdf/demo_capital.pdf` をドラッグ&ドロップ
   - 期待: 「ノートPC」等の明細が自動抽出される

2. **分類結果確認**
   - 各明細に「資本的支出 / 費用」「税務判定 / 会計実務判定」が表示
   - 勘定科目・耐用年数が自動付与されていることを確認

3. **明細の手動修正**
   - 任意の明細のドロップダウンを変更（例: 費用→資本的支出）
   - 「承認」ボタンでユーザー判断を記録

4. **サマリ確認**
   - 資本的支出合計・費用合計・ガイダンス件数が表示される

5. **教師データとして保存（再学習）**
   - 修正したデータを「学習データとして保存」
   - 次回以降の分類精度向上に反映される

### 期待される画面遷移
```
トップページ → PDFアップロード → 抽出結果プレビュー
→ Tax/Practice 2エージェント合議結果 → 手動修正 → サマリ → 保存完了
```

## テスト実行

```bash
# フロントエンドテスト（578件）
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/fixed-asset-agentic-pro/web/
npm run test          # 578テスト PASS

# その他
npm run lint          # ESLint
npm run build         # ビルド確認
```

```bash
# バックエンドテスト（267件）
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/fixed-asset-ashigaru/
pytest                # 267テスト
```

---
最終更新: 2026-03-03（テスト件数更新: frontend 578件 / backend 267件）
