"""disclosure-multiagent FastAPI backend.

Usage:
    PYTHONPATH=scripts:. uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import sys
from pathlib import Path

# scripts/ をインポートパスに追加
_PROJECT_ROOT = Path(__file__).parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import edinet, analyze, status, checklist, checklist_eval

app = FastAPI(
    title="disclosure-multiagent API",
    description="有価証券報告書の開示変更分析パイプライン",
    version="1.0.0",
)

# CORS for Next.js dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(edinet.router)
app.include_router(analyze.router)
app.include_router(status.router)
app.include_router(checklist.router)
app.include_router(checklist_eval.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "disclosure-multiagent"}
