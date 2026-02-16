from playwright.sync_api import Page, expect

class Demoqa.ComPage:
    def __init__(self, page: Page):
        self.page = page

    LI_NTH_CHILD_2_____RCT_TEXT___LABEL____RCT_CHECKBOX____RCT_ICON___PATH = 'li:nth-child(2) > .rct-text > label > .rct-checkbox > .rct-icon > path'

    def click_li_nth_child_2_____rct_text___label____rct_checkbox____rct_icon___path(self):
        self.page.click(self.LI_NTH_CHILD_2_____RCT_TEXT___LABEL____RCT_CHECKBOX____RCT_ICON___PATH)

    def close_page(self):
        self.page.close()

