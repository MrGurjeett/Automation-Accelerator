"""
Locator Generation Engine — generates Playwright locators from resolved DOM elements.

Once RAG identifies the correct element, this module generates the best
Playwright-compatible locator based on attribute priority.

Locator priority order:
  1. data-test
  2. id
  3. name
  4. aria-label
  5. role
  6. text

Example output:
    [data-test="login-button"]
    #username
    input[name='password']
"""
from __future__ import annotations

import logging
from typing import Optional

from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeout

from framework.rag.element_resolver import ResolvedElement

logger = logging.getLogger(__name__)


def generate_locator(
    page: Page,
    element: ResolvedElement,
) -> Optional[Locator]:
    """Generate the best Playwright locator for a resolved DOM element.

    Tries locator candidates in priority order and returns the first
    that resolves to at least one visible element.

    Parameters
    ----------
    page : Page
        Playwright page instance.
    element : ResolvedElement
        Resolved element from RAG.

    Returns
    -------
    Locator or None
        The first working locator, or None if none succeed.
    """
    # Build locator candidates in priority order
    candidates = _build_priority_candidates(element)

    logger.info(
        "[LOCATOR] Generating locator for '%s' (tag: %s, %d candidates)",
        element.matched_element, element.tag, len(candidates),
    )

    for strategy, selector in candidates:
        try:
            locator = page.locator(selector)

            # Avoid flakiness: during navigation/DOM updates, a correct locator
            # can briefly return 0 matches. Prefer a short attach wait.
            locator.first.wait_for(state="attached", timeout=1500)

            logger.info(
                "[LOCATOR] Using %s: %s (for '%s')",
                strategy, selector, element.matched_element,
            )
            return locator
        except PlaywrightTimeout:
            continue
        except Exception as exc:
            logger.debug(
                "[LOCATOR] Strategy '%s' failed for '%s': %s",
                strategy, element.matched_element, exc,
            )
            continue

    logger.warning(
        "[LOCATOR] No working locator found for '%s'", element.matched_element,
    )
    return None


def get_best_selector(element: ResolvedElement) -> Optional[str]:
    """Return the best CSS selector string (without testing against a page).

    Useful for logging and POM generation.
    """
    candidates = _build_priority_candidates(element)
    if candidates:
        strategy, selector = candidates[0]
        logger.info("[LOCATOR] Best selector for '%s': %s", element.matched_element, selector)
        return selector
    return None


def _build_priority_candidates(element: ResolvedElement) -> list[tuple[str, str]]:
    """Build locator candidates in strict priority order."""
    candidates: list[tuple[str, str]] = []
    attrs = element.attributes

    # 1. data-test (highest priority)
    if attrs.get("data-test"):
        candidates.append(("data-test", f"[data-test='{attrs['data-test']}']"))

    # 2. id (escape dots for CSS)
    if attrs.get("id"):
        escaped_id = attrs["id"].replace(".", "\\.")
        candidates.append(("id", f"#{escaped_id}"))

    # 3. name
    if attrs.get("name"):
        candidates.append(("name", f"[name='{attrs['name']}']"))

    # 4. aria-label
    if attrs.get("aria-label"):
        candidates.append(("aria-label", f"[aria-label='{attrs['aria-label']}']"))

    # 5. role
    if attrs.get("role"):
        candidates.append(("role", f"[role='{attrs['role']}']"))

    # 6. text (lowest priority)
    vtext = attrs.get("visible_text", "") or ""
    if vtext and len(vtext) < 50:
        candidates.append(("text", f"text={vtext}"))

    # Also add stored locator candidates from DOM extraction
    used = {c[1] for c in candidates}
    for loc in element.locator_candidates:
        if loc not in used:
            candidates.append(("stored", loc))

    return candidates
