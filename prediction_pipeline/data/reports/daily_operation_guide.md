# 競輪予測パイプライン 日次運用手順書

作成: 2026-02-28（cmd_102k: Stage 2 = 足軽手動トリガー方式に変更）
更新: 2026-03-01（cmd_105k: collect_results.py新規・roi_tracker sport対応・bet_parser dedup完成）

---

## 設計方針（cmd_102k 方針転換）

> 殿の判断: 「Haikuで回すより、おぬしたち（Claude Code足軽）のほうが信頼できる」
> Sonnet/Opusの推論力はHaikuより圧倒的に上。出走表の文脈読解・Mr.T CREの再現にはHaikuでは力不足。

- **Stage 1 / Stage 3**: cron自動実行
- **Stage 2**: Claude Code足軽（Sonnet）が手動実行
- ANTHROPIC_API_KEY は不要（足軽が直接予測テキストを生成するため）

---

## 日次自動フロー（cmd_105k 更新版）

```
07:00 [cron] Stage 1: stage1_keirin
  → 出走表収集・フィルター適用
  → predictions/requests/*.yaml 生成

07:05〜 [家老弐] Stage 2 依頼（足軽6へ send-keys）
  → 各足軽がリクエストを読み、予測テキストを生成
  → predictions/results/*.yaml に書き込み

18:00 [cron] Stage 3: stage3_keirin
  → 予測結果を読み込み bet 計算
  → output/YYYYMMDD/keirin_*.json 保存
  → Discord 通知
  → ★NEW: roi_tracker.py --sport keirin 自動呼び出し（monthly_roi.json 更新）
```

> **cmd_105k 変更点**: Stage 3 完了後に `roi_tracker.py --scan-month YYYYMM --sport keirin`
> が自動実行される。3/1 以降は Stage 3 成功 → `monthly_roi.json` が自動更新される。
> 手動での roi_tracker 呼び出しは不要になった。

---

## 日次スケジュール

| 時刻 | 担当 | 作業 | コマンド/手順 |
|------|------|------|--------------|
| **07:00** | cron自動 | Stage 1: レース取得+フィルター+リクエスト生成 | `cron_pipeline.sh stage1_keirin` |
| **07:05〜** | 家老弐 | Stage 2依頼: 足軽6にsend-keysで投入 | 下記「家老の手順」参照 |
| **〜09:00** | 足軽6 | Stage 2: 予測テキスト生成 | 下記「足軽の手順」参照 |
| **18:00** | cron自動 | Stage 3: 結果集約+bet計算+Discord通知+ROI自動更新 | `cron_pipeline.sh stage3_keirin` |
| **18:05〜** | 任意 | レース結果収集（新機能） | `collect_results.py --date YYYYMMDD` |

---

## 家老弐の朝の手順（07:05頃）

```bash
# 1. Stage 1 完了確認
tmux capture-pane -t multiagent:0.6 -p | tail -5
# → "Stage 1 完了: N件のリクエストを生成" を確認

# 2. 足軽6へ Stage 2 依頼（send-keys）
tmux send-keys -t multiagent:0.6 'queue/predictions/requests/ にリクエストがある。stage2_process.py --list で確認して予測を生成せよ'
tmux send-keys -t multiagent:0.6 Enter
```

---

## 足軽（Stage 2）の実行手順

```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline
source .venv/bin/activate

# ステップ1: リクエスト一覧を確認
python scripts/stage2_process.py --list

# 出力例:
# [1] pred_keirin_大垣_12 (filter=A, conf=1, stage=Ｓ級初特選)
# [2] pred_keirin_和歌山_12 (filter=A, conf=1, stage=Ｓ級初日特選)

# ステップ2: 各リクエストの詳細を確認（system_prompt + user_prompt を読む）
python scripts/stage2_process.py --show pred_keirin_大垣_12

# ステップ3: 予測テキストを生成して書き込む
# → system_prompt と user_prompt を読み、予測テキストを生成する
# → 生成した予測テキストを一時ファイルに書き、--text-file で書き込む
cat > /tmp/pred_大垣_12.txt << 'EOF'
軸: 1番（郡司浩平）
相手: 5番（古性優作）、3番（山口拳矢）、9番（嘉永泰斗）
買い目: 3連複ながし 1-359（3点）
根拠: SS級2名が軸候補。郡司の逃げ＋古性の捲りでラインが形成される可能性高い。競走得点117.7で最上位。
EOF
python scripts/stage2_process.py --write pred_keirin_大垣_12 --text-file /tmp/pred_大垣_12.txt

# 全リクエストを処理したら Stage 3 を待つ（18:00 cron自動実行）
```

---

## 予測テキストのフォーマット（必須）

Stage 3 が軸・相手を自動解析するため、以下のフォーマットに従うこと:

```
軸: [車番]番（[選手名]）
相手: [車番]番（[選手名]）、[車番]番（[選手名]）[、...]
買い目: [賭式] [軸]-[相手組合せ]（[点数]点）
根拠: [200字以内の根拠]
```

