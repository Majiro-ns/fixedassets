"""
ゴールドデータ検証テストセット（設計書V2.2 Section 9A）

現時点では以下の2種類のテストを実施:
1. JSON Schema Validation - ゴールドデータファイルの構造検証
2. Expected Value Consistency Check - 期待値の整合性チェック（税法根拠に基づく）

APIが実装されたら @pytest.mark.skip を外してAPI統合テストを有効化すること。
"""
import json
import os
from pathlib import Path
from typing import Any

import pytest

# ─── パス設定 ────────────────────────────────────────────────────────────────
GOLD_DATA_DIR = Path(__file__).parent / "gold_data"

# ─── ゴールドデータ一覧の収集 ────────────────────────────────────────────────

def _load_all_gold_cases() -> list[tuple[str, dict]]:
    """gold_data/ 配下の全JSONファイルから全テストケースを収集する"""
    cases = []
    for json_file in sorted(GOLD_DATA_DIR.glob("*.json")):
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
        for case in data:
            cases.append((case["test_id"], case))
    return cases


ALL_GOLD_CASES = _load_all_gold_cases()

# ─── JSON Schema Validation ───────────────────────────────────────────────────

REQUIRED_FIELDS = {"test_id", "category", "input", "expected", "basis"}
REQUIRED_INPUT_FIELDS = {"description", "amount", "quantity"}
REQUIRED_EXPECTED_FIELDS = {"verdict", "account_category", "useful_life", "rationale_keywords"}
VALID_VERDICTS = {"CAPITAL", "EXPENSE", "GUIDANCE"}
VALID_CATEGORIES = {
    "明確な固定資産",
    "明確な費用",
    "少額固定資産",
    "一括償却資産",
    "修繕vs資本的支出",
    "分裂ケース",
}


@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_schema_top_level(test_id: str, case: dict[str, Any]) -> None:
    """ゴールドデータのトップレベルフィールドが全て存在すること"""
    missing = REQUIRED_FIELDS - set(case.keys())
    assert not missing, f"{test_id}: 必須フィールドが不足: {missing}"


@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_schema_input_fields(test_id: str, case: dict[str, Any]) -> None:
    """input フィールドの構造が正しいこと"""
    inp = case["input"]
    missing = REQUIRED_INPUT_FIELDS - set(inp.keys())
    assert not missing, f"{test_id}: input の必須フィールドが不足: {missing}"
    assert isinstance(inp["description"], str) and inp["description"], (
        f"{test_id}: input.description は空でない文字列であること"
    )
    assert isinstance(inp["amount"], (int, float)) and inp["amount"] > 0, (
        f"{test_id}: input.amount は正の数値であること"
    )
    assert isinstance(inp["quantity"], int) and inp["quantity"] >= 1, (
        f"{test_id}: input.quantity は1以上の整数であること"
    )


@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_schema_expected_fields(test_id: str, case: dict[str, Any]) -> None:
    """expected フィールドの構造が正しいこと"""
    exp = case["expected"]
    missing = REQUIRED_EXPECTED_FIELDS - set(exp.keys())
    assert not missing, f"{test_id}: expected の必須フィールドが不足: {missing}"
    assert isinstance(exp["rationale_keywords"], list) and len(exp["rationale_keywords"]) >= 1, (
        f"{test_id}: expected.rationale_keywords は1件以上のリストであること"
    )


@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_valid_verdict(test_id: str, case: dict[str, Any]) -> None:
    """verdict が CAPITAL / EXPENSE / GUIDANCE のいずれかであること"""
    verdict = case["expected"]["verdict"]
    assert verdict in VALID_VERDICTS, (
        f"{test_id}: verdict '{verdict}' は {VALID_VERDICTS} のいずれかであること"
    )


@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_valid_category(test_id: str, case: dict[str, Any]) -> None:
    """category が定義済みカテゴリのいずれかであること"""
    cat = case["category"]
    assert cat in VALID_CATEGORIES, (
        f"{test_id}: category '{cat}' は {VALID_CATEGORIES} のいずれかであること"
    )


def test_unique_test_ids() -> None:
    """全テストケースのIDが一意であること"""
    all_ids = [c[0] for c in ALL_GOLD_CASES]
    assert len(all_ids) == len(set(all_ids)), f"重複するtest_idが存在する: {all_ids}"


# ─── Expected Value Consistency Check ────────────────────────────────────────
# 税法根拠に基づく期待値の整合性チェック

@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_amount_under_100k_must_be_expense_or_guidance(test_id: str, case: dict[str, Any]) -> None:
    """
    取得価額 < 100,000円 は EXPENSE または GUIDANCE であること
    根拠: 法令133条（少額の減価償却資産）- 10万円未満は全額損金算入
    """
    amount = case["input"]["amount"]
    verdict = case["expected"]["verdict"]
    if amount < 100_000:
        assert verdict in {"EXPENSE", "GUIDANCE"}, (
            f"{test_id}: 取得価額{amount:,}円 < 10万円 → verdict は EXPENSE/GUIDANCE のはず（実際: {verdict}）"
        )


