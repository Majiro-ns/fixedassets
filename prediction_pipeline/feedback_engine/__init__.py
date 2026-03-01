"""
feedback_engine — フィードバックループ心臓部

予想→結果→分析→フィルター改善の自動学習サイクルを担う。

モジュール:
    predictions_log.py  : 教師データ JSONL 書込・読込・更新
    analyzer.py         : 週次フィードバック分析
    optimizer.py        : 月次フィルター自動最適化
    prompt_tuner.py     : 四半期プロンプト微調整（将来実装）
    report_generator.py : 週次/月次レポート生成（将来実装）
"""

from feedback_engine.predictions_log import PredictionsLog

__all__ = ["PredictionsLog"]
