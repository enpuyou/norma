"""Server-Sent Events — real-time updates for trust changes, runs, violations.

Clients subscribe to GET /api/events/stream and receive JSON event objects:
  - run_completed:      new run finished (quality, trust, status)
  - trust_changed:      agent trust score updated
  - violation_detected: enforcement triggered
  - agent_created:      new agent onboarded

Usage in frontend:
  const es = new EventSource("http://localhost:8080/api/events/stream");
  es.onmessage = (e) => { const data = JSON.parse(e.data); ... };
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

router = APIRouter()

# ── In-process event bus ──────────────────────────────────────────────────────
# For single-process deploys (which is what we have with SQLite).
# For multi-process, swap for Redis pub/sub.

_subscribers: list[asyncio.Queue] = []


def broadcast(event_type: str, data: dict[str, Any]) -> None:
    """Push an event to all connected SSE clients. Fire-and-forget."""
    payload = {
        "type": event_type,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    dead: list[asyncio.Queue] = []
    for q in _subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    # Prune dead queues
    for q in dead:
        _subscribers.remove(q)


async def _event_generator(queue: asyncio.Queue):
    """Yield SSE-formatted messages from queue."""
    try:
        # Send initial heartbeat
        yield f"data: {json.dumps({'type': 'connected', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # keepalive
                yield f": keepalive {datetime.now(timezone.utc).isoformat()}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        if queue in _subscribers:
            _subscribers.remove(queue)


@router.post("/broadcast")
async def broadcast_event(body: dict = Body(...)) -> dict:
    """Allow external callers (e.g. norma-watch CLI) to fire SSE events."""
    event_type = body.pop("type", "run_started")
    broadcast(event_type, body)
    return {"ok": True}


@router.get("/stream")
async def event_stream():
    """SSE endpoint — streams real-time events to the dashboard."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.append(queue)

    return StreamingResponse(
        _event_generator(queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
