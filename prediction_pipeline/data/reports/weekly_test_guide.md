# 1週間運用テスト手順書

**作成日**: 2026-02-22
**担当**: ashigaru4 (subtask_019c)
**目的**: Haiku APIで競輪予想パイプラインの1週間自動運用テストを実施する

---

## テスト期間

**2026-02-24（月）〜 2026-03-02（日）** (7日間)

---

## 前提条件

```bash
# 作業ディレクトリ
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline

# APIキー確認（必須）
echo $ANTHROPIC_API_KEY | head -c 10
# 未設定の場合:
export ANTHROPIC_API_KEY="your_key_here"
```

---

## 毎朝の手順（実行コマンド）

### 予想生成（Haiku API）

```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline

# 当日予想生成（例: 2026-02-24）
python3 scripts/daily_run.py --sport keirin --date 2026-02-24

# APIキー未設定の場合はdry-runで動作確認
python3 scripts/daily_run.py --sport keirin --date 2026-02-24 --dry-run
```

**出力先**: `data/predictions/prediction_keirin_YYYYMMDD.json`

### 日付別コマンド一覧

| 日付 | コマンド |
|------|---------|
| 月 2/24 | `python3 scripts/daily_run.py --sport keirin --date 2026-02-24` |
| 火 2/25 | `python3 scripts/daily_run.py --sport keirin --date 2026-02-25` |
| 水 2/26 | `python3 scripts/daily_run.py --sport keirin --date 2026-02-26` |
| 木 2/27 | `python3 scripts/daily_run.py --sport keirin --date 2026-02-27` |
| 金 2/28 | `python3 scripts/daily_run.py --sport keirin --date 2026-02-28` |
| 土 3/01 | `python3 scripts/daily_run.py --sport keirin --date 2026-03-01` |
| 日 3/02 | `python3 scripts/daily_run.py --sport keirin --date 2026-03-02` |

---

## 翌日の結果取得

```bash
# 前日の結果を取得（例: 2/25に2/24の結果取得）
python3 scripts/fetch_results.py --date 2026-02-24
```

**出力先**: `data/results/results_keirin_YYYYMMDD.json`

---

## 週末の集計

```bash
# 1週間分の集計レポート生成
python3 scripts/weekly_report.py --start 2026-02-24 --end 2026-03-02
```

**出力先**: `data/reports/weekly_YYYYMMDD_YYYYMMDD.json`

---

## 記録項目（毎日記録すること）

| 項目 | 内容 |
|------|------|
| 対象レース数（フィルター前） | keirin.jpから取得したレース総数 |
| 対象レース数（フィルター後） | S1×準決勝・決勝を通過したレース数 |
| Haiku予想品質評価 | 日本語の自然さ、軸選定の妥当性（1-5点） |
| 的中率 | 翌日結果確認後に記入 |
| 回収率 | 翌日結果確認後に記入 |
| API消費量 | トークン数（Haiku API呼び出し回数 × 平均トークン） |
| エラー・例外 | 発生した場合はログと内容を記録 |

---

## モデル切替方法

`config/settings.yaml` の `llm.model` を編集するだけで切り替え可能：

```yaml
llm:
  model: claude-haiku-4-5-20251001   # Haiku（高速・低コスト）
  # model: claude-sonnet-4-6         # Sonnet（高品質・高コスト）
  fallback_model: claude-sonnet-4-6
```

---

## DoS対策確認

`config/settings.yaml` で以下が設定されていることを毎回確認：

```yaml
scraping:
  min_interval_sec: 3      # 3秒以上の間隔（必須）
  max_requests_per_session: 20  # 1セッション最大20件
```

**違反は切腹レベル** — 絶対に変更するな

---

## 緊急停止手順

```bash
# プロセス確認
ps aux | grep daily_run

# 強制停止
kill -9 [PID]
```

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| ANTHROPIC_API_KEY エラー | `export ANTHROPIC_API_KEY=...` を設定 |
| レース取得0件 | keirin.jp が開催日か確認。スタブ実装のためパース強化が必要 |
| フィルター通過0件 | S1準決勝・決勝が開催されているか確認 |
| JSON保存エラー | `data/predictions/` ディレクトリの書き込み権限確認 |

---

## 週次テスト評価基準

| 指標 | 合格ライン |
|------|-----------|
| 的中率 | 20%以上 |
| 回収率 | 80%以上（損失許容範囲内） |
| Haiku品質 | 平均3点以上/5点 |
| エラー発生率 | 5%以下 |
| API呼び出し成功率 | 95%以上 |
