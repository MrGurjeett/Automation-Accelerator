"""
Conftest for generated feature execution.

Provides Playwright fixtures and POM registration.
Each test case executes in a FRESH browser context — no AI at runtime.

Dynamic pages (without hand-crafted POMs) are handled via DynamicPage,
which resolves elements through the DOM Knowledge Base at runtime.

Execution stability:
  pytest-playwright's `context` fixture is function-scoped by default,
  so each test automatically gets its own isolated browser context and page.
  This prevents state leakage between test cases.
"""
from __future__ import annotations

import logging

import os

import pytest
from playwright.sync_api import Page, BrowserContext

from core.pages.base_page import _healed_locators, set_rag_resolver
from core.pages.login_page import LoginPage
from core.pages.page_registry import PAGE_REGISTRY, DYNAMIC_PAGES, register_dynamic_pages
from core.pages.dynamic_page import DynamicPage
from utils.config_loader import get_config

logger = logging.getLogger(__name__)

_DEFAULT_E2E_BASE_URL = "https://parabank.parasoft.com/parabank/index.htm"

# Session-level RAG resolver and DOM store (set once, reused across tests)
_session_resolver = None
_session_dom_store = None


@pytest.fixture(scope="session", autouse=True)
def _skip_e2e_when_parabank_is_down(browser, base_url):
    """Guardrail for the public ParaBank demo.

    The ParaBank demo occasionally returns an internal error immediately
    after login ("An internal error has occurred and has been logged.").
    When that happens, all downstream E2E flows fail for reasons unrelated
    to the framework. We skip in that specific case.

    This guard only applies when the target host is the default ParaBank
    domain; for any other BASE_URL we do NOT skip.
    """
    if "parabank.parasoft.com" not in (base_url or ""):
        return

    username = (os.environ.get("UI_USERNAME") or "john").strip()
    password = (os.environ.get("UI_PASSWORD") or "demo").strip()

    ctx = browser.new_context(viewport={"width": 1280, "height": 720})
    try:
        page = ctx.new_page()
        page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
        page.locator("input[name='username']").fill(username)
        page.locator("input[name='password']").fill(password)
        page.locator("input[value='Log In']").first.click(timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=60000)

        panel_text = ""
        try:
            if page.locator("#rightPanel").count() > 0:
                panel_text = page.locator("#rightPanel").inner_text(timeout=5000) or ""
            else:
                panel_text = page.locator("body").inner_text(timeout=5000) or ""
        except Exception:
            panel_text = ""

        if "an internal error has occurred" in panel_text.lower():
            pytest.skip(
                "ParaBank demo site is currently returning an internal error after login; "
                "skipping E2E to avoid false negatives."
            )
    finally:
        ctx.close()


@pytest.fixture(scope="session")
def browser_type_launch_args():
    return {"headless": False, "slow_mo": 300}


@pytest.fixture(scope="session")
def browser_context_args():
    return {
        "viewport": {"width": 1920, "height": 1080},
    }


@pytest.fixture(scope="session")
def base_url():
    """Provide the base URL for the target application.

    Resolution order:
    1) env var BASE_URL (preferred)
    2) config/config.yaml environments[environment].base_url
    3) ParaBank default (keeps repo runnable out-of-the-box)

    Note: for ParaBank, this should typically be the full index URL, e.g.
    https://parabank.parasoft.com/parabank/index.htm
    """
    env = os.environ.get("BASE_URL")
    if env and env.strip():
        return env.strip().rstrip("/")

    try:
        cfg = get_config()
        env_cfg = cfg.get_environment_config()
        url = str(env_cfg.get("base_url", "")).strip()
        if url:
            return url.rstrip("/")
    except Exception:
        pass

    return _DEFAULT_E2E_BASE_URL


@pytest.fixture
def context(browser, browser_context_args):
    """Create a FRESH browser context for every test case.

    Ensures complete isolation — cookies, storage, and state are
    not shared between tests.  Context is closed after the test.
    """
    ctx = browser.new_context(**browser_context_args)
    logger.info("Fresh browser context created for test")
    yield ctx
    ctx.close()
    logger.info("Browser context closed after test")


@pytest.fixture
def page(context: BrowserContext):
    """Create a new page inside the fresh context for each test."""
    pg = context.new_page()
    yield pg
    pg.close()


@pytest.fixture(autouse=True)
def _clear_healed_locator_cache():
    """Clear the healed-locator cache before each test to avoid stale references."""
    _healed_locators.clear()


@pytest.fixture(scope="session", autouse=True)
def _setup_rag_resolver():
    """Initialize RAG resolver at session start for DynamicPage support."""
    global _session_resolver, _session_dom_store
    try:
        from ai.config import AIConfig
        from ai.clients.azure_openai_client import AzureOpenAIClient
        from ai.rag.embedder import EmbeddingService
        from framework.vector_store.qdrant_client import DOMVectorStore
        from framework.rag.element_resolver import RAGElementResolver

        config = AIConfig.load()
        ai_client = AzureOpenAIClient(config.azure_openai)
        embedder = EmbeddingService(ai_client)
        dom_store = DOMVectorStore(embedder)

        if dom_store.is_populated():
            resolver = RAGElementResolver(dom_store)
            _session_resolver = resolver
            _session_dom_store = dom_store
            set_rag_resolver(resolver, dom_store)
            logger.info("[RAG] Session-level resolver initialized for DynamicPage")

            # Discover dynamic pages from DOM KB (subprocess doesn't inherit DYNAMIC_PAGES)
            try:
                results = dom_store.search("page link button input", top_k=200, min_score=0.0)
                page_names = {r.get("metadata", {}).get("page", "") for r in results} - {""}
                register_dynamic_pages(page_names)
                logger.info("[RAG] Discovered %d dynamic page(s) from DOM KB", len(page_names))
            except Exception as exc2:
                logger.warning("[RAG] Could not discover dynamic pages: %s", exc2)
        else:
            logger.info("[RAG] DOM KB not populated — DynamicPage will use healing only")
    except Exception as exc:
        logger.warning("[RAG] Could not initialize session resolver: %s", exc)


@pytest.fixture
def pom_instances(page: Page) -> dict:
    """Instantiate all registered POM classes and DynamicPage instances.

    Returns a dict mapping page-name → POM instance.
    Static POMs (LoginPage etc.) are prioritized over DynamicPage.
    """
    instances = {}

    # Static POMs
    for name, cls in PAGE_REGISTRY.items():
        instances[name] = cls(page)

    # Dynamic pages (DOM-backed, no hand-crafted POM)
    if _session_resolver is not None:
        for name in DYNAMIC_PAGES:
            if name not in instances:
                instances[name] = DynamicPage(page, name, _session_resolver)
                logger.debug("[DYNAMIC] Created DynamicPage for '%s'", name)

    return instances
