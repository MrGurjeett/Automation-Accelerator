"""Pipeline utility functions — extracted from main.py to avoid circular imports.

These functions are pure utilities with no dependency on PipelineService,
making them safe to import from both ``main.py`` and ``pipeline.service``.
"""
from __future__ import annotations

import glob
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ── Excel auto-detection constants ─────────────────────────────────────

INPUT_DIR = "input"
RAW_SUFFIX = "_raw"  # e.g. test_cases_raw.xlsx


def detect_excel() -> tuple[str, str | None]:
    """Auto-detect Excel files in the input/ folder.

    Returns
    -------
    tuple[str, str | None]
        (template_path, raw_path).
        - If only a structured template exists: (template, None)
        - If only a raw file exists: (generated_template, raw_path)
        - If both exist: (template, raw_path)  — raw takes priority and
          will overwrite the template during conversion.

    Raises
    ------
    FileNotFoundError
        If input/ does not exist or contains no .xlsx files.
    """
    if not os.path.isdir(INPUT_DIR):
        raise FileNotFoundError(
            f"Input folder '{INPUT_DIR}/' not found. "
            f"Create it and place your Excel file there."
        )

    xlsx_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.xlsx")))
    if not xlsx_files:
        raise FileNotFoundError(
            f"No .xlsx files found in '{INPUT_DIR}/'. "
            f"Place your test-case Excel file there."
        )

    # Separate raw files from template files
    raw_files = [f for f in xlsx_files if RAW_SUFFIX in os.path.basename(f)]
    template_files = [f for f in xlsx_files if RAW_SUFFIX not in os.path.basename(f)]

    raw_path: str | None = None
    template_path: str

    if raw_files:
        if len(raw_files) > 1:
            raise ValueError(
                f"Multiple raw .xlsx files in '{INPUT_DIR}/': {raw_files}. "
                f"Keep exactly one raw file."
            )
        raw_path = raw_files[0]
        # Derive template name: test_cases_raw.xlsx → test_cases.xlsx
        base = os.path.basename(raw_path).replace(RAW_SUFFIX, "")
        template_path = os.path.join(INPUT_DIR, base)
    elif template_files:
        if len(template_files) > 1:
            raise ValueError(
                f"Multiple .xlsx files in '{INPUT_DIR}/': {template_files}. "
                f"Keep exactly one."
            )
        template_path = template_files[0]
    else:
        raise FileNotFoundError(
            f"No valid .xlsx files found in '{INPUT_DIR}/'."
        )

    return template_path, raw_path


# ── DOM page discovery ─────────────────────────────────────────────────

def discover_dom_pages(dom_store: Any) -> set[str]:
    """Discover unique page names stored in the DOM Knowledge Base.

    Queries the DOM vector store and extracts distinct page names from
    the stored elements' metadata.  These become dynamic pages that can
    be handled without hand-crafted POMs.
    """
    try:
        # Use a broad search to get elements from all pages
        results = dom_store.search(
            "page navigation menu link button input", top_k=200, min_score=0.0,
        )
        page_names: set[str] = set()
        for r in results:
            page = r.get("metadata", {}).get("page", "")
            if page:
                page_names.add(page)
        logger.info(
            "[DOM] Discovered %d page(s) in DOM KB: %s",
            len(page_names), sorted(page_names),
        )
        return page_names
    except Exception as exc:
        logger.warning("[DOM] Could not discover pages from DOM KB: %s", exc)
        return set()
