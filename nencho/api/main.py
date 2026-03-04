"""nencho FastAPI backend.

Usage:
    PYTHONPATH=. uvicorn api.main:app --reload --port 8000

環境変数:
    CORS_ORIGINS: 許可するオリジン（カンマ区切り）。未設定時は localhost:3000 のみ許可。
                  例: "http://localhost:3000,http://frontend:3000"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import calculate, csv_import, dependents, employees, export, session, year_end_report

app = FastAPI(
    title="nencho API",
    description="年末調整計算エンジン REST API",
    version="1.0.0",
)

_cors_raw = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(calculate.router)
app.include_router(export.router)
app.include_router(session.router)
app.include_router(employees.router)
app.include_router(csv_import.router)
app.include_router(year_end_report.router)
app.include_router(dependents.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "nencho"}
