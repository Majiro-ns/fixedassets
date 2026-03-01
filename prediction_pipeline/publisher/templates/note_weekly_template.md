# {week_label} 競輪予想 週次レポート

> 本記事はAI予想パイプライン（Mr.T CREプロファイル統合）による自動生成週次レポートです。
> 期間: {week_start} 〜 {week_end}

---

## 週次サマリー

| 指標 | 値 | 評価 |
|------|-----|------|
| 総予想数 | {total_predictions}件 | - |
| S評価投稿数 | {s_count}件 | - |
| 的中数 | {hit_count}件 | - |
| 的中率 | {hit_rate}% | {hit_rate_eval} |
| 投資合計 | {total_investment}円 | - |
| 払戻合計 | {total_payout}円 | - |
| 収支 | {net_profit}円 | {profit_eval} |
| 週次回収率 | {weekly_recovery}% | {recovery_eval} |

---

## 曜日別成績

{weekday_stats}

---

## 今週のハイライト

### 最高配当的中

{best_hit}

### S評価レース成績

{s_results}

---

## フィルター別分析

| フィルター | 件数 | 的中率 | 回収率 |
|-----------|------|--------|--------|
| C（堅実型） | {filter_c_n} | {filter_c_hit}% | {filter_c_recovery}% |
| A（標準型） | {filter_a_n} | {filter_a_hit}% | {filter_a_recovery}% |
| B（穴狙い型） | {filter_b_n} | {filter_b_hit}% | {filter_b_recovery}% |

---

## 来週の戦略メモ

{strategy_memo}

---

## 月次累計（参考）

| 指標 | 値 |
|------|-----|
| 月次回収率 | {monthly_recovery}% |
| 累計収支 | {monthly_profit}円 |
| 月次的中率 | {monthly_hit_rate}% |

---

*生成日時: {generated_at}*
*パイプライン: prediction_pipeline v1.0 / filter: Mr.T CRE統合*
