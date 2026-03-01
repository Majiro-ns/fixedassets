#!/usr/bin/env python3
"""
m6_law_url_collector.py -- M6 法令URL自動収集スクリプト（草案）

目的: law_entries_human_capital.yaml の source_confirmed: false エントリを
     e-Gov 法令 API で検索し、URL 候補 JSON を出力する（YAML は更新しない）

使い方:
    python3 scripts/m6_law_url_collector.py [--yaml PATH] [--output PATH]

robots.txt 調査結果（2026-02-27）:
    - fsa.go.jp/robots.txt → 404（未公開）→ スクレイピング不実施
    - laws.e-gov.go.jp/robots.txt → HTML（未公開）→ 公式 API のみ使用

e-Gov API 動作確認（2026-02-27）:
    - GET /api/1/lawlists/{1|2|3|4} → HTTP 200 / XML / キー不要 ✅
    - 法令閲覧 URL: https://laws.e-gov.go.jp/law/{LawId}
"""

from __future__ import annotations
import argparse, json, xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
import urllib.request, urllib.error
import yaml

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_YAML = _REPO_ROOT / "10_Research" / "law_entries_human_capital.yaml"
_DEFAULT_OUTPUT = _REPO_ROOT / "10_Research" / "law_url_candidates.json"
_EGOV_BASE = "https://laws.e-gov.go.jp/api/1"
_EGOV_URL = "https://laws.e-gov.go.jp/law/{law_id}"
_CATEGORIES = [2, 3, 4]  # 2=法律 3=政令 4=府令
_ROBOTS_SUMMARY = (
    "fsa.go.jp: robots.txt→404。利用規約確認要、スクレイピング不実施。"
    " laws.e-gov.go.jp: robots.txt→HTML(未公開)。公式API(/api/1/)は政府提供のため利用可。"
)


def _fetch(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "disclosure-multiagent/m6"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8")
    except urllib.error.URLError as e:
        print(f"  [WARN] fetch failed: {url} → {e}")
        return None


def _get_law_list(category: int) -> list[dict]:
    xml_text = _fetch(f"{_EGOV_BASE}/lawlists/{category}")
    if not xml_text:
        return []
    root = ET.fromstring(xml_text)
    if root.findtext(".//Result/Code") != "0":
        return []
    return [
        {"law_id": n.findtext("LawId", ""), "law_name": n.findtext("LawName", "")}
        for n in root.findall(".//LawNameListInfo")
        if n.findtext("LawId") and n.findtext("LawName")
    ]


def _match(law_name: str, laws: list[dict]) -> Optional[dict]:
    """法令名で完全一致→部分一致の順で検索"""
    for law in laws:
        if law["law_name"] == law_name:
            return {**law, "confidence": "high"}
    hits = [l for l in laws if law_name in l["law_name"] or l["law_name"] in law_name]
    if len(hits) == 1:
        return {**hits[0], "confidence": "medium"}
    if hits:
        best = min(hits, key=lambda h: abs(len(h["law_name"]) - len(law_name)))
        return {**best, "confidence": "low"}
    return None


def collect(yaml_path: Path, output_path: Path) -> dict:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    unconfirmed = [e for e in entries if not e.get("source_confirmed", False)]
    print(f"全エントリ: {len(entries)} / source_confirmed:false = {len(unconfirmed)} 件")

    print("e-Gov API 法令リスト取得中...")
    all_laws: list[dict] = []
    for cat in _CATEGORIES:
        laws = _get_law_list(cat)
        print(f"  category={cat}: {len(laws)} 件")
        all_laws.extend(laws)

    candidates, skipped = [], []
    for e in unconfirmed:
        eid, lname, cur = e.get("id",""), e.get("law_name",""), e.get("source","")
        m = _match(lname, all_laws)
        if m:
            candidates.append({
                "entry_id": eid, "law_name": lname,
                "current_url": cur,
                "proposed_url": _EGOV_URL.format(law_id=m["law_id"]),
                "egov_law_id": m["law_id"], "egov_law_name": m["law_name"],
                "confidence": m["confidence"], "source": "e-Gov API lawlists",
                "note": f"e-Gov 正式名称: {m['law_name']!r}。手動 YAML が最終権威。適用前に人手確認必須。",
            })
            print(f"  ✅ {eid}: {m['confidence']} → {_EGOV_URL.format(law_id=m['law_id'])}")
        else:
            skipped.append({"entry_id": eid, "law_name": lname, "current_url": cur,
                            "reason": "e-Gov 法令リストに一致なし。手動確認推奨。"})
            print(f"  ⚠️  {eid}: 一致なし（スキップ）")

    result = {
        "metadata": {
            "yaml_path": str(yaml_path),
            "total_entries": len(entries),
            "unconfirmed_count": len(unconfirmed),
            "candidates_found": len(candidates),
            "skipped_count": len(skipped),
            "egov_api_status": "HTTP 200 / XML / キー不要 ✅",
        },
        "robots_txt_summary": _ROBOTS_SUMMARY,
        "candidates": candidates,
        "skipped": skipped,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n出力: {output_path}  (candidates={len(candidates)}, skipped={len(skipped)})")
    return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--yaml", type=Path, default=_DEFAULT_YAML)
    p.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    args = p.parse_args()
    collect(args.yaml, args.output)


if __name__ == "__main__":
    main()
