"""
Report Utilities
Helper functions for test reporting
"""
import logging
from pathlib import Path
from datetime import datetime
import json
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ReportUtils:
    """Utilities for test reporting"""

    @staticmethod
    def create_report_directory(base_dir: str = "reports") -> Path:
        """Create a timestamped report directory"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = Path(base_dir) / timestamp
        report_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Report directory created: {report_dir}")
        return report_dir

    @staticmethod
    def save_screenshot(page, filename: str, directory: str = "screenshots") -> str:
        """Save a screenshot"""
        screenshot_dir = Path(directory)
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = screenshot_dir / f"{filename}_{timestamp}.png"
        
        page.screenshot(path=str(filepath))
        logger.info(f"Screenshot saved: {filepath}")
        return str(filepath)

    @staticmethod
    def save_test_results(results: Dict[str, Any], filename: str = "test_results.json") -> None:
        """Save test results to JSON file"""
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Test results saved: {filename}")

    @staticmethod
    def generate_html_report(test_data: Dict[str, Any], output_file: str = "report.html") -> None:
        """Generate a simple HTML report"""
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Test Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #333; }}
                .summary {{ background: #f0f0f0; padding: 15px; border-radius: 5px; }}
                .pass {{ color: green; }}
                .fail {{ color: red; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
            </style>
        </head>
        <body>
            <h1>Test Execution Report</h1>
            <div class="summary">
                <p><strong>Generated:</strong> {timestamp}</p>
                <p><strong>Total Tests:</strong> {total}</p>
                <p class="pass"><strong>Passed:</strong> {passed}</p>
                <p class="fail"><strong>Failed:</strong> {failed}</p>
            </div>
            <table>
                <tr>
                    <th>Test Name</th>
                    <th>Status</th>
                    <th>Duration</th>
                </tr>
                {test_rows}
            </table>
        </body>
        </html>
        """
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = test_data.get('total', 0)
        passed = test_data.get('passed', 0)
        failed = test_data.get('failed', 0)
        
        test_rows = ""
        for test in test_data.get('tests', []):
            status_class = "pass" if test['status'] == 'passed' else "fail"
            test_rows += f"""
            <tr>
                <td>{test['name']}</td>
                <td class="{status_class}">{test['status']}</td>
                <td>{test.get('duration', 'N/A')}</td>
            </tr>
            """
        
        html_content = html_template.format(
            timestamp=timestamp,
            total=total,
            passed=passed,
            failed=failed,
            test_rows=test_rows
        )
        
        with open(output_file, 'w') as f:
            f.write(html_content)
        
        logger.info(f"HTML report generated: {output_file}")

    @staticmethod
    def attach_to_allure(name: str, content: str, attachment_type: str = "text/plain") -> None:
        """Attach content to Allure report"""
        try:
            import allure
            allure.attach(content, name=name, attachment_type=attachment_type)
            logger.info(f"Attached to Allure: {name}")
        except ImportError:
            logger.warning("Allure not installed. Skipping attachment.")
