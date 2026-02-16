# Python + Playwright Automation Framework

A comprehensive test automation framework using Python, Playwright, and pytest-bdd for UI and API testing.

## Features

- **UI Automation**: Playwright-based browser automation
- **API Testing**: RESTful API testing capabilities
- **BDD Support**: pytest-bdd for behavior-driven development
- **Page Object Model**: Organized page objects for maintainability
- **Data-Driven Testing**: Support for YAML, JSON, and Excel data sources
- **Codegen Postprocessing**: Transform Playwright recordings into structured tests
- **Multiple Environments**: Easy environment switching (dev/qa/staging/prod)
- **Reporting**: Allure and pytest-html reports with screenshots
- **Database Validation**: Built-in database connectivity
- **Email Notifications**: Send test reports via email

## Project Structure

```
project_root/
├── config/              # Configuration files
├── features/            # BDD feature files and step definitions
├── pages/               # Page Object Model classes
├── api/                 # API client classes
├── recorder/            # Codegen and recording utilities
├── utils/               # Utility modules
├── tests/               # Test modules
└── requirements.txt     # Python dependencies
```

## Installation

1. Install Python 3.8 or higher

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
playwright install
```

## Configuration

Edit `config/config.yaml` to configure:
- Environment settings (URLs, credentials)
- Browser settings (headless, viewport, etc.)
- Test execution settings (parallel workers, retries)
- Database connection details
- Email settings

## Running Tests

### Run all tests:
```bash
pytest
```

### Run specific test file:
```bash
pytest tests/test_login.py
```

### Run BDD features:
```bash
pytest features/
```

### Run with specific markers:
```bash
pytest -m smoke
```

### Run in parallel:
```bash
pytest -n 4
```

### Generate Allure report:
```bash
pytest --alluredir=allure-results
allure serve allure-results
```

## Using Playwright Codegen

### Launch codegen and postprocess:
```bash
python recorder/run_codegen_and_postprocess.py --url https://example.com
```

### Launch codegen only:
```bash
python recorder/launch_codegen.py --url https://example.com
```

### Postprocess existing recording:
```bash
python recorder/postprocess_codegen.py recorded_test.py my_test
```

## Writing Tests

### Page Object Example:
```python
from pages.base_page import BasePage

class MyPage(BasePage):
    BUTTON = 'button#submit'
    
    def click_submit(self):
        self.click(self.BUTTON)
```

### Test Example:
```python
def test_example(page, base_url):
    my_page = MyPage(page)
    my_page.navigate_to(f"{base_url}/page")
    my_page.click_submit()
```

### BDD Feature Example:
```gherkin
Feature: Login
  Scenario: Successful login
    Given I am on the login page
    When I enter valid credentials
    Then I should see the home page
```

## Data-Driven Testing

Load test data from YAML, JSON, or Excel:

```python
from utils.data_loader import DataLoader

user_data = DataLoader.get_test_data("users.valid_user")
```

## API Testing

```python
from api.user_api import UserAPI

user_api = UserAPI("https://api.example.com")
response = user_api.get_user("123")
```

## Environment Variables

Override configuration with environment variables:
- `TEST_ENV`: Set environment (dev/qa/staging/prod)
- `BASE_URL`: Override base URL
- `HEADLESS`: Run in headless mode (true/false)

## Best Practices

1. Use Page Object Model for UI elements
2. Keep test data in separate files
3. Use descriptive test names
4. Add logging for debugging
5. Take screenshots on failures
6. Use fixtures for test setup/teardown
7. Follow BDD naming conventions

## Troubleshooting

### Browser not launching:
```bash
playwright install
```

### Import errors:
```bash
pip install -r requirements.txt
```

### Database connection issues:
Check `config/config.yaml` database settings

## Contributing

1. Create a feature branch
2. Add tests for new features
3. Update documentation
4. Submit pull request

## License

MIT License
