"""
DOM Extractor — extracts interactive UI elements from ParaBank pages.

Launches Playwright in headless mode, logs in, visits each application page,
and captures structured element data (inputs, buttons, links, selects, textareas).

Output is a list of structured knowledge documents ready for embedding.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, Page

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────

PARABANK_URL = "https://parabank.parasoft.com/parabank/"

# Pages to capture after login (label → relative URL path)
TARGET_PAGES = {
    "Open New Account": "openaccount.htm",
    "Accounts Overview": "overview.htm",
    "Transfer Funds": "transfer.htm",
    "Bill Pay": "billpay.htm",
    "Find Transactions": "findtrans.htm",
    "Update Contact Info": "updateprofile.htm",
    "Request Loan": "requestloan.htm",
}

# Element types to capture
CAPTURE_TAGS = ["input", "button", "a", "select", "textarea"]

# Attributes to extract for each element
CAPTURE_ATTRS = [
    "id", "name", "placeholder", "aria-label", "data-test",
    "href", "type", "class", "value", "role",
]


@dataclass
class DOMElement:
    """Structured representation of a single DOM element."""
    page_name: str
    element_name: str
    tag: str
    visible_text: str = ""
    attributes: dict = field(default_factory=dict)
    locator_candidates: list = field(default_factory=list)

    def to_knowledge_doc(self) -> str:
        """Convert to structured knowledge document for embedding."""
        lines = [
            f"Page: {self.page_name}",
            f"Element Name: {self.element_name}",
            f"Tag: {self.tag}",
            "Attributes:",
        ]
        for key, val in self.attributes.items():
            if val:
                lines.append(f"    {key}={val}")
        if self.visible_text:
            lines.append(f"Visible Text: {self.visible_text}")
        if self.locator_candidates:
            lines.append("Locator Candidates:")
            for loc in self.locator_candidates:
                lines.append(f"    {loc}")
        return "\n".join(lines)


def _derive_element_name(tag: str, attrs: dict, text: str) -> str:
    """Derive a human-readable element name from tag, attributes, and text."""
    # Priority: aria-label → placeholder → id → name → text → tag
    if attrs.get("aria-label"):
        return attrs["aria-label"]
    if attrs.get("placeholder"):
        return attrs["placeholder"]
    if attrs.get("id"):
        raw = attrs["id"]
        # Convert camelCase/snake_case/kebab-case to Title Case
        import re
        tokens = re.split(r"[-_]", raw)
        return " ".join(t.capitalize() for t in tokens if t)
    if attrs.get("name"):
        import re
        tokens = re.split(r"[-_]", attrs["name"])
        return " ".join(t.capitalize() for t in tokens if t)
    if text and len(text) < 50:
        return text.strip()
    # For submit/button inputs, use value attribute as name
    if tag == "input" and attrs.get("type") in ("submit", "button") and attrs.get("value"):
        return attrs["value"]
    return f"{tag.capitalize()} Element"


def _generate_locator_candidates(tag: str, attrs: dict, text: str) -> list[str]:
    """Generate locator candidates in priority order."""
    candidates = []

    if attrs.get("data-test"):
        candidates.append(f"[data-test='{attrs['data-test']}']")
    if attrs.get("id"):
        escaped_id = attrs["id"].replace(".", "\\.")
        candidates.append(f"#{escaped_id}")
    if attrs.get("name"):
        candidates.append(f"[name='{attrs['name']}']")
    if attrs.get("aria-label"):
        candidates.append(f"[aria-label='{attrs['aria-label']}']")
    if attrs.get("role"):
        candidates.append(f"[role='{attrs['role']}']")
    # For submit/button inputs, use value attribute
    if tag == "input" and attrs.get("type") in ("submit", "button") and attrs.get("value"):
        candidates.append(f"input[value='{attrs['value']}']")
    if text and len(text) < 50:
        candidates.append(f"text={text.strip()}")

    return candidates


def _extract_page_elements(page: Page, page_name: str) -> List[DOMElement]:
    """Extract all interactive elements from a single page."""
    elements: List[DOMElement] = []
    selector = ", ".join(CAPTURE_TAGS)

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        page.wait_for_load_state("domcontentloaded", timeout=10000)

    raw_elements = page.query_selector_all(selector)
    logger.info("[DOM] Found %d raw elements on '%s'", len(raw_elements), page_name)

    seen_ids: set[str] = set()

    for el in raw_elements:
        try:
            tag = el.evaluate("e => e.tagName").lower()

            # Skip hidden elements
            is_hidden = el.evaluate(
                "e => e.offsetParent === null && e.tagName !== 'BODY' && "
                "window.getComputedStyle(e).display === 'none'"
            )
            if is_hidden:
                continue

            # Extract attributes
            attrs = {}
            for attr in CAPTURE_ATTRS:
                val = el.get_attribute(attr)
                if val and val.strip():
                    attrs[attr] = val.strip()

            # Skip elements with no useful identifiers
            if not any(attrs.get(a) for a in ["id", "name", "placeholder", "aria-label", "data-test"]):
                # Still include if it has visible text (buttons, links)
                text = ""
                try:
                    text = el.inner_text().strip()[:100]
                except Exception:
                    pass
                # For input[type=submit/button], use value as visible text
                if not text or len(text) < 2:
                    if tag == "input" and attrs.get("type") in ("submit", "button"):
                        text = attrs.get("value", "")
                if not text or len(text) < 2:
                    continue
            else:
                text = ""
                try:
                    text = el.inner_text().strip()[:100]
                except Exception:
                    pass

            # Deduplicate by id
            el_id = attrs.get("id", "")
            if el_id:
                if el_id in seen_ids:
                    continue
                seen_ids.add(el_id)

            element_name = _derive_element_name(tag, attrs, text)
            locator_candidates = _generate_locator_candidates(tag, attrs, text)

            dom_el = DOMElement(
                page_name=page_name,
                element_name=element_name,
                tag=tag,
                visible_text=text,
                attributes=attrs,
                locator_candidates=locator_candidates,
            )
            elements.append(dom_el)

        except Exception as exc:
            logger.debug("[DOM] Skipping element due to error: %s", exc)
            continue

    logger.info("[DOM] Extracted %d structured elements from '%s'", len(elements), page_name)
    return elements


def extract_all_pages(
    base_url: str = PARABANK_URL,
    username: str = "john",
    password: str = "demo",
    *,
    target_pages: dict[str, str] | None = None,
    login_url: str | None = None,
) -> List[DOMElement]:
    """Extract DOM elements from all target pages.

    1. Launch headless Playwright
    2. Navigate to ParaBank and log in
    3. Visit each target page
    4. Extract interactive elements

    Returns list of DOMElement instances.
    """
    all_elements: List[DOMElement] = []

    logger.info("[DOM] ═══════════════════════════════════════════════════")
    logger.info("[DOM]   DOM Knowledge Extraction — ParaBank")
    logger.info("[DOM] ═══════════════════════════════════════════════════")

    # Accept either a base directory (".../parabank/") or a full login page
    # (".../parabank/index.htm").
    cleaned = (base_url or "").strip()
    if not cleaned:
        cleaned = PARABANK_URL

    if cleaned.lower().endswith((".htm", ".html")):
        base_dir = cleaned.rsplit("/", 1)[0] + "/"
        effective_login_url = login_url or cleaned
    else:
        base_dir = cleaned if cleaned.endswith("/") else cleaned + "/"
        effective_login_url = login_url or urljoin(base_dir, "index.htm")

    pages = target_pages or TARGET_PAGES

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # ── Login ───────────────────────────────────────────────────
        logger.info("[DOM] Navigating to login: %s", effective_login_url)
        page.goto(effective_login_url, wait_until="networkidle", timeout=30000)

        # Fill login form
        page.fill("input[name='username']", username)
        page.fill("input[name='password']", password)
        page.click("input[value='Log In']")
        page.wait_for_load_state("networkidle", timeout=15000)

        # Verify login success
        if "overview" in page.url or "parabank" in page.url:
            logger.info("[DOM] Login successful — URL: %s", page.url)
        else:
            logger.warning("[DOM] Login may have failed — URL: %s", page.url)

        # ── Extract Login Page elements (before navigation) ─────────
        # Go back to login page to extract its elements
        login_elements = _extract_login_page(page, base_dir, effective_login_url)
        all_elements.extend(login_elements)

        # ── Extract each target page ────────────────────────────────
        for page_name, path in pages.items():
            url = urljoin(base_dir, path)
            logger.info("[DOM] Navigating to '%s': %s", page_name, url)
            try:
                page.goto(url, wait_until="networkidle", timeout=20000)
                elements = _extract_page_elements(page, page_name)
                all_elements.extend(elements)
                logger.info(
                    "[DOM] Captured %d elements from '%s'",
                    len(elements), page_name,
                )
            except Exception as exc:
                logger.error("[DOM] Failed to extract '%s': %s", page_name, exc)
                continue

        browser.close()

    logger.info("[DOM] ═══════════════════════════════════════════════════")
    logger.info("[DOM]   Total elements extracted: %d", len(all_elements))
    logger.info("[DOM] ═══════════════════════════════════════════════════")

    return all_elements


def _extract_login_page(page: Page, base_dir: str, login_url: str) -> List[DOMElement]:
    """Extract elements from the login page."""
    # Navigate to login page
    page.goto(login_url or urljoin(base_dir, "index.htm"), wait_until="networkidle", timeout=15000)

    # Manually define core login elements (login page is simple/well-known)
    login_elements = [
        DOMElement(
            page_name="Login Page",
            element_name="Username",
            tag="input",
            visible_text="",
            attributes={"name": "username", "type": "text", "class": "input"},
            locator_candidates=["input[name='username']", "[name='username']"],
        ),
        DOMElement(
            page_name="Login Page",
            element_name="Password",
            tag="input",
            visible_text="",
            attributes={"name": "password", "type": "password", "class": "input"},
            locator_candidates=["input[name='password']", "[name='password']"],
        ),
        DOMElement(
            page_name="Login Page",
            element_name="Login Button",
            tag="input",
            visible_text="Log In",
            attributes={"type": "submit", "value": "Log In", "class": "button"},
            locator_candidates=["input[value='Log In']", "[type='submit']"],
        ),
    ]

    # Also extract dynamic elements
    dynamic = _extract_page_elements(page, "Login Page")

    # Merge — prefer manual definitions but add any extra dynamic elements
    manual_names = {e.element_name for e in login_elements}
    for el in dynamic:
        if el.element_name not in manual_names:
            login_elements.append(el)

    logger.info("[DOM] Captured %d elements from 'Login Page'", len(login_elements))
    return login_elements
