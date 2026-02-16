import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width":1920,"height":1080})
    page = context.new_page()
    page.goto("https://demoqa.com/")
    page.locator(".card-up").first.click()
    page.get_by_text("Text Box").click()
    expect(page.get_by_role("heading")).to_contain_text("Text Box")
    page.get_by_text("Check Box").click()
    page.get_by_role("button", name="Toggle").click()
    page.locator(".rct-icon.rct-icon-uncheck > path").first.click()
    page.locator(".rct-icon.rct-icon-uncheck").first.click()
    page.get_by_text("Radio Button").click()
    page.get_by_text("Yes").click()
    expect(page.get_by_role("paragraph")).to_contain_text("Yes")
    page.get_by_text("Web Tables").click()
    page.get_by_role("button", name="Add").click()
    page.get_by_role("textbox", name="First Name").click()
    page.get_by_role("textbox", name="First Name").fill("aaa")
    page.get_by_role("textbox", name="Last Name").click()
    page.get_by_role("textbox", name="Last Name").fill("bbb")
    page.get_by_role("textbox", name="name@example.com").click()
    page.get_by_role("textbox", name="name@example.com").fill("cc@bb.aa")
    page.get_by_role("textbox", name="Age").click()
    page.get_by_role("textbox", name="Age").fill("22")
    page.get_by_role("textbox", name="Salary").click()
    page.get_by_role("textbox", name="Salary").fill("22222")
    page.get_by_role("textbox", name="Department").click()
    page.get_by_role("textbox", name="Department").fill("sew")
    page.get_by_role("button", name="Submit").click()
    page.get_by_text("Buttons").click()
    page.get_by_role("button", name="Double Click Me").dblclick()
    expect(page.locator("#doubleClickMessage")).to_contain_text("You have done a double click")
    page.get_by_role("button", name="Right Click Me").dblclick()
    page.get_by_role("button", name="Right Click Me").click(button="right")
    expect(page.locator("#rightClickMessage")).to_contain_text("You have done a right click")
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
