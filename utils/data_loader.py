"""Secure test-data loader.

Loads test data from ``config/testdata/`` (YAML or JSON) and provides
dot-notation key traversal (e.g. ``"users.valid_user"``).

Security considerations:
- Uses ``yaml.safe_load`` (prevents arbitrary object instantiation).
- Validates file paths to prevent directory traversal.
- Restricts file extensions to ``.yaml``, ``.yml``, ``.json``.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

from project_root import get_project_root

_PROJECT_ROOT = get_project_root()
_TESTDATA_DIR = _PROJECT_ROOT / "config" / "testdata"
_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".yaml", ".yml", ".json"})


def _validate_data_path(path: Path) -> Path:
    """Ensure *path* resolves within the testdata directory."""
    resolved = path.resolve()
    if not str(resolved).startswith(str(_TESTDATA_DIR.resolve())):
        raise ValueError(
            f"Test data path traversal blocked: {path!r} is outside testdata dir."
        )
    if resolved.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported test data extension '{resolved.suffix}'. "
            f"Allowed: {_ALLOWED_EXTENSIONS}"
        )
    return resolved


@lru_cache(maxsize=16)
def _load_data_file(path: Path) -> dict[str, Any]:
    """Load a single data file (YAML or JSON) with caching."""
    safe_path = _validate_data_path(path)
    with open(safe_path, "r", encoding="utf-8") as fh:
        if safe_path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(fh)
        else:
            data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping at top level in {safe_path}")
    return data


def _resolve_dotpath(data: dict[str, Any], dotpath: str) -> Any:
    """Walk a dict hierarchy using a dot-separated key path.

    Example: ``_resolve_dotpath(data, "users.valid_user")`` returns
    ``data["users"]["valid_user"]``.
    """
    parts = dotpath.split(".")
    current: Any = data
    for part in parts:
        if not isinstance(current, dict):
            raise KeyError(
                f"Cannot descend into non-dict at '{part}' (full path: {dotpath})"
            )
        if part not in current:
            raise KeyError(f"Key '{part}' not found (full path: {dotpath})")
        current = current[part]
    return current


class DataLoader:
    """Load and query test data from the ``config/testdata/`` directory.

    Provides two main entry points:

    - ``DataLoader.get_test_data("users.valid_user")`` — loads the default
      data file (``sample_data.yaml``) and traverses via dot-notation.
    - ``DataLoader.load_file("custom.json")`` — loads an arbitrary data file
      from the test-data directory.
    """

    _default_file: str = "sample_data.yaml"

    @classmethod
    def get_test_data(cls, dotpath: str, *, filename: str | None = None) -> Any:
        """Return a value from the test data using dot-notation traversal.

        Args:
            dotpath: Dot-separated key path, e.g. ``"users.valid_user"``.
            filename: Optional data file name (default ``sample_data.yaml``).

        Returns:
            The value at the given path (dict, list, scalar, …).
        """
        fname = filename or cls._default_file
        data = _load_data_file(_TESTDATA_DIR / fname)
        return _resolve_dotpath(data, dotpath)

    @classmethod
    def load_file(cls, filename: str) -> dict[str, Any]:
        """Load an entire test-data file and return its top-level dict."""
        return dict(_load_data_file(_TESTDATA_DIR / filename))

    @classmethod
    def get_all_test_data(cls, *, filename: str | None = None) -> dict[str, Any]:
        """Return the full contents of a test-data file as a dict."""
        fname = filename or cls._default_file
        return dict(_load_data_file(_TESTDATA_DIR / fname))
