#!/usr/bin/env python3
"""
Stage 2 自動化スクリプト — CRE統合 predictor.py による予測テキスト生成
=======================================================================

predictor.py の generate_prediction() を活用して CRE プロファイルを注入した
予想テキストを自動生成する。

queue/predictions/requests/ の未処理リクエストYAMLを読み込み、
generate_prediction() で予測テキストを生成して
queue/predictions/results/ に結果YAMLを書き込む。

使い方:
    python scripts/stage2_haiku.py               # 全pending処理
    python scripts/stage2_haiku.py --dry-run     # API呼び出しなし（動作確認のみ）
    python scripts/stage2_haiku.py --limit 5     # 最大5件処理
"""

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQ_DIR = ROOT / "queue" / "predictions" / "requests"
RES_DIR = ROOT / "queue" / "predictions" / "results"

# src/ を import パスに追加
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# .env から環境変数をロード（cronはホーム環境変数を読まないため）
ENV_FILE = ROOT / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value and key not in os.environ:
                    os.environ[key] = value

from src.predictor import generate_prediction  # noqa: E402


def _parse_axis_partners(prediction_text: str) -> tuple[int | None, list[int]]:
    """予測テキストから軸番号と相手番号リストを抽出する（dedup済み）。"""
    axis: int | None = None
    partners: list[int] = []

    axis_match = re.search(r"(?:軸|本命)[：:]\s*(\d+)番?", prediction_text)
    if axis_match:
        axis = int(axis_match.group(1))
        partner_match = re.search(
            r"(?:軸相手|相手)[：:](.*?)(?:\n|買い目|$)",
            prediction_text,
            re.DOTALL,
        )
        if partner_match:
            raw = [int(n) for n in re.findall(r"\d+", partner_match.group(1))]
            seen_p: set[int] = set()
            for p in raw:
                if p != axis and p not in seen_p:
                    partners.append(p)
                    seen_p.add(p)
            partners = partners[:4]
    else:
        nums = re.findall(r"\b([1-7])\b", prediction_text)
        if len(nums) >= 2:
            axis = int(nums[0])
            seen_f: set[int] = {axis}
            for n in nums[1:5]:
                v = int(n)
                if v not in seen_f:
                    partners.append(v)
                    seen_f.add(v)

    return axis, partners


def get_pending_requests(limit: int = 0) -> list:
    """未処理（results/に対応ファイルなし）のリクエストYAMLを返す。"""
    if not REQ_DIR.exists():
        return []
    result = []
    for req_file in sorted(REQ_DIR.glob("*.yaml")):
        task_id = req_file.stem
        res_file = RES_DIR / f"{task_id}.yaml"
        if not res_file.exists():
            req = yaml.safe_load(req_file.read_text(encoding="utf-8"))
            result.append((task_id, req, req_file))
        if limit > 0 and len(result) >= limit:
            break
    return result


def process_request(task_id: str, req: dict, config: dict, dry_run: bool = False) -> bool:
    """1件のリクエストを処理して結果YAMLを書き出す。"""
    filter_type = req.get("filter_type", "A")
    sport = req.get("sport", "keirin")

    print(f"\n  処理中: {task_id}")
    print(f"  開催: {req.get('venue')} {req.get('race_no')}R  [{filter_type}型]")

    if dry_run:
        print(f"  [DRY RUN] API呼び出しをスキップします。")
        return True

    try:
        prediction_text = generate_prediction(
            race_data=req,
            predictor_profile={},
            config=config,
            filter_type=filter_type if filter_type in ("A", "B", "C") else "A",
            sport=sport,
        )
    except Exception as e:
        print(f"  [ERROR] 予測生成エラー: {e}")
        return False

    preview = prediction_text[:100].replace("\n", " ")
    print(f"  予測: {preview}...")

    axis, partners = _parse_axis_partners(prediction_text)

    RES_DIR.mkdir(parents=True, exist_ok=True)
    res_file = RES_DIR / f"{task_id}.yaml"

    result = {
        "task_id": task_id,
        "status": "done",
        "timestamp": datetime.now().isoformat(),
        "model_used": config.get("llm", {}).get("model", "unknown"),
        "sport": sport,
        "venue": req.get("venue", ""),
        "race_no": req.get("race_no", ""),
        "filter_type": filter_type,
        "prediction_text": prediction_text,
        "axis": axis,
        "partners": partners,
    }
    res_file.write_text(
        yaml.dump(result, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"  ✅ 保存: {res_file.name}")
    return True


def _load_config() -> dict:
    """config/settings.yaml を読み込み、パスを ROOT 基準で絶対化して返す。"""
    settings_path = ROOT / "config" / "settings.yaml"
    config: dict = {}
    if settings_path.exists():
        config = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}

    # 相対パスを ROOT 基準で絶対化
    pipeline = config.setdefault("pipeline", {})
    for key in ("cre_profile_path", "config_dir"):
        val = pipeline.get(key, "")
        if val and not Path(val).is_absolute():
            pipeline[key] = str(ROOT / val)

    return config


def main():
    parser = argparse.ArgumentParser(
        description="Stage 2 自動化 — CRE統合 predictor.py で予測テキスト生成"
    )
    parser.add_argument("--dry-run", action="store_true", help="API呼び出しをスキップ（動作確認のみ）")
    parser.add_argument("--limit", type=int, default=0, help="処理件数上限（0=無制限）")
    args = parser.parse_args()

    config = _load_config()

    if args.dry_run:
        config["dry_run"] = True

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key and not args.dry_run:
        print("警告: ANTHROPIC_API_KEY が設定されていません。")
        print("  code_agent IPC モード（足軽手動）にフォールバックします。")

    pending = get_pending_requests(limit=args.limit)

    if not pending:
        print("未処理のリクエストはありません。")
        print("先に Stage 1 を実行してください:")
        print("  python scripts/ashigaru_predict.py --date $(date +%Y%m%d) --stage 1")
        return

    print(f"{'='*60}")
    print(f"  Stage 2 CRE統合 自動実行 ({len(pending)}件)")
    if args.dry_run:
        print(f"  [DRY RUN モード — API呼び出しなし]")
    else:
        print(f"  モデル: {config.get('llm', {}).get('model', '?')}")
    print(f"{'='*60}")

    success = 0
    for task_id, req, req_file in pending:
        if process_request(task_id, req, config, dry_run=args.dry_run):
            success += 1

    print(f"\n{'='*60}")
    print(f"  完了: {success}/{len(pending)}件成功")
    print(f"{'='*60}")

    if success > 0 and not args.dry_run:
        print(f"\n次のステップ: Stage 3 で bet 計算を実行")
        print(f"  python scripts/ashigaru_predict.py --date $(date +%Y%m%d) --stage 3")


if __name__ == "__main__":
    main()
