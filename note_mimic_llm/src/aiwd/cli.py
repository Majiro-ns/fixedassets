from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Dict

from .config import load_config, ensure_dir
from .extract import iter_target_files, extract_text
from .featurize import compute_features
from .detector import try_hf_probs
from .ensemble import ensemble_lite, ensemble_full
from .io import write_csv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aiwd", description="AI文章検出（感度優先）ツール")
    p.add_argument("target", nargs="?", help="解析対象フォルダ")
    p.add_argument("--out", dest="out", default=None, help="出力CSVのパス（既定: 対象フォルダ直下 ai_detect_result.csv）")
    p.add_argument("--encoding", choices=["shift_jis", "utf-8-sig"], default="shift_jis", help="CSV文字コード")
    p.add_argument("--full", action="store_true", help="HF 検出器を使用（初回のみモデル取得）")
    p.add_argument("--thresholds", nargs=2, type=float, metavar=("HI", "MID"), help="判定しきい値（AI_LIKE, GREY）")
    p.add_argument("--max-chunks", type=int, default=40, help="HF推論の最大チャンク数")
    p.add_argument("--quiet", action="store_true", help="ログ最小化")
    p.add_argument("--version", action="store_true", help="バージョン表示")
    return p


def main(argv: List[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print("aiwd 1.0.0")
        return 0

    if not args.target:
        print("フォルダパスを指定してください（GUI起動は exe から）")
        return 2

    cfg = load_config(None)
    thresholds = {
        "hi": args.thresholds[0] if args.thresholds else float(cfg["thresholds"]["hi"]),
        "mid": args.thresholds[1] if args.thresholds else float(cfg["thresholds"]["mid"]),
    }

    lite_w = cfg["weights"]["lite"]
    full_w = cfg["weights"]["full"]

    target_dir = Path(args.target)
    if not target_dir.exists() or not target_dir.is_dir():
        print("そのフォルダは存在しません。")
        return 2

    out_path = Path(args.out) if args.out else target_dir / "ai_detect_result.csv"
    enc = "cp932" if args.encoding == "shift_jis" else "utf-8-sig"
    log_dir = target_dir / "logs"
    ensure_dir(log_dir.as_posix())
    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        handlers=[
            logging.FileHandler(log_dir / "aiwd-errors.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        format="%(asctime)s %(levelname)s %(message)s",
    )

    files = iter_target_files(target_dir)
    if not files:
        print("対象ファイルが見つかりません（pdf/docx/txt）。")
        return 0

    rows: List[Dict[str, object]] = []
    ok = 0
    skipped = 0
    failed = 0
    for i, f in enumerate(files, 1):
        try:
            text, err = extract_text(f)
            if err:
                logging.warning("%s: %s", f, err)
            feats = compute_features(text)

            clf_mean = None
            clf_max = None
            if args.full and len(text) >= 10:
                m, x, _ = try_hf_probs(text)
                clf_mean, clf_max = m, x

            if args.full:
                score, decision = ensemble_full(feats, clf_mean, clf_max, lite_w, full_w, thresholds)
            else:
                score, decision = ensemble_lite(feats, lite_w, thresholds)

            row = {
                "filename": str(f.relative_to(target_dir)),
                "length_chars": int(feats["length_chars"]),
                "clf_ai_prob_mean": None if clf_mean is None else float(clf_mean),
                "clf_ai_prob_max": None if clf_max is None else float(clf_max),
                "ttr": round(1.0 - feats["ttr_ai"], 6),  # original TTR
                "avg_sentence_len": round(feats["avg_sentence_len"], 6),
                "connective_rate": round(feats["connective_rate"], 6),
                "trigram_repeat_ratio": round(feats["trigram_repeat_ratio"], 6),
                "rhythm_variance": round(feats["rhythm_variance"], 6),
                "abstract_rate": round(feats["abstract_rate"], 6),
                "punct_density": round(feats["punct_density"], 6),
                "ensemble_score": round(score, 6),
                "decision": decision,
            }
            rows.append(row)
            if decision == "INSUFFICIENT_TEXT":
                skipped += 1
            else:
                ok += 1
        except Exception as e:
            logging.exception("処理失敗: %s", f)
            failed += 1

    write_csv(rows, out_path, encoding=enc)
    print(json.dumps({
        "success": ok,
        "skipped": skipped,
        "failed": failed,
        "out": out_path.as_posix(),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
