"""
Excel Modifier — test helper for injecting invalid data into Excel inputs.

Creates temporary .xlsx files with controlled defects for testing pipeline
validation, recovery, and decision-making paths.

Usage::

    from tests.helpers.excel_modifier import (
        create_valid_excel,
        create_excel_missing_columns,
        create_excel_invalid_actions,
        create_excel_missing_required_values,
        create_excel_mixed_valid_invalid,
    )

    # Fully valid — should pass validation
    path = create_valid_excel(tmp_path)

    # Missing TC_ID column — schema validation will fail
    path = create_excel_missing_columns(tmp_path, drop_columns=["TC_ID"])

    # Invalid action values — action validation will fail
    path = create_excel_invalid_actions(tmp_path)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical valid data — matches the required schema exactly
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = ["TC_ID", "Page", "Action", "Target", "Value", "Expected"]

VALID_ROWS: list[dict[str, str]] = [
    {
        "TC_ID": "TC001",
        "Page": "Login",
        "Action": "navigate",
        "Target": "Login Page",
        "Value": "-",
        "Expected": "-",
    },
    {
        "TC_ID": "TC001",
        "Page": "Login",
        "Action": "fill",
        "Target": "Username",
        "Value": "testuser",
        "Expected": "-",
    },
    {
        "TC_ID": "TC001",
        "Page": "Login",
        "Action": "fill",
        "Target": "Password",
        "Value": "testpass",
        "Expected": "-",
    },
    {
        "TC_ID": "TC001",
        "Page": "Login",
        "Action": "click",
        "Target": "Login Button",
        "Value": "-",
        "Expected": "-",
    },
    {
        "TC_ID": "TC002",
        "Page": "Login",
        "Action": "navigate",
        "Target": "Login Page",
        "Value": "-",
        "Expected": "-",
    },
    {
        "TC_ID": "TC002",
        "Page": "Login",
        "Action": "fill",
        "Target": "Username",
        "Value": "admin",
        "Expected": "-",
    },
    {
        "TC_ID": "TC002",
        "Page": "Login",
        "Action": "fill",
        "Target": "Password",
        "Value": "admin123",
        "Expected": "-",
    },
    {
        "TC_ID": "TC002",
        "Page": "Login",
        "Action": "click",
        "Target": "Login Button",
        "Value": "-",
        "Expected": "-",
    },
]


def _write_excel(rows: list[dict[str, Any]], path: Path) -> Path:
    """Write rows to an .xlsx file and return the path."""
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
    logger.debug("Created test Excel: %s (%d rows)", path, len(rows))
    return path


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def create_valid_excel(directory: Path, filename: str = "valid_input.xlsx") -> Path:
    """Create a fully valid Excel file that should pass all validation stages.

    Returns
    -------
    Path
        Path to the created .xlsx file.
    """
    return _write_excel(VALID_ROWS, directory / filename)


def create_excel_missing_columns(
    directory: Path,
    drop_columns: list[str] | None = None,
    filename: str = "missing_columns.xlsx",
) -> Path:
    """Create an Excel file with missing required columns.

    This triggers schema validation failure (``validate_schema`` raises ValueError).

    Parameters
    ----------
    drop_columns : list[str]
        Columns to remove.  Default: ``["TC_ID"]``.
    """
    drops = drop_columns or ["TC_ID"]
    rows = [{k: v for k, v in row.items() if k not in drops} for row in VALID_ROWS]
    return _write_excel(rows, directory / filename)


def create_excel_invalid_actions(
    directory: Path,
    invalid_action: str = "explode",
    filename: str = "invalid_actions.xlsx",
) -> Path:
    """Create an Excel file where some rows have unsupported Action values.

    This triggers action validation failure for the affected test cases.

    Parameters
    ----------
    invalid_action : str
        The unsupported action to inject (default: ``"explode"``).
    """
    rows = [dict(row) for row in VALID_ROWS]
    # Inject invalid action into TC001's second step
    rows[1] = {**rows[1], "Action": invalid_action}
    return _write_excel(rows, directory / filename)


def create_excel_missing_required_values(
    directory: Path,
    filename: str = "missing_values.xlsx",
) -> Path:
    """Create an Excel file with missing required values.

    - ``fill`` action with Value = ``"-"`` (dash = not applicable, invalid for fill)

    This triggers action validation failure for the affected test case.
    """
    rows = [dict(row) for row in VALID_ROWS]
    # fill with dash value — invalid (dash means "not applicable" for fill)
    # Row index 1 is TC001's "fill Username" step
    rows[1] = {**rows[1], "Value": "-"}
    return _write_excel(rows, directory / filename)


def create_excel_mixed_valid_invalid(
    directory: Path,
    filename: str = "mixed_input.xlsx",
) -> Path:
    """Create an Excel file where TC001 is invalid but TC002 is valid.

    This tests partial validation: TC001 should be rejected while TC002 passes.
    Useful for testing recovery agents that operate on rejected test cases.
    """
    rows = [dict(row) for row in VALID_ROWS]
    # Make TC001 invalid: unsupported action on fill step (index 1)
    rows[1] = {**rows[1], "Action": "destroy"}
    # TC002 (indices 4-7) remains valid
    return _write_excel(rows, directory / filename)


def create_excel_custom(
    directory: Path,
    rows: list[dict[str, str]],
    filename: str = "custom_input.xlsx",
) -> Path:
    """Create an Excel file with fully custom row data.

    Parameters
    ----------
    rows : list[dict]
        Each dict must have the required column keys.
    """
    return _write_excel(rows, directory / filename)


def inject_invalid_rows(
    source_rows: list[dict[str, str]],
    *,
    add_bad_actions: int = 0,
    remove_values: int = 0,
    bad_action_name: str = "explode",
) -> list[dict[str, str]]:
    """Modify an existing row list in-place for testing.

    Parameters
    ----------
    source_rows : list[dict]
        Original valid rows (will be copied, not mutated).
    add_bad_actions : int
        Number of rows to change to an unsupported action.
    remove_values : int
        Number of 'fill' rows to set Value to '-' (invalid).
    bad_action_name : str
        The unsupported action to inject.

    Returns
    -------
    list[dict]
        Modified copy of the rows.
    """
    rows = [dict(row) for row in source_rows]
    modified = 0

    if add_bad_actions > 0:
        for i, row in enumerate(rows):
            if modified >= add_bad_actions:
                break
            rows[i] = {**row, "Action": bad_action_name}
            modified += 1

    modified = 0
    if remove_values > 0:
        for i, row in enumerate(rows):
            if modified >= remove_values:
                break
            if row.get("Action") == "fill":
                rows[i] = {**row, "Value": "-"}
                modified += 1

    return rows