---

## stage2_process.py の使い方

| オプション | 用途 |
|-----------|------|
| `--list` | pending/done のリクエスト一覧を表示 |
| `--show {task_id}` | 指定リクエストの system_prompt + user_prompt を表示 |
| `--write {task_id} --text-file /tmp/xxx.txt` | 予測テキストファイルをresult YAMLに書き込む |

> **注意**: `--prediction "..."` と `--from-stdin` はスクリプトに存在しない。必ず `--text-file` を使用せよ。

---

## Haiku API fallback（緊急時）

足軽が利用できない場合のみ使用:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python scripts/stage2_haiku.py
```

通常運用では使用しない。

---

## Stage 3 完了確認

```bash
# Stage 3 ログ確認
tail -20 data/logs/cron.log

# 出力JSON確認
ls output/$(date +%Y%m%d)/

# サマリー確認
cat output/$(date +%Y%m%d)/summary.md
```

---

## レース結果確認手順（新機能: collect_results.py）

> **cmd_105k 追加機能**: `collect_results.py` が Stage 3 完了後に
> 当日の bet 結果を自動集約し、roi_tracker への反映まで行う。

```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline
source .venv/bin/activate

# 事前確認（ドライラン）: 当日の収集対象を確認
python scripts/collect_results.py --date $(date +%Y%m%d) --dry-run

# 本実行: Stage 3 結果を収集・保存・ROI更新
python scripts/collect_results.py --date $(date +%Y%m%d)

# 特定日付の指定（手動実行時）
python scripts/collect_results.py --date 20260301

# ROI更新をスキップして収集のみ
python scripts/collect_results.py --date 20260301 --no-roi-update
```

### collect_results.py オプション一覧

| オプション | 説明 | 例 |
|-----------|------|-----|
| `--date YYYYMMDD` | 対象日付（必須） | `--date 20260301` |
| `--dry-run` | 保存・ROI更新をスキップ（確認用） | `--dry-run` |
| `--no-roi-update` | roi_tracker への反映をスキップ | `--no-roi-update` |
| `--verbose` | デバッグログ表示 | `--verbose` |

---

## レース結果記録手順（手動入力・Stage 3 完了後に実施）

> **cmd_105k 以降**: Stage 3 完了後、cron が `roi_tracker.py --sport keirin` を
> 自動呼び出しするため、`monthly_roi.json` は自動更新される。
> 払戻額（payout）の記録は `collect_results.py` または `record_result.py` で行う。
>
> **2月分の未記録レース（6件）**: 2/23〜2/28 のレースは手動入力が必要。
> 下記「record_result.py の使い方」を参照。

### 基本フロー（翌日朝 or Stage 3 確認後）

```bash
cd /mnt/c/Users/owner/Desktop/llama3_wallthinker/prediction_pipeline
source .venv/bin/activate

# ステップ1: 記録すべきレース一覧を確認
python scripts/record_result.py --list
# → 未記録（❌）のレースに対して払戻額を調べて記録する

# ステップ2: 結果を記録（的中の場合）
python scripts/record_result.py --race 20260228_和歌山_12 --payout 5400
# ステップ2（不的中の場合）
python scripts/record_result.py --race 20260228_和歌山_12 --payout 0

# ステップ3: 月次集計を確認
python scripts/record_result.py --summary
```

### record_result.py オプション一覧

| オプション | 説明 | 例 |
|-----------|------|-----|
| `--list` | 未記録BETレース一覧を表示 | `--list` |
| `--summary` | 月次ROIサマリー表示 | `--summary` |
| `--race` | レースID（YYYYMMDD_会場_R番号） | `--race 20260228_和歌山_12` |
| `--payout` | 払戻額（円）。不的中は 0 | `--payout 5400` |
| `--result` | 着順メモ（任意） | `--result "4-6-2"` |
| `--dry-run` | 書き込まずに確認のみ | `--dry-run` |
| `--venue`/`--race-no`/`--date` | 個別指定（--race の代替） | `--venue 和歌山 --race-no 12 --date 20260228` |

### 払戻額の調べ方

keirin.jp でレース結果を確認:
1. [keirin.jp](https://keirin.jp) → レース結果 → 開催日・会場を選択
2. 買い目の払戻金額を確認
3. `--payout` に入力

### 記録後の確認

```bash
# backtest_real.py で実績確認（記録が増えたら意味のある数値が出る）
python scripts/backtest_real.py

