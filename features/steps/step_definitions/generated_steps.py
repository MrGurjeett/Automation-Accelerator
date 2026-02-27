"""
Generated Step Definitions
"""
from pathlib import Path
import sys
from playwright.sync_api import expect
from pytest_bdd import given, when, parsers
import logging

PAGES_DIR = (Path(__file__).resolve().parent / r'..\..\..\pages\generated').resolve()
if str(PAGES_DIR) not in sys.path:
    sys.path.append(str(PAGES_DIR))

from demoqacompage import DemoqaComPage

logger = logging.getLogger(__name__)


@given('the user is on the Demoqa Com page')
def step_001_open_demoqa_com(page):
    page_obj = DemoqaComPage(page)
    page_obj.open()
    logger.info('Opened page')

@when('the user clicks Elements Link')
def step_002_click_elements_link(page):
    DemoqaComPage(page).click_elements_link()

@when('the user clicks Check Box Link')
def step_003_click_check_box_link(page):
    DemoqaComPage(page).click_check_box_link()

@when('the user clicks Rc Tree Switcher')
def step_004_click_rc_tree_switcher(page):
    DemoqaComPage(page).click_rc_tree_switcher()

@when('the user clicks Select Downloads Checkbox')
def step_005_click_select_downloads_checkbox(page):
    DemoqaComPage(page).click_select_downloads_checkbox()

@when('the user clicks Select Desktop Checkbox')
def step_006_click_select_desktop_checkbox(page):
    DemoqaComPage(page).click_select_desktop_checkbox()

@when('the user clicks Rc Tree Switcher Rc Tree Switcher Close')
def step_007_click_rc_tree_switcher_rc_tree_switcher_close(page):
    DemoqaComPage(page).click_rc_tree_switcher_rc_tree_switcher_close()

@when('the user clicks Select Commands Checkbox')
def step_008_click_select_commands_checkbox(page):
    DemoqaComPage(page).click_select_commands_checkbox()

@when('the user clicks Text Box Link')
def step_009_click_text_box_link(page):
    DemoqaComPage(page).click_text_box_link()

@when('the user clicks Full Name Textbox')
def step_010_click_full_name_textbox(page):
    DemoqaComPage(page).click_full_name_textbox()

@when(parsers.parse("the user enters '{value}' into Full Name Textbox"))
def step_011_enter_full_name_textbox(page, value):
    DemoqaComPage(page).fill_in_full_name_textbox(value)

@when('the user clicks Name@Example Com Textbox')
def step_012_click_name_example_com_textbox(page):
    DemoqaComPage(page).click_name_example_com_textbox()

@when(parsers.parse("the user enters '{value}' into Name@Example Com Textbox"))
def step_013_enter_name_example_com_textbox(page, value):
    DemoqaComPage(page).fill_in_name_example_com_textbox(value)

@when('the user checks Impressive Radio')
def step_014_check_impressive_radio(page):
    DemoqaComPage(page).check_impressive_radio()
    expect(page.locator('label').filter(has_text='Impressive')).to_be_visible()

@when('the user clicks Buttons Link')
def step_015_click_buttons_link(page):
    DemoqaComPage(page).click_buttons_link()

@when('the user clicks Click Me Button')
def step_016_click_click_me_button(page):
    DemoqaComPage(page).click_click_me_button()

@when('the user right clicks Right Click Me Button')
def step_017_right_click_right_click_me_button(page):
    DemoqaComPage(page).right_click_right_click_me_button()
    expect(page.locator('#dynamicClickMessage')).to_contain_text('You have done a dynamic click')

@when('the user closes the page')
def step_018_close_page(page):
    DemoqaComPage(page).close_page()
