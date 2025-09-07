# tests/test_snapshot.py
# -*- coding: utf-8 -*-
import os, json, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

GOLDEN = os.path.join(ROOT, "tests", "golden", "demo_estimate.snapshot.json")

def test_snapshot_exists():
    assert os.path.exists(GOLDEN), "Golden snapshot is missing. Run scripts/generate_golden.py first."

def test_snapshot_shape_and_values():
    with open(GOLDEN, "r", encoding="utf-8") as f:
        snap = json.load(f)
    # 最低限の安定項目を厳しめにチェック
    assert isinstance(snap.get("item_count"), int) and snap["item_count"] > 0
    assert isinstance(snap.get("items"), list) and len(snap["items"]) == snap["item_count"]
    # 各行のキー存在と型
    for it in snap["items"]:
        for k in ["desc", "amount", "decision"]:
            assert k in it
        assert it["decision"] in (None, "asset", "expense", "review", "error", "OPEX", "CAPEX")