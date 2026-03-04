"""扶養控除申告書管理サービス

従業員データ（SecureStore に保存済み）に "dependents" リストとして
扶養親族情報を付加・管理する純粋関数群。

データ構造:
  employee_data["dependents"] = [
      {
          "dep_name":   str,  # 扶養親族氏名
          "relation":   str,  # 続柄: "spouse" | "child" | "parent" | "other"
          "birth_year": int,  # 生年（西暦。0=不明）
          "income":     int,  # 所得金額（円。0=非課税扶養）
      },
      ...
  ]
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

VALID_RELATIONS = {"spouse", "child", "parent", "other"}


# ---------------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------------

def validate_dependent(dep: dict) -> list[str]:
    """扶養親族データのバリデーション。

    Args:
        dep: 扶養親族データ dict

    Returns:
        エラーメッセージのリスト（空リスト = 問題なし）
    """
    errors: list[str] = []

    # 氏名
    if not str(dep.get("dep_name", "")).strip():
        errors.append("dep_name（氏名）が未入力です")

    # 続柄
    relation = dep.get("relation", "")
    if relation not in VALID_RELATIONS:
        errors.append(
            f"relation は {sorted(VALID_RELATIONS)} のいずれかで入力してください: {relation!r}"
        )

    # 生年
    birth_year_raw = dep.get("birth_year", 0)
    try:
        birth_year = int(birth_year_raw)
        if birth_year != 0 and not (1900 <= birth_year <= 2100):
            errors.append(
                f"birth_year は 0（不明）または 1900〜2100 の西暦年で入力してください: {birth_year}"
            )
    except (ValueError, TypeError):
        errors.append(f"birth_year は整数で入力してください: {birth_year_raw!r}")

    # 所得
    income_raw = dep.get("income", 0)
    try:
        income = int(income_raw)
        if income < 0:
            errors.append(f"income は 0 以上で入力してください: {income}")
    except (ValueError, TypeError):
        errors.append(f"income は整数で入力してください: {income_raw!r}")

    return errors


# ---------------------------------------------------------------------------
# 純粋関数（SecureStore 非依存）
# ---------------------------------------------------------------------------

def add_dependent(employee_data: dict, dep: dict) -> dict:
    """従業員データに扶養親族を追加した新しい dict を返す。

    Args:
        employee_data: SecureStore から取得した従業員データ dict
        dep: 追加する扶養親族 dict

    Returns:
        dependents リストに dep を追加した新しい employee_data dict
    """
    data = dict(employee_data)
    deps = list(data.get("dependents", []))
    deps.append({
        "dep_name": str(dep["dep_name"]).strip(),
        "relation": str(dep["relation"]),
        "birth_year": int(dep.get("birth_year", 0)),
        "income": int(dep.get("income", 0)),
    })
    data["dependents"] = deps
    return data


def get_dependents(employee_data: dict) -> list[dict]:
    """従業員データから扶養親族リストを返す。

    Args:
        employee_data: SecureStore から取得した従業員データ dict

    Returns:
        扶養親族リスト（未登録の場合は空リスト）
    """
    return list(employee_data.get("dependents", []))


def delete_dependent(employee_data: dict, dep_index: int) -> dict:
    """指定インデックスの扶養親族を削除した新しい dict を返す。

    Args:
        employee_data: SecureStore から取得した従業員データ dict
        dep_index: 削除するインデックス（0始まり）

    Returns:
        指定インデックスを除いた新しい employee_data dict

    Raises:
        IndexError: dep_index が範囲外の場合
    """
    data = dict(employee_data)
    deps = list(data.get("dependents", []))
    if dep_index < 0 or dep_index >= len(deps):
        raise IndexError(
            f"扶養親族インデックス {dep_index} が範囲外です（登録件数: {len(deps)}）"
        )
    deps.pop(dep_index)
    data["dependents"] = deps
    return data
