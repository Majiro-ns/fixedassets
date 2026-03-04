"""サプライヤー比較・最安値探索ルーター (T008)

エンドポイント:
  GET /api/suppliers/list                      — 登録サプライヤー一覧
  GET /api/suppliers/compare/{part_number}     — 複数サプライヤーの最新価格一覧
  GET /api/suppliers/cheapest/{part_number}    — 最安値サプライヤー（発注先推奨）
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.models.schemas import (
    CheapestSupplierResponse,
    Supplier,
    SupplierCompareResponse,
    SupplierListResponse,
    SupplierPriceInfo,
)
from api.services import supplier_service

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("/list", response_model=SupplierListResponse)
def list_suppliers():
    """登録サプライヤー一覧を返す。"""
    suppliers = supplier_service.get_supplier_list()
    return SupplierListResponse(
        suppliers=[Supplier(**s) for s in suppliers],
        count=len(suppliers),
    )


@router.get("/compare/{part_number}", response_model=SupplierCompareResponse)
def compare_suppliers(part_number: str):
    """部品番号を指定し、複数サプライヤーの最新価格を一覧で返す。最安値をハイライト。"""
    result = supplier_service.get_supplier_price_comparison(part_number)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"部品番号 {part_number} が見つかりません",
        )
    return SupplierCompareResponse(
        part_number=result["part_number"],
        description=result["description"],
        suppliers=[SupplierPriceInfo(**s) for s in result["suppliers"]],
        cheapest_supplier=result["cheapest_supplier"],
        cheapest_price=result["cheapest_price"],
    )


@router.get("/cheapest/{part_number}", response_model=CheapestSupplierResponse)
def get_cheapest_supplier(part_number: str):
    """最安値サプライヤーのみを返す（発注先推奨）。"""
    result = supplier_service.get_cheapest_supplier(part_number)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"部品番号 {part_number} の価格データが見つかりません",
        )
    return CheapestSupplierResponse(**result)
