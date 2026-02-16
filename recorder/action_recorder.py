"""
Action Recorder
Records user actions and generates test code
"""
import logging
from playwright.sync_api import Page
from typing import List, Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ActionRecorder:
    """Records user actions on a page"""

    def __init__(self):
        self.actions: List[Dict] = []

    def record_action(self, action_type: str, **kwargs) -> None:
        """Record an action"""
        action = {
            "type": action_type,
            "timestamp": self._get_timestamp(),
            **kwargs
        }
        self.actions.append(action)
        logger.info(f"Recorded: {action_type} - {kwargs}")

    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.now().isoformat()

    def setup_listeners(self, page: Page) -> None:
        """Setup page listeners to record actions"""
        
        # Record navigation
        page.on("framenavigated", lambda frame: 
                self.record_action("navigate", url=frame.url) if frame == page.main_frame else None)

        # Note: Additional listeners can be added for clicks, fills, etc.
        logger.info("Listeners setup complete")

    def get_actions(self) -> List[Dict]:
        """Get recorded actions"""
        return self.actions

    def clear_actions(self) -> None:
        """Clear recorded actions"""
        self.actions = []
        logger.info("Actions cleared")

    def export_to_file(self, filename: str) -> None:
        """Export actions to a file"""
        import json
        
        with open(filename, 'w') as f:
            json.dump(self.actions, f, indent=2)
        
        logger.info(f"Actions exported to: {filename}")

    def generate_code(self) -> str:
        """Generate Python code from recorded actions"""
        code_lines = [
            "from playwright.sync_api import Page",
            "",
            "def recorded_test(page: Page):",
        ]

        for action in self.actions:
            if action["type"] == "navigate":
                code_lines.append(f'    page.goto("{action["url"]}")')
            elif action["type"] == "click":
                code_lines.append(f'    page.locator("{action["locator"]}").click()')
            elif action["type"] == "fill":
                code_lines.append(f'    page.locator("{action["locator"]}").fill("{action["value"]}")')

        return "\n".join(code_lines)
