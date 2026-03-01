"""
競輪・競艇予想パイプライン 統合実行スクリプト
==============================================

scripts/daily_run.py を基に、より統合的なメインエントリーポイントとして実装。
--config で設定ファイルパスを指定し、--date（必須）で対象日を指定する。

使用例:
    python main.py --date 20260224
    python main.py --date 20260224 --sport keirin --dry-run
    python main.py --date 20260224 --config config/settings.yaml --max-races 3
    python main.py --date 20260224 --sport kyotei --max-races 6
    python main.py --date 20260224 --sport keirin --save-fixture

Mock Mode（APIキーなしデモ用）:
    KEIRIN_MOCK_MODE=1 python main.py --date 20260228 --dry-run
    KEIRIN_MOCK_MODE=1 python main.py --date 20260228 --sport keirin --max-races 3
    → 環境変数 KEIRIN_MOCK_MODE=1 を設定するとAPIキーなしでパイプライン全体が動作する
    → score上位3選手を軸・相手として機械的に選択（精度は期待しない。動作確認用）
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# プロジェクトルートを sys.path に追加（src/ をインポート可能にする）
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.expected_payout import estimate_expected_payout
from src.filter_engine import FilterEngine
from src.formatter import (
    batch_to_text_summary,
    format_batch,
    format_prediction,
    save_prediction,
)
from src.predictor import generate_prediction
from src.profile_loader import ProfileLoader

logger = logging.getLogger(__name__)

# fixture 保存・読み込みディレクトリ
FIXTURES_DIR = ROOT / "data" / "fixtures"


# ─────────────────────────────────────────────────────────
# 設定・ログ
# ─────────────────────────────────────────────────────────


def load_settings(config_path: str) -> Dict[str, Any]:
    """
    設定ファイル（YAML）を読み込む。

    Args:
        config_path: 設定ファイルのパス（ROOT からの相対パスまたは絶対パス）。

    Returns:
        設定辞書。

    Raises:
        FileNotFoundError: 設定ファイルが存在しない場合。
    """
    path = Path(config_path)
    if not path.is_absolute():
        path = ROOT / config_path
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

    handlers: list = [logging.StreamHandler()]
    log_file = log_cfg.get("file")
    if log_file:
        log_path = ROOT / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(level=level, format=fmt, handlers=handlers)


# ─────────────────────────────────────────────────────────
# fixture 読み書き（--dry-run / --save-fixture 対応）
# ─────────────────────────────────────────────────────────


def _load_fixture(sport: str, date: str) -> List[Dict[str, Any]]:
    """
    data/fixtures/ から fixture データを読み込む。

    優先順位:
        1. data/fixtures/{sport}_{date}.json（日付指定ファイル）
        2. data/fixtures/{sport}_[0-9]*.json の最新ファイル
        3. data/fixtures/{sport}_sample.json（サンプルデータ）
        4. 空リスト（fixture が1件もない場合）

    Args:
        sport: "keirin" または "kyotei"。
        date: 対象日付（YYYYMMDD）。

    Returns:
        レース辞書のリスト（各辞書に "sport" キーを付加済み）。
    """
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 日付指定ファイル
    dated_path = FIXTURES_DIR / f"{sport}_{date}.json"
    if dated_path.exists():
        logger.info("[DRY-RUN] fixture 読み込み: %s", dated_path)
        with open(dated_path, encoding="utf-8") as f:
            races = json.load(f)
        for r in races:
            r["sport"] = sport
        return races

    # 2. 最新の日付付き fixture（{sport}_YYYYMMDD.json 形式）
    dated_fixtures = sorted(
        FIXTURES_DIR.glob(f"{sport}_[0-9]*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if dated_fixtures:
        latest = dated_fixtures[0]
        logger.info("[DRY-RUN] 最新 fixture 読み込み: %s", latest)
        with open(latest, encoding="utf-8") as f:
            races = json.load(f)
        for r in races:
            r["sport"] = sport
        return races

    # 3. サンプルデータ
    sample_path = FIXTURES_DIR / f"{sport}_sample.json"
    if sample_path.exists():
        logger.info("[DRY-RUN] サンプル fixture 読み込み: %s", sample_path)
        with open(sample_path, encoding="utf-8") as f:
            races = json.load(f)
        for r in races:
            r["sport"] = sport
        return races

    logger.warning("[DRY-RUN] fixture が見つかりません（data/fixtures/%s_*.json）。空リストを返します。", sport)
    return []


def _save_fixture(sport: str, date: str, races: List[Dict[str, Any]]) -> None:
    """
    スクレイピング結果を data/fixtures/{sport}_{date}.json に保存する。

    Args:
        sport: "keirin" または "kyotei"。
        date: 対象日付（YYYYMMDD）。
        races: fetch_races() が返したレースリスト。
    """
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    fixture_path = FIXTURES_DIR / f"{sport}_{date}.json"
    with open(fixture_path, "w", encoding="utf-8") as f:
        json.dump(races, f, ensure_ascii=False, indent=2)
    logger.info("[SAVE-FIXTURE] 保存完了: %s (%d 件)", fixture_path, len(races))


# ─────────────────────────────────────────────────────────
# レース取得
# ─────────────────────────────────────────────────────────


def fetch_races(
    sport: str,
    date: str,
    config: Dict[str, Any],
    dry_run: bool = False,
    save_fixture: bool = False,
) -> List[Dict[str, Any]]:
    """
    指定スポーツ・日付のレーススケジュールを取得する。

    --dry-run 時は data/fixtures/ からデータを読み込みスクレイピングをスキップ。
    --save-fixture 時はスクレイピング結果を data/fixtures/ に保存する。

    Args:
        sport: "keirin" または "kyotei"。
        date: 対象日付（YYYYMMDD）。
        config: settings.yaml の内容。
        dry_run: True の場合、fixture から読み込む（スクレイピングなし）。
        save_fixture: True の場合、スクレイピング結果を fixture として保存。

    Returns:
        レース辞書のリスト。各辞書に "sport" キーを付加して返す。

    Raises:
        ValueError: sport が未対応の値の場合。
    """
    if dry_run:
        return _load_fixture(sport, date)

    if sport == "keirin":
        from src.keirin_scraper import KeirinScraper
        scraper = KeirinScraper(config)
        races = scraper.fetch_schedule(date=date)
    elif sport == "kyotei":
        from src.kyotei_scraper import KyoteiScraper
        scraper = KyoteiScraper(config)
        races = scraper.fetch_schedule(date=date)
    else:
        raise ValueError(
            f"未対応のスポーツ: {sport}。keirin または kyotei を指定してください。"
        )

    for r in races:
        r["sport"] = sport

    if save_fixture:
        _save_fixture(sport, date, races)

    return races


# ─────────────────────────────────────────────────────────
# レース処理（フィルター → 予想 → 賭け式）
# ─────────────────────────────────────────────────────────


def process_race(
    race: Dict[str, Any],
    filter_engine: FilterEngine,
    profile: Dict[str, Any],
    config: Dict[str, Any],
    dry_run: bool = False,
    mock_mode: bool = False,
) -> Dict[str, Any]:
    """
    1 レースをフィルター → 予想 → 賭け式計算で処理する。

    1 レースの失敗が全体を止めないよう、呼び出し元でエラーをキャッチすること。

    Args:
        race: レース辞書（venue_name, race_no, grade, stage, entries を含む）。
        filter_engine: フィルターエンジンインスタンス。
        profile: 予想師プロファイル辞書。
        config: settings.yaml の内容。
        dry_run: True の場合 API を呼ばずモック予想を返す。
        mock_mode: True の場合 KEIRIN_MOCK_MODE 相当の動作をする。
                   score上位3選手を軸・相手として機械的に選択する。
                   APIキーチェックをスキップ。出力に mock_mode=True を記録する。

    Returns:
        format_prediction() の返り値。
        フィルター除外の場合は bet_type: "skip" を含む。
        mock_mode=True の場合は result["mock_mode"]=True が追加される。
    """
    venue = race.get("venue_name", "")
    race_no = race.get("race_no", "")
    grade = race.get("grade", "")
    stage = race.get("stage", "")

    # F8 統合: フィルター適用前に expected_payout を補完（cmd_144k_sub4）
    # race に expected_payout が未設定の場合のみ estimate_expected_payout() で補完する。
    # スクレイパーがオッズ等から設定済みの場合はそちらを優先。
    if race.get("expected_payout") is None:
        est_payout = estimate_expected_payout(race)
        if est_payout is not None:
            race["expected_payout"] = est_payout
            logger.debug(
                "[F8推定] %s %sR expected_payout=%.0f円（score_spreadベース推定）",
                venue, race_no, est_payout,
            )
        else:
            logger.debug(
                "[F8推定スキップ] %s %sR score_spreadデータ不足 → F8をスキップ",
                venue, race_no,
            )

    # フィルター適用（apply() は Tuple[bool, List[str]] を返す）
    passed, filter_reasons = filter_engine.apply(race)
    if not passed:
        logger.info(
            "[スキップ] %s %sR %s %s（フィルター条件未達: %s）",
            venue, race_no, grade, stage, filter_reasons,
        )
        return format_prediction(
            race_info=race,
            prediction_text="",
            bet_result={"bet_type": "skip", "reason": f"フィルター除外: {'; '.join(filter_reasons)}"},
            profile=profile,
        )

    # BUG-3: 分類実行（classify() で filter_type=C/A/B を決定）
    classification = filter_engine.classify(race)
    filter_type = classification.get("type", "A")
    conf_score = classification.get("confidence", 0)
    logger.info(
        "[分類] %s %sR → filter_type=%s（堅実度スコア=%d / 理由: %s）",
        venue, race_no, filter_type,
        conf_score,
        ", ".join(classification.get("reasons", [])),
    )

    # F10: 信頼度スコア閾値チェック（C3強化フィルター / cmd_089）
    # mock_mode=True の場合はスキップ: mock予想は confidence_score に依存しない
    # （score top3 で機械的に選択するため、F10 でフィルタリングすると mock 予想が生成されない）
    min_conf = filter_engine.filters.get("min_confidence_score", 0)
    if min_conf > 0 and conf_score < min_conf and not mock_mode:
        logger.info(
            "[スキップF10] %s %sR confidence_score=%d < 閾値%d（filter_type=%s）",
            venue, race_no, conf_score, min_conf, filter_type,
        )
        return format_prediction(
            race_info=race,
            prediction_text="",
            bet_result={
                "bet_type": "skip",
                "reason": f"F10[信頼度]: confidence_score={conf_score} < 閾値{min_conf}",
            },
            profile=profile,
        )

    logger.info("[処理中] %s %sR %s %s", venue, race_no, grade, stage)

    # BUG-4: sport を race 辞書から取得（fetch_races() で付与済み）
    sport = race.get("sport", "keirin")

    # 予想生成
    # W-1修正 (cmd_146k_sub4): mock_mode を dry_run より先にチェックする。
    # mock_mode=True + dry_run=True の同時指定時、mock予想を生成する（APIは呼ばない）。
    # 優先順位: mock_mode > dry_run > 実API呼び出し
    model_used = "dry-run"
    _mock_result: Optional[Dict[str, Any]] = None

    if mock_mode:
        # KEIRIN_MOCK_MODE: APIキーなしでパイプライン全体を動作させるデモ用
        # dry_run=True と同時指定されても mock_mode が優先される（W-1修正）
        from src.stage2_process import _generate_mock_prediction
        _mock_result = _generate_mock_prediction(race)
        prediction_text = _mock_result["prediction_text"]
        model_used = "mock"
        logger.info(
            "[MOCK MODE] %s %sR → axis=%s partners=%s",
            venue, race_no, _mock_result.get("axis"), _mock_result.get("partners"),
        )
    elif dry_run:
        prediction_text = (
            f"[DRY RUN] {venue} {race_no}R {grade} {stage} [filter_type={filter_type}]\n"
            "軸: 1番\n相手: 2番、3番、4番\nコメント: テスト予想（API未呼び出し）"
        )
    else:
        try:
            prediction_text = generate_prediction(
                race, profile, config,
                filter_type=filter_type,  # BUG-3: CRE戦略切り替えのため filter_type を伝搬
                sport=sport,              # BUG-4: 競艇用プロンプトテンプレートのため sport を伝搬
            )
            model_used = config.get("llm", {}).get("model", "unknown")
        except Exception as e:
            logger.error("[エラー] 予想生成失敗 %s %sR: %s", venue, race_no, e)
            return format_prediction(
                race_info=race,
                prediction_text=f"予想生成エラー: {e}",
                bet_result={"bet_type": "skip", "reason": f"予想エラー: {e}"},
                profile=profile,
            )

    # 賭け式計算
    bet_result = _extract_and_calc_bet(prediction_text, race, config)

    # F12: 点数上限チェック（C3条件5 / cmd_089）
    max_bets = filter_engine.filters.get("max_bets_per_race", 0)
    num_bets = bet_result.get("num_bets")
    if max_bets > 0 and num_bets is not None and num_bets > max_bets:
        logger.info(
            "[スキップF12] %s %sR num_bets=%d > 上限%d（C3条件5）",
            venue, race_no, num_bets, max_bets,
        )
        bet_result = {
            "bet_type": "skip",
            "reason": f"F12[点数上限]: {num_bets}点 > 上限{max_bets}点（C3条件5）",
        }

    result = format_prediction(
        race_info=race,
        prediction_text=prediction_text,
        bet_result=bet_result,
        profile=profile,
        model_used=model_used,
    )
    # BUG-3: filter_type を結果に含める（format_prediction は metadata 引数なし）
    result["filter_type"] = filter_type
    # mock_mode フラグを記録（実予想と区別するため）
    if mock_mode and _mock_result is not None:
        result["mock_mode"] = True
        result["mock_confidence"] = _mock_result.get("confidence", "mock")
        result["mock_reasoning"] = _mock_result.get("reasoning", "")
    return result


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
        calc_from_strategy() の出力辞書。解析失敗時は skip を返す。
    """
    from src.bet_calculator import calc_from_strategy

    bet_cfg = config.get("betting", {})
    strategy = bet_cfg.get("default_strategy", "sanrenpu_nagashi")

    axis_match = re.search(r"軸[：:]\s*(\d+)番?", prediction_text)
    if not axis_match:
        # フォールバック: 数字のみで解析
        numbers = re.findall(r"\b([1-7])\b", prediction_text)
        if len(numbers) >= 2:
            axis = int(numbers[0])
            partners = [int(n) for n in numbers[1:4] if int(n) != axis]
        else:
            logger.warning("軸・相手を解析できませんでした。見送りとします。")
            return {"bet_type": "skip", "reason": "軸・相手の解析失敗"}
    else:
        axis = int(axis_match.group(1))
        partner_line_match = re.search(r"相手[：:](.*)", prediction_text)
        if partner_line_match:
            partners = [int(n) for n in re.findall(r"\d+", partner_line_match.group(1))]
            partners = [p for p in partners if p != axis][:4]
        else:
            partners = []

    if len(partners) < 2:
        logger.warning(
            "相手が2名未満。見送りとします。軸=%s 相手=%s", axis, partners
        )
        return {"bet_type": "skip", "reason": f"相手不足（{len(partners)}名）"}

    try:
        return calc_from_strategy(strategy, axis, partners, bet_cfg)
    except Exception as e:
        logger.error("賭け式計算エラー: %s", e)
        return {"bet_type": "skip", "reason": f"賭け式計算エラー: {e}"}


