"""
Version Manager — mtime-based versioning for generated artifacts.

If Excel file modification timestamp changed → regenerate.
If unchanged → execute existing feature.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

VERSIONS_DIR = "artifacts/versions"
LATEST_MANIFEST = "artifacts/latest.json"


def compute_hash(file_path: str | Path) -> str:
    """Compute SHA256 hash of a file (used for version folder naming)."""
    with open(file_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def has_changed(excel_path: str | Path) -> bool:
    """Check if the Excel file has changed since last generation.

    Uses file modification timestamp (mtime) instead of SHA256 hash
    to reliably detect when the Excel file has been modified.
    """
    current_mtime = os.path.getmtime(excel_path)
    manifest = _load_manifest()
    stored_mtime = manifest.get("mtime")

    if stored_mtime is None or stored_mtime != current_mtime:
        logger.info(
            "Excel mtime changed: stored=%s, current=%s",
            stored_mtime, current_mtime,
        )
        return True

    logger.info("Excel mtime unchanged (%s). No regeneration needed.", current_mtime)
    return False


def create_version_folder(excel_path: str | Path) -> str:
    """Create a versioned output folder and update the manifest.

    Returns the absolute path to the new version folder.
    """
    file_hash = compute_hash(excel_path)
    current_mtime = os.path.getmtime(excel_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{file_hash[:12]}_{timestamp}"
    folder_path = os.path.join(VERSIONS_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    # Update manifest with mtime for change detection
    manifest = {
        "hash": file_hash,
        "mtime": current_mtime,
        "timestamp": timestamp,
        "folder": folder_path,
        "excel": str(excel_path),
    }
    _save_manifest(manifest)
    logger.info("Version folder created: %s", folder_path)
    return folder_path


def get_latest_version_folder() -> str | None:
    """Return the latest version folder path, or None."""
    manifest = _load_manifest()
    folder = manifest.get("folder")
    if folder and os.path.isdir(folder):
        return folder
    return None


def save_artifact(version_folder: str, filename: str, content: str) -> str:
    """Save a generated artifact into the version folder."""
    path = os.path.join(version_folder, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info("Artifact saved: %s", path)
    return path


# ── Internal helpers ────────────────────────────────────────────────────

def _load_manifest() -> dict:
    if os.path.exists(LATEST_MANIFEST):
        with open(LATEST_MANIFEST, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_manifest(data: dict) -> None:
    os.makedirs(os.path.dirname(LATEST_MANIFEST), exist_ok=True)
    with open(LATEST_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