@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_amount_300k_or_more_cannot_be_bulk_depreciation(test_id: str, case: dict[str, Any]) -> None:
    """
    取得価額 >= 300,000円 は account_category が 一括償却資産 でないこと
    根拠: 法令133条の2（一括償却資産）- 上限20万円未満
    ※中小企業の少額減価償却資産（法令133条の3）は30万円未満が上限
    """
    amount = case["input"]["amount"]
    account_category = case["expected"]["account_category"]
    if amount >= 300_000:
        assert account_category != "一括償却資産", (
            f"{test_id}: 取得価額{amount:,}円 >= 30万円 → account_category は 一括償却資産 にはなれない"
        )


@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_capital_verdict_must_have_useful_life_or_null_for_guidance(
    test_id: str, case: dict[str, Any]
) -> None:
    """
    verdict=CAPITAL の場合は useful_life が整数 >= 1 であること
    verdict=EXPENSE/GUIDANCE の場合は useful_life が null であること
    """
    verdict = case["expected"]["verdict"]
    useful_life = case["expected"]["useful_life"]
    if verdict == "CAPITAL":
        assert isinstance(useful_life, int) and useful_life >= 1, (
            f"{test_id}: verdict=CAPITAL → useful_life は1以上の整数のはず（実際: {useful_life}）"
        )
    elif verdict in {"EXPENSE", "GUIDANCE"}:
        assert useful_life is None, (
            f"{test_id}: verdict={verdict} → useful_life は null のはず（実際: {useful_life}）"
        )


@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_guidance_verdict_account_category_is_null(test_id: str, case: dict[str, Any]) -> None:
    """
    verdict=GUIDANCE の場合は account_category が null であること
    根拠: Section 9A - 分裂ケースはAI単独で勘定科目を確定できない
    """
    verdict = case["expected"]["verdict"]
    account_category = case["expected"]["account_category"]
    if verdict == "GUIDANCE":
        assert account_category is None, (
            f"{test_id}: verdict=GUIDANCE → account_category は null のはず（実際: {account_category}）"
        )


@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_basis_is_not_empty(test_id: str, case: dict[str, Any]) -> None:
    """basis（根拠）フィールドが空でないこと（テスト期待値の根拠明記 CHECK-9準拠）"""
    basis = case.get("basis", "")
    assert isinstance(basis, str) and len(basis) > 10, (
        f"{test_id}: basis（根拠）は10文字以上の説明が必要"
    )


# ─── カテゴリ別件数チェック ────────────────────────────────────────────────────

def test_gold_data_coverage() -> None:
    """
    全カテゴリに最低2件のテストケースが存在すること
    根拠: Section 9A - カテゴリ各2〜3件を要件とする
    """
    from collections import Counter
    counts = Counter(case["category"] for _, case in ALL_GOLD_CASES)
    for category in VALID_CATEGORIES:
        assert counts[category] >= 2, (
            f"カテゴリ '{category}' のテストケースが不足: {counts[category]}件（最低2件必要）"
        )


def test_gold_data_total_count() -> None:
    """
    ゴールドデータが合計10件以上15件以下であること
    根拠: Section 9A - 10〜15件を要件とする
    """
    total = len(ALL_GOLD_CASES)
    assert 10 <= total <= 15, (
        f"ゴールドデータの件数が範囲外: {total}件（10〜15件の範囲であること）"
    )


# ─── API統合テスト（API実装後に有効化）────────────────────────────────────────

@pytest.mark.skip(reason="API v2/classify未実装のため。Tax Agent実装後に有効化すること")
@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_api_verdict_matches_expected(test_id: str, case: dict[str, Any]) -> None:
    """
    [API実装後に有効化]
    Tax Agent APIが返す verdict が期待値と一致すること
    精度目標: 正答率 >= 80%（Section 9A.3）
    """
    # TODO: API実装後に以下を有効化
    # from app.agents.tax_agent import classify_line_item
    # result = classify_line_item(
    #     description=case["input"]["description"],
    #     amount=case["input"]["amount"],
    # )
    # assert result.verdict == case["expected"]["verdict"], (
    #     f"{test_id}: verdict不一致 期待={case['expected']['verdict']} 実際={result.verdict}"
    # )
    pytest.fail("このテストはAPI実装後に実装すること")


@pytest.mark.skip(reason="API v2/classify未実装のため。Tax Agent実装後に有効化すること")
@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_api_account_category_matches_expected(test_id: str, case: dict[str, Any]) -> None:
    """
    [API実装後に有効化]
    Tax Agent APIが返す account_category が期待値と一致すること
    精度目標: 勘定科目一致率 >= 70%（Section 9A.3）
    """
    # TODO: API実装後に以下を有効化
    pytest.fail("このテストはAPI実装後に実装すること")


@pytest.mark.skip(reason="API v2/classify未実装のため。Tax Agent実装後に有効化すること")
@pytest.mark.parametrize("test_id,case", ALL_GOLD_CASES, ids=[c[0] for c in ALL_GOLD_CASES])
def test_api_useful_life_matches_expected(test_id: str, case: dict[str, Any]) -> None:
    """
    [API実装後に有効化]
    Tax Agent APIが返す useful_life が期待値と一致すること
    """
    # TODO: API実装後に以下を有効化
    pytest.fail("このテストはAPI実装後に実装すること")
