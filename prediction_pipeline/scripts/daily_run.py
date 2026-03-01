"""
競輪・競艇予想パイプライン 日次実行スクリプト
=============================================

引数なしで実行可能なメインエントリーポイント。
settings.yaml を読み込み、対象スポーツのレース一覧を取得し、
フィルター → 予想生成 → 賭け式計算 → 保存 の順に処理する。

使用例:
    python scripts/daily_run.py
    python scripts/daily_run.py --sport keirin --date 20260222
    python scripts/daily_run.py --sport kyotei --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# プロジェクトルートを sys.path に追加
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.filter_engine import FilterEngine
from src.formatter import format_prediction, format_batch, save_prediction, batch_to_text_summary
from src.predictor import generate_prediction
from src.profile_loader import ProfileLoader

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 設定読み込み
# ─────────────────────────────────────────────────────────

def load_settings(settings_path: str = "config/settings.yaml") -> Dict[str, Any]:
    """
    settings.yaml を読み込む。

    Args:
        settings_path: 設定ファイルのパス。

    Returns:
        設定辞書。
    """
    path = ROOT / settings_path
    if not path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")

    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    logger.info("設定読み込み完了: %s", path)
    return config


def setup_logging(config: Dict[str, Any]) -> None:
    """
    ログ設定を初期化する。

    Args:
        config: settings.yaml の内容。
    """
    log_cfg = config.get("logging", {})
    level_str = log_cfg.get("level", "INFO")
    level = getattr(logging, level_str.upper(), logging.INFO)
    fmt = log_cfg.get("format", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # ログディレクトリ作成
    log_file = log_cfg.get("file")
    handlers: list = [logging.StreamHandler()]
    if log_file:
        log_path = ROOT / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(level=level, format=fmt, handlers=handlers)


# ─────────────────────────────────────────────────────────
# レース取得
# ─────────────────────────────────────────────────────────

def fetch_races(sport: str, date: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    指定スポーツのレーススケジュールを取得する。

    Args:
        sport: "keirin" または "kyotei"。
        date: 日付文字列（YYYYMMDD）。
        config: settings.yaml の内容。

    Returns:
        レース辞書のリスト。
    """
    if sport == "keirin":
        from src.keirin_scraper import KeirinScraper
        scraper = KeirinScraper(config)
        races = scraper.fetch_schedule(date=date)
        for r in races:
            r["sport"] = "keirin"
        return races

    elif sport == "kyotei":
        from src.kyotei_scraper import KyoteiScraper
        scraper = KyoteiScraper(config)
        races = scraper.fetch_schedule(date=date)
        for r in races:
            r["sport"] = "kyotei"
        return races

    else:
        raise ValueError(f"未対応のスポーツ: {sport}。keirin または kyotei を指定してください。")


# ─────────────────────────────────────────────────────────
# レース処理（フィルター → 予想 → 賭け式）
# ─────────────────────────────────────────────────────────

