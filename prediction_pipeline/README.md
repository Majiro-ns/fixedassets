# 競輪・競艇予想パイプライン

競輪・競艇の出走情報を取得し、Claude Haiku API で予想を生成する自動パイプライン。

## セットアップ

```bash
# 依存パッケージのインストール
pip install -r requirements.txt

# APIキーを環境変数に設定（必須）
export ANTHROPIC_API_KEY="your_api_key_here"
```

## 使い方

### 基本実行（競輪・本日）

```bash
python scripts/daily_run.py
```

### オプション指定

```bash
# 競艇・日付指定
python scripts/daily_run.py --sport kyotei --date 20260222

# APIを呼ばないDRYランテスト
python scripts/daily_run.py --dry-run

# 予想師プロファイル指定
python scripts/daily_run.py --profile mr_t
```

### テスト実行

```bash
# 全テスト（APIキー不要のテストのみ）
pytest tests/

# 実接続テスト（KEIRIN.JPへのHTTPリクエストを実行）
KEIRIN_REAL_ACCESS=1 pytest tests/test_keirin_scraper.py

# Haiku/Sonnet予想生成テスト（APIキー必須）
pytest tests/test_predictor.py
```

## ディレクトリ構成

```
prediction_pipeline/
├── config/
│   ├── settings.yaml          # 全体設定（モデル名、賭け設定等）
│   ├── keirin/
│   │   ├── venues.yaml        # 競輪場マスター（43場）
│   │   ├── filters.yaml       # S1×準決勝フィルター
│   │   └── profiles/
│   │       └── mr_t.yaml      # Mr.T予想師プロファイル
│   └── kyotei/
│       ├── venues.yaml        # 競艇場マスター（24場）
│       └── filters.yaml       # 競艇フィルター
├── src/
│   ├── base_scraper.py        # スクレイパー抽象基底クラス
│   ├── keirin_scraper.py      # KEIRIN.JPスクレイパー
│   ├── kyotei_scraper.py      # boatrace.jpスクレイパー
│   ├── profile_loader.py      # 予想師プロファイルローダー
│   ├── predictor.py           # Haiku/Sonnet API予想生成
│   ├── filter_engine.py       # レースフィルター
│   ├── formatter.py           # JSON/テキスト出力フォーマッター
│   └── bet_calculator.py      # 賭け式・投資額計算
├── scripts/
│   ├── daily_run.py           # 日次実行メインスクリプト
│   ├── fetch_results.py       # 結果取得CLI
│   └── weekly_report.py       # 週次レポート生成
├── data/
│   ├── predictions/           # 予想JSON出力先
│   ├── results/               # レース結果
│   └── reports/               # 週次レポート
└── tests/
    ├── test_keirin_scraper.py
    ├── test_predictor.py
    └── test_filter_engine.py
```

## モデル切り替え

`config/settings.yaml` の `llm.model` を変更するだけで Haiku ↔ Sonnet を切り替えられる。

```yaml
llm:
  model: claude-haiku-4-5-20251001   # ← ここを変更
  fallback_model: claude-sonnet-4-6
```

## 注意事項

- **DoS対策**: リクエスト間隔3秒以上、1セッション20件まで（settings.yaml で設定）
- **APIキー**: 環境変数 `ANTHROPIC_API_KEY` から読む。ハードコード禁止
- **フィルター**: デフォルトは S1×準決勝・決勝のみ（競輪）
- **予算管理**: デフォルト1日上限12,600円（6レース × 2,100円）

## 設計

- 競輪・競艇の冗長性ある設計（`--sport` オプションで切り替え）
- 全モジュールに docstring 記載
- エラー時はログに記録して次のレースに進む
