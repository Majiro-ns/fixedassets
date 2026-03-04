"""yuka-ai FastAPI backend.

Usage:
    cd yuka-ai
    PYTHONPATH=. uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import dashboard, prices, orders, delivery, emails, erp, imap, ocr, analytics, procurement, suppliers, reports

app = FastAPI(
    title="yuka-ai API",
    description="調達AIエージェント — 価格追跡・発注管理・納期管理",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(prices.router)
app.include_router(orders.router)
app.include_router(delivery.router)
app.include_router(emails.router)
app.include_router(erp.router)
app.include_router(imap.router)
app.include_router(ocr.router)
app.include_router(analytics.router)
app.include_router(procurement.router)
app.include_router(suppliers.router)
app.include_router(reports.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "yuka-ai"}
