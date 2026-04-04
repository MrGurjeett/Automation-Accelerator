"""FastAPI dashboard server with WebSocket log streaming."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from dashboard.backend.event_bus import event_bus
from dashboard.backend.routes import status, runs, files

# Ensure project root is on path
from project_root import get_project_root, ensure_importable
PROJECT_ROOT = ensure_importable()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Automation Accelerator Dashboard",
    version="1.0.0",
    description="AI-Driven Test Automation Pipeline Dashboard",
)

# CORS for local dev (Vite runs on :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(status.router)
app.include_router(runs.router)
app.include_router(files.router)



@app.on_event("startup")
async def startup():
    """Initialize database, migrate existing runs, capture event loop."""
    import asyncio
    # Capture the running event loop so the EventBus can publish from threads
    event_bus.set_loop(asyncio.get_running_loop())

    from dashboard.backend.db import init_db, migrate_from_versions
    init_db()
    count = migrate_from_versions()
    if count:
        logger.info("Migrated %d existing runs to database", count)

    # Start a background task that buffers all events for the HTTP fallback
    asyncio.create_task(_buffer_subscriber())


# ── Server-side log buffer (HTTP fallback for browsers where WS fails) ──
_log_buffer: list[dict[str, Any]] = []
_log_buffer_lock = asyncio.Lock() if hasattr(asyncio, 'Lock') else None
_MAX_LOG_BUFFER = 2000


async def _buffer_subscriber() -> None:
    """Background task: subscribe to event_bus and buffer all events."""
    queue = event_bus.subscribe()
    logger.info("[buffer] Background event buffer started")
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=5.0)
            _buffer_event(event)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass


def _buffer_event(event: dict[str, Any]) -> None:
    """Store events in the server-side buffer."""
    global _log_buffer
    _log_buffer.append(event)
    if len(_log_buffer) > _MAX_LOG_BUFFER:
        _log_buffer = _log_buffer[-_MAX_LOG_BUFFER:]


@app.get("/api/live-logs")
async def get_live_logs(since: int = 0):
    """Primary log delivery endpoint. Frontend polls this every 500ms.
    Returns events added after index `since` (cursor-based pagination)."""
    events = _log_buffer[since:] if since < len(_log_buffer) else []
    return {
        "events": events,
        "total": len(_log_buffer),
        "next_since": len(_log_buffer),
    }


@app.post("/api/live-logs/clear")
async def clear_live_logs():
    """Clear the log buffer (called when starting a new run)."""
    global _log_buffer
    _log_buffer = []
    return {"ok": True}


@app.websocket("/ws/logs")
async def websocket_logs(ws: WebSocket):
    """WebSocket endpoint (kept for backward compatibility, not primary delivery)."""
    await ws.accept()
    logger.info("[ws] Browser WebSocket connected")
    queue = event_bus.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await ws.send_text(json.dumps(event))
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "heartbeat"}))
    except WebSocketDisconnect:
        logger.info("[ws] Browser WebSocket disconnected")
    except Exception as exc:
        logger.warning("[ws] WebSocket error: %s", exc)
    finally:
        event_bus.unsubscribe(queue)


# Serve frontend static files (production build)
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve the React SPA - all non-API routes return index.html.
        index.html is served with no-cache so browsers always load latest JS bundle."""
        file_path = FRONTEND_DIST / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(
            str(FRONTEND_DIST / "index.html"),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )


def main():
    """Entry point for running the dashboard server."""
    import uvicorn

    port = int(os.environ.get("DASHBOARD_PORT", "8200"))
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0")

    logging.basicConfig(level=logging.INFO)
    logger.info("Starting Automation Accelerator Dashboard on %s:%d", host, port)

    uvicorn.run(
        "dashboard.backend.server:app",
        host=host,
        port=port,
        reload=True,
        reload_dirs=[str(Path(__file__).parent)],
    )


if __name__ == "__main__":
    main()
