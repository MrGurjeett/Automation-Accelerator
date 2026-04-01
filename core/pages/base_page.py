"""
Core Base Page for the Excel-Driven Compiler.
Wraps Playwright Page with action primitives used by the dispatcher.

Includes rule-based locator healing:
  When a POM locator fails, fallback strategies are attempted automatically.
  Healing is deterministic (no AI at runtime).

Integration with RAG Element Resolver:
  If POM lookup fails AND the RAG resolver is available, it attempts to
  find the element via Qdrant similarity search before falling back to healing.
"""
from __future__ import annotations

import logging
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, expect
import ai.ai_stats as ai_stats

logger = logging.getLogger(__name__)
ai_logger = logging.getLogger("ai_reasoning")

# ── Healed locator cache ────────────────────────────────────────────────
# Prevents repeated healing attempts for the same field within a session.
_healed_locators: dict[str, object] = {}

# ── RAG resolver (set by conftest at session start) ─────────────────────
# When available, provides AI-driven element resolution before healing.
_rag_resolver = None
_rag_dom_store = None


def set_rag_resolver(resolver, dom_store=None):
    """Inject RAG resolver for runtime element resolution fallback."""
    global _rag_resolver, _rag_dom_store
    _rag_resolver = resolver
    _rag_dom_store = dom_store
    logger.info("[RAG] Element resolver injected into BasePage")


def heal_locator(page: Page, field: str):
    """Attempt alternative locator strategies when the primary POM locator fails.

    Resolution flow:
      1. Check healed locator cache
      2. Try RAG Element Resolver (if available) — AI-driven DOM matching
      3. Rule-based strategies (deterministic fallback):
         a. Placeholder   — input[placeholder='<field>']
         b. Label          — <label>field</label> → associated input
         c. data-test      — [data-test='<field-normalized>']
         d. Role (textbox) — role=textbox with accessible name
         e. Role (button)  — role=button with accessible name
         f. Text           — text=field  (least reliable, last resort)

    Returns the first locator that resolves to at least one element.
    Raises Exception if all strategies fail.
    """
    # Check cache first — avoids repeated healing for the same field
    if field in _healed_locators:
        logger.info("[HEALING] Using cached healed locator for '%s'", field)
        return _healed_locators[field]

    # ── RAG Resolution (AI-driven, if available) ────────────────────
    if _rag_resolver is not None:
        try:
            resolved = _rag_resolver.resolve(field)
            if resolved and resolved.locator_candidates:
                from framework.locator_engine import generate_locator
                rag_locator = generate_locator(page, resolved)
                if rag_locator is not None:
                    logger.info(
                        "[RAG] Element '%s' resolved via RAG → '%s'",
                        field, resolved.matched_element,
                    )
                    ai_logger.info("[RAG] Resolved '%s' → '%s' (score: %.2f)", field, resolved.matched_element, resolved.score)
                    ai_stats.increment("rag_resolutions")
                    _healed_locators[field] = rag_locator
                    return rag_locator
        except Exception as exc:
            logger.debug("[RAG] RAG resolution failed for '%s': %s", field, exc)

    # ── Rule-based healing (deterministic fallback) ─────────────────

    # Normalize field name for data-test attribute lookup
    # e.g. "Username" → "username", "Login Button" → "login-button"
    data_test_name = field.lower().replace(" ", "-")

    strategies = [
        ("placeholder",   lambda: page.get_by_placeholder(field)),
        ("label",         lambda: page.get_by_label(field)),
        ("data-test",     lambda: page.locator(f"[data-test='{data_test_name}']")),
        ("role/textbox",  lambda: page.get_by_role("textbox", name=field)),
        ("role/button",   lambda: page.get_by_role("button", name=field)),
        ("text",          lambda: page.locator(f"text={field}").first),
    ]

    for strategy_name, strategy_fn in strategies:
        try:
            locator = strategy_fn()
            if locator.count() > 0:
                logger.info(
                    "[HEALING] '%s' recovered using %s strategy",
                    field, strategy_name,
                )
                ai_logger.info("[LOCATOR] Healed '%s' via %s strategy", field, strategy_name)
                ai_stats.increment("locator_healing")
                _healed_locators[field] = locator
                return locator
        except Exception:
            logger.debug(
                "[HEALING] Strategy '%s' failed for '%s'", strategy_name, field
            )
            continue

    raise Exception(
        f"[HEALING FAILED] Unable to locate element for '{field}'. "
        f"Tried: {[s[0] for s in strategies]}"
    )


