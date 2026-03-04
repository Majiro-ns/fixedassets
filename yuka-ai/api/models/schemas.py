"""Pydantic schemas for yuka-ai API."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel


# ─── Dashboard ───────────────────────────────────────────────────────────────

class DeliveryAlert(BaseModel):
    id: int
    part_number: str
    supplier_name: str
    order_date: str
    expected_delivery_date: str
    quantity: int
    status: str
    notes: Optional[str] = None


class DeliveryAlerts(BaseModel):
    overdue: List[DeliveryAlert]
    today: List[DeliveryAlert]
    tomorrow: List[DeliveryAlert]


class PriceRow(BaseModel):
    part_number: str
    description: str
    category: Optional[str] = None
    latest_price: float
    price_date: str
    source: Optional[str] = None
    prev_price: Optional[float] = None
    change_pct: Optional[float] = None


class OrderSummary(BaseModel):
    id: int
    po_number: str
    supplier_name: Optional[str] = None
    status: str
    issue_date: Optional[str] = None
    grand_total: Optional[float] = None


class DashboardResponse(BaseModel):
    delivery_alerts: DeliveryAlerts
    price_summary: List[PriceRow]
    recent_orders: List[OrderSummary]


# ─── Prices ──────────────────────────────────────────────────────────────────

class Part(BaseModel):
    part_number: str
    description: str
    category: Optional[str] = None
    ec_site: Optional[str] = None
    lead_time_days: Optional[int] = None
    price_record_count: Optional[int] = None


class AddPartRequest(BaseModel):
    part_number: str
    description: str
    category: str = ""
    ec_site: str = "monotaro"
    threshold_pct: float = 5.0


class AddPartResponse(BaseModel):
    part_id: int
    message: str


# ─── Orders ──────────────────────────────────────────────────────────────────

class Order(BaseModel):
    id: int
    po_number: str
    supplier_name: Optional[str] = None
    status: str
    issue_date: Optional[str] = None
    delivery_date: Optional[str] = None
    grand_total: Optional[float] = None
    notes: Optional[str] = None


class Supplier(BaseModel):
    id: int
    name: str
    code: Optional[str] = None


class CreateOrderRequest(BaseModel):
    po_number: str
    supplier_id: int
    delivery_date: str
    notes: str = ""


class CreateOrderResponse(BaseModel):
    order_id: int
    message: str


# ─── Delivery ────────────────────────────────────────────────────────────────

class DeliveryRecord(BaseModel):
    id: int
    part_number: str
    supplier_name: str
    order_date: str
    expected_delivery_date: str
    quantity: int
    unit_price: Optional[float] = None
    status: str
    notes: Optional[str] = None


class AddDeliveryRequest(BaseModel):
    part_number: str
    supplier_name: str
    order_date: str
    expected_delivery_date: str
    quantity: int = 1
    unit_price: Optional[float] = None
    notes: str = ""


class AddDeliveryResponse(BaseModel):
    delivery_id: int
    message: str


class MarkReceivedResponse(BaseModel):
    success: bool
    message: str


# ─── Price History / Manual / Alerts ─────────────────────────────────────────

class PriceHistoryItem(BaseModel):
    price: float
    fetched_at: str
    source: Optional[str] = None


class RecordManualPriceRequest(BaseModel):
    part_number: str
    description: str
    price: float
    source: str = "manual"


class RecordManualPriceResponse(BaseModel):
    message: str
    latest_price: Optional[float] = None
    change_pct: Optional[float] = None


class PriceAlertItem(BaseModel):
    part_number: str
    description: str
    latest_price: float
    prev_price: float
    change_pct: float
    alert_level: str  # INFO / WARNING / CRITICAL


# ─── Approval Workflow ────────────────────────────────────────────────────────

class ApprovalItem(BaseModel):
    id: int
    po_number: str
    requester: str
    reason: str
    amount: float
    status: str
    requested_at: str
    resolved_at: Optional[str] = None
    resolver: Optional[str] = None
    comment: Optional[str] = None


class RequestApprovalRequest(BaseModel):
    amount: float
    requester: str = "system"
    reason: str = ""


class RequestApprovalResponse(BaseModel):
    id: int
    message: str


class ResolveApprovalRequest(BaseModel):
    action: str  # "approved" or "rejected"
    resolver: str = "system"
    comment: str = ""


class ResolveApprovalResponse(BaseModel):
    message: str
    status: str


# ─── MISUMI 価格検索 ──────────────────────────────────────────────────────────

class MisumiPriceResult(BaseModel):
    part_number: str
    product_name: str
    brand_name: str = ""
    unit_price: Optional[float] = None
    currency: str = "JPY"
    days_to_ship: Optional[int] = None
    min_quantity: int = 1
    unit: str = "個"
    category: str = ""
    product_url: str = ""
    image_url: str = ""


# ─── Email 解析・送信 ─────────────────────────────────────────────────────────

class ParseEmailRequest(BaseModel):
    text: str
    source: str = "text"


class ParsedEmailItem(BaseModel):
    part_number: str
    quantity: Optional[int] = None


class ParseEmailResponse(BaseModel):
    subject: str
    sender: str
    body: str
    order_number: Optional[str] = None
    delivery_date: Optional[str] = None
    extracted_items: List[ParsedEmailItem]
    source: str


class SendDeliveryConfirmRequest(BaseModel):
    to: str
    supplier_name: str
    po_number: str
    body: Optional[str] = None


class SendEmailResponse(BaseModel):
    success: bool
    message: str


# ─── ERP 連携 ────────────────────────────────────────────────────────────────

class ErpExportLogItem(BaseModel):
    id: int
    po_number: str
    format: str
    output_path: Optional[str] = None
    exported_at: str


# ─── IMAP 自動取得（T005b / F-18）──────────────────────────────────────────

class ImapFetchRequest(BaseModel):
    limit: int = 10
    subject_filter: Optional[str] = None
    dry_run: bool = True


class ImapFetchedEmail(BaseModel):
    subject: str
    sender: str
    body: str
    order_number: Optional[str] = None
    delivery_date: Optional[str] = None
    extracted_items: List["ParsedEmailItem"]
    source: str


class ImapFetchResponse(BaseModel):
    emails: List[ImapFetchedEmail]
    fetched_count: int
    mode: str
    error: Optional[str] = None


# ─── OCR 連携（T005b / F-19）───────────────────────────────────────────────

class OcrExtractRequest(BaseModel):
    file_path: str
    force_mock: bool = False


class OcrExtractedItem(BaseModel):
    part_number: str
    quantity: Optional[int] = None


class OcrExtractResponse(BaseModel):
    raw_text: str
    order_number: Optional[str] = None
    delivery_date: Optional[str] = None
    items: List[OcrExtractedItem]
    source_file: str
    engine: str
    page_count: int
    error: Optional[str] = None


# ─── ERP 直接インポート（T005b / F-20）─────────────────────────────────────

class ErpImportRequest(BaseModel):
    po_number: str
    dry_run: bool = True


class ErpImportResponse(BaseModel):
    success: bool
    po_number: str
    mode: str
    erp_reference_id: Optional[str] = None
    imported_at: str
    error: Optional[str] = None


class ErpImportLogItem(BaseModel):
    id: int
    po_number: str
    mode: str
    success: bool
    erp_reference_id: Optional[str] = None
    error: Optional[str] = None
    imported_at: str


# ─── Analytics（価格トレンド分析・発注タイミング推奨）─────────────────────────

class PriceTrendItem(BaseModel):
    price: float
    fetched_at: str
    source: Optional[str] = None


class PriceTrendResponse(BaseModel):
    part_number: str
    trend_direction: str       # "rising" | "falling" | "stable" | "unknown"
    trend_pct: float           # 最古→最新の変動率(%)
    avg_price: float
    min_price: float
    max_price: float
    latest_price: float
    data_points: int
    volatility_pct: float      # 変動係数(%) = stdev/avg*100
    history: List[PriceTrendItem]


class BuyRecommendationResponse(BaseModel):
    part_number: str
    action: str                # "BUY_NOW" | "WAIT" | "NEUTRAL"
    reason: str
    score: float               # 0〜100（高いほど今すぐ買いが推奨）
    current_price: float
    avg_price: float
    trend_pct: float
    trend_direction: str


# ─── Procurement（発注自動化 T007）────────────────────────────────────────────

class LowStockItem(BaseModel):
    part_number: str
    description: str
    category: Optional[str] = None
    current_stock: int
    reorder_point: int
    shortage: int              # reorder_point - current_stock


class LowStockResponse(BaseModel):
    items: List[LowStockItem]
    count: int


class AutoOrderCandidate(BaseModel):
    part_number: str
    description: str
    category: Optional[str] = None
    current_stock: int
    reorder_point: int
    shortage: int
    action: str                # "BUY_NOW"
    reason: str
    score: float               # 0〜100
    current_price: float
    avg_price: float
    trend_pct: float


class AutoOrderCandidatesResponse(BaseModel):
    candidates: List[AutoOrderCandidate]
    count: int


class PendingApprovalItem(BaseModel):
    id: int
    po_number: str
    requester: str
    reason: str
    amount: float
    status: str
    requested_at: str
    resolved_at: Optional[str] = None
    resolver: Optional[str] = None
    comment: Optional[str] = None


class PendingApprovalsResponse(BaseModel):
    items: List[PendingApprovalItem]
    count: int


# ─── Supplier Comparison（サプライヤー比較・最安値探索 T008）────────────────────

class SupplierPriceInfo(BaseModel):
    supplier_id: Optional[int] = None
    supplier_name: str
    supplier_code: Optional[str] = None
    latest_price: float
    price_date: str
    source: Optional[str] = None
    is_cheapest: bool = False
    cost_score: float           # 現在は latest_price と同値（リードタイム考慮は拡張予定）


class SupplierCompareResponse(BaseModel):
    part_number: str
    description: Optional[str] = None
    suppliers: List[SupplierPriceInfo]
    cheapest_supplier: Optional[str] = None
    cheapest_price: Optional[float] = None


class CheapestSupplierResponse(BaseModel):
    part_number: str
    description: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_name: str
    supplier_code: Optional[str] = None
    latest_price: float
    price_date: str
    source: Optional[str] = None


class SupplierListResponse(BaseModel):
    suppliers: List[Supplier]   # 既存 Supplier モデル（id, name, code）を再利用
    count: int


# ─── Reports（月次コスト分析 T009）────────────────────────────────────────────

class MonthlyCostItem(BaseModel):
    part_number: str
    description: str
    total_amount: float
    avg_unit_price: float
    order_count: int


class MonthlyCostResponse(BaseModel):
    year_month: str
    items: List[MonthlyCostItem]
    count: int
    grand_total: float


class CostTrendPoint(BaseModel):
    year_month: str
    total_amount: float
    order_count: int


class CostTrendResponse(BaseModel):
    months: int
    data: List[CostTrendPoint]


class ExportCsvRequest(BaseModel):
    report_type: str = "monthly_cost"    # "monthly_cost" | "cost_trend"
    year_month: Optional[str] = None     # monthly_cost 対象月 (YYYY-MM)。None で最新月自動選択
    months: int = 6                      # cost_trend の取得月数
