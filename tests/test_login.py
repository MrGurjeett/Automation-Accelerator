"""
Sample test module
Demonstrates basic Playwright testing without BDD
"""
import pytest
from pages.login_page import LoginPage
from pages.home_page import HomePage
from utils.data_loader import DataLoader
import logging

logger = logging.getLogger(__name__)


class TestLogin:
    """Test cases for login functionality"""

    def test_successful_login(self, page, base_url):
        """Test successful login with valid credentials"""
        # Arrange
        login_page = LoginPage(page)
        user_data = DataLoader.get_test_data("users.valid_user")
        
        # Act
        login_page.navigate_to(f"{base_url}/login")
        login_page.login(user_data['username'], user_data['password'])
        
        # Assert
        home_page = HomePage(page)
        home_page.wait_for_url(f"{base_url}/home")
        assert home_page.is_user_logged_in(), "User should be logged in"
        
        logger.info("Test successful login - PASSED")

    def test_failed_login(self, page, base_url):
        """Test failed login with invalid credentials"""
        # Arrange
        login_page = LoginPage(page)
        user_data = DataLoader.get_test_data("users.invalid_user")
        
        # Act
        login_page.navigate_to(f"{base_url}/login")
        login_page.login(user_data['username'], user_data['password'])
        
        # Assert
        assert login_page.is_visible(login_page.ERROR_MESSAGE), "Error message should be displayed"
        
        logger.info("Test failed login - PASSED")

    @pytest.mark.parametrize("username,password,should_succeed", [
        ("valid@test.com", "Test@123", True),
        ("invalid@test.com", "wrong", False),
    ])
    def test_login_parametrized(self, page, base_url, username, password, should_succeed):
        """Parametrized login test"""
        # Arrange
        login_page = LoginPage(page)
        
        # Act
        login_page.navigate_to(f"{base_url}/login")
        login_page.login(username, password)
        
        # Assert
        if should_succeed:
            home_page = HomePage(page)
            assert home_page.is_user_logged_in(), "User should be logged in"
        else:
            assert login_page.is_visible(login_page.ERROR_MESSAGE), "Error should be shown"
        
        logger.info(f"Test login parametrized ({username}) - PASSED")


class TestHomePage:
    """Test cases for home page functionality"""

    def test_search_functionality(self, page, base_url):
        """Test search functionality"""
        # Setup - login first
        login_page = LoginPage(page)
        user_data = DataLoader.get_test_data("users.valid_user")
        login_page.navigate_to(f"{base_url}/login")
        login_page.login(user_data['username'], user_data['password'])
        
        # Test search
        home_page = HomePage(page)
        search_term = "automation"
        home_page.search_for(search_term)
        
        # Verify (simplified - would need actual search results verification)
        logger.info("Test search functionality - PASSED")

    def test_logout(self, page, base_url):
        """Test logout functionality"""
        # Setup - login first
        login_page = LoginPage(page)
        user_data = DataLoader.get_test_data("users.valid_user")
        login_page.navigate_to(f"{base_url}/login")
        login_page.login(user_data['username'], user_data['password'])
        
        # Test logout
        home_page = HomePage(page)
        home_page.click_logout()
        
        # Verify redirected to login
        login_page.wait_for_url(f"{base_url}/login")
        
        logger.info("Test logout - PASSED")
