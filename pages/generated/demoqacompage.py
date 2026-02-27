from playwright.sync_api import Page, expect

class DemoqaComPage:
    def __init__(self, page: Page):
        self.page = page

    URL = 'https://demoqa.com/'

    def open(self):
        self.page.goto(self.URL)
        self.page.wait_for_load_state('domcontentloaded')

    RC_TREE_SWITCHER = '.rc-tree-switcher'
    RC_TREE_SWITCHER_RC_TREE_SWITCHER_CLOSE = '.rc-tree-switcher.rc-tree-switcher_close'

    def click_elements_link(self):
        self.page.get_by_role('link', name='Elements').click()

    def click_check_box_link(self):
        self.page.get_by_role('link', name='Check Box').click()

    def click_rc_tree_switcher(self):
        self.page.locator(self.RC_TREE_SWITCHER).first.wait_for(state='visible')
        self.page.locator(self.RC_TREE_SWITCHER).first.click()

    def click_select_downloads_checkbox(self):
        self.page.get_by_role('checkbox', name='Select Downloads').click()

    def click_select_desktop_checkbox(self):
        self.page.get_by_role('checkbox', name='Select Desktop').click()

    def click_rc_tree_switcher_rc_tree_switcher_close(self):
        self.page.locator(self.RC_TREE_SWITCHER_RC_TREE_SWITCHER_CLOSE).first.wait_for(state='visible')
        self.page.locator(self.RC_TREE_SWITCHER_RC_TREE_SWITCHER_CLOSE).first.click()

    def click_select_commands_checkbox(self):
        self.page.get_by_role('checkbox', name='Select Commands').click()

    def click_text_box_link(self):
        self.page.get_by_role('link', name='Text Box').click()

    def click_full_name_textbox(self):
        self.page.get_by_role('textbox', name='Full Name').click()

    def fill_in_full_name_textbox(self, value):
        self.page.get_by_role('textbox', name='Full Name').fill(value)

    def click_name_example_com_textbox(self):
        self.page.get_by_role('textbox', name='name@example.com').click()

    def fill_in_name_example_com_textbox(self, value):
        self.page.get_by_role('textbox', name='name@example.com').fill(value)

    def check_impressive_radio(self):
        self.page.get_by_role('radio', name='Impressive').check()

    def click_buttons_link(self):
        self.page.get_by_role('link', name='Buttons').click()

    def click_click_me_button(self):
        self.page.get_by_role('button', name='Click Me', exact=True).click()

    def right_click_right_click_me_button(self):
        self.page.get_by_role('button', name='Right Click Me').click(button='right')

    def close_page(self):
        self.page.close()

