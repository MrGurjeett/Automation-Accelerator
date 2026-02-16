"""
Test Step Definitions
"""
from pytest_bdd import when, parsers
import logging

logger = logging.getLogger(__name__)

@when(parsers.re(r"the user clicks on (?P<locator>.+)"))
def click_element(page, locator):
    """Click on an element"""
    page.locator(locator).click()
    logger.info(f"Clicked on {locator}")


@when(parsers.re(r"the user enters '(?P<text>.*)' in (?P<locator>.+)"))
def enter_text(page, text, locator):
    """Enter text in an element"""
    page.locator(locator).fill(text)
    logger.info(f"Entered '{text}' in {locator}")


@when(parsers.re(r"the user presses '(?P<key>.*)' in (?P<locator>.+)"))
def press_key(page, key, locator):
    """Press a key on an element"""
    page.locator(locator).press(key)
    logger.info(f"Pressed '{key}' in {locator}")


@when('the user closes the page')
def close_page(page):
    """Close the page"""
    # Page will be closed by the fixture teardown
    logger.info("Test completed - page will be closed by fixture")
