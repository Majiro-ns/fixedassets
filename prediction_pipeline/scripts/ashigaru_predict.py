#!/usr/bin/env python3
"""
足軽予測スクリプト — 2段階パイプライン
======================================

Stage 1: レース取得 + フィルター + リクエストYAML生成（main.pyのdry-run相当）
Stage 2: 足軽（Claude Code）がリクエストを読み、予測結果YAMLを書き出す
Stage 3: 結果を集約してbet計算 + 出力JSON生成

使い方:
    python scripts/ashigaru_predict.py --date 20260301 --stage 1    # レース取得→リクエスト生成
    python scripts/ashigaru_predict.py --date 20260301 --stage 3    # 結果集約→bet計算→出力

Stage 2（予測生成）は足軽がqueue/predictions/requests/*.yamlを読んで
手動（Claude Codeの推論で）予測テキストを生成し、
queue/predictions/results/*.yamlに書き込む。
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.filter_engine import FilterEngine
from src.formatter import format_batch, batch_to_text_summary, format_prediction, save_prediction
from src.predictor import load_cre_profile, build_cre_system_prompt, load_prompt_template
from src.predictor import _render_template, _build_system_prompt, _build_user_prompt
from src.kdreams_scraper import KdreamsScraper

REQ_DIR = ROOT / "queue" / "predictions" / "requests"
RES_DIR = ROOT / "queue" / "predictions" / "results"
FIXTURES_DIR = ROOT / "data" / "fixtures"

logger = logging.getLogger(__name__)


def fetch_races_kdreams(date: str) -> list:
    """Kドリームスから全レース（出走表付き）を取得する。"""
    scraper = KdreamsScraper()
    return scraper.fetch_all_races(date)


def stage1_fetch_and_filter(date: str, sport: str, config_path: str, max_races: int) -> None:
    """Stage 1: レース取得 → フィルター適用 → リクエストYAML生成"""
    from main import load_settings, setup_logging, fetch_races

    config = load_settings(config_path)
    setup_logging(config)

    logger.info("=== Stage 1: レース取得 + フィルター + リクエスト生成 ===")

    # フィルターエンジン
    config_dir = config.get("pipeline", {}).get("config_dir", "config")
    filters_path = ROOT / config_dir / sport / "filters.yaml"
    filter_engine = FilterEngine(str(filters_path), sport=sport)

    # プロファイル
    cre_profile_path = config.get("pipeline", {}).get("cre_profile_path")
    if cre_profile_path:
        profile_file = ROOT / cre_profile_path
        if profile_file.exists():
            with open(profile_file, encoding="utf-8") as f:
                profile = yaml.safe_load(f) or {}
        else:
            profile = {"predictor_name": "mr_t_default", "profile_id": "mr_t"}
    else:
        profile = {"predictor_name": "mr_t_default", "profile_id": "mr_t"}

    # レース取得（kdreams → keirin.jp → fixture フォールバック）
    logger.info("レース取得中... (sport=%s, date=%s)", sport, date)
    races = []
    if sport == "keirin":
        try:
            logger.info("Kドリームスからスクレイピング中...")
            races = fetch_races_kdreams(date)
            if races:
                logger.info("Kドリームス: %d件取得成功", len(races))
                # fixture保存
                from main import _save_fixture
                _save_fixture(sport, date, races)
        except Exception as e:
            logger.error("Kドリームスエラー: %s", e)

    if not races:
        try:
            races = fetch_races(sport, date, config, dry_run=False, save_fixture=False)
            if races:
                from main import _save_fixture
                _save_fixture(sport, date, races)
            else:
                logger.info("スクレイピング結果0件。fixture からフォールバック読み込みを試みます...")
                races = fetch_races(sport, date, config, dry_run=True, save_fixture=False)
        except Exception as e:
            logger.error("レース取得エラー: %s", e)
            logger.info("fixture からフォールバック読み込みを試みます...")
            races = fetch_races(sport, date, config, dry_run=True, save_fixture=False)

    if not races:
        logger.warning("対象レースが0件。")
        return

    if max_races > 0:
        races = races[:max_races]

    logger.info("取得レース: %d件", len(races))

    # フィルター適用 + リクエスト生成
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    RES_DIR.mkdir(parents=True, exist_ok=True)

    # 日付クリア: 前日以前のYAMLをarchiveに退避
    today = date
    for src_dir in [REQ_DIR, RES_DIR]:
        archive = src_dir.parent / "archive"
        archive.mkdir(exist_ok=True)
        for f in src_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                if data.get("date", today) != today:
                    f.rename(archive / f.name)
                    logger.info("[archive] %s → archive/", f.name)
            except Exception:
                pass

    generated = 0

    for race in races:
        venue = race.get("venue_name", "?")
        race_no = race.get("race_no", "?")
        grade = race.get("grade", "?")
        stage = race.get("stage", "?")

        # フィルター
        passed, reasons = filter_engine.apply(race)
        filter_passed = passed
        filter_reasons = reasons if not passed else []
        if not passed:
            logger.info("[フィルター不合格] %s %sR %s %s: %s", venue, race_no, grade, stage, reasons)

        if passed:
            # 分類
            classification = filter_engine.classify(race)
            filter_type = classification.get("type", "C")
            conf_score = classification.get("confidence", 0)

            # F9拡張: expected_payoutが未設定の場合、confidence_scoreでType上書き
            # (kdreams_scraper は expected_payout を返さないため全レースが Type C になる問題を解消)
            # conf=0 → C（堅実）, conf=1 → A（標準）, conf>=2 → B（穴狙い）
            if race.get("expected_payout") is None:
                if conf_score >= 2:
                    filter_type = "B"
                elif conf_score >= 1:
                    filter_type = "A"
                else:
                    filter_type = "C"
        else:
            filter_type = "none"
            conf_score = 0
            # フィルター非通過レースはrequests/に書き出さない（cmd_136k_sub1）
            logger.info("[SKIP] %s %sR: フィルター非通過 → requests/書き出しをスキップ", venue, race_no)
            continue

        # F10チェック: 除外せず記録のみ
        f10_passed = True
        min_conf = filter_engine.filters.get("min_confidence_score", 0)
        if min_conf > 0 and conf_score < min_conf:
            f10_passed = False
            logger.info("[F10記録] %s %sR conf=%d < %d", venue, race_no, conf_score, min_conf)

        # プロンプト構築
        template = load_prompt_template(config_dir, sport)
        if template is not None:
            if cre_profile_path and filter_type != "none":
                cre_profile = load_cre_profile(str(ROOT / cre_profile_path))
                cre_text = build_cre_system_prompt(cre_profile, filter_type)
            else:
                cre_text = _build_system_prompt(profile)
            race_with_filter = {**race, "_filter_type": filter_type}
            system_prompt, user_prompt = _render_template(template, cre_text, race_with_filter, sport=sport)
        else:
            system_prompt = _build_system_prompt(profile)
            user_prompt = _build_user_prompt(race)

        # リクエストYAML書き出し
        task_id = f"pred_{sport}_{venue}_{race_no}"
        req_file = REQ_DIR / f"{task_id}.yaml"
        request = {
            "task_id": task_id,
            "status": "pending",
            "timestamp": datetime.now().isoformat(),
            "date": date,
            "venue": venue,
            "race_no": race_no,
            "grade": grade,
            "stage": stage,
            "sport": sport,
            "filter_passed": filter_passed,
            "filter_reasons": filter_reasons,
            "f10_passed": f10_passed,
            "filter_type": filter_type,
            "confidence_score": conf_score,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "entries_summary": [
                {
                    "car_no": e.get("car_no"),
                    "name": e.get("name"),
                    "grade": e.get("grade"),
                    "leg_type": e.get("leg_type"),
                }
                for e in race.get("entries", [])
            ],
        }
        req_file.write_text(
            yaml.dump(request, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        generated += 1
        logger.info("[リクエスト生成] %s %sR → %s (filter=%s, conf=%d)",
                     venue, race_no, req_file.name, filter_type, conf_score)

    logger.info("=== Stage 1 完了: %d件のリクエストを生成 ===", generated)
    if generated > 0:
        logger.info("次のステップ: queue/predictions/requests/ のYAMLを読み、予測テキストを生成してください。")
        logger.info("結果は queue/predictions/results/ に書き込んでください。")


def stage3_aggregate(date: str, sport: str, config_path: str) -> None:
    """Stage 3: 結果集約 → bet計算 → 出力JSON"""
    from main import load_settings, setup_logging
    from src.bet_calculator import calc_from_strategy
    import re

    config = load_settings(config_path)
    setup_logging(config)

    logger.info("=== Stage 3: 結果集約 + bet計算 ===")

    # プロファイル
    cre_profile_path = config.get("pipeline", {}).get("cre_profile_path")
    if cre_profile_path:
        profile_file = ROOT / cre_profile_path
        if profile_file.exists():
            with open(profile_file, encoding="utf-8") as f:
                profile = yaml.safe_load(f) or {}
        else:
            profile = {"predictor_name": "mr_t_default", "profile_id": "mr_t"}
    else:
        profile = {"predictor_name": "mr_t_default", "profile_id": "mr_t"}

    output_dir = ROOT / config.get("pipeline", {}).get("output_dir", "output") / date
    output_dir.mkdir(parents=True, exist_ok=True)

    bet_cfg = config.get("betting", {})
    strategy = bet_cfg.get("default_strategy", "sanrenpu_nagashi")

    results = []
    for res_file in sorted(RES_DIR.glob("*.yaml")):
        res = yaml.safe_load(res_file.read_text(encoding="utf-8"))
        if not res or res.get("status") != "done":
            continue

        task_id = res["task_id"]
        prediction_text = res.get("prediction_text", "")

        # 対応するリクエストからレース情報を取得
        req_file = REQ_DIR / f"{task_id}.yaml"
        if not req_file.exists():
            logger.warning("リクエストファイルなし: %s", req_file)
            continue
        req = yaml.safe_load(req_file.read_text(encoding="utf-8"))

        # 構造化データ優先、なければテキストパース
        if res.get("axis") is not None and res.get("partners"):
            axis = res["axis"]
            partners = res["partners"]
        else:
            # フォールバック: 既存の正規表現パース
            axis_match = re.search(r"(?:軸|本命)[：:]\s*(\d+)番?", prediction_text)
            if not axis_match:
                numbers = re.findall(r"\b([1-7])\b", prediction_text)
                if len(numbers) >= 2:
                    axis = int(numbers[0])
                    # deduplication: 同一選手が複数回言及される場合を除去（順序保持）
                    partners = list(dict.fromkeys(
                        [int(n) for n in numbers[1:4] if int(n) != axis]
                    ))
                else:
                    logger.warning("[%s] 軸・相手を解析できず。スキップ。", task_id)
                    continue
            else:
                axis = int(axis_match.group(1))
                partner_match = re.search(r"(?:軸相手|相手)[：:](.*)", prediction_text)
                if partner_match:
                    raw_partners = [int(n) for n in re.findall(r"\d+", partner_match.group(1))]
                    # deduplication: 同一選手が重複登録されるバグ修正（順序保持）
                    partners = list(dict.fromkeys(
                        [p for p in raw_partners if p != axis]
                    ))[:4]
                else:
                    partners = []

        if len(partners) < 2:
            logger.warning("[%s] 相手不足 (%d名)。スキップ。", task_id, len(partners))
            continue

        # bet計算
        try:
            bet_result = calc_from_strategy(strategy, axis, partners, bet_cfg)
        except Exception as e:
            logger.error("[%s] bet計算エラー: %s", task_id, e)
            continue

        # 結果フォーマット
        race_info = {
            "venue_name": req.get("venue", "?"),
            "race_no": req.get("race_no", "?"),
            "grade": req.get("grade", "?"),
            "stage": req.get("stage", "?"),
            "date": req.get("date", date),
            "sport": req.get("sport", sport),
        }

        result = {
            "timestamp": datetime.now().isoformat(),
            "date": date,
            "sport": sport,
            "race_info": race_info,
            "predictor": {
                "name": profile.get("predictor_name", "claude-code-agent"),
                "profile_id": profile.get("profile_id", "code_agent"),
                "model": res.get("model_used", "claude-code-agent"),
            },
            "prediction": {
                "text": prediction_text,
            },
            "bet": bet_result,
            "filter_type": req.get("filter_type", "A"),
            "filter_passed": req.get("filter_passed", True),
        }
        results.append(result)

        # 個別JSON保存
        venue = req.get("venue", "unknown")
        race_no = req.get("race_no", "0")
        out_file = output_dir / f"{sport}_{venue}_{race_no}.json"
        out_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("[保存] %s → 軸:%d 相手:%s 投資:%d円",
                     out_file.name, axis, partners, bet_result.get("total_investment", 0))

    if not results:
        logger.warning("処理結果0件。予測結果YAMLが queue/predictions/results/ にあるか確認してください。")
        return

    # サマリー
    total_investment = sum(r.get("bet", {}).get("total_investment", 0) for r in results)
    logger.info("=== Stage 3 完了: %d件 / 合計投資 %d円 ===", len(results), total_investment)

    summary_lines = [
        f"# 予測サマリー {date} ({sport})",
        f"予測モデル: claude-code-agent",
        f"処理件数: {len(results)}",
        f"合計投資額: {total_investment:,}円",
        "",
    ]
    for r in results:
        ri = r["race_info"]
        b = r["bet"]
        summary_lines.append(
            f"- {ri['venue_name']} {ri['race_no']}R [{r['filter_type']}] "
            f"→ {b.get('display', 'N/A')} ({b.get('total_investment', 0):,}円)"
        )

    summary_path = output_dir / "summary.md"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    logger.info("サマリー: %s", summary_path)
    print("\n".join(summary_lines))


def main():
    parser = argparse.ArgumentParser(description="足軽予測スクリプト（2段階パイプライン）")
    parser.add_argument("--date", required=True, help="対象日 YYYYMMDD")
    parser.add_argument("--sport", default="keirin", choices=["keirin", "kyotei"])
    parser.add_argument("--stage", type=int, required=True, choices=[1, 3],
                        help="1=レース取得+リクエスト生成, 3=結果集約+bet計算")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--max-races", type=int, default=0)
    args = parser.parse_args()

    if args.stage == 1:
        stage1_fetch_and_filter(args.date, args.sport, args.config, args.max_races)
    elif args.stage == 3:
        stage3_aggregate(args.date, args.sport, args.config)


if __name__ == "__main__":
    main()
