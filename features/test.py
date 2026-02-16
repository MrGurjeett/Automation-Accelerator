"""
Test runner for test.feature
This file runs the BDD scenarios defined in test.feature

Usage:
    pytest features/test.py
    pytest features/test.py -v
    pytest features/test.py -v -s
"""
from pytest_bdd import scenarios, given
import logging
from pathlib import Path
import sys

# Import step definitions from generated steps module
from testing import *

logger = logging.getLogger(__name__)

# Prevent direct execution - must be run through pytest
if __name__ == '__main__':
    print("=" * 70)
    print("ERROR: This test file must be run through pytest, not directly.")
    print("=" * 70)
    print("\nCorrect usage:")
    print("  pytest features/test.py")
    print("  pytest features/test.py -v")
    print("  pytest features/test.py -v -s")
    print("\nFrom this directory, run:")
    print(f'  cd "{Path(__file__).parent.parent}"')
    print("  pytest features/test.py -v")
    print("=" * 70)
    sys.exit(1)

# Load all scenarios from test.feature using absolute path
FEATURE_FILE = Path(__file__).parent / 'test.feature'
scenarios(str(FEATURE_FILE))


# Fixed Step Definition (page-specific)
@given('the user is on the sauce login page')
def navigate_to_sauce_login(page):
    """Navigate to Sauce Demo login page"""
    page.goto('https://www.demoblaze.com/')
    page.wait_for_load_state('networkidle')
    logger.info("Navigated to Parabank registration page")