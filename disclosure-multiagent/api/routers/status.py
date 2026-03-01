"""Pipeline status endpoint with SSE support."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from api.models.schemas import PipelineStatus
from api.services.pipeline import get_task

router = APIRouter(prefix="/api", tags=["status"])


@router.get("/status/{task_id}", response_model=PipelineStatus)
async def get_status(task_id: str):
    """タスク状態をJSON形式で取得 (ポーリング用)."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task not found: {task_id}")
    return task


@router.get("/status/{task_id}/stream")
async def stream_status(task_id: str):
    """SSEでパイプライン進捗をリアルタイムストリーム."""
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task not found: {task_id}")

    async def event_generator():
        last_state = ""
        while True:
            task = get_task(task_id)
            if not task:
                break

            current_state = json.dumps(task.model_dump(), ensure_ascii=False, default=str)
            if current_state != last_state:
                last_state = current_state
                yield {
                    "event": "status",
                    "data": current_state,
                }

            if task.status in ("done", "error"):
                yield {
                    "event": "complete",
                    "data": current_state,
                }
                break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())
