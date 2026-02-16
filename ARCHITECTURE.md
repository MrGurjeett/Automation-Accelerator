# Python + Playwright Automation Framework Architecture

## 1. Project Structure

```
project_root/
├── config/
│   ├── config.yaml
│   └── testdata/
│
├── features/
│   ├── *.feature
│   └── steps/
│       ├── conftest.py
│       ├── hooks.py
│       └── step_definitions/
│
├── pages/
│   ├── base_page.py
│   └── <page_name>_page.py
│
├── api/
│   ├── __init__.py
│   ├── base_api.py
│   └── <api_name>_api.py
│
├── recorder/
│   ├── postprocess_codegen.py
│   ├── postprocess_config.json
│   ├── run_codegen_and_postprocess.py
│   ├── action_recorder.py
│   └── launch_codegen.py
│
├── utils/
│   ├── config_loader.py
│   ├── data_loader.py
│   ├── db_manager.py
│   ├── report_utils.py
│   ├── excel_utils.py
│   └── email_utils.py
│
├── tests/
│   └── <test_module>.py
│
├── requirements.txt
├── pytest.ini
├── README.md
└── playwright.config.ts
```

## 2. Core Components

### Configuration
Centralized YAML-based configuration loaded via utility helpers.

### Test Data
Supports YAML, JSON, and Excel driven testing.

### Page Object Model
One page class per UI screen with Playwright bindings.

### API Layer
Encapsulated API clients with reusable base logic.

### Codegen Postprocessing
Transforms Playwright codegen output into:
- pytest-bdd steps
- Page Object methods
- Assertion-aware actions

### Reporting
Allure / pytest-html with screenshots on failure.

## 3. Key Capabilities
- UI Automation (Playwright)
- API Automation
- Data-driven tests
- DB & Email validation
- Parallel execution
- Environment switching

## 4. How to Use
1. Record flows using Playwright codegen
2. Run postprocess_codegen.py
3. Execute tests via pytest