# ─────────────────────────────────────────────────────────
# 出力
# ─────────────────────────────────────────────────────────


def save_race_result(
    result: Dict[str, Any],
    output_dir: Path,
    sport: str,
) -> str:
    """
    1 レースの予想結果を output/{date}/{sport}_{venue}_{race_no}.json に保存する。

    Args:
        result: format_prediction() の返り値。
        output_dir: 出力ディレクトリ（output/{date}/）。
        sport: スポーツ種別文字列。

    Returns:
        保存したファイルパス文字列。
    """
    race_info = result.get("race_info", {})
    venue = race_info.get("venue_name", "unknown").replace(" ", "_")
    race_no = race_info.get("race_no", "0")
    filename = f"{sport}_{venue}_{race_no}.json"
    return save_prediction(result, output_dir=str(output_dir), filename=filename)


# ─────────────────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────────────────


def run(
    date: str,
    sport: str = "keirin",
    dry_run: bool = False,
    config_path: str = "config/settings.yaml",
    max_races: int = 6,
    save_fixture: bool = False,
) -> None:
    """
    予想パイプラインのメイン処理。

    Args:
        date: 対象日付（YYYYMMDD または YYYY-MM-DD）。
        sport: 対象スポーツ（"keirin" or "kyotei"）。
        dry_run: True の場合 fixture からデータを読み込み API 呼び出しをスキップ。
        config_path: 設定ファイルのパス。
        max_races: 処理するレースの最大数（0 以下で無制限）。
        save_fixture: True の場合、スクレイピング結果を data/fixtures/ に保存。
    """
    date = date.replace("-", "")

    # KEIRIN_MOCK_MODE 確認（環境変数で制御）
    mock_mode = os.environ.get("KEIRIN_MOCK_MODE", "0") == "1"

    # 設定・ログ初期化
    config = load_settings(config_path)
    setup_logging(config)
    logger.info("=== 競輪・競艇予想パイプライン 開始 ===")
    if mock_mode:
        logger.info("[MOCK MODE] KEIRIN_MOCK_MODE=1 が設定されています。APIキーなしでデモ動作します。")
    logger.info(
        "sport=%s / date=%s / dry_run=%s / mock_mode=%s / save_fixture=%s / max_races=%d / config=%s",
        sport, date, dry_run, mock_mode, save_fixture, max_races, config_path,
    )

    # 出力ディレクトリ
    output_dir = (
        ROOT / config.get("pipeline", {}).get("output_dir", "output") / date
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    # プロファイル読み込み（BUG-6: sport に対応したプロファイルを選択）
    cre_profile_path = config.get("pipeline", {}).get("cre_profile_path")
    if cre_profile_path and sport in str(cre_profile_path):
        # sport と一致するパスならそのまま使用
        # 例: sport=keirin かつ cre_profile_path に "keirin" が含まれる場合
        profile_file = ROOT / cre_profile_path
        if profile_file.exists():
            with open(profile_file, encoding="utf-8") as f:
                profile: Dict[str, Any] = yaml.safe_load(f) or {}
            logger.info("CRE プロファイル読み込み完了: %s", profile_file)
        else:
            logger.warning("CRE プロファイルが見つかりません: %s", profile_file)
            profile = {"predictor_name": "mr_t_default", "profile_id": "mr_t"}
    else:
        # cre_profile_path が未設定 or sport と不一致のパス（例: kyotei実行時に keirin パスが設定されている）
        # → sport 別プロファイルディレクトリから自動選択
        if cre_profile_path:
            logger.info(
                "cre_profile_path(%s) が sport=%s と不一致のため、sport 別ディレクトリを使用します。",
                cre_profile_path, sport,
            )
        profile_dir = ROOT / f"config/{sport}/profiles"
        loader = ProfileLoader(str(profile_dir))
        available = loader.list_profiles() if hasattr(loader, "list_profiles") else []
        profile_id = available[0] if available else "mr_t"
        profile = loader.load_or_default(
            profile_id,
            default={"predictor_name": f"{sport}_default", "profile_id": profile_id},
        )
        logger.info(
            "sport=%s プロファイルディレクトリから選択: profile_id=%s（ディレクトリ: %s）",
            sport, profile_id, profile_dir,
        )
    logger.info("予想師プロファイル: %s", profile.get("predictor_name", "unknown"))

    # フィルターエンジン初期化（sport 引数は足軽2の filter_engine.py 更新と連携）
    config_dir = config.get("pipeline", {}).get("config_dir", "config")
    filters_path = ROOT / config_dir / sport / "filters.yaml"
    filter_engine = FilterEngine(str(filters_path), sport=sport)

    # レース取得
    logger.info("レーススケジュール取得中... (%s)", date)
    try:
        races = fetch_races(sport, date, config, dry_run=dry_run, save_fixture=save_fixture)
    except Exception as e:
        logger.error("レース取得エラー: %s", e)
        races = []

    if not races:
        logger.warning("対象レースが0件でした。")
        return

    logger.info("取得レース数: %d", len(races))

    # max_races 制限
    if max_races > 0:
        races = races[:max_races]
        logger.info("max_races=%d 制限適用: %d 件に絞りました", max_races, len(races))

    # 各レース処理（1 レース失敗時も継続）
    results = []
    for race in races:
        try:
            result = process_race(race, filter_engine, profile, config, dry_run=dry_run, mock_mode=mock_mode)
            results.append(result)
            saved_path = save_race_result(result, output_dir, sport)
            logger.info("保存: %s", saved_path)
        except Exception as e:
            venue = race.get("venue_name", "?")
            race_no = race.get("race_no", "?")
            logger.error("[エラー] %s %sR の処理に失敗しました: %s", venue, race_no, e)

    if not results:
        logger.warning("処理結果が0件でした。")
        return

    # 統計ログ
    passed = [r for r in results if r.get("bet", {}).get("bet_type") != "skip"]
    logger.info("フィルター通過レース: %d / %d", len(passed), len(results))
    total_investment = sum(
        r.get("bet", {}).get("total_investment", 0)
        for r in passed
    )
    logger.info("合計投資額: %d 円", total_investment)

    # F8全除外警告: 全レースがF8で除外された場合はアラート（cmd_144k_sub4）
    if results and not passed:
        f8_excluded = [
            r for r in results
            if any(
                "F8" in reason
                for reason in r.get("bet", {}).get("reason", "").split("; ")
            )
        ]
        if f8_excluded:
            filter_engine_threshold = filter_engine.filters.get(
                "expected_payout_min", 20_000
            )
            logger.warning(
                "[F8全除外警告] 全%d件がF8(期待配当<%.0f円)で除外されました。"
                " F8閾値の引き下げまたはF8無効化を検討してください。",
                len(f8_excluded), filter_engine_threshold,
            )

    # バッチ形式のサマリー Markdown を保存
    batch = format_batch(
        results,
        meta={"sport": sport, "date": date, "dry_run": dry_run},
    )
    summary_text = batch_to_text_summary(batch)
    summary_path = output_dir / "summary.md"
    summary_path.write_text(summary_text, encoding="utf-8")
    logger.info("サマリー保存: %s", summary_path)

    # コンソール出力
    print(summary_text)
    logger.info("=== パイプライン完了 ===")


# ─────────────────────────────────────────────────────────
# CLI エントリーポイント
# ─────────────────────────────────────────────────────────


def main() -> None:
    """コマンドライン引数を解析して run() を呼び出すエントリーポイント。"""
    parser = argparse.ArgumentParser(
        description="競輪・競艇予想パイプライン 統合実行スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用例:\n"
            "  python main.py --date 20260224\n"
            "  python main.py --date 20260224 --sport keirin --dry-run\n"
            "  python main.py --date 20260224 --config config/settings.yaml --max-races 3\n"
            "  python main.py --date 20260224 --sport keirin --save-fixture\n"
        ),
    )
    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYYMMDD",
        help="処理対象日（必須）",
    )
    parser.add_argument(
        "--sport",
        choices=["keirin", "kyotei"],
        default="keirin",
        help="対象スポーツ（デフォルト: keirin）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fixture からデータ読み込み・API 呼び出しをスキップするテストモード",
    )
    parser.add_argument(
        "--save-fixture",
        action="store_true",
        help="スクレイピング結果を data/fixtures/{sport}_{date}.json に保存する",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        metavar="PATH",
        help="設定ファイルパス（デフォルト: config/settings.yaml）",
    )
    parser.add_argument(
        "--max-races",
        type=int,
        default=6,
        metavar="N",
        help="処理するレースの最大数（デフォルト: 6）",
    )

    args = parser.parse_args()
    run(
        date=args.date,
        sport=args.sport,
        dry_run=args.dry_run,
        config_path=args.config,
        max_races=args.max_races,
        save_fixture=args.save_fixture,
    )


if __name__ == "__main__":
    main()
