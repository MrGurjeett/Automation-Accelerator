"""
Login Page Object Model for ParaBank.

All locators live ONLY here. AI never touches locators at runtime.
Feature files never contain locator code.

During generation, AI + RAG may resolve targets to elements,
but execution uses only these static POM locators.
"""
from __future__ import annotations

from playwright.sync_api import Page

from core.pages.base_page import BasePage


class LoginPage(BasePage):
    """POM for the ParaBank Login page — https://parabank.parasoft.com/"""

    SUPPORTED_FIELDS = {
        "Login Page": lambda page: page,                                       # navigate target
        "Username": lambda page: page.locator("input[name='username']"),
        "Password": lambda page: page.locator("input[name='password']"),
        "Login Button": lambda page: page.locator("input[value='Log In']"),
        "Submit Button": lambda page: page.locator("input[value='Log In']"),   # alias
        "Welcome Message": lambda page: page.locator(".smallText"),
        "Error Message": lambda page: page.locator(".error"),
        "Accounts Overview Title": lambda page: page.locator("h1.title").first,
    }

    def __init__(self, page: Page) -> None:
        super().__init__(page)
