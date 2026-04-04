"""Status and progress API routes."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from dashboard.backend.run_manager import run_manager, ARTIFACTS_DIR, LOG_PATH

router = APIRouter()

from project_root import get_project_root

PROJECT_ROOT = get_project_root()


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


@router.get("/api/status")
async def get_status():
    state = run_manager.status()
    return {
        "state": state.to_dict(),
        "ui_state": _read_json(ARTIFACTS_DIR / "ui_state.json"),
        "latest_run": _read_json(ARTIFACTS_DIR / "latest_run.json"),
        "latest_stats": _read_json(ARTIFACTS_DIR / "latest_stats.json"),
        "cumulative_stats": _read_json(ARTIFACTS_DIR / "cumulative_stats.json"),
    }


@router.get("/api/progress")
async def get_progress():
    return run_manager.get_progress()


@router.get("/api/logs")
async def get_logs(lines: int = 200):
    lines = min(max(lines, 1), 2000)
    return {"lines": run_manager.tail(lines)}


@router.get("/api/inputs")
async def get_inputs():
    input_dir = PROJECT_ROOT / "input"
    files = []
    if input_dir.exists():
        for f in sorted(input_dir.iterdir()):
            if f.suffix.lower() in (".xlsx", ".xls"):
                files.append({
                    "name": f.name,
                    "path": str(f.relative_to(PROJECT_ROOT)),
                    "is_raw": "_raw" in f.stem.lower(),
                    "size": f.stat().st_size,
                })
    return {"files": files}
