"""Workspace bootstrap for consistent environment configuration.

Python automatically imports `sitecustomize` (if present on `sys.path`) during
startup. We use that to load this repo's `.env` early so subprocesses and tools
(Neuro-SAN server/client, pytest, etc.) see the same environment variables.

This file is intentionally small and safe:
- No hard failures if python-dotenv is missing.
- Does not overwrite existing env vars unless DOTENV_OVERRIDE is set.
"""

from __future__ import annotations

import os
from pathlib import Path


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    repo_root = Path(__file__).resolve().parent
    env_file = repo_root / ".env"
    if not env_file.exists():
        return

    override = _truthy(os.getenv("DOTENV_OVERRIDE"))
    load_dotenv(dotenv_path=env_file, override=override)


def _set_compat_env_aliases() -> None:
    # Neuro-SAN's Azure policy primarily reads OPENAI_API_VERSION and
    # AZURE_OPENAI_DEPLOYMENT_NAME; this repo uses AZURE_OPENAI_API_VERSION and
    # AZURE_OPENAI_CHAT_DEPLOYMENT.
    if not os.getenv("OPENAI_API_VERSION") and os.getenv("AZURE_OPENAI_API_VERSION"):
        os.environ["OPENAI_API_VERSION"] = os.environ["AZURE_OPENAI_API_VERSION"]

    if not os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") and os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT"):
        os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"] = os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"]


_load_env()
_set_compat_env_aliases()
