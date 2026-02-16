"""
Generated Step Definitions
"""
from pathlib import Path
import sys
from playwright.sync_api import expect
from pytest_bdd import given, when, parsers
import logging

PAGES_DIR = (Path(__file__).resolve().parent / r'..\pageClasses').resolve()
if str(PAGES_DIR) not in sys.path:
    sys.path.append(str(PAGES_DIR))

from demoqacompage import DemoqaComPage

logger = logging.getLogger(__name__)


@given('the user is on the Demoqa Com page')
def step_001_open_demoqa_com(page):
    page_obj = DemoqaComPage(page)
    page_obj.open()
    logger.info('Opened page')

@when('the user clicks Card Up')
def step_002_click_card_up(page):
    DemoqaComPage(page).click_card_up()

@when('the user clicks Text Box')
def step_003_click_text_box(page):
    DemoqaComPage(page).click_text_box()
    expect(page.get_by_role('heading')).to_contain_text('Text Box')

@when('the user clicks Check Box')
def step_004_click_check_box(page):
    DemoqaComPage(page).click_check_box()

@when('the user clicks Toggle Button')
def step_005_click_toggle_button(page):
    DemoqaComPage(page).click_toggle_button()

@when('the user clicks Rct Icon Rct Icon Uncheck > Path')
def step_006_click_rct_icon_rct_icon_uncheck___path(page):
    DemoqaComPage(page).click_rct_icon_rct_icon_uncheck___path()

@when('the user clicks Rct Icon Rct Icon Uncheck')
def step_007_click_rct_icon_rct_icon_uncheck(page):
    DemoqaComPage(page).click_rct_icon_rct_icon_uncheck()

@when('the user clicks Radio Button')
def step_008_click_radio_button(page):
    DemoqaComPage(page).click_radio_button()

@when('the user clicks Yes')
def step_009_click_yes(page):
    DemoqaComPage(page).click_yes()
    expect(page.get_by_role('paragraph')).to_contain_text('Yes')

@when('the user clicks Web Tables')
def step_010_click_web_tables(page):
    DemoqaComPage(page).click_web_tables()

@when('the user clicks Add Button')
def step_011_click_add_button(page):
    DemoqaComPage(page).click_add_button()

@when('the user clicks First Name Textbox')
def step_012_click_first_name_textbox(page):
    DemoqaComPage(page).click_first_name_textbox()

@when(parsers.parse("the user enters '{value}' into First Name Textbox"))
def step_013_enter_first_name_textbox(page, value):
    DemoqaComPage(page).fill_in_first_name_textbox(value)

@when('the user clicks Last Name Textbox')
def step_014_click_last_name_textbox(page):
    DemoqaComPage(page).click_last_name_textbox()

@when(parsers.parse("the user enters '{value}' into Last Name Textbox"))
def step_015_enter_last_name_textbox(page, value):
    DemoqaComPage(page).fill_in_last_name_textbox(value)

@when('the user clicks Name@Example Com Textbox')
def step_016_click_name_example_com_textbox(page):
    DemoqaComPage(page).click_name_example_com_textbox()

@when(parsers.parse("the user enters '{value}' into Name@Example Com Textbox"))
def step_017_enter_name_example_com_textbox(page, value):
    DemoqaComPage(page).fill_in_name_example_com_textbox(value)

@when('the user clicks Age Textbox')
def step_018_click_age_textbox(page):
    DemoqaComPage(page).click_age_textbox()

@when(parsers.parse("the user enters '{value}' into Age Textbox"))
def step_019_enter_age_textbox(page, value):
    DemoqaComPage(page).fill_in_age_textbox(value)

@when('the user clicks Salary Textbox')
def step_020_click_salary_textbox(page):
    DemoqaComPage(page).click_salary_textbox()

@when(parsers.parse("the user enters '{value}' into Salary Textbox"))
def step_021_enter_salary_textbox(page, value):
    DemoqaComPage(page).fill_in_salary_textbox(value)

@when('the user clicks Department Textbox')
def step_022_click_department_textbox(page):
    DemoqaComPage(page).click_department_textbox()

@when(parsers.parse("the user enters '{value}' into Department Textbox"))
def step_023_enter_department_textbox(page, value):
    DemoqaComPage(page).fill_in_department_textbox(value)

@when('the user clicks Submit Button')
def step_024_click_submit_button(page):
    DemoqaComPage(page).click_submit_button()

@when('the user clicks Buttons')
def step_025_click_buttons(page):
    DemoqaComPage(page).click_buttons()

@when('the user double clicks Double Click Me Button')
def step_026_dblclick_double_click_me_button(page):
    DemoqaComPage(page).dblclick_double_click_me_button()
    expect(page.locator('#doubleClickMessage')).to_contain_text('You have done a double click')

@when('the user double clicks Right Click Me Button')
def step_027_dblclick_right_click_me_button(page):
    DemoqaComPage(page).dblclick_right_click_me_button()

@when('the user right clicks Right Click Me Button')
def step_028_right_click_right_click_me_button(page):
    DemoqaComPage(page).right_click_right_click_me_button()
    expect(page.locator('#rightClickMessage')).to_contain_text('You have done a right click')

@when('the user closes the page')
def step_029_close_page(page):
    DemoqaComPage(page).close_page()
