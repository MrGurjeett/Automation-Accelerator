"""File browsing and reading API routes."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

from project_root import get_project_root

PROJECT_ROOT = get_project_root()

ALLOWED_ROOTS = {
    "artifacts": PROJECT_ROOT / "artifacts",
    "generated": PROJECT_ROOT / "generated",
    "docs": PROJECT_ROOT / "docs",
    "core": PROJECT_ROOT / "core",
    "framework": PROJECT_ROOT / "framework",
    "input": PROJECT_ROOT / "input",
}

ALLOWED_TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".txt", ".md", ".rst", ".csv",
    ".feature", ".gherkin", ".html", ".css", ".xml", ".hocon",
    ".env", ".sh", ".bat", ".ps1", ".log",
}


@router.get("/api/files")
async def list_files(root: str = "artifacts"):
    if root not in ALLOWED_ROOTS:
        raise HTTPException(status_code=400, detail=f"Invalid root: {root}")

    base = ALLOWED_ROOTS[root]
    if not base.exists():
        return {"files": [], "root": root}

    entries = []
    for item in sorted(base.rglob("*")):
        if item.is_file():
            rel = item.relative_to(base)
            entries.append({
                "name": item.name,
                "path": f"{root}/{rel.as_posix()}",
                "size": item.stat().st_size,
                "is_dir": False,
                "ext": item.suffix.lower(),
            })
        elif item.is_dir():
            rel = item.relative_to(base)
            entries.append({
                "name": item.name,
                "path": f"{root}/{rel.as_posix()}",
                "size": 0,
                "is_dir": True,
                "ext": "",
            })

    return {"files": entries, "root": root}


@router.get("/api/file")
async def read_file(path: str):
    # Security: validate path is within allowed roots
    parts = path.split("/", 1)
    if len(parts) < 2 or parts[0] not in ALLOWED_ROOTS:
        raise HTTPException(status_code=400, detail="Invalid path")

    base = ALLOWED_ROOTS[parts[0]]
    full_path = (base / parts[1]).resolve()

    # Path traversal check
    if not str(full_path).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Not a file")

    ext = full_path.suffix.lower()
    if ext not in ALLOWED_TEXT_EXTS:
        raise HTTPException(status_code=400, detail=f"File type {ext} not supported")

    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    mime = mimetypes.guess_type(str(full_path))[0] or "text/plain"

    return {
        "path": path,
        "content": content,
        "size": full_path.stat().st_size,
        "mime": mime,
        "ext": ext,
    }
