"""
Conftest for pytest
Contains fixtures and configuration for tests
"""
import pytest
from playwright.sync_api import Browser, BrowserContext, Page
from utils.config_loader import get_config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def config():
    """Load configuration"""
    return get_config()


@pytest.fixture(scope="session")
def browser_type_launch_args(config):
    """Get browser launch arguments from config - overrides pytest-playwright"""
    browser_config = config.get_browser_config()
    headless = browser_config.get("headless", False)
    slow_mo = browser_config.get("slow_mo", 0)
    
    logger.info(f"Browser launch args - headless: {headless}, slow_mo: {slow_mo}")
    
    return {
        "headless": headless,
        "slow_mo": slow_mo
    }


@pytest.fixture(scope="session")
def browser_context_args(config):
    """Get browser context arguments from config - overrides pytest-playwright"""
    browser_config = config.get_browser_config()
    viewport = browser_config.get("viewport", {})
    
    return {
        "viewport": {
            "width": viewport.get("width", 1920),
            "height": viewport.get("height", 1080)
        },
        "record_video_dir": "videos/" if browser_config.get("video", False) else None
    }


@pytest.fixture(scope="function")
def base_url(config):
    """Get base URL from config"""
    env_config = config.get_environment_config()
    return env_config.get("base_url", "https://example.com")


# Hook to set default timeout on page
@pytest.fixture(scope="function")
def page(page: Page, config):
    """Override page fixture to add custom configuration"""
    browser_config = config.get_browser_config()
    timeout = browser_config.get("timeout", 30000)
    page.set_default_timeout(timeout)
    
    logger.info(f"Page created with timeout: {timeout}ms")
    
    yield page
    
    # Screenshot on failure
    if browser_config.get("screenshot_on_failure", True):
        if hasattr(page, '_test_failed'):
            from utils.report_utils import ReportUtils
            ReportUtils.save_screenshot(page, "failure")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to detect test failures"""
    outcome = yield
    rep = outcome.get_result()
    
    if rep.when == "call" and rep.failed:
        # Mark page fixture as failed for screenshot
        if "page" in item.funcargs:
            item.funcargs["page"]._test_failed = True
