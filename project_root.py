"""Centralised project root resolution.

Every module that needs to know the Automation-Accelerator root directory
should call :func:`get_project_root` rather than computing
``Path(__file__).resolve().parents[N]`` locally.  This eliminates the
fragile ``parents[N]`` pattern that broke whenever files moved between
directories.

Resolution order
----------------
1. ``AA_ROOT`` environment variable (explicit, always wins)
2. Filesystem walk — ascend from *this* file until we find the sentinel
   ``main.py`` that lives at the repo root.

The result is cached after the first call (module-level ``_CACHED_ROOT``).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHED_ROOT: Path | None = None

# Sentinel file that uniquely identifies the Automation-Accelerator root.
_SENTINEL = "main.py"


def get_project_root() -> Path:
    """Return the Automation-Accelerator project root as an absolute Path.

    Raises
    ------
    RuntimeError
        If the root cannot be determined (env var missing *and* sentinel
        file not found in any ancestor directory).
    """
    global _CACHED_ROOT
    if _CACHED_ROOT is not None:
        return _CACHED_ROOT

    # 1. Explicit environment variable
    env_root = os.environ.get("AA_ROOT", "").strip()
    if env_root:
        p = Path(env_root).resolve()
        if not p.is_dir():
            raise RuntimeError(
                f"AA_ROOT is set to '{env_root}' but it is not a valid directory."
            )
        _CACHED_ROOT = p
        logger.debug("Project root from AA_ROOT: %s", _CACHED_ROOT)
        return _CACHED_ROOT

    # 2. Walk up from this file to find the sentinel
    current = Path(__file__).resolve().parent
    for _ in range(10):  # safety limit
        if (current / _SENTINEL).is_file():
            _CACHED_ROOT = current
            logger.debug("Project root from sentinel: %s", _CACHED_ROOT)
            return _CACHED_ROOT
        parent = current.parent
        if parent == current:
            break
        current = parent

    raise RuntimeError(
        "Cannot determine the Automation-Accelerator project root.  "
        "Set the AA_ROOT environment variable to the absolute path of the "
        "repository root (the directory that contains main.py)."
    )


def ensure_importable() -> Path:
    """Ensure the project root is on ``sys.path`` so internal packages
    (``ai``, ``pipeline``, ``utils``, etc.) are importable.

    Returns the root path for convenience.
    """
    root = get_project_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root
