from playwright.sync_api import Page, expect

class WwwDemoblazeComPage:
    def __init__(self, page: Page):
        self.page = page

    URL = 'https://www.demoblaze.com/'

    def open(self):
        self.page.goto(self.URL)
        self.page.wait_for_load_state('domcontentloaded')


    def click_phones_link(self):
        self.page.get_by_role('link', name='Phones').click()

    def click_samsung_galaxy_s6_link(self):
        self.page.get_by_role('link', name='Samsung galaxy s6').click()

    def click_add_to_cart_link(self):
        self.page.get_by_role('link', name='Add to cart').click()

    def click_home__current__link(self):
        self.page.get_by_role('link', name='Home (current)').click()

    def click_monitors_link(self):
        self.page.get_by_role('link', name='Monitors').click()

    def click_apple_monitor_link(self):
        self.page.get_by_role('link', name='Apple monitor').click()

    def click_add_to_cart_link_1(self):
        self.page.get_by_role('link', name='Add to cart').click()

    def click_cart_link(self):
        self.page.get_by_role('link', name='Cart', exact=True).click()

    def click_delete_link(self):
        self.page.get_by_role('link', name='Delete').first.click()

    def click_home__current__link_1(self):
        self.page.get_by_role('link', name='Home (current)').click()

    def close_page(self):
        self.page.close()

