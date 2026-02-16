"""
Base Page Module
Contains the BasePage class with common page operations
"""
from playwright.sync_api import Page, expect
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class BasePage:
    """Base class for all page objects"""

    def __init__(self, page: Page):
        self.page = page
        self.timeout = 30000

    def navigate_to(self, url: str) -> None:
        """Navigate to a specific URL"""
        logger.info(f"Navigating to: {url}")
        self.page.goto(url)

    def click(self, locator: str, timeout: Optional[int] = None) -> None:
        """Click on an element"""
        timeout = timeout or self.timeout
        logger.info(f"Clicking element: {locator}")
        self.page.locator(locator).click(timeout=timeout)

    def fill(self, locator: str, text: str, timeout: Optional[int] = None) -> None:
        """Fill text in an input field"""
        timeout = timeout or self.timeout
        logger.info(f"Filling '{locator}' with text: {text}")
        self.page.locator(locator).fill(text, timeout=timeout)

    def get_text(self, locator: str, timeout: Optional[int] = None) -> str:
        """Get text from an element"""
        timeout = timeout or self.timeout
        logger.info(f"Getting text from: {locator}")
        return self.page.locator(locator).inner_text(timeout=timeout)

    def is_visible(self, locator: str, timeout: Optional[int] = None) -> bool:
        """Check if element is visible"""
        timeout = timeout or self.timeout
        try:
            return self.page.locator(locator).is_visible(timeout=timeout)
        except Exception as e:
            logger.warning(f"Element not visible: {locator} - {e}")
            return False

    def is_enabled(self, locator: str, timeout: Optional[int] = None) -> bool:
        """Check if element is enabled"""
        timeout = timeout or self.timeout
        return self.page.locator(locator).is_enabled(timeout=timeout)

    def wait_for_selector(self, locator: str, state: str = "visible", timeout: Optional[int] = None) -> None:
        """Wait for an element to be in a specific state"""
        timeout = timeout or self.timeout
        logger.info(f"Waiting for '{locator}' to be '{state}'")
        self.page.wait_for_selector(locator, state=state, timeout=timeout)

    def wait_for_url(self, url: str, timeout: Optional[int] = None) -> None:
        """Wait for URL to match"""
        timeout = timeout or self.timeout
        logger.info(f"Waiting for URL: {url}")
        self.page.wait_for_url(url, timeout=timeout)

    def take_screenshot(self, path: str) -> None:
        """Take a screenshot"""
        logger.info(f"Taking screenshot: {path}")
        self.page.screenshot(path=path)

    def get_title(self) -> str:
        """Get page title"""
        return self.page.title()

    def get_url(self) -> str:
        """Get current URL"""
        return self.page.url

    def press_key(self, locator: str, key: str) -> None:
        """Press a key on an element"""
        logger.info(f"Pressing key '{key}' on '{locator}'")
        self.page.locator(locator).press(key)

    def select_option(self, locator: str, value: str) -> None:
        """Select an option from dropdown"""
        logger.info(f"Selecting option '{value}' in '{locator}'")
        self.page.locator(locator).select_option(value)

    def check(self, locator: str) -> None:
        """Check a checkbox"""
        logger.info(f"Checking checkbox: {locator}")
        self.page.locator(locator).check()

    def uncheck(self, locator: str) -> None:
        """Uncheck a checkbox"""
        logger.info(f"Unchecking checkbox: {locator}")
        self.page.locator(locator).uncheck()

    def hover(self, locator: str) -> None:
        """Hover over an element"""
        logger.info(f"Hovering over: {locator}")
        self.page.locator(locator).hover()

    def double_click(self, locator: str) -> None:
        """Double click an element"""
        logger.info(f"Double clicking: {locator}")
        self.page.locator(locator).dblclick()

    def expect_visible(self, locator: str) -> None:
        """Assert element is visible"""
        logger.info(f"Asserting element is visible: {locator}")
        expect(self.page.locator(locator)).to_be_visible()

    def expect_text(self, locator: str, text: str) -> None:
        """Assert element contains text"""
        logger.info(f"Asserting element '{locator}' contains text: {text}")
        expect(self.page.locator(locator)).to_contain_text(text)

    def expect_value(self, locator: str, value: str) -> None:
        """Assert element has value"""
        logger.info(f"Asserting element '{locator}' has value: {value}")
        expect(self.page.locator(locator)).to_have_value(value)
