# -*- coding: utf-8 -*-
import os
import pandas as pd
from typing import Dict, Any, Optional, Tuple, List

class UsefulLifeResolver:
    """
    Excel(2シート) 駆動の耐用年数解決クラス
      - life_table(category, tax_useful_life, book_useful_life_default, notes)
      - bias_rules(book_min, book_max, rule_name, kw_include, kw_exclude, delta_years)
    """
    def __init__(self, xlsx_path: str = None):
        self.xlsx_path = xlsx_path or os.getenv("USEFUL_LIFE_XLSX", "useful_life.xlsx")
        if not os.path.exists(self.xlsx_path):
            raise FileNotFoundError(f"useful life workbook not found: {self.xlsx_path}")
        ENGINE = "openpyxl"
        self.life_df = pd.read_excel(self.xlsx_path, sheet_name="life_table", engine=ENGINE)
        try:
            self.bias_df = pd.read_excel(self.xlsx_path, sheet_name="bias_rules", engine=ENGINE)
        except Exception:
            self.bias_df = pd.DataFrame(columns=["rule_name","kw_include","kw_exclude","delta_years","book_min","book_max"])
        # 正規化
        for col in ["category","notes"]:
            if col in self.life_df.columns:
                self.life_df[col] = self.life_df[col].astype(str)
        for col in ["kw_include","kw_exclude","rule_name"]:
            if col in self.bias_df.columns:
                self.bias_df[col] = self.bias_df[col].astype(str)

    def _match_bias(self, desc: str) -> List[Dict[str, Any]]:
        desc_l = (desc or "").lower()
        hits = []
        for _, r in self.bias_df.iterrows():
            inc = [w.strip().lower() for w in str(r.get("kw_include","")).split("|") if w.strip()]
            exc = [w.strip().lower() for w in str(r.get("kw_exclude","")).split("|") if w.strip()]
            if inc and not any(w in desc_l for w in inc):
                continue
            if exc and any(w in desc_l for w in exc):
                continue
            hits.append({
                "rule_name": r.get("rule_name"),
                "delta_years": float(r.get("delta_years",0) or 0),
                "book_min": float(r.get("book_min",0) or 0),
                "book_max": float(r.get("book_max",999) or 999),
            })
        return hits

    def resolve(self, category: str, description: str) -> Dict[str, Any]:
        row = self.life_df[self.life_df["category"]==category].head(1)
        if row.empty:
            return {
                "useful_life": None, "tax_useful_life": None,
                "basis": "unknown_category",
                "notes": None,
                "life_adjustments": []
            }
        r = row.iloc[0]
        tax_years = int(r.get("tax_useful_life")) if pd.notna(r.get("tax_useful_life")) else None
        book_default = int(r.get("book_useful_life_default")) if pd.notna(r.get("book_useful_life_default")) else tax_years
        notes = r.get("notes")

        # 偏差適用（帳簿側のみ、min/max ガード）
        book_years = book_default
        adjustments = []
        for hit in self._match_bias(description):
            candidate = int(max(hit["book_min"], min(hit["book_max"], book_years + hit["delta_years"])))
            adjustments.append({
                "rule_name": hit["rule_name"],
                "before": book_years,
                "after": candidate,
                "guard_min": hit["book_min"],
                "guard_max": hit["book_max"]
            })
            book_years = candidate

        return {
            "useful_life": book_years,
            "tax_useful_life": tax_years,
            "basis": "excel_table+bias",
            "notes": notes,
            "life_adjustments": adjustments
        }