# 月次ログの生データ確認
cat data/logs/monthly_roi.json
```

---

## 3/1 初回ランチェックリスト

> **目的**: cmd_105k 変更（dedup・roi_tracker sport対応・collect_results.py）の
> 本番初回動作確認。各チェックポイントで問題があれば家老弐に報告せよ。

### Stage 1 完了後（07:05頃）

```bash
# リクエストが生成されているか確認
ls queue/predictions/requests/*.yaml 2>/dev/null | wc -l
# → 1件以上あれば OK

# 生成内容を確認（venue・race_no・filter_type が正しいか）
python scripts/stage2_process.py --list
```

- [ ] `predictions/requests/` に `*.yaml` が1件以上生成されている
- [ ] 各リクエストの `filter_type` が A/B/C のいずれかである

### Stage 2 完了後（09:00頃）

```bash
# 予測結果が書き込まれているか確認
ls queue/predictions/results/*.yaml 2>/dev/null | wc -l

# 予測テキストに「軸:」または「本命:」が含まれるか確認
grep -l "軸\|本命" queue/predictions/results/*.yaml
```

- [ ] `predictions/results/` に対応する `*.yaml` が生成されている
- [ ] 予測テキストに「軸:」または「本命:」「相手:」または「軸相手:」が含まれる

### Stage 3 実行前（17:55頃）

```bash
# Stage 3 実行前: bet_parser 修正済み確認（keirin_*.json の partners を目視確認）
# Stage 3 後に生成される keirin_*.json の partners が重複していないか確認用コマンド:
# （Stage 3 後に実行）
ls output/$(date +%Y%m%d)/keirin_*.json 2>/dev/null
```

- [ ] `cron.log` に前回の Stage 3 エラーがないことを確認 (`tail -30 data/logs/cron.log`)

### Stage 3 完了後（18:05頃）

```bash
# Stage 3 ログで roi_tracker 自動呼び出し成功を確認
grep "roi_tracker\|monthly_roi" data/logs/cron.log | tail -5

# output に keirin_*.json が生成されているか確認
ls output/$(date +%Y%m%d)/keirin_*.json

# partners に重複がないか目視確認（bet_parser dedup 動作確認）
cat output/$(date +%Y%m%d)/keirin_*.json | python3 -c "
import json, sys
for line in sys.stdin:
    try:
        d = json.loads(line)
        p = d.get('partners', [])
        if len(p) != len(set(p)):
            print('⚠️ 重複あり:', p)
        else:
            print('✅ partners OK:', p)
    except: pass
"
```

- [ ] `cron.log` に `roi_tracker.py` の実行ログがある（エラーなし）
- [ ] `output/$(date +%Y%m%d)/keirin_*.json` が生成されている
- [ ] 各 JSON の `partners` に重複番号がない

### 翌朝確認（3/2 朝）

```bash
# monthly_roi.json に 202603 エントリが追加されているか確認
python3 -c "
import json
data = json.load(open('data/logs/monthly_roi.json'))
print('202603' in data and '✅ 3月エントリあり' or '❌ 3月エントリなし')
if '202603' in data:
    m = data['202603']
    print(f'  bet_count={m[\"bet_count\"]}, total_investment=¥{m[\"total_investment\"]:,}')
"
```

- [ ] `monthly_roi.json` に `202603` エントリが存在する
- [ ] `bet_count` がこの日のBET件数と一致している

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| Stage 1 が 0件 | 月曜/日曜は対象レース少ない | `filters.yaml` の `exclude_day_of_week` 確認 |
| Stage 2 request が pending のまま | 足軽が未処理 | `stage2_process.py --list` で確認、手動実行 |
| Stage 3 で「0件処理」 | Stage 2 結果なし | `queue/predictions/results/` を確認 |
| Discord 通知失敗 | DISCORD_WEBHOOK_URL 未設定 | `.env` の `DISCORD_WEBHOOK_URL` を確認 |

---

## 関連ファイル

| ファイル | 用途 | 備考 |
|---------|------|------|
| `scripts/ashigaru_predict.py` | Stage 1 / Stage 3 本体 | regex修正済み（cmd_105k）|
| `scripts/stage2_process.py` | 足軽用 Stage 2 ヘルパー | |
| `scripts/stage2_haiku.py` | Haiku API fallback（通常不使用） | |
| `scripts/collect_results.py` | **NEW** Stage 3 結果収集・ROI反映 | cmd_105k 新規 |
| `scripts/record_result.py` | 払戻額手動入力 | 2月分未記録レース用 |
| `scripts/roi_tracker.py` | 月次ROI集計 | --sport keirin 対応済み（cmd_105k）|
| `scripts/backtest_real.py` | 実バックテスト | 実績記録後に有効化 |
| `scripts/cron_pipeline.sh` | cron ラッパー | Stage3後にroi_tracker自動呼び出し追加（cmd_105k）|
| `scripts/setup_cron.sh` | crontab 登録スクリプト | |
| `src/bet_calculator.py` | 賭け式計算 | dedup修正済み（cmd_105k）|
| `queue/predictions/requests/` | Stage 1 が生成するリクエスト | |
| `queue/predictions/results/` | 足軽が書き込む予測結果 | |
| `data/logs/cron.log` | cron 実行ログ | |
| `data/logs/monthly_roi.json` | 月次ROI記録 | Stage3後に自動更新（cmd_105k〜）|

*作成: 家老弐 / cmd_102k*
*更新: 足軽7 / cmd_105k（collect_results.py・roi_tracker sport対応・bet_parser dedup完成・3/1チェックリスト追加）*