def process_race(
    race: Dict[str, Any],
    filter_engine: FilterEngine,
    profile: Dict[str, Any],
    config: Dict[str, Any],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    1 レースをフィルター → 予想 → 賭け式計算 で処理する。

    Args:
        race: レース辞書。
        filter_engine: フィルターエンジンインスタンス。
        profile: 予想師プロファイル辞書。
        config: settings.yaml の内容。
        dry_run: True の場合 API を呼ばずモックを返す。

    Returns:
        処理結果辞書。フィルター除外の場合は bet_type: "skip" を含む。
    """
    venue = race.get("venue_name", "")
    race_no = race.get("race_no", "")
    stage = race.get("stage", "")
    grade = race.get("grade", "")

    # フィルター適用
    if not filter_engine.apply(race):
        logger.info("[スキップ] %s %sR %s %s（フィルター条件未達）", venue, race_no, grade, stage)
        return format_prediction(
            race_info=race,
            prediction_text="",
            bet_result={"bet_type": "skip", "reason": f"フィルター除外: {grade} {stage}"},
            profile=profile,
        )

    logger.info("[処理中] %s %sR %s %s", venue, race_no, grade, stage)

    # 予想生成
    if dry_run:
        prediction_text = (
            f"[DRY RUN] {venue} {race_no}R {grade} {stage}\n"
            "軸: 1番\n相手: 2番、3番、4番\nコメント: テスト予想（API未呼び出し）"
        )
        model_used = "dry-run"
    else:
        try:
            prediction_text = generate_prediction(race, profile, config)
            model_used = config["llm"]["model"]
        except Exception as e:
            logger.error("[エラー] 予想生成失敗 %s %sR: %s", venue, race_no, e)
            return format_prediction(
                race_info=race,
                prediction_text=f"予想生成エラー: {e}",
                bet_result={"bet_type": "skip", "reason": f"予想エラー: {e}"},
                profile=profile,
            )

    # 賭け式計算（予想テキストから軸・相手を抽出）
    bet_result = _extract_and_calc_bet(prediction_text, race, config)

    return format_prediction(
        race_info=race,
        prediction_text=prediction_text,
        bet_result=bet_result,
        profile=profile,
        model_used=model_used,
    )


def _extract_and_calc_bet(
    prediction_text: str,
    race: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    予想テキストから軸・相手を解析し、賭け式を計算する。

    Args:
        prediction_text: LLM 出力テキスト。
        race: レース情報辞書。
        config: settings.yaml の内容。

    Returns:
        bet_calculator の出力辞書。解析失敗時は skip を返す。
    """
    from src.bet_calculator import calc_from_strategy

    bet_cfg = config.get("betting", {})
    strategy = bet_cfg.get("default_strategy", "sanrenpu_nagashi")

    # 簡易パース: 「軸: N番」「相手: N番、M番...」を抽出
    import re
    axis_match = re.search(r"軸[：:]\s*(\d+)番", prediction_text)
    partner_matches = re.findall(r"相手[：:][^\n]*?(\d+)番", prediction_text)

    if not axis_match:
        # 数字のみのフォールバック解析
        numbers = re.findall(r"\b([1-7])\b", prediction_text)
        if len(numbers) >= 2:
            axis = int(numbers[0])
            partners = [int(n) for n in numbers[1:4] if int(n) != axis]
        else:
            logger.warning("軸・相手を解析できませんでした。見送りとします。")
            return {"bet_type": "skip", "reason": "軸・相手の解析失敗"}
    else:
        axis = int(axis_match.group(1))
        # 相手行全体から数字を抽出
        partner_line_match = re.search(r"相手[：:](.*)", prediction_text)
        if partner_line_match:
            partners = [int(n) for n in re.findall(r"\d+", partner_line_match.group(1))]
            partners = [p for p in partners if p != axis][:4]  # 最大4名
        else:
            partners = []

    if len(partners) < 2:
        logger.warning("相手が2名未満。見送りとします。軸=%s 相手=%s", axis, partners)
        return {"bet_type": "skip", "reason": f"相手不足（{len(partners)}名）"}

    try:
        return calc_from_strategy(strategy, axis, partners, bet_cfg)
    except Exception as e:
        logger.error("賭け式計算エラー: %s", e)
        return {"bet_type": "skip", "reason": f"賭け式計算エラー: {e}"}


# ─────────────────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────────────────

def run(
    sport: str = "keirin",
    date: Optional[str] = None,
    dry_run: bool = False,
    profile_id: str = "mr_t",
    max_races: Optional[int] = None,
) -> None:
    """
    日次予想パイプラインのメイン処理。

    Args:
        sport: 対象スポーツ（"keirin" or "kyotei"）。
        date: 対象日付（YYYYMMDD または YYYY-MM-DD）。省略時は本日。
        dry_run: True の場合 API 呼び出しをスキップ。
        profile_id: 使用する予想師プロファイル ID。
        max_races: 処理するレースの最大数。None の場合は全件。
    """
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    # 日付フォーマット正規化: YYYY-MM-DD → YYYYMMDD
    date = date.replace("-", "")

    # 設定読み込み
    config = load_settings()
    setup_logging(config)
    logger.info("=== 競輪・競艇予想パイプライン 開始 ===")
    logger.info("スポーツ: %s / 日付: %s / DRY RUN: %s", sport, date, dry_run)

    # プロファイル読み込み
    profiles_dir = ROOT / config.get(sport, {}).get("profile_dir", f"config/{sport}/profiles")
    loader = ProfileLoader(str(profiles_dir))
    profile = loader.load_or_default(
        profile_id,
        default={"predictor_name": f"{profile_id}_default", "profile_id": profile_id},
    )
    logger.info("予想師プロファイル: %s", profile.get("predictor_name", profile_id))

    # フィルターエンジン初期化
    filters_path = ROOT / config.get(sport, {}).get("config_dir", f"config/{sport}") / "filters.yaml"
    filter_engine = FilterEngine(str(filters_path))

    # レース取得
    logger.info("レーススケジュール取得中... (%s)", date)
    try:
        races = fetch_races(sport, date, config)
    except Exception as e:
        logger.error("レース取得エラー: %s", e)
        races = []

    if not races:
        logger.warning("対象レースが0件でした。")
        return

    logger.info("取得レース数: %d", len(races))

    # max_races 制限
    if max_races is not None and max_races > 0:
        races = races[:max_races]
        logger.info("max_races=%d 制限適用: %d 件に絞りました", max_races, len(races))

    # 各レース処理
    results = []
    for race in races:
        result = process_race(race, filter_engine, profile, config, dry_run=dry_run)
        results.append(result)

    # 通過レース数カウント
    passed = [r for r in results if r.get("bet", {}).get("bet_type") != "skip"]
    logger.info("フィルター通過レース: %d / %d", len(passed), len(races))

    # バッチ保存
    batch = format_batch(results, meta={"sport": sport, "date": date, "profile": profile_id})
    output_path = save_prediction(
        batch,
        output_dir=str(ROOT / "data" / "predictions"),
        filename=f"prediction_{sport}_{date}.json",
    )
    logger.info("保存先: %s", output_path)

    # テキストサマリー出力
    print(batch_to_text_summary(batch))
    logger.info("=== パイプライン完了 ===")


def main() -> None:
    """CLI エントリーポイント。"""
    parser = argparse.ArgumentParser(
        description="競輪・競艇予想パイプライン 日次実行スクリプト"
    )
    parser.add_argument(
        "--sport",
        choices=["keirin", "kyotei"],
        default="keirin",
        help="対象スポーツ（デフォルト: keirin）",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="対象日付 YYYYMMDD（デフォルト: 本日）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API 呼び出しをスキップするテストモード",
    )
    parser.add_argument(
        "--profile",
        default="mr_t",
        help="予想師プロファイル ID（デフォルト: mr_t）",
    )

    parser.add_argument(
        "--max-races",
        type=int,
        default=None,
        help="処理するレースの最大数（デフォルト: 無制限）",
    )

    args = parser.parse_args()
    run(
        sport=args.sport,
        date=args.date,
        dry_run=args.dry_run,
        profile_id=args.profile,
        max_races=args.max_races,
    )


if __name__ == "__main__":
    main()
