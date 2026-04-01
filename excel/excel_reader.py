"""
Excel Reader — reads the strict-contract .xlsx input.

Only .xlsx is accepted. Returns list[dict] with exact column names.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def read_excel(file_path: str | Path) -> list[dict[str, str]]:
    """Read an Excel file and return rows as list of dicts.

    Raises
    ------
    ValueError
        If the file is not .xlsx or is empty.
    FileNotFoundError
        If the file does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")
    if path.suffix.lower() != ".xlsx":
        raise ValueError(f"Only .xlsx files are supported, got '{path.suffix}'")

    df = pd.read_excel(path, dtype=str)
    # Value column: blanks → empty string (supports empty-field tests)
    # All other columns: blanks → "-"
    if "Value" in df.columns:
        df["Value"] = df["Value"].fillna("")
    df = df.fillna("-")
    rows = df.to_dict("records")

    if not rows:
        raise ValueError("Excel file contains no data rows")

    logger.info("Excel loaded: %d rows from %s", len(rows), path.name)
    return rows
