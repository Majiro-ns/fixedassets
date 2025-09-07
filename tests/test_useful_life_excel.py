# tests/test_useful_life_excel.py
import os
import pandas as pd
import pytest

from fixed_asset_classifier import useful_life_excel as ulx

# リポジトリ直下の useful_life.xlsx を参照
X = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'useful_life.xlsx'))

def test_workbook_has_required_sheets_and_columns():
    xf = pd.ExcelFile(X, engine='openpyxl')
    names = set(xf.sheet_names)
    assert {'life_table', 'bias_rules'}.issubset(names)

    life = pd.read_excel(X, sheet_name='life_table', engine='openpyxl')
    bias = pd.read_excel(X, sheet_name='bias_rules', engine='openpyxl')

    for c in ['category', 'tax_useful_life', 'book_useful_life_default', 'notes']:
        assert c in life.columns

    for c in ['rule_name', 'kw_include', 'kw_exclude', 'delta_years', 'book_min', 'book_max']:
        assert c in bias.columns


def test_resolver_returns_consistent_dict():
    r = ulx.UsefulLifeResolver(xlsx_path=X)
    # 「レンダリング」を含めることで bias_rules が存在しても/しなくても安全に通る範囲で検証
    out = r.resolve('PC', "Let's Note ノートPC レンダリング用途")
    assert isinstance(out, dict)
    for key in ['useful_life', 'tax_useful_life', 'basis', 'notes', 'life_adjustments']:
        assert key in out

    # 値の健全性（範囲チェック）
    # 既定 life_table(PC=4年) と bias_rules(±調整, 2〜6年の想定レンジ) をゆるやかに担保
    assert 2 <= int(out.get('useful_life') or 0) <= 6
    assert int(out.get('tax_useful_life') or 0) in (4, 5)


def test_resolver_handles_missing_bias_sheet_gracefully(monkeypatch):
    # bias_rules が無くても例外を出さず既定値で返せること（モンキーパッチで空DFに）
    class Dummy(ulx.UsefulLifeResolver):
        def __init__(self, xlsx_path):
            self.xlsx_path = xlsx_path
            self.life_df = pd.read_excel(xlsx_path, sheet_name='life_table', engine='openpyxl')
            self.bias_df = pd.DataFrame(columns=['rule_name','kw_include','kw_exclude','delta_years','book_min','book_max'])

    r = Dummy(X)
    out = r.resolve('PC', '一般事務用途')
    assert isinstance(out, dict)
    assert out.get('useful_life') is not None  # 既定表からは拾える
