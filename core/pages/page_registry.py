"""
Page Registry — single source of truth for all POM classes.

Maps Excel 'Page' column values to POM classes.
The dispatcher resolves targets from here. AI never builds locators.

Dynamic pages: Pages discovered in the DOM Knowledge Base but without
hand-crafted POMs are tracked in DYNAMIC_PAGES and resolved via RAG.
"""
from __future__ import annotations

import logging
from typing import Dict, Set, Type

from core.pages.base_page import BasePage
from core.pages.login_page import LoginPage

logger = logging.getLogger(__name__)

# Maps the exact 'Page' string used in Excel → POM class
PAGE_REGISTRY: Dict[str, Type[BasePage]] = {
    "Login": LoginPage,
}

# Dynamic pages discovered from DOM KB (no manual POM needed)
# Set at startup by main.py after DOM extraction
DYNAMIC_PAGES: Set[str] = set()


def register_dynamic_pages(page_names: set[str]) -> None:
    """Register pages discovered in the DOM KB that lack manual POMs.

    These pages will be handled by DynamicPage at runtime.
    """
    new_pages = page_names - set(PAGE_REGISTRY.keys())
    DYNAMIC_PAGES.update(new_pages)
    if new_pages:
        logger.info(
            "[REGISTRY] Registered %d dynamic page(s): %s",
            len(new_pages), sorted(new_pages),
        )


def is_known_page(page_name: str) -> bool:
    """Check if a page exists in the registry OR as a dynamic page."""
    return page_name in PAGE_REGISTRY or page_name in DYNAMIC_PAGES


def get_page_class(page_name: str) -> Type[BasePage]:
    """Lookup a POM class by name. Raises if not found."""
    if page_name not in PAGE_REGISTRY:
        raise ValueError(
            f"Unknown page '{page_name}'. "
            f"Registered pages: {sorted(PAGE_REGISTRY.keys())}"
        )
    return PAGE_REGISTRY[page_name]


def get_supported_fields(page_name: str) -> set[str]:
    """Return the set of supported field names for a page.

    For dynamic pages, returns an empty set (fields are resolved via RAG).
    """
    if page_name in DYNAMIC_PAGES:
        return set()  # DynamicPage supports any field via RAG
    cls = get_page_class(page_name)
    return set(cls.SUPPORTED_FIELDS.keys())
