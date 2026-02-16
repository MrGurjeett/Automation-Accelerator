"""
Login Page Object
"""
from pages.base_page import BasePage
from playwright.sync_api import Page


class LoginPage(BasePage):
    """Login page object with locators and methods"""

    # Locators
    USERNAME_INPUT = 'input[name="username"]'
    PASSWORD_INPUT = 'input[name="password"]'
    LOGIN_BUTTON = 'button[type="submit"]'
    ERROR_MESSAGE = '.error-message'
    FORGOT_PASSWORD_LINK = 'a:has-text("Forgot Password")'
    REMEMBER_ME_CHECKBOX = 'input[name="remember"]'

    def __init__(self, page: Page):
        super().__init__(page)

    def enter_username(self, username: str) -> None:
        """Enter username"""
        self.fill(self.USERNAME_INPUT, username)

    def enter_password(self, password: str) -> None:
        """Enter password"""
        self.fill(self.PASSWORD_INPUT, password)

    def click_login(self) -> None:
        """Click login button"""
        self.click(self.LOGIN_BUTTON)

    def login(self, username: str, password: str) -> None:
        """Perform complete login"""
        self.enter_username(username)
        self.enter_password(password)
        self.click_login()

    def get_error_message(self) -> str:
        """Get error message text"""
        return self.get_text(self.ERROR_MESSAGE)

    def click_forgot_password(self) -> None:
        """Click forgot password link"""
        self.click(self.FORGOT_PASSWORD_LINK)

    def check_remember_me(self) -> None:
        """Check remember me checkbox"""
        self.check(self.REMEMBER_ME_CHECKBOX)

    def is_login_button_enabled(self) -> bool:
        """Check if login button is enabled"""
        return self.is_enabled(self.LOGIN_BUTTON)
