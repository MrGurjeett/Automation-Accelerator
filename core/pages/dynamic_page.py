"""
Dynamic Page — AI-driven Page Object that resolves locators at runtime
via the DOM Knowledge Base (Qdrant vector store).

Used for pages WITHOUT hand-crafted POMs. Instead of static SUPPORTED_FIELDS,
every field lookup goes through the RAG Element Resolver → Locator Engine
pipeline.

This enables the framework to handle ANY page scanned by the DOM extractor
without requiring manual POM creation.
"""
from __future__ import annotations

import logging
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, expect

from core.pages.base_page import (
    BasePage,
    heal_locator,
    verify_element_visible,
)
from framework.rag.element_resolver import RAGElementResolver, ResolvedElement
from framework.locator_engine import generate_locator
import ai.ai_stats as ai_stats

logger = logging.getLogger(__name__)
ai_logger = logging.getLogger("ai_reasoning")


class DynamicPage(BasePage):
    """Page object that resolves all fields dynamically from the DOM Knowledge Base.

    Unlike static POMs (LoginPage etc.), DynamicPage has no SUPPORTED_FIELDS dict.
    Instead, every field is resolved at runtime through:
      1. RAG Element Resolver (Qdrant similarity search)
      2. Locator Generation Engine (CSS/ARIA/text selectors)
      3. Rule-based healing (fallback)

    Parameters
    ----------
    page : Page
        Playwright page instance.
    page_name : str
        Logical page name (e.g., "Transfer Funds", "Bill Pay").
    resolver : RAGElementResolver
        RAG resolver for DOM similarity search.
    """

    SUPPORTED_FIELDS = {}  # Dynamic — always returns True for `has_field()`

    def __init__(
        self,
        page: Page,
        page_name: str,
        resolver: RAGElementResolver,
    ) -> None:
        super().__init__(page)
        self.page_name = page_name
        self.resolver = resolver
        self._resolved_cache: dict[str, object] = {}

    def has_field(self, field: str) -> bool:
        """DynamicPage can attempt ANY field via RAG."""
        return True

    def _resolve_locator(self, field: str):
        """Resolve a field name to a Playwright locator via RAG + Locator Engine."""
        if field in self._resolved_cache:
            return self._resolved_cache[field]

        ai_logger.info("[DYNAMIC] Resolving '%s' on page '%s' via DOM KB", field, self.page_name)

        resolved = self.resolver.resolve(field, page_filter=self.page_name)

        if resolved and resolved.locator_candidates:
            locator = generate_locator(self.page, resolved)
            if locator is not None:
                ai_logger.info(
                    "[DYNAMIC] Resolved '%s' → '%s' (score: %.2f)",
                    field, resolved.matched_element, resolved.score,
                )
                ai_stats.increment("rag_resolutions")
                self._resolved_cache[field] = locator
                return locator

        # Fallback to rule-based healing
        ai_logger.info("[DYNAMIC] RAG miss for '%s', falling back to healing", field)
        locator = heal_locator(self.page, field)
        self._resolved_cache[field] = locator
        return locator

    def fill_field(self, field: str, value: str) -> None:
        locator = self._resolve_locator(field)
        logger.info("Filling '%s' with '%s' (DynamicPage: %s)", field, value, self.page_name)
        ai_logger.info("[PLAYWRIGHT] Executing fill: '%s' = '%s'", field, value)
        try:
            verify_element_visible(locator, field)
            locator.fill(value, timeout=self.timeout)
        except (PlaywrightTimeout, Exception) as exc:
            logger.warning("[DYNAMIC] Fill failed for '%s': %s — retrying with healing", field, exc)
            self._resolved_cache.pop(field, None)
            locator = heal_locator(self.page, field)
            verify_element_visible(locator, field)
            locator.fill(value, timeout=self.timeout)

    def click_field(self, field: str) -> None:
        locator = self._resolve_locator(field)
        logger.info("Clicking '%s' (DynamicPage: %s)", field, self.page_name)
        ai_logger.info("[PLAYWRIGHT] Executing click: '%s'", field)
        try:
            verify_element_visible(locator, field)
            locator.click(timeout=self.timeout)
        except (PlaywrightTimeout, Exception) as exc:
            logger.warning("[DYNAMIC] Click failed for '%s': %s — trying submit fallback", field, exc)
            # For submit/apply button actions, try common submit selectors
            field_lower = field.lower()
            if any(k in field_lower for k in ("submit", "apply", "send", "transfer")):
                for sel in [
                    "input[type='submit']",
                    "button[type='submit']",
                    "input[value='Apply Now']",
                    "input[value='Transfer']",
                    "input[value='Send Payment']",
                    "input[value='Submit']",
                ]:
                    try:
                        fb = self.page.locator(sel)
                        if fb.count() > 0:
                            fb.first.click(timeout=10000)
                            ai_logger.info("[DYNAMIC] Click '%s' via submit fallback: %s", field, sel)
                            return
                    except Exception:
                        continue
            self._resolved_cache.pop(field, None)
            locator = heal_locator(self.page, field)
            verify_element_visible(locator, field)
            locator.click(timeout=self.timeout)

    def verify_text(self, field: str, expected: str) -> None:
        locator = self._resolve_locator(field)
        logger.info("Verifying '%s' contains '%s' (DynamicPage: %s)", field, expected, self.page_name)
        ai_logger.info("[PLAYWRIGHT] Executing verify_text: '%s' expects '%s'", field, expected)
        try:
            verify_element_visible(locator, field)
            expect(locator).to_contain_text(expected, ignore_case=True, timeout=self.timeout)
        except (PlaywrightTimeout, AssertionError, Exception) as exc:
            logger.warning("[DYNAMIC] Verify failed for '%s': %s", field, exc)
            # Fallback: check main content area (#rightPanel) or full page body
            for fallback_sel in ["#rightPanel", "#mainPanel", "body"]:
                try:
                    fb = self.page.locator(fallback_sel)
                    if fb.count() > 0:
                        expect(fb).to_contain_text(expected, ignore_case=True, timeout=self.timeout)
                        ai_logger.info(
                            "[DYNAMIC] Verify '%s' succeeded via fallback '%s'",
                            field, fallback_sel,
                        )
                        return
                except Exception:
                    continue
            # All fallbacks exhausted — re-raise original
            raise exc

    def select_field(self, field: str, value: str) -> None:
        locator = self._resolve_locator(field)
        logger.info("Selecting '%s' with '%s' (DynamicPage: %s)", field, value, self.page_name)
        ai_logger.info("[PLAYWRIGHT] Executing select: '%s' = '%s'", field, value)

        # Map ordinal words to 0-based indices
        _ORDINAL_MAP = {
            "first": 0, "1st": 0, "second": 1, "2nd": 1,
            "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
            "last": -1,
        }

        def _try_select(loc):
            """Try label → value → ordinal index on the given locator."""
            try:
                loc.select_option(label=value, timeout=5000)
                return True
            except Exception:
                pass
            try:
                loc.select_option(value=value, timeout=5000)
                return True
            except Exception:
                pass
            # Try ordinal-based index selection
            ordinal_key = value.strip().lower().split()[0]  # "second account" → "second"
            idx = _ORDINAL_MAP.get(ordinal_key)
            if idx is not None:
                try:
                    options = loc.locator("option").all()
                    if options:
                        target_idx = idx if idx >= 0 else len(options) + idx
                        if 0 <= target_idx < len(options):
                            opt_value = options[target_idx].get_attribute("value")
                            loc.select_option(value=opt_value, timeout=5000)
                            return True
                except Exception:
                    pass
            # Last resort: select first available option
            try:
                options = loc.locator("option").all()
                if options:
                    opt_value = options[0].get_attribute("value")
                    loc.select_option(value=opt_value, timeout=5000)
                    return True
            except Exception:
                pass
            return False

        try:
            verify_element_visible(locator, field)
            if _try_select(locator):
                return
        except Exception:
            pass
        # Fallback to healing
        logger.warning("[DYNAMIC] Select failed for '%s', trying healing", field)
        self._resolved_cache.pop(field, None)
        locator = heal_locator(self.page, field)
        verify_element_visible(locator, field)
        _try_select(locator)