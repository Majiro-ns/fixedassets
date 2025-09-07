# -*- coding: utf-8 -*-
"""
asset_advisor.py
Orchestrates the classification process by using the rule engine first,
and then falling back to the LLM classifier for undecided items.
Also enriches each item with a nested useful-life object resolved from Excel.
"""
from typing import Dict, Any
import traceback

from rule_engine import RuleEngine
from llm_classifier import classify_with_llm
from useful_life_excel import UsefulLifeResolver


class AssetAdvisoryAgent:
    """
    抽出された見積もりデータを基に、各項目が固定資産に該当するかを判定するエージェント。
    ルールエンジンとLLM判定を組み合わせたハイブリッド方式を採用します。
    判定後に「耐用年数」情報（Excel + バイアス規則）をネスト構造で付与します。
    """

    def __init__(self):
        """
        エージェントを初期化し、ルールエンジン／耐用年数リゾルバをロードします。
        LLMクライアントは外部モジュールで管理されるため、ここでは初期化しません。
        """
        try:
            self.rule_engine = RuleEngine(rules_file='rules.json')
            print("INFO: Rule Engine initialized successfully.")
        except ValueError as e:
            print(f"ERROR: Failed to initialize RuleEngine: {e}")
            self.rule_engine = None

        self._life = None
        try:
            self._life = UsefulLifeResolver()
            print("INFO: UsefulLifeResolver initialized successfully.")
        except Exception as e:
            print(f"WARN: UsefulLifeResolver init failed: {e}")

    # --------------------------- Internal helpers ---------------------------

    @staticmethod
    def _infer_category_from_desc(item: Dict[str, Any]) -> str | None:
        """
        説明文からカテゴリを推定。
        life_table 側の代表カテゴリ名に正規化して返す: "PC" / "Server" / "Building附属設備" / "Software"
        """
        # 既存カテゴリがあれば最優先
        cat = item.get("category")
        if cat:
            return str(cat)

        desc = (item.get("description") or "")
        desc_l = desc.lower()

        # ノイズを軽く正規化（全角→半角、記号落とし など、必要最低限）
        import re
        z2h = str.maketrans({'’':"'", '“':'"', '”':'"', '−':"-", '–':"-"})
        desc_l = desc_l.translate(z2h)

        PC_TOKENS = [
            "pc","note pc","notepc","ノートpc","ノート","パソコン","laptop","desktop","デスクトップ",
            "let's note","lets note","letsnote","thinkpad","dynabook","lavie","vaio",
            "macbook","surface","latitude","inspiron","elitebook","probook","ideapad","legion","spectre","envy"
        ]
        SERVER_TOKENS = [
            "server","サーバ","proliant","poweredge","thinksystem","primergy","rx","rack","タワーサーバ"
        ]
        BLD_TOKENS = ["工事","設置","据付","取付","配線","内装","改修","取付工賃","据え付け","搬入"]
        SW_TOKENS = ["software","ソフト","ライセンス","license","subscription","サブスク","年間契約","保守更新"]

        if any(t in desc_l for t in PC_TOKENS):
            return "PC"
        if any(t in desc_l for t in SERVER_TOKENS):
            return "Server"
        if any(t in desc_l for t in BLD_TOKENS):
            return "Building附属設備"
        if any(t in desc_l for t in SW_TOKENS):
            return "Software"

        # 金額帯ヒューリスティクス（最後の砦）：CAPEXで10万～30万円帯は PC っぽい
        try:
            amt = float(item.get("amount") or 0)
        except Exception:
            amt = 0
        decision = ((item.get("classification") or {}).get("decision") or "").lower()
        if decision in ("capex", "asset") and 100000 <= amt <= 300000:
            return "PC"

        return None

    def _attach_useful_life(self, item: Dict[str, Any]) -> None:
        """
        item に nested useful_life オブジェクトを付与する。
        付与形：
        item["useful_life"] = {
            "years": int|None,
            "tax_years": int|None,
            "code": str|None,        # 推定カテゴリ
            "basis": str,            # "excel_table+bias" | "unknown_category" など
            "notes": str|None,
            "adjustments": list,     # バイアス適用履歴
        }
        """
        try:
            if not self._life:
                return
            cat = self._infer_category_from_desc(item)
            if cat:
                ul = self._life.resolve(cat, item.get("description", ""))
            else:
                ul = {
                    "useful_life": None,
                    "tax_useful_life": None,
                    "basis": "unknown_category",
                    "notes": None,
                    "life_adjustments": [],
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

    # ------------------------------ Public API ------------------------------

    def classify_items(self, extracted_data: Dict[str, Any], is_sme: bool, sme_ytd_applied: float = 0.0) -> Dict[str, Any]:
        """
        明細の各項目を分類し、結果を元のデータに追記します。
        1) ルールエンジン → 2) LLM（フォールバック） → 3) 耐用年数のネスト付与
        """
        if "line_items" not in extracted_data or not extracted_data["line_items"]:
            return extracted_data

        # 会社・期間の共通コンテキスト
        company_ctx = {"is_sme": is_sme}
        period_ctx = {"sme_ytd_applied": sme_ytd_applied}

        if not self.rule_engine:
            # エンジンが初期化に失敗した場合、classification は review に倒しつつ、耐用年数だけは試みる
            for item in extracted_data["line_items"]:
                item["classification"] = {"decision": "review", "reason": "Rule engine failed to load."}
                self._attach_useful_life(item)
            return extracted_data

        for item in extracted_data["line_items"]:
            try:
                # 1) ルールエンジン用のコンテキスト
                context = {
                    "expenditure_amount": item.get("amount"),
                    "description": item.get("description", ""),
                    "bundle_role": item.get("role", "solo"),
                    "prior_acquisition_cost": item.get("prior_acquisition_cost"),  # for repair rule
                    **company_ctx,
                    **period_ctx,
                }

                # 2) ルールエンジン実行
                final_rule_result = self.rule_engine.run(context)

                # 3) ルールが最終結論を出したか
                if final_rule_result and final_rule_result.get("final_node_id") and final_rule_result.get("conclusion"):
                    item["classification"] = final_rule_result
                else:
                    # 4) LLMフォールバック
                    rule_trace = {
                        "final_node_id": final_rule_result.get("final_node_id") if final_rule_result else None,
                        "history": final_rule_result.get("history") if final_rule_result else [],
                    }
                    llm_result = classify_with_llm(
                        item=item,
                        company_ctx=company_ctx,
                        period_ctx=period_ctx,
                        rule_trace=rule_trace
                    )
                    item["classification"] = llm_result

            except Exception as e:
                item["classification"] = {
                    "decision": "error",
                    "reason": f"Classification error: {e}",
                    "traceback": traceback.format_exc(),
                }

            # 5) 耐用年数ネスト付与（常に最後に実施）
            self._attach_useful_life(item)

        return extracted_data
