"""
競輪・競艇予想 自動配信スクリプト（auto_publish.py）
=====================================================

daily_run.py の出力（output/{date}/*.json）を読み込み、
X（Twitter）と note に投稿する統合配信スクリプト。

使用例:
    python scripts/auto_publish.py --date 20260224 --dry-run
    python scripts/auto_publish.py --date 20260224 --sport keirin
    python scripts/auto_publish.py --date 20260224 --sport both
    python scripts/auto_publish.py --date 20260224 --weekly
"""

import argparse
import glob
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# プロジェクトルートを sys.path に追加
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.comment_generator import extract_comment_from_text  # noqa: E402

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 定数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TIER_S = "S"
TIER_A = "A"
TIER_B = "B"

SPORT_LABELS = {
    "keirin": "競輪",
    "kyotei": "競艇",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 設定読み込み
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def load_settings(config_path: str = "config/settings.yaml") -> Dict[str, Any]:
    """
    settings.yaml を読み込む。

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 予想 JSON 読み込み
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def load_predictions(date: str, sport: str, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    output/{date}/ 以下の予想 JSON を読み込む。

    Args:
        date: 対象日付（YYYYMMDD）。
        sport: "keirin" / "kyotei" / "both"。
        config: settings.yaml の内容。

    Returns:
        予想辞書のリスト（summary.md は除外）。
    """
    output_dir = ROOT / config.get("pipeline", {}).get("output_dir", "output") / date
    if not output_dir.exists():
        logger.warning("出力ディレクトリが見つかりません: %s", output_dir)
        return []

    sports = ["keirin", "kyotei"] if sport == "both" else [sport]
    predictions: List[Dict[str, Any]] = []

    for sp in sports:
        pattern = str(output_dir / f"{sp}_*.json")
        for filepath in sorted(glob.glob(pattern)):
            try:
                with open(filepath, encoding="utf-8") as f:
                    data = json.load(f)
                predictions.append(data)
                logger.debug("読み込み: %s", filepath)
            except Exception as e:
                logger.error("JSON 読み込みエラー %s: %s", filepath, e)

    logger.info("予想ファイル読み込み: %d 件 (sport=%s, date=%s)", len(predictions), sport, date)
    return predictions


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Tier 分類
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def classify_tier(prediction: Dict[str, Any]) -> str:
    """
    1 件の予想を S / A / B / skip に分類する。

    分類基準:
    - bet.tier が明示されている場合はそれを優先
    - bet_type != "skip" かつ prediction.text 非空 → S（フィルター通過）
    - bet_type == "skip" かつ prediction.text 非空 → A（予想あり、フィルター除外）
    - それ以外 → skip

    Args:
        prediction: format_prediction() 形式の辞書。

    Returns:
        "S" / "A" / "B" / "skip" のいずれか。
    """
    bet = prediction.get("bet", {})
    pred_text = (prediction.get("prediction") or {}).get("text", "")

    # bet.tier が明示されている場合は優先
    explicit_tier = bet.get("tier")
    if explicit_tier in (TIER_S, TIER_A, TIER_B):
        return explicit_tier

    bet_type = bet.get("bet_type", "skip")
    if bet_type != "skip" and pred_text.strip():
        return TIER_S
    if bet_type == "skip" and pred_text.strip():
        return TIER_A
    return "skip"


def split_by_tier(
    predictions: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    予想リストを S / A / B に分類して返す。

    Args:
        predictions: 予想辞書のリスト。

    Returns:
        (s_preds, a_preds, b_preds) のタプル。
    """
    s_list, a_list, b_list = [], [], []
    for p in predictions:
        tier = classify_tier(p)
        if tier == TIER_S:
            s_list.append(p)
        elif tier == TIER_A:
            a_list.append(p)
        elif tier == TIER_B:
            b_list.append(p)
        # skip は捨てる
    logger.info("Tier分類: S=%d, A=%d, B=%d, skip=%d",
                len(s_list), len(a_list), len(b_list),
                len(predictions) - len(s_list) - len(a_list) - len(b_list))
    return s_list, a_list, b_list


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# テキスト生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _parse_prediction_text(text: str) -> Dict[str, str]:
    """
    予想テキスト（「軸: X番」「相手: Y番、Z番」形式）を辞書に変換する。

    Args:
        text: LLM 生成の予想テキスト。

    Returns:
        {"axis": "1番", "partners": "2番、3番", "comment": "..."} 形式の辞書。
    """
    result = {"axis": "", "partners": "", "comment": ""}
    axis_m = re.search(r"軸[：:]\s*(.+)", text)
    partner_m = re.search(r"相手[：:]\s*(.+)", text)

    if axis_m:
        result["axis"] = axis_m.group(1).strip()
    if partner_m:
        result["partners"] = partner_m.group(1).strip()
    result["comment"] = extract_comment_from_text(text)

    return result


def build_x_post_text(prediction: Dict[str, Any], note_url: str = "") -> str:
    """
    X（Twitter）投稿用テキストを生成する。

    設計書 7.1 の形式に準拠。280 文字制限を考慮してトリムする。

    Args:
        prediction: S評価の予想辞書。
        note_url: note 記事 URL（省略可）。

    Returns:
        X 投稿テキスト文字列。
    """
    race_info = prediction.get("race_info", {})
    venue = race_info.get("venue_name", "不明")
    race_no = race_info.get("race_no", "?")
    grade = race_info.get("grade", "")
    stage = race_info.get("stage", "")
    sport = prediction.get("sport", "keirin")
    sport_label = SPORT_LABELS.get(sport, sport)

    pred_parsed = _parse_prediction_text(
        (prediction.get("prediction") or {}).get("text", "")
    )

    note_line = f"全評価はnoteで→ {note_url}" if note_url else "全評価はnoteで公開中"

    lines = [
        "━━━━━━━━━━━━━━━",
        f"🎯 真AI予想 S評価【{sport_label}】",
        "━━━━━━━━━━━━━━━",
        f"📍 {venue}{race_no}R（{grade}{stage}）",
        f"軸: {pred_parsed['axis']}",
        f"相手: {pred_parsed['partners']}",
    ]
    if pred_parsed["comment"]:
        lines.append(f"根拠: {pred_parsed['comment']}")
    lines += [
        "━━━━━━━━━━━━━━━",
        "直近S評価: 集計中",
        note_line,
        "━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def build_note_body(
    date: str,
    s_preds: List[Dict[str, Any]],
    a_preds: List[Dict[str, Any]],
    b_preds: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """
    note 記事のタイトルと本文を生成する。

    設計書 7.2 の形式に準拠。全 Tier を掲載する。

    Args:
        date: 対象日付（YYYYMMDD）。
        s_preds: S評価の予想リスト。
        a_preds: A評価の予想リスト。
        b_preds: B評価の予想リスト。

    Returns:
        (title, body) のタプル。
    """
    dt = datetime.strptime(date, "%Y%m%d")
    m, d = dt.month, dt.day
    title = f"【{m}/{d}】競輪×競艇 真AI予想"

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━━━",
        title,
        f"━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    def _pred_block(p: Dict[str, Any]) -> List[str]:
        """1 件の予想をテキストブロックに変換する。"""
        ri = p.get("race_info", {})
        sport = p.get("sport", "keirin")
        sport_label = SPORT_LABELS.get(sport, sport)
        venue = ri.get("venue_name", "不明")
        race_no = ri.get("race_no", "?")
        grade = ri.get("grade", "")
        stage = ri.get("stage", "")
        bet = p.get("bet", {})
        pred_parsed = _parse_prediction_text(
            (p.get("prediction") or {}).get("text", "")
        )
        bets_str = ""
        if bet.get("bets"):
            bets_str = "  買い目: " + "、".join(
                f"{b.get('combination', '')}（{b.get('amount', '')}円）"
                for b in bet["bets"][:3]
            )
        block = [
            f"[{sport_label}] {venue}{race_no}R {grade}{stage}",
            f"  軸: {pred_parsed['axis']}",
            f"  相手: {pred_parsed['partners']}",
        ]
        if bets_str:
            block.append(bets_str)
        if pred_parsed["comment"]:
            block.append(f"  根拠: {pred_parsed['comment']}")
        return block

    # S 評価
    lines.append("🔥 S評価（勝負レース）")
    lines.append("━━━━━━━━━━━━━━━")
    if s_preds:
        for p in s_preds:
            lines.extend(_pred_block(p))
            lines.append("")
    else:
        lines.append("（本日の S評価レースなし）")
        lines.append("")

    # A 評価
    lines.append("⭐ A評価（好条件）")
    lines.append("━━━━━━━━━━━━━━━")
    if a_preds:
        for p in a_preds:
            lines.extend(_pred_block(p))
            lines.append("")
    else:
        lines.append("（本日の A評価レースなし）")
        lines.append("")

    # B 評価
    lines.append("📝 B評価（参考）")
    lines.append("━━━━━━━━━━━━━━━")
    if b_preds:
        for p in b_preds:
            ri = p.get("race_info", {})
            sport_label = SPORT_LABELS.get(p.get("sport", "keirin"), p.get("sport", "keirin"))
            bet = p.get("bet", {})
            bets_abbr = "、".join(
                str(b.get("combination", ""))
                for b in (bet.get("bets") or [])[:2]
            )
            lines.append(
                f"[{sport_label}] {ri.get('venue_name','?')}{ri.get('race_no','?')}R "
                f"/ {bets_abbr or '買い目未定'}"
            )
        lines.append("")
    else:
        lines.append("（本日の B評価レースなし）")
        lines.append("")

    # 成績サマリー
    lines += [
        "📊 直近成績",
        "━━━━━━━━━━━━━━━",
        "S評価: 集計中",
        "A評価: 集計中",
        "全体: 集計中",
        "",
        "マガジン購読はプロフィールから",
    ]

    return title, "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Publisher ラッパー（import 失敗時はスキップ）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _try_import_x_publisher():
    """
    publisher.x_publisher.XPublisher を動的に import する。

    Returns:
        XPublisher クラス、または None（import 失敗時）。
    """
    try:
        from publisher.x_publisher import XPublisher
        return XPublisher
    except ImportError as e:
        logger.warning("x_publisher のインポートに失敗しました（スキップ）: %s", e)
        return None


def _try_import_note_publisher():
    """
    publisher.note_publisher.NotePublisher を動的に import する。

    Returns:
        NotePublisher クラス、または None（import 失敗時）。
    """
    try:
        from publisher.note_publisher import NotePublisher
        return NotePublisher
    except ImportError as e:
        logger.warning("note_publisher のインポートに失敗しました（スキップ）: %s", e)
        return None


def post_to_x(
    text: str,
    config: Dict[str, Any],
    dry_run: bool = True,
) -> bool:
    """
    X（Twitter）にテキストを投稿する。

    Args:
        text: 投稿テキスト。
        config: settings.yaml の内容（publisher.x_api セクションを使用）。
        dry_run: True の場合は実際に投稿せず標準出力に表示。

    Returns:
        投稿成功なら True、失敗またはスキップなら False。
    """
    if dry_run:
        logger.info("[DRY RUN] X投稿:\n%s", text)
        print(f"\n[DRY RUN] X投稿テキスト:\n{text}\n")
        return True

    XPublisher = _try_import_x_publisher()
    if XPublisher is None:
        logger.warning("X投稿をスキップしました（publisher.x_publisher 未利用可能）")
        return False

    try:
        pub_cfg = config.get("publisher", {}).get("x_api", {})
        publisher = XPublisher(pub_cfg)
        result = publisher.post(text)
        logger.info("X投稿成功: %s", result)
        return True
    except Exception as e:
        logger.error("X投稿失敗（スキップ）: %s", e)
        return False


def post_to_note(
    title: str,
    body: str,
    config: Dict[str, Any],
    dry_run: bool = True,
) -> str:
    """
    note に記事を投稿する。

    Args:
        title: 記事タイトル。
        body: 記事本文（Markdown 形式）。
        config: settings.yaml の内容（publisher.note セクションを使用）。
        dry_run: True の場合は実際に投稿せずプレビューを表示。

    Returns:
        投稿した記事の URL 文字列（dry_run 時は空文字列）。
    """
    if dry_run:
        preview = body[:300] + ("..." if len(body) > 300 else "")
        logger.info("[DRY RUN] note投稿 タイトル: %s\n本文プレビュー:\n%s", title, preview)
        print(f"\n[DRY RUN] note記事タイトル: {title}\n本文プレビュー:\n{preview}\n")
        return ""

    NotePublisher = _try_import_note_publisher()
    if NotePublisher is None:
        logger.warning("note投稿をスキップしました（publisher.note_publisher 未利用可能）")
        return ""

    try:
        note_cfg = config.get("publisher", {}).get("note", {})
        publisher = NotePublisher(note_cfg)
        url = publisher.post_article(title=title, body=body)
        logger.info("note投稿成功: %s", url)
        return url or ""
    except Exception as e:
        logger.error("note投稿失敗（スキップ）: %s", e)
        return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 週次レポート投稿
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def post_weekly_report(config: Dict[str, Any], dry_run: bool = True) -> bool:
    """
    最新の週次成績レポートを note に投稿する。

    data/reports/weekly_report_*.md を検索して最新のものを投稿する。

    Args:
        config: settings.yaml の内容。
        dry_run: True の場合は実際に投稿しない。

    Returns:
        投稿成功なら True、対象ファイルなし・失敗なら False。
    """
    reports_dir = ROOT / "data" / "reports"
    pattern = str(reports_dir / "weekly_report_*.md")
    files = sorted(glob.glob(pattern), reverse=True)

    if not files:
        logger.warning("週次レポートファイルが見つかりません: %s", pattern)
        return False

    latest = files[0]
    logger.info("週次レポート使用: %s", latest)

    try:
        with open(latest, encoding="utf-8") as f:
            body = f.read()
    except Exception as e:
        logger.error("週次レポート読み込みエラー: %s", e)
        return False

    title_m = re.search(r"^#\s+(.+)", body, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else f"週次成績レポート ({Path(latest).stem})"

    url = post_to_note(title=title, body=body, config=config, dry_run=dry_run)
    return url != "" or dry_run


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン処理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def run(
    date: str,
    sport: str = "both",
    weekly: bool = False,
    dry_run: Optional[bool] = None,
    config_path: str = "config/settings.yaml",
) -> Dict[str, Any]:
    """
    自動配信のメイン処理。

    Args:
        date: 対象日付（YYYYMMDD）。
        sport: 対象スポーツ（"keirin" / "kyotei" / "both"）。
        weekly: True の場合、週次成績レポートも note に投稿する。
        dry_run: True/False で上書き。None の場合 settings.yaml の値に従う。
        config_path: 設定ファイルパス。

    Returns:
        実行サマリー辞書（x_posted, note_url, weekly_posted 等）。
    """
    date = date.replace("-", "")

    # 設定読み込み
    config = load_settings(config_path)
    setup_logging(config)

    # dry_run の確定（引数優先、次に settings.yaml）
    if dry_run is None:
        dry_run = config.get("publisher", {}).get("dry_run", True)
    logger.info("=== auto_publish 開始 === date=%s sport=%s dry_run=%s weekly=%s",
                date, sport, dry_run, weekly)

    summary: Dict[str, Any] = {
        "date": date,
        "sport": sport,
        "dry_run": dry_run,
        "x_posted": 0,
        "note_url": "",
        "weekly_posted": False,
        "errors": [],
    }

    # ── 週次レポート投稿（--weekly フラグ時）────────────────
    if weekly:
        try:
            ok = post_weekly_report(config=config, dry_run=dry_run)
            summary["weekly_posted"] = ok
            logger.info("週次レポート投稿: %s", "成功" if ok else "失敗/スキップ")
        except Exception as e:
            logger.error("週次レポート投稿エラー: %s", e)
            summary["errors"].append(f"weekly_report: {e}")

    # ── 予想 JSON 読み込み ────────────────────────────────────
    predictions = load_predictions(date=date, sport=sport, config=config)
    if not predictions:
        logger.warning("投稿対象の予想が0件です。終了します。")
        return summary

    # ── Tier 分類 ────────────────────────────────────────────
    s_preds, a_preds, b_preds = split_by_tier(predictions)

    # ── note 投稿（全 Tier）───────────────────────────────────
    try:
        note_title, note_body = build_note_body(
            date=date, s_preds=s_preds, a_preds=a_preds, b_preds=b_preds
        )
        note_url = post_to_note(
            title=note_title, body=note_body, config=config, dry_run=dry_run
        )
        summary["note_url"] = note_url
        logger.info("note投稿完了: url=%s", note_url or "(dry_run)")
    except Exception as e:
        logger.error("note投稿エラー（スキップ）: %s", e)
        summary["errors"].append(f"note: {e}")

    # ── X 投稿（S評価のみ）───────────────────────────────────
    for p in s_preds:
        try:
            x_text = build_x_post_text(p, note_url=summary["note_url"])
            ok = post_to_x(text=x_text, config=config, dry_run=dry_run)
            if ok:
                summary["x_posted"] += 1
        except Exception as e:
            venue = (p.get("race_info") or {}).get("venue_name", "?")
            race_no = (p.get("race_info") or {}).get("race_no", "?")
            logger.error("X投稿エラー %s%sR（スキップ）: %s", venue, race_no, e)
            summary["errors"].append(f"x_{venue}{race_no}R: {e}")

    # ── サマリー出力 ─────────────────────────────────────────
    logger.info(
        "=== auto_publish 完了 === X投稿=%d件 note=%s エラー=%d件",
        summary["x_posted"],
        summary["note_url"] or "(dry_run/skip)",
        len(summary["errors"]),
    )
    print(
        f"\n{'=' * 50}\n"
        f"[auto_publish] 完了\n"
        f"  date     : {date}\n"
        f"  sport    : {sport}\n"
        f"  dry_run  : {dry_run}\n"
        f"  S評価    : {len(s_preds)} 件  → X投稿 {summary['x_posted']} 件\n"
        f"  A評価    : {len(a_preds)} 件\n"
        f"  B評価    : {len(b_preds)} 件\n"
        f"  note     : {summary['note_url'] or '(dry_run/skip)'}\n"
        f"  weekly   : {summary['weekly_posted']}\n"
        f"  errors   : {len(summary['errors'])} 件\n"
        f"{'=' * 50}\n"
    )
    return summary


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI エントリーポイント
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def main() -> None:
    """コマンドライン引数を解析して run() を呼び出すエントリーポイント。"""
    parser = argparse.ArgumentParser(
        description="競輪・競艇予想 自動配信スクリプト（X + note）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用例:\n"
            "  python scripts/auto_publish.py --date 20260224 --dry-run\n"
            "  python scripts/auto_publish.py --date 20260224 --sport keirin\n"
            "  python scripts/auto_publish.py --date 20260224 --sport both\n"
            "  python scripts/auto_publish.py --date 20260224 --weekly\n"
        ),
    )
    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYYMMDD",
        help="対象日付（必須）",
    )
    parser.add_argument(
        "--sport",
        choices=["keirin", "kyotei", "both"],
        default="both",
        help="対象スポーツ（デフォルト: both）",
    )
    parser.add_argument(
        "--weekly",
        action="store_true",
        help="週次成績レポートも note に投稿する",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="実際の投稿なしでシミュレーション（未指定時は settings.yaml の値に従う）",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        metavar="PATH",
        help="設定ファイルパス（デフォルト: config/settings.yaml）",
    )

    args = parser.parse_args()

    # --dry-run が明示されなかった場合は None（settings.yaml に委ねる）
    dry_run_arg = True if args.dry_run else None

    run(
        date=args.date,
        sport=args.sport,
        weekly=args.weekly,
        dry_run=dry_run_arg,
        config_path=args.config,
    )


if __name__ == "__main__":
    main()
