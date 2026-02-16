import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width":1920,"height":1080})
    page = context.new_page()
    page.goto("https://demoqa.com/")
    page.locator(".card-up").first.click()
    page.get_by_text("Buttons").click()
    page.get_by_role("button", name="Double Click Me").dblclick()
    page.get_by_role("button", name="Right Click Me").dblclick()
    page.get_by_role("button", name="Click Me", exact=True).dblclick()
    page.close()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
