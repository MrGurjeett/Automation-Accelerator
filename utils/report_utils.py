"""Small helper used by test teardown to save screenshots and simple reports.

This is a lightweight stub to ensure test teardown does not fail when
`utils.report_utils.ReportUtils` is imported. Extend as needed.
"""
from playwright.sync_api import Page
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ReportUtils:
    @staticmethod
    def save_screenshot(page: Page, name: str = "failure") -> str:
        Path("screenshots").mkdir(parents=True, exist_ok=True)
        path = Path("screenshots") / f"{name}.png"
        try:
            page.screenshot(path=str(path))
            logger.info("Saved screenshot: %s", path)
        except Exception as exc:
            logger.warning("Failed to save screenshot: %s", exc)
        return str(path)
