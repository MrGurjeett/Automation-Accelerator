from playwright.sync_api import Page, expect

class DemoqaComPage:
    def __init__(self, page: Page):
        self.page = page

    URL = 'https://demoqa.com/'

    def open(self):
        self.page.goto(self.URL)
        self.page.wait_for_load_state('domcontentloaded')

    CARD_UP = '.card-up'
    RCT_ICON_RCT_ICON_UNCHECK___PATH = '.rct-icon.rct-icon-uncheck > path'
    RCT_ICON_RCT_ICON_UNCHECK = '.rct-icon.rct-icon-uncheck'

    def click_card_up(self):
        self.page.locator(self.CARD_UP).first.wait_for(state='visible')
        self.page.locator(self.CARD_UP).first.click()

    def click_text_box(self):
        self.page.get_by_text('Text Box').click()

    def click_check_box(self):
        self.page.get_by_text('Check Box').click()

    def click_toggle_button(self):
        self.page.get_by_role('button', name='Toggle').click()

    def click_rct_icon_rct_icon_uncheck___path(self):
        if self.page.locator(self.RCT_ICON_RCT_ICON_UNCHECK___PATH).first.count() > 0:
            self.page.locator(self.RCT_ICON_RCT_ICON_UNCHECK___PATH).first.click(force=True)

    def click_rct_icon_rct_icon_uncheck(self):
        if self.page.locator(self.RCT_ICON_RCT_ICON_UNCHECK).first.count() > 0:
            self.page.locator(self.RCT_ICON_RCT_ICON_UNCHECK).first.click(force=True)

    def click_radio_button(self):
        self.page.get_by_text('Radio Button').click()

    def click_yes(self):
        self.page.get_by_text('Yes').click()

    def click_web_tables(self):
        self.page.get_by_text('Web Tables').click()

    def click_add_button(self):
        self.page.get_by_role('button', name='Add').click()

    def click_first_name_textbox(self):
        self.page.get_by_role('textbox', name='First Name').click()

    def fill_in_first_name_textbox(self, value):
        self.page.get_by_role('textbox', name='First Name').fill(value)

    def click_last_name_textbox(self):
        self.page.get_by_role('textbox', name='Last Name').click()

    def fill_in_last_name_textbox(self, value):
        self.page.get_by_role('textbox', name='Last Name').fill(value)

    def click_name_example_com_textbox(self):
        self.page.get_by_role('textbox', name='name@example.com').click()

    def fill_in_name_example_com_textbox(self, value):
        self.page.get_by_role('textbox', name='name@example.com').fill(value)

    def click_age_textbox(self):
        self.page.get_by_role('textbox', name='Age').click()

    def fill_in_age_textbox(self, value):
        self.page.get_by_role('textbox', name='Age').fill(value)

    def click_salary_textbox(self):
        self.page.get_by_role('textbox', name='Salary').click()

    def fill_in_salary_textbox(self, value):
        self.page.get_by_role('textbox', name='Salary').fill(value)

    def click_department_textbox(self):
        self.page.get_by_role('textbox', name='Department').click()

    def fill_in_department_textbox(self, value):
        self.page.get_by_role('textbox', name='Department').fill(value)

    def click_submit_button(self):
        self.page.get_by_role('button', name='Submit').click()

    def click_buttons(self):
        self.page.get_by_text('Buttons').click()

    def dblclick_double_click_me_button(self):
        self.page.get_by_role('button', name='Double Click Me').dblclick()

    def dblclick_right_click_me_button(self):
        self.page.get_by_role('button', name='Right Click Me').dblclick()

    def right_click_right_click_me_button(self):
        self.page.get_by_role('button', name='Right Click Me').click(button='right')

    def close_page(self):
        self.page.close()

