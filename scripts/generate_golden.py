# scripts/generate_golden.py
# -*- coding: utf-8 -*-
import os, json, datetime, sys
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "fixed_asset_classifier"))

load_dotenv()  # .env 読み込み
os.environ.setdefault("ANALYZER_VERSION", "v2")  # v2で固定

from fixed_asset_classifier.main import run_analysis  # 正準の入口

PDF_PATH = os.path.join(ROOT, "fixed_asset_classifier", "input_pdfs", "demo_estimate.pdf")
OUT_RAW = os.path.join(ROOT, "tests", "golden", "demo_estimate.raw.json")
OUT_SNAP = os.path.join(ROOT, "tests", "golden", "demo_estimate.snapshot.json")

def to_snapshot(parsed: dict):
    """非決定要素を落として比較に耐えるスナップショットだけに圧縮"""
    items = []
    for it in parsed.get("line_items", []) or []:
        cls = (it.get("classification") or {})
        items.append({
            "desc": (it.get("description") or "").strip(),
            "amount": it.get("amount"),
            "decision": cls.get("decision"),
            "final_node_id": cls.get("final_node_id"),
            # 将来: 耐用年数レイヤを入れるなら ↓ を埋める
            "useful_life_years": (it.get("useful_life") or {}).get("years"),
            "useful_life_code": (it.get("useful_life") or {}).get("code"),
        })
    return {
        "total_amount": parsed.get("total_amount"),
        "item_count": len(items),
        "items": items,
    }

def main():
    if not os.path.exists(PDF_PATH):
        raise FileNotFoundError(f"PDF not found: {PDF_PATH}")

    print(f"[generate_golden] ANALYZER_VERSION={os.getenv('ANALYZER_VERSION')}")
    parsed = run_analysis(pdf_path=PDF_PATH, use_temp_input=False, is_sme=True)

    # 1) 生の結果（デバッグ/回帰調査用）
    with open(OUT_RAW, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2, sort_keys=True)

    # 2) スナップショット（安定比較用）
    snap = to_snapshot(parsed)
    with open(OUT_SNAP, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"[generate_golden] wrote:\n  - {OUT_RAW}\n  - {OUT_SNAP}")

if __name__ == "__main__":
    main()