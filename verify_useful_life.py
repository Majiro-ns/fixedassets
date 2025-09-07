import sys, os
ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(ROOT, "fixed_asset_classifier"))
from fixed_asset_classifier.main import run_analysis
pdf = os.path.join(ROOT, "fixed_asset_classifier", "input_pdfs", "demo_estimate.pdf")
out = run_analysis(pdf_path=pdf, use_temp_input=False, is_sme=True)
assert "line_items" in out and isinstance(out["line_items"], list) and len(out["line_items"])>0, "no items"
assert all(isinstance(li.get("useful_life"), dict) for li in out["line_items"]), "useful_life object missing"
print("OK: useful life integrated; items=", len(out["line_items"]))
