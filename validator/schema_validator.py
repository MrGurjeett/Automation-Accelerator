"""
Schema Validator — enforces the strict Excel column contract.

Exact match only. Missing, extra, or renamed columns → hard stop.
"""
from __future__ import annotations

import logging
from typing import Sequence

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"TC_ID", "Page", "Action", "Target", "Value", "Expected"}


def validate_schema(columns: Sequence[str]) -> None:
    """Validate that columns match the required schema exactly.

    Raises
    ------
    ValueError
        On any schema mismatch (missing, extra, or renamed columns).
    """
    incoming = set(columns)
    if incoming == REQUIRED_COLUMNS:
        logger.info("Schema validated — columns match exactly.")
        return

    missing = REQUIRED_COLUMNS - incoming
    extra = incoming - REQUIRED_COLUMNS
    parts: list[str] = []
    if missing:
        parts.append(f"Missing: {sorted(missing)}")
    if extra:
        parts.append(f"Extra: {sorted(extra)}")
    raise ValueError(f"Schema mismatch. {'; '.join(parts)}")
