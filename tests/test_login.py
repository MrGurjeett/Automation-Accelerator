"""Sample UI tests.

These are *integration* tests: they require a reachable web app and
working credentials. They are marked `ui` and are skipped by default.
Enable with:

  - `--run-ui` or `RUN_UI_TESTS=1`
  - `BASE_URL=...`
  - optionally `UI_USERNAME` / `UI_PASSWORD`
"""

from __future__ import annotations

import os
import logging

import pytest
from playwright.sync_api import expect

from core.pages.login_page import LoginPage
from utils.data_loader import DataLoader

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.ui


def _get_ui_credentials() -> tuple[str, str]:
    username = os.environ.get("UI_USERNAME", "").strip()
    password = os.environ.get("UI_PASSWORD", "").strip()
    if username and password:
        return username, password

    user_data = DataLoader.get_test_data("users.valid_user")
    return str(user_data.get("username", "")), str(user_data.get("password", ""))


def _index_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.lower().endswith((".html", ".htm")):
        return base
    return f"{base}/index.htm"


class TestLogin:
    """Login flow smoke tests."""

    def test_successful_login(self, page, base_url):
        login_page = LoginPage(page)
        username, password = _get_ui_credentials()

        login_page.navigate_to(_index_url(base_url))
        login_page.fill_field("Username", username)
        login_page.fill_field("Password", password)
        login_page.click_field("Login Button")

        # ParaBank: successful login shows an "Accounts Overview" title.
        login_page.verify_text("Accounts Overview Title", "Accounts Overview")

    def test_failed_login(self, page, base_url):
        login_page = LoginPage(page)
        invalid = DataLoader.get_test_data("users.invalid_user")

        login_page.navigate_to(_index_url(base_url))
        login_page.fill_field("Username", str(invalid.get("username", "")))
        login_page.fill_field("Password", str(invalid.get("password", "")))
        login_page.click_field("Login Button")

        error_locator = LoginPage.SUPPORTED_FIELDS["Error Message"](page)
        expect(error_locator).to_be_visible()

    @pytest.mark.parametrize(
        "username,password,should_succeed",
        [
            ("valid@test.com", "Test@123", True),
            ("invalid@test.com", "wrong", False),
        ],
    )
    def test_login_parametrized(self, page, base_url, username, password, should_succeed):
        login_page = LoginPage(page)

        login_page.navigate_to(_index_url(base_url))
        login_page.fill_field("Username", username)
        login_page.fill_field("Password", password)
        login_page.click_field("Login Button")

        if should_succeed:
            login_page.verify_text("Accounts Overview Title", "Accounts Overview")
        else:
            error_locator = LoginPage.SUPPORTED_FIELDS["Error Message"](page)
            expect(error_locator).to_be_visible()