def verify_element_visible(locator, field: str, timeout: int = 10000) -> None:
    """Wait for the element to be visible before performing an action.

    Reduces flaky failures caused by acting on elements that aren't
    rendered yet.  Timeout is 10 s to accommodate slow-loading pages.
    """
    try:
        # If the locator matches multiple elements, most actions will raise a
        # Playwright strict-mode violation. Narrow to the first match for the
        # pre-check so we can proceed (or fail later with a clearer assertion).
        if locator.count() > 1:
            locator = locator.first
    except Exception:
        # If count() fails for any reason, fall back to using the locator as-is.
        pass
    try:
        locator.wait_for(state="visible", timeout=timeout)
    except PlaywrightTimeout:
        logger.warning(
            "[PRE-CHECK] Element for '%s' not visible within %dms", field, timeout
        )
        raise
    except Exception as exc:
        # Handle strict-mode violations (multiple matches) that can still occur
        # in some locator shapes.
        if "strict mode violation" in str(exc).lower():
            try:
                locator.first.wait_for(state="visible", timeout=timeout)
                return
            except Exception:
                pass
        raise


class BasePage:
    """Thin wrapper over Playwright Page used by POM classes.

    Includes automatic locator healing: if the primary POM locator fails
    with a timeout, fallback strategies are attempted before giving up.
    """

    SUPPORTED_FIELDS: dict = {}

    def __init__(self, page: Page) -> None:
        self.page = page
        self.timeout = 30_000

    # ── Actions ───────────────────────────────────────────────────

    def navigate_to(self, url: str) -> None:
        logger.info("Navigating to: %s", url)
        self.page.goto(url)

    def fill_field(self, field: str, value: str) -> None:
        locator_fn = self.SUPPORTED_FIELDS.get(field)
        if not locator_fn:
            raise ValueError(f"Unknown field '{field}' on {self.__class__.__name__}")
        locator = locator_fn(self.page)
        logger.info("Filling '%s' with '%s'", field, value)
        ai_logger.info("[PLAYWRIGHT] Executing fill: '%s' = '%s'", field, value)
        try:
            verify_element_visible(locator, field)
            locator.fill(value, timeout=self.timeout)
        except (PlaywrightTimeout, Exception) as exc:
            logger.warning("[HEALING] Primary locator FAILED for '%s': %s", field, exc)
            locator = heal_locator(self.page, field)
            verify_element_visible(locator, field)
            locator.fill(value, timeout=self.timeout)
            logger.info("[HEALING] fill_field succeeded for '%s' via healed locator", field)

    def click_field(self, field: str) -> None:
        locator_fn = self.SUPPORTED_FIELDS.get(field)
        if not locator_fn:
            raise ValueError(f"Unknown field '{field}' on {self.__class__.__name__}")
        locator = locator_fn(self.page)
        logger.info("Clicking '%s'", field)
        ai_logger.info("[PLAYWRIGHT] Executing click: '%s'", field)
        try:
            verify_element_visible(locator, field)
            locator.click(timeout=self.timeout)
        except (PlaywrightTimeout, Exception) as exc:
            logger.warning("[HEALING] Primary locator FAILED for '%s': %s", field, exc)
            locator = heal_locator(self.page, field)
            verify_element_visible(locator, field)
            locator.click(timeout=self.timeout)
            logger.info("[HEALING] click_field succeeded for '%s' via healed locator", field)

    def verify_text(self, field: str, expected: str) -> None:
        locator_fn = self.SUPPORTED_FIELDS.get(field)
        if not locator_fn:
            raise ValueError(f"Unknown field '{field}' on {self.__class__.__name__}")
        locator = locator_fn(self.page)
        logger.info("Verifying '%s' contains '%s'", field, expected)
        ai_logger.info("[PLAYWRIGHT] Executing verify_text: '%s' expects '%s'", field, expected)
        try:
            verify_element_visible(locator, field)
            expect(locator).to_contain_text(expected, timeout=self.timeout)
        except (PlaywrightTimeout, AssertionError, Exception) as exc:
            logger.warning("[HEALING] Primary locator FAILED for '%s': %s", field, exc)
            locator = heal_locator(self.page, field)
            verify_element_visible(locator, field)
            expect(locator).to_contain_text(expected, timeout=self.timeout)
            logger.info("[HEALING] verify_text succeeded for '%s' via healed locator", field)
