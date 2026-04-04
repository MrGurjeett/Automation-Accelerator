"""Run control and history API routes."""
from __future__ import annotations

import base64
import json
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dashboard.backend.run_manager import run_manager, ARTIFACTS_DIR

router = APIRouter()

from project_root import get_project_root

PROJECT_ROOT = get_project_root()


class StartRunRequest(BaseModel):
    mode: str = "pipeline"
    force: bool = False
    scan: bool = False
    env: dict[str, str] = {}
    config: str | None = None  # Named pipeline config (overrides mode)


class UploadExcelRequest(BaseModel):
    filename: str
    content_base64: str


@router.post("/api/run")
async def start_run(req: StartRunRequest):
    state = run_manager.start(
        mode=req.mode,
        force=req.force,
        scan=req.scan,
        env=req.env,
        config=req.config,
    )
    if state.error and not state.running:
        raise HTTPException(status_code=409, detail=state.error)
    return {"ok": True, "state": state.to_dict()}


@router.post("/api/stop")
async def stop_run():
    state = run_manager.stop()
    return {"ok": True, "state": state.to_dict()}


@router.post("/api/pause")
async def pause_run():
    run_manager.pause()
    return {"ok": True, "state": run_manager.status().to_dict()}


@router.post("/api/resume")
async def resume_run():
    run_manager.resume()
    return {"ok": True, "state": run_manager.status().to_dict()}


@router.get("/api/configs")
async def list_configs():
    """List all available pipeline configs."""
    try:
        from pipeline.config import list_available_configs
        configs = list_available_configs()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"configs": configs}


@router.post("/api/clear_output")
async def clear_output():
    removed = []
    # Clear generated features
    gen_dir = PROJECT_ROOT / "generated" / "features"
    if gen_dir.exists():
        for f in gen_dir.glob("*.feature"):
            f.unlink()
            removed.append(str(f.name))

    # Clear stats artifacts
    for name in ("latest_run.json", "latest_stats.json"):
        p = ARTIFACTS_DIR / name
        if p.exists():
            p.unlink()
            removed.append(name)

    return {"ok": True, "removed": removed}


@router.post("/api/upload_excel")
async def upload_excel(req: UploadExcelRequest):
    # Sanitize filename
    filename = re.sub(r"[^\w\-. ]", "_", req.filename)
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xls files allowed")

    try:
        content = base64.b64decode(req.content_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 content")

    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 25MB)")

    input_dir = PROJECT_ROOT / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    dest = input_dir / filename
    dest.write_bytes(content)

    return {"ok": True, "path": str(dest.relative_to(PROJECT_ROOT)), "size": len(content)}


@router.get("/api/runs")
async def list_runs():
    """List all versioned runs from artifacts/versions/."""
    versions_dir = ARTIFACTS_DIR / "versions"
    runs = []
    if versions_dir.exists():
        for folder in sorted(versions_dir.iterdir(), reverse=True):
            if not folder.is_dir():
                continue
            summary_path = folder / "run_summary.json"
            entry = {"folder": folder.name, "path": str(folder)}
            if summary_path.exists():
                try:
                    entry["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
                except Exception:
                    entry["summary"] = None
            runs.append(entry)
    return {"runs": runs}


@router.get("/api/runs/db")
async def list_runs_db(limit: int = 100, offset: int = 0):
    """List runs from SQLite database."""
    from dashboard.backend.db import get_all_runs
    return {"runs": get_all_runs(limit, offset)}


@router.get("/api/analytics")
async def get_analytics():
    """Return analytics data for charts."""
    from dashboard.backend.db import get_analytics
    return get_analytics()
