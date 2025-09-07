# -*- coding: utf-8 -*-
import io, os, re, sys
ROOT = os.path.dirname(os.path.dirname(__file__))
target = os.path.join(ROOT, "fixed_asset_classifier", "asset_advisor.py")
if not os.path.exists(target): 
    raise SystemExit("asset_advisor.py not found: %s" % target)

txt = open(target, "r", encoding="utf-8").read()
changed = False

# 1) import の確保
if "from useful_life_excel import UsefulLifeResolver" not in txt:
    txt = txt.replace("from llm_classifier import classify_with_llm", "from llm_classifier import classify_with_llm\nfrom useful_life_excel import UsefulLifeResolver")
    changed = True

# 2) __init__ に resolver の初期化を注入（無ければ追記）
if "UsefulLifeResolver()" not in txt:
    pat = r"(def __init__\\(self\\):[\\s\\S]*?)(\\n\\s*def\\s+classify_items\\()"
    block = "\\n        self._life = None\\n        try:\\n            self._life = UsefulLifeResolver()\\n        except Exception as e:\\n            print(\"WARN: UsefulLifeResolver init failed: {}.\".format(e))\\n\\n        "
    txt, n = re.subn(pat, lambda m: m.group(1)+block+m.group(2), txt, count=1)
    if n: changed = True

# 3) for ループ内に「ネスト出力」挿入（classification 設定後）
nest_block = '''
try:
    if self._life:
        desc_l = (item.get("description","") or "").lower()
        cat = item.get("category") or (
            "Server" if "server" in desc_l else
            "PC" if "pc" in desc_l else
            None
        )
        ul = self._life.resolve(cat, item.get("description","")) if cat else {
            "useful_life": None,
            "tax_useful_life": None,
            "basis": "unknown_category",
            "notes": None,
            "life_adjustments": []
        }
        item["useful_life"] = {
            "years": ul.get("useful_life"),
            "tax_years": ul.get("tax_useful_life"),
            "code": cat,
            "basis": ul.get("basis"),
            "notes": ul.get("notes"),
            "adjustments": ul.get("life_adjustments", []),
        }
except Exception as e:
    print(f"WARN: useful life resolve failed: {e}")
'''.strip()

# 旧フラット出力の除去
flat_patterns = [
    r'\\n\\s*item\["useful_life"\]\\s*=\\s*[^\\n]+\\n',
    r'\\n\\s*item\["tax_useful_life"\]\\s*=\\s*[^\\n]+\\n',
    r'\\n\\s*item\["useful_life_basis"\]\\s*=\\s*[^\\n]+\\n',
    r'\\n\\s*item\["useful_life_notes"\]\\s*=\\s*[^\\n]+\\n',
    r'\\n\\s*item\["life_adjustments"\]\\s*=\\s*[^\\n]+\\n',
]
for p in flat_patterns:
    txt, n = re.subn(p, "\\n", txt)
    if n: changed = True

# classification 直後を探して注入（多重注入防止）
if 'item["useful_life"] = {' not in txt:
    anchor = 'item["classification"] = '
    pos = txt.find(anchor)
    if pos != -1:
        # 行末まで進めてその直後へ差し込み
        line_end = txt.find("\\n", pos)
        if line_end == -1: line_end = pos
        txt = txt[:line_end+1] + "        " + nest_block.replace("\\n", "\\n        ") + "\\n" + txt[line_end+1:]
        changed = True

if changed:
    open(target, "w", encoding="utf-8", newline="").write(txt)
    print("PATCHED:", target)
else:
    print("UNCHANGED:", target)