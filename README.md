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

## Agentic AI + RAG

The framework now includes a production-ready agentic AI module under [ai](ai).

### Required Azure OpenAI environment variables

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_EMBEDDING_ENDPOINT` (optional, defaults to `AZURE_OPENAI_ENDPOINT`)
- `AZURE_OPENAI_EMBEDDING_API_KEY` (optional, defaults to `AZURE_OPENAI_API_KEY`)
- `AZURE_OPENAI_CHAT_DEPLOYMENT`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
- `AZURE_OPENAI_API_VERSION` (optional, default: `2024-10-21`)

### Main classes

- [AgentOrchestrator](ai/agents/orchestrator.py)
- [IntentAgent](ai/agents/intent_agent.py)
- [EmbeddingService](ai/rag/embedder.py)
- [QdrantVectorStore](ai/rag/vectordb.py)
- [InMemoryVectorStore](ai/rag/vectordb.py)
- [Retriever](ai/rag/retriever.py)
- [FeatureGenerator](ai/generator/feature_generator.py)
- [StepGenerator](ai/generator/step_generator.py)

### Qdrant DB setup

In [config/config.yaml](config/config.yaml), set:

- `ai.rag.vector_store: "qdrant"`
- `ai.rag.qdrant_persist_path: ".qdrant"`
- `ai.rag.qdrant_collection_name: "automation_kb"`

Use `"in_memory"` for non-persistent local testing.

### Python compatibility (recommended in restricted environments)

If you have issues with C++ compiler bindings, you can fallback to the standard in-memory storage:

- `ai.rag.vector_store: "in_memory_persist"`
- `ai.rag.in_memory_persist_path: ".vector_store/store.json"`

This keeps retrieval persistent across runs without changing Python version.

### Vector DB backend recommendation

- Python 3.14 + local persistent + higher scale: use `qdrant`
- Python 3.14 + simplest setup: use `in_memory_persist`
- `chroma` can remain optional, but may fail on Python 3.14 depending on dependency stack.

For Qdrant local mode in [config/config.yaml](config/config.yaml):

- `ai.rag.vector_store: "qdrant"`
- `ai.rag.qdrant_persist_path: ".qdrant"`
- `ai.rag.qdrant_collection_name: "automation_kb"`

### Quick usage

```python
from ai.agents.orchestrator import AgentOrchestrator

orchestrator = AgentOrchestrator(config_path="config/config.yaml")
result = orchestrator.run("Generate login feature and step definitions")
print(result)
```

### Staged CLI workflow

Use [ai/pipeline_cli.py](ai/pipeline_cli.py) for stage-wise execution.

1) Stage 1: Capture user actions via Playwright codegen

```bash
python ai/pipeline_cli.py stage1-codegen --url https://demoqa.com/ --output codegen_output.py
```

2) Stage 2: Generate baseline files from codegen

```bash
python ai/pipeline_cli.py stage2-baseline --codegen codegen_output.py --scenario "Checkout flow"
```

3) Stage 3: Index baseline + knowledge base into vector store (Chroma)

```bash
python ai/pipeline_cli.py stage3-index --config config/config.yaml
```

4) Stage 4: Generate enhanced files (baseline retained for comparison)

```bash
python ai/pipeline_cli.py stage4-enhance --config config/config.yaml --query "Create readable checkout automation"
```

5) Run all stages in one go

```bash
python ai/pipeline_cli.py stage-all --url https://demoqa.com/ --scenario "Checkout flow" --query "Create readable checkout automation"
```

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
