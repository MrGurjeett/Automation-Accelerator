"""
Home Page Object
"""
from pages.base_page import BasePage
from playwright.sync_api import Page


class HomePage(BasePage):
    """Home page object with locators and methods"""

    # Locators
    WELCOME_MESSAGE = 'h1.welcome'
    SEARCH_INPUT = 'input[type="search"]'
    SEARCH_BUTTON = 'button[aria-label="Search"]'
    USER_PROFILE = '.user-profile'
    LOGOUT_BUTTON = 'button:has-text("Logout")'
    NAVIGATION_MENU = 'nav.main-navigation'

    def __init__(self, page: Page):
        super().__init__(page)

    def get_welcome_message(self) -> str:
        """Get welcome message text"""
        return self.get_text(self.WELCOME_MESSAGE)

    def search_for(self, term: str) -> None:
        """Perform a search"""
        self.fill(self.SEARCH_INPUT, term)
        self.click(self.SEARCH_BUTTON)

    def click_logout(self) -> None:
        """Click logout button"""
        self.click(self.LOGOUT_BUTTON)

    def is_user_logged_in(self) -> bool:
        """Check if user is logged in"""
        return self.is_visible(self.USER_PROFILE)

    def navigate_to_section(self, section_name: str) -> None:
        """Navigate to a specific section"""
        self.click(f'{self.NAVIGATION_MENU} >> text="{section_name}"')
