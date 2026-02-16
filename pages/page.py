class Page:
    def __init__(self, page):
        self.page = page

    def click_get_by_role_link_name_admin_page(self):
    self.page.get_by_role("link", name="Admin Page").click()

    def click_get_by_role_button_name_clean(self):
    self.page.get_by_role("button", name="Clean").click()

    def click_get_by_role_button_name_initialize(self):
    self.page.get_by_role("button", name="Initialize").click()

    def click_page_locator(self):
    self.page.page.locator(...).click()
    self.page.page.locator(...).click()

    def fill_page_locator(self):
    self.page.page.locator(...).fill('input[name=\"username\"]')
    self.page.page.locator(...).fill('input[name=\"password\"]')

    def click_get_by_role_button_name_log_in(self):
    self.page.get_by_role("button", name="Log In").click()

    def click_get_by_text_experience_the_difference(self):
    self.page.get_by_text("Experience the difference").click()

    def click_get_by_text_bookstore_exact_true(self):
    self.page.get_by_text("Bookstore", exact=True).click()

    def click_get_by_text_bookstore_version_2_0(self):
    self.page.get_by_text("Bookstore (Version 2.0).click()
