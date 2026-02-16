"""
Login Step Definitions
"""
from pytest_bdd import scenarios, given, when, then, parsers
from pages.login_page import LoginPage
from pages.home_page import HomePage
from utils.data_loader import DataLoader
import logging

logger = logging.getLogger(__name__)

# Load all scenarios from the feature file
scenarios('../login.feature')


@given('the user is on the sauce login page')

def go_to_login_sauce_page(page):

    login_page = LoginPage(page)

    print('STEP: the user is on the login page')

    page.set_default_timeout(30000)

    try:

        login_page.goto('https://www.saucedemo.com')

    except Exception as exc:

        print(f'Login step failed: {exc}')

    return login_page
 

@given('I am on the login page')
def navigate_to_login_page(page, base_url):
    """Navigate to login page"""
    login_page = LoginPage(page)
    login_page.navigate_to(f"{base_url}/login")
    logger.info("Navigated to login page")


@when('I enter valid username and password')
def enter_valid_credentials(page):
    """Enter valid credentials"""
    login_page = LoginPage(page)
    user_data = DataLoader.get_test_data("users.valid_user")
    
    login_page.enter_username(user_data['username'])
    login_page.enter_password(user_data['password'])
    logger.info("Entered valid credentials")


@when('I enter invalid username and password')
def enter_invalid_credentials(page):
    """Enter invalid credentials"""
    login_page = LoginPage(page)
    user_data = DataLoader.get_test_data("users.invalid_user")
    
    login_page.enter_username(user_data['username'])
    login_page.enter_password(user_data['password'])
    logger.info("Entered invalid credentials")


@when(parsers.parse('I enter username "{username}" and password "{password}"'))
def enter_credentials(page, username, password):
    """Enter specific credentials"""
    login_page = LoginPage(page)
    login_page.enter_username(username)
    login_page.enter_password(password)
    logger.info(f"Entered credentials: {username}")


@when('I click the login button')
def click_login_button(page):
    """Click login button"""
    login_page = LoginPage(page)
    login_page.click_login()
    logger.info("Clicked login button")


@then('I should be redirected to the home page')
def verify_home_page(page, base_url):
    """Verify user is on home page"""
    home_page = HomePage(page)
    home_page.wait_for_url(f"{base_url}/home")
    logger.info("User redirected to home page")


@then('I should see a welcome message')
def verify_welcome_message(page):
    """Verify welcome message is displayed"""
    home_page = HomePage(page)
    home_page.expect_visible(home_page.WELCOME_MESSAGE)
    logger.info("Welcome message verified")


@then('I should see an error message')
def verify_error_message(page):
    """Verify error message is displayed"""
    login_page = LoginPage(page)
    login_page.expect_visible(login_page.ERROR_MESSAGE)
    logger.info("Error message verified")


@then('I should remain on the login page')
def verify_on_login_page(page, base_url):
    """Verify user is still on login page"""
    current_url = page.url
    assert "/login" in current_url, f"Expected login page, but got: {current_url}"
    logger.info("User remains on login page")


@then(parsers.parse('I should see "{expected_text}"'))
def verify_text_present(page, expected_text):
    """Verify specific text is present"""
    page.wait_for_selector(f'text="{expected_text}"', state="visible", timeout=5000)
    logger.info(f"Verified text present: {expected_text}")
