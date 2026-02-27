import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width":1920,"height":1080})
    page = context.new_page()
    page.goto("https://demoqa.com/")
    page.get_by_role("link", name="Elements").click()
    page.get_by_role("link", name="Check Box").click()
    page.locator(".rc-tree-switcher").click()
    page.get_by_role("checkbox", name="Select Downloads").click()
    page.get_by_role("checkbox", name="Select Desktop").click()
    page.locator(".rc-tree-switcher.rc-tree-switcher_close").first.click()
    page.get_by_role("checkbox", name="Select Commands").click()
    page.get_by_role("link", name="Text Box").click()
    page.get_by_role("textbox", name="Full Name").click()
    page.get_by_role("textbox", name="Full Name").fill("gurjeet")
    page.get_by_role("textbox", name="name@example.com").click()
    page.get_by_role("textbox", name="name@example.com").fill("g@g.com")
    page.get_by_role("listitem").filter(has_text="Radio Button").click()
    page.get_by_role("radio", name="Impressive").check()
    expect(page.locator("label").filter(has_text="Impressive")).to_be_visible()
    page.get_by_role("link", name="Buttons").click()
    page.get_by_role("button", name="Click Me", exact=True).click()
    page.get_by_role("button", name="Right Click Me").click(button="right")
    expect(page.locator("#dynamicClickMessage")).to_contain_text("You have done a dynamic click")
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
