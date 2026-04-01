"""
Action Validator — validates each row BEFORE the AI stage.

Checks:
  - Action is in SUPPORTED_ACTIONS
  - Page exists in PAGE_REGISTRY
  - Target exists in POM SUPPORTED_FIELDS (unless '-')
  - fill requires Value
  - verify_text requires Expected
"""
from __future__ import annotations

import logging

from core.pages.page_registry import PAGE_REGISTRY, DYNAMIC_PAGES, get_supported_fields

logger = logging.getLogger(__name__)

SUPPORTED_ACTIONS = {"fill", "click", "navigate", "verify_text", "select"}


def validate_action(row: dict[str, str]) -> None:
    """Validate a single Excel row against action rules. Raises on failure."""
    action = row.get("Action", "")
    page = row.get("Page", "")
    target = row.get("Target", "")
    value = row.get("Value", "")
    expected = row.get("Expected", "")

    # 1. Action must be supported
    if action not in SUPPORTED_ACTIONS:
        raise ValueError(
            f"Unsupported action '{action}'. "
            f"Supported: {sorted(SUPPORTED_ACTIONS)}"
        )

    # 2. Page must exist in registry OR be a dynamic (DOM-backed) page
    if page not in PAGE_REGISTRY and page not in DYNAMIC_PAGES:
        raise ValueError(
            f"Unknown page '{page}'. "
            f"Registered: {sorted(PAGE_REGISTRY.keys())}. "
            f"Dynamic: {sorted(DYNAMIC_PAGES)}"
        )

    # 3. Target must exist in POM (unless '-' for navigate or page is dynamic)
    #    Dynamic pages resolve targets via RAG at runtime.
    if target != "-" and page not in DYNAMIC_PAGES:
        fields = get_supported_fields(page)
        if target not in fields:
            raise ValueError(
                f"ValidationError: Target '{target}' not supported by POM "
                f"for page '{page}'. "
                f"Available fields: {sorted(fields)}. "
                f"Add the target to the Page Object Model or fix the Excel data."
            )

    # 4. fill — Value may be empty (empty-field test), but must not be dash
    #    Dash means "not applicable" which is invalid for fill.
    if action == "fill" and value == "-":
        raise ValueError(
            f"Action 'fill' requires a Value (use empty cell for empty-field test). "
            f"Target='{target}', Value='{value}'"
        )

    # 5. verify_text requires Expected
    if action == "verify_text" and (not expected or expected == "-"):
        raise ValueError(
            f"Action 'verify_text' requires a non-empty Expected. "
            f"Target='{target}', Expected='{expected}'"
        )
