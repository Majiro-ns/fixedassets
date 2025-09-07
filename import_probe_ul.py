# import_probe_ul.py
import sys, os
ROOT = os.path.dirname(__file__)
sys.path.insert(0, ROOT)
from fixed_asset_classifier import useful_life_excel
print("OK:", useful_life_excel.__file__)
