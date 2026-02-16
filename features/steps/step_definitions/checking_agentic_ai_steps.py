from pytest_bdd import given, when, then

@when('the user clicks get_by_role("link", name="Admin Page")')
def step_impl(page):
    pass

@when('the user clicks get_by_role("button", name="Clean")')
def step_impl(page):
    pass

@when('the user clicks get_by_role("button", name="Initialize")')
def step_impl(page):
    pass

@when('the user clicks page.locator(...)')
def step_impl(page):
    pass

@when('the user fills page.locator(...)')
def step_impl(page):
    pass

@when('the user fills page.locator(...)')
def step_impl(page):
    pass

@when('the user clicks get_by_role("button", name="Log In")')
def step_impl(page):
    pass

@when('the user clicks get_by_text("Experience the difference")')
def step_impl(page):
    pass

@when('the user clicks page.locator(...)')
def step_impl(page):
    pass

@when('the user clicks get_by_text("Bookstore", exact=True)')
def step_impl(page):
    pass

@when('the user clicks get_by_text("Bookstore (Version 2.0)')
def step_impl(page):
    pass
