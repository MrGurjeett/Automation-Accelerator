"""ADO Data Source — fetch test case data from Azure DevOps Git repos.

Implements the ADO-first, Excel-fallback pipeline input strategy:
  1. If ADO is configured (env vars + data URL), fetch JSON from ADO Git
  2. Save locally as input/ado_data.json
  3. If ADO is not configured or fails, fall back to Excel in input/

Environment variables:
  - ADO_ORGANIZATION / ADO_ORG  — Azure DevOps organization name
  - ADO_PROJECT                 — Azure DevOps project name
  - ADO_PAT                     — Personal Access Token
  - ADO_DATA_URL                — Full ADO Git Items API URL for the data file
  - ADO_DATA_REPO               — (alt) Repository name (defaults to project)
  - ADO_DATA_PATH               — (alt) File path within the repo
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def fetch_ado_data(input_dir: str | Path | None = None) -> dict[str, Any]:
    """Try to fetch test data from ADO. Returns status dict.

    Returns:
        {
            "source": "ado" | "excel" | "none",
            "ok": bool,
            "data_path": str | None,  # local file path to use
            "rows": list[dict] | None,  # parsed rows if available
            "message": str,
        }
    """
    # Determine input directory
    aa_root = Path(__file__).resolve().parent.parent
    if input_dir is None:
        input_dir = aa_root / "input"
    else:
        input_dir = Path(input_dir)

    # Check if ADO is configured
    ado_org = os.environ.get("ADO_ORGANIZATION") or os.environ.get("ADO_ORG")
    ado_project = os.environ.get("ADO_PROJECT")
    ado_pat = os.environ.get("ADO_PAT")
    ado_data_url = os.environ.get("ADO_DATA_URL")
    ado_data_repo = os.environ.get("ADO_DATA_REPO")
    ado_data_path = os.environ.get("ADO_DATA_PATH")

    if not all([ado_org, ado_pat]) or not (ado_data_url or ado_data_path):
        logger.info("[ADO DataSource] ADO not configured — will use Excel fallback")
        return _excel_fallback(input_dir, "ADO not configured (missing env vars)", use_ado_cache=False)

    # Try to fetch from ADO
    try:
        from pipeline.connectors.ado import ADOConnector

        connector = ADOConnector(
            organization=ado_org,
            project=ado_project or "",
            pat=ado_pat,
        )

        result = connector.connect()
        if not result.ok:
            logger.warning("[ADO DataSource] ADO connect failed: %s", result.error)
            return _excel_fallback(input_dir, f"ADO connect failed: {result.error}")

        # Fetch the data file
        fetch_query: dict[str, Any] = {"type": "git_file"}
        if ado_data_url:
            fetch_query["url"] = ado_data_url
        else:
            fetch_query["path"] = ado_data_path
            if ado_data_repo:
                fetch_query["repository"] = ado_data_repo

        result = connector.fetch(fetch_query)

        if not result.ok:
            logger.warning("[ADO DataSource] ADO fetch failed: %s", result.error)
            return _excel_fallback(input_dir, f"ADO fetch failed: {result.error}")

        content = result.data.get("content")
        if content is None:
            return _excel_fallback(input_dir, "ADO returned empty content")

        # Parse the data
        rows = _parse_ado_content(content)
        if not rows:
            return _excel_fallback(input_dir, "ADO data has no rows")

        # Save locally for pipeline to use
        local_path = input_dir / "ado_data.json"
        input_dir.mkdir(parents=True, exist_ok=True)
        local_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

        logger.info(
            "[ADO DataSource] Fetched %d test cases from ADO → %s",
            len(rows), local_path,
        )

        return {
            "source": "ado",
            "ok": True,
            "data_path": str(local_path),
            "rows": rows,
            "row_count": len(rows),
            "message": f"Fetched {len(rows)} test cases from ADO",
        }

    except ImportError as exc:
        logger.warning("[ADO DataSource] Cannot import ADO connector: %s", exc)
        return _excel_fallback(input_dir, f"Import error: {exc}")
    except Exception as exc:
        logger.error("[ADO DataSource] Unexpected error: %s", exc, exc_info=True)
        return _excel_fallback(input_dir, f"Error: {exc}")


def _parse_ado_content(content: Any) -> list[dict[str, Any]]:
    """Parse ADO file content into rows (list of dicts).

    Supports:
      - Direct list of dicts: [{TC_ID, Page, Action, ...}, ...]
      - Object with "rows" key: {"rows": [...]}
      - Object with "test_cases" key: {"test_cases": [...]}
      - Object with "testCases" key: {"testCases": [...]}
    """
    if isinstance(content, list):
        return content
    if isinstance(content, dict):
        for key in ("rows", "test_cases", "testCases", "data", "items"):
            if key in content and isinstance(content[key], list):
                return content[key]
        # If dict has TC_ID-like keys, it might be a single test case
        if "TC_ID" in content or "Page" in content:
            return [content]
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
            return _parse_ado_content(parsed)
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _excel_fallback(
    input_dir: Path, reason: str, *, use_ado_cache: bool = True,
) -> dict[str, Any]:
    """Fall back to Excel file in input directory.

    Parameters
    ----------
    use_ado_cache : bool
        If True (default), prefer cached ado_data.json from a previous run.
        If False (when ADO is not configured at all), skip the cache and
        go straight to Excel files.
    """
    # Look for Excel files
    excel_files = sorted(input_dir.glob("*.xlsx")) if input_dir.exists() else []

    # Only use cached ADO JSON if ADO was configured but the fetch failed
    # (NOT when ADO is entirely unconfigured — user expects Excel in that case)
    if use_ado_cache:
        ado_json = input_dir / "ado_data.json"
        if ado_json.exists():
            try:
                rows = json.loads(ado_json.read_text(encoding="utf-8"))
                if rows:
                    logger.info(
                        "[ADO DataSource] Using cached ADO data: %s (%d rows)",
                        ado_json, len(rows),
                    )
                    return {
                        "source": "ado_cached",
                        "ok": True,
                        "data_path": str(ado_json),
                        "rows": rows,
                        "row_count": len(rows),
                        "message": f"Using cached ADO data ({len(rows)} rows). ADO fetch skipped: {reason}",
                    }
            except Exception:
                pass

    if excel_files:
        logger.info(
            "[ADO DataSource] Falling back to Excel: %s (reason: %s)",
            excel_files[0].name, reason,
        )
        return {
            "source": "excel",
            "ok": True,
            "data_path": str(excel_files[0]),
            "rows": None,  # Let the pipeline read it via normal Excel flow
            "message": f"Using Excel input: {excel_files[0].name}. ADO: {reason}",
        }

    return {
        "source": "none",
        "ok": False,
        "data_path": None,
        "rows": None,
        "message": f"No input data found. ADO: {reason}. No Excel in {input_dir}",
    }
