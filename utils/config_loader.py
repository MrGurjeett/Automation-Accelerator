"""Secure configuration loader.

Loads ``config/config.yaml``, resolves ``${ENV_VAR}`` placeholders from
the environment, validates URLs for HTTPS in non-dev environments, and
ensures the ``.env`` file (if present) has restrictive permissions.
"""

from __future__ import annotations

import logging
import os
import re
import stat
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.yaml"
_ENV_PATH = _PROJECT_ROOT / ".env"
_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")

# Environments where plain-HTTP URLs are acceptable (development only).
_HTTPS_EXEMPT_ENVS: frozenset[str] = frozenset({"dev", "local", "test"})


# ── .env permission check ─────────────────────────────────────────────────

def _check_env_file_permissions(env_path: Path = _ENV_PATH) -> None:
    """Warn if ``.env`` file is world- or group-readable (Unix only).

    On macOS/Linux the file should be ``600`` (owner read/write only).
    """
    if not env_path.exists():
        return
    try:
        mode = env_path.stat().st_mode
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            logger.warning(
                ".env file has overly permissive permissions (%o). "
                "Run: chmod 600 %s",
                stat.S_IMODE(mode),
                env_path,
            )
    except OSError:
        pass  # Non-Unix or virtual filesystem — skip


# ── YAML loading with safe_load ────────────────────────────────────────────

def _safe_load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML with ``yaml.safe_load`` to prevent arbitrary object
    instantiation (CWE-502)."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping at top level in {path}")
    return data


# ── Environment-variable resolution ───────────────────────────────────────

def _resolve_value(value: Any) -> Any:
    """Recursively resolve ``${VAR}`` placeholders in strings, lists, dicts."""
    if isinstance(value, str):
        return _ENV_VAR_RE.sub(
            lambda m: os.environ.get(m.group(1), m.group(0)), value
        )
    if isinstance(value, dict):
        return {k: _resolve_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item) for item in value]
    return value


# ── URL TLS validation ─────────────────────────────────────────────────────

def _validate_urls_https(cfg: dict[str, Any], env_name: str) -> None:
    """In non-dev environments, ensure all configured URLs use HTTPS."""
    if env_name in _HTTPS_EXEMPT_ENVS:
        return

    for section in ("environments", "api", "ai"):
        _walk_for_urls(cfg.get(section, {}), section, env_name)


def _walk_for_urls(obj: Any, path: str, env_name: str) -> None:
    if isinstance(obj, str) and obj.startswith("http://"):
        logger.warning(
            "Insecure HTTP URL in config [%s] for env '%s': %s  — "
            "use HTTPS in non-development environments.",
            path, env_name, obj,
        )
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk_for_urls(v, f"{path}.{k}", env_name)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_for_urls(v, f"{path}[{i}]", env_name)


# ── Config wrapper class ──────────────────────────────────────────────────

class Config:
    """Read-only configuration wrapper with section accessors.

    Exposes the resolved ``config.yaml`` via typed helpers that match the
    interface expected by ``conftest.py``, ``test_api.py``, etc.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self._environment = data.get("environment", "qa")

    # ── Section accessors ──────────────────────────────────────────────

    def get_environment_config(self) -> dict[str, Any]:
        envs = self._data.get("environments", {})
        return dict(envs.get(self._environment, {}))

    def get_browser_config(self) -> dict[str, Any]:
        return dict(self._data.get("browser", {}))

    def get_test_config(self) -> dict[str, Any]:
        return dict(self._data.get("test", {}))

    def get_database_config(self) -> dict[str, Any]:
        return dict(self._data.get("database", {}))

    def get_email_config(self) -> dict[str, Any]:
        return dict(self._data.get("email", {}))

    def get_reporting_config(self) -> dict[str, Any]:
        return dict(self._data.get("reporting", {}))

    def get_api_config(self) -> dict[str, Any]:
        return dict(self._data.get("api", {}))

    def get_ai_config(self) -> dict[str, Any]:
        return dict(self._data.get("ai", {}))

    # ── Generic getter ─────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


# ── Public API ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_config(config_path: str | Path | None = None) -> Config:
    """Load and cache the project configuration.

    Steps:
    1. Load ``.env`` (if present) and check its file permissions.
    2. Parse ``config/config.yaml`` with ``yaml.safe_load``.
    3. Resolve ``${ENV_VAR}`` placeholders.
    4. Warn on plain-HTTP URLs outside dev environments.
    5. Return a ``Config`` wrapper for typed access.

    The result is cached so repeated calls return the same instance.
    """
    path = Path(config_path) if config_path else _CONFIG_PATH

    # 1. Load .env
    load_dotenv(_ENV_PATH)
    _check_env_file_permissions()

    # 2. Parse YAML
    raw = _safe_load_yaml(path)

    # 3. Resolve env vars
    resolved = _resolve_value(raw)

    # 4. TLS check
    env_name = resolved.get("environment", "qa")
    _validate_urls_https(resolved, env_name)

    return Config(resolved)
