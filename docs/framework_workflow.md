# Automation Accelerator Framework - How It Works

This document provides a comprehensive, end-to-end breakdown of how the AI-Governed BDD Automation Framework operates.

---

## 🚀 Quick Start — Running the Framework

### Prerequisites

- Python 3.12+ with venv activated (`.venv/`)
- Azure OpenAI credentials in `.env` (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`)
- Playwright browsers installed (`playwright install chromium`)
- Excel test-case file placed in the `input/` folder

### Commands

| Command | What It Does |
|---|---|
| `python main.py` | **Full E2E** — auto-detect Excel → validate → normalize via Azure OpenAI + Qdrant → generate feature → run tests in headed Chromium |
| `python main.py --generate-only` | **Generate only** — same pipeline but skips test execution |
| `python main.py --force` | Force regeneration even if Excel is unchanged |
| `python main.py --force --generate-only` | Force regenerate, skip tests |
| `python main.py --excel path/to/file.xlsx` | Use a specific Excel file instead of auto-detecting from `input/` |

### Single Entrypoint

The **only** file a user needs to execute is:

```
python main.py
```

Everything is automatic — zero prompts, zero manual file editing, zero approval steps.

### What Happens When You Run `python main.py`

```
Step  1  │  Auto-detect .xlsx file in input/ folder
Step  2  │  Schema validation (exact column match — hard stop on failure)
Step  3  │  Group rows by TC_ID
Step  4  │  Action & workflow validation per TC (hard stop on failure)
Step  5  │  AI normalisation via Azure OpenAI + Qdrant RAG (per step)
Step  6  │  Confidence gate at 0.85 per TC (reject below threshold)
Step  7  │  Generate parameterized .feature file (auto-overwrite)
Step  8  │  Create versioned folder under artifacts/versions/ (SHA256 hash)
Step  9  │  Auto-execute pytest in headed Chromium browser
Step 10  │  Print structured logs + exit with test result code
```

### Excel Contract (Strict Schema)

The Excel file **must** have exactly these columns:

| TC_ID | Page | Action | Target | Value | Expected |
|---|---|---|---|---|---|
| TC01 | Login | navigate | Login Page | - | - |
| TC01 | Login | fill | Username | student | - |
| TC01 | Login | fill | Password | Password123 | - |
| TC01 | Login | click | Submit Button | - | - |
| TC01 | Login | verify_text | Success Message | - | Logged In Successfully |

- **TC_ID**: Groups steps into a test case
- **Page**: Must match a registered POM in `core/pages/page_registry.py`
- **Action**: One of `navigate`, `fill`, `click`, `verify_text`
- **Target**: Must match a key in the POM's `SUPPORTED_FIELDS`
- **Value**: Data to fill (leave blank for empty-field tests, use `-` for non-fill actions)
- **Expected**: Expected text for `verify_text` actions

### Auto-Versioning Behavior

| Condition | Behavior |
|---|---|
| Excel changed | Full pipeline runs, new version folder created |
| Excel unchanged | Skips regeneration, runs tests from existing feature |
| `--force` flag | Forces full pipeline regardless of hash |

### Key Files (Do NOT Modify During Execution)

| File | Purpose |
|---|---|
| `core/pages/login_page.py` | POM — all locators live here exclusively |
| `core/pages/base_page.py` | Playwright wrapper (fill, click, verify) |
| `core/pages/page_registry.py` | Maps Excel Page column to POM classes |
| `core/steps/conftest.py` | Playwright fixtures, BASE_URL, POM setup |
| `core/steps/test_generated.py` | Step definitions matching generated Gherkin |

These files are **frozen** — the pipeline never modifies them.

### Output Files (Auto-Generated)

| File | Purpose |
|---|---|
| `generated/features/login.feature` | Generated BDD scenarios (auto-overwritten) |
| `artifacts/versions/<hash>_<timestamp>/` | Versioned copy of each generation |
| `artifacts/latest.json` | Manifest tracking current Excel hash |

---

## Architecture Deep Dive

### Project Structure (Current)

```
Automation-Accelerator/
├── main.py                         # Single entrypoint — orchestrates full pipeline
├── input/                          # Drop your .xlsx here (auto-detected)
│   └── test_cases.xlsx
├── excel/
│   └── excel_reader.py             # Reads .xlsx via pandas, returns list[dict]
├── validator/
│   ├── schema_validator.py         # Exact column match check (hard stop)
│   ├── action_validator.py         # Per-row action/target/value validation
│   └── workflow_validator.py       # Per-TC sequence validation (navigate first, etc.)
├── ai/
│   ├── config.py                   # AIConfig — loads .env + config.yaml
│   ├── normalizer.py               # Azure OpenAI + Qdrant RAG normaliser
│   ├── security.py                 # Prompt injection guards
│   ├── clients/
│   │   └── azure_openai_client.py  # Azure OpenAI SDK wrapper with retry
│   └── rag/
│       ├── embedder.py             # text-embedding-3-large embedding service
│       ├── retriever.py            # Qdrant similarity search
│       ├── vectordb.py             # Qdrant local persistent vector store
│       ├── text_chunker.py         # Document chunking utility
│       └── document_loader.py      # File-based document loader
├── generator/
│   ├── feature_generator.py        # Generates parameterized Gherkin .feature files
│   └── version_manager.py          # SHA256 hash-based versioning + manifest
├── execution/
│   └── runner.py                   # Auto-runs pytest as subprocess, parses results
├── core/                           # FROZEN — never modified by pipeline
│   ├── pages/
│   │   ├── base_page.py            # Playwright wrapper (fill, click, verify_text)
│   │   ├── login_page.py           # POM — all locators in SUPPORTED_FIELDS
│   │   └── page_registry.py        # Maps Excel "Page" column → POM class
│   └── steps/
│       ├── conftest.py             # Playwright fixtures, BASE_URL, POM instantiation
│       └── test_generated.py       # Step definitions matching generated Gherkin
├── generated/
│   └── features/
│       └── login.feature           # Auto-generated (overwritten each run)
├── artifacts/
│   ├── latest.json                 # Manifest with current Excel hash
│   └── versions/                   # Versioned snapshots per generation
├── config/
│   └── config.yaml                 # RAG / Azure OpenAI settings
├── .env                            # Azure OpenAI credentials (never committed)
└── pytest.ini                      # Playwright + pytest-bdd runner config
```

---

## 📥 Phase 1: Excel Ingestion & Validation

### Step 1: Auto-Detect Excel

When `python main.py` runs, it scans the `input/` folder for a single `.xlsx` file.

- **File:** `main.py` → `detect_excel()`
- **Behaviour:** Raises `FileNotFoundError` if no `.xlsx` found, raises `ValueError` if multiple `.xlsx` files exist.

### Step 2: Version Check (SHA256)

Before doing any work, the pipeline checks if the Excel has changed since the last run.

- **File:** `generator/version_manager.py` → `has_changed()`
- **Behaviour:**
  - Computes SHA256 hash of the Excel file
  - Compares against `artifacts/latest.json`
  - If unchanged → skips regeneration, runs tests from existing feature (unless `--force`)
  - If changed → proceeds with full pipeline

### Step 3: Read Excel

- **File:** `excel/excel_reader.py` → `read_excel()`
- **Behaviour:**
  - Reads `.xlsx` via pandas with `dtype=str`
  - Blank Value cells → empty string `""` (supports empty-field tests)
  - All other blank cells → `"-"`
  - Returns `list[dict]`

### Step 4: Schema Validation (Hard Stop)

- **File:** `validator/schema_validator.py` → `validate_schema()`
- **Behaviour:** Checks that columns match **exactly**: `TC_ID`, `Page`, `Action`, `Target`, `Value`, `Expected`. Any mismatch → `ValueError` → pipeline aborts.

### Step 5: Action & Workflow Validation (Hard Stop, Per TC)

- **File:** `validator/action_validator.py` → `validate_action()`
  - Action must be in `{navigate, fill, click, verify_text}`
  - Page must exist in `PAGE_REGISTRY`
  - Target must exist in POM's `SUPPORTED_FIELDS`
  - `fill` requires a non-dash Value
  - `verify_text` requires a non-dash Expected

- **File:** `validator/workflow_validator.py` → `validate_workflow()`
  - First step must be `navigate`
  - No duplicate navigates in a single TC
  - At least 2 steps per TC

---

## 🧠 Phase 2: AI Normalisation (Azure OpenAI + Qdrant RAG)

AI is **mandatory** during generation. AI is **never** used during test execution.

### Step 6: Qdrant Knowledge Base Seeding

- **File:** `ai/normalizer.py` → `AINormaliser.__init__()`
- **Behaviour:**
  - Embeds all BDD reference steps (navigate, fill, click, verify_text targets) using `text-embedding-3-large`
  - Upserts vectors into a local Qdrant persistent store (`.qdrant/` directory)
  - Collection name: `automation_kb`

### Step 7: Per-Step Normalisation

For each step in each TC:

1. **Embed the query** — convert `(action, target)` into a vector via Azure embeddings
2. **Qdrant similarity search** — retrieve top-K matching reference steps from the KB
3. **Build RAG context** — format retrieved steps as structured context
4. **GPT-4.1 prompt** — send the step + RAG context to Azure OpenAI with strict JSON output rules
5. **Parse response** — extract `normalized_action`, `normalized_target`, `value`, `expected`, `confidence`
6. **Confidence gate** — if any step in a TC scores below **0.85**, the entire TC is **rejected**

- **Files:**
  - `ai/normalizer.py` → `AINormaliser.normalise_tc()`
  - `ai/clients/azure_openai_client.py` → handles Azure API calls with retry
  - `ai/rag/embedder.py` → `EmbeddingService` (text-embedding-3-large)
  - `ai/rag/retriever.py` → `Retriever` (Qdrant similarity search)
  - `ai/rag/vectordb.py` → `QdrantVectorStore` (local persistent store)

### Output

Each accepted TC produces a list of `NormalisedStep` objects:
```python
@dataclass
class NormalisedStep:
    normalized_action: str    # e.g. "fill"
    normalized_target: str    # e.g. "Username"
    value: str | None         # e.g. "student"
    expected: str | None      # e.g. "Logged In Successfully"
    confidence: float         # e.g. 1.0
```

---

## 📝 Phase 3: Feature Generation & Versioning

### Step 8: Generate Parameterized Feature File

- **File:** `generator/feature_generator.py`
- **Behaviour:**
  - Groups accepted TCs by **flow signature** (ordered sequence of action+target, ignoring data values)
  - TCs with identical flow → merged into a single `Scenario Outline` with `Examples` table
  - TCs with different flows → separate Scenario Outlines
  - Empty values → represented as `[EMPTY]` sentinel in the Examples table
  - Output written to `generated/features/<name>.feature` (auto-overwrite, no prompt)

### Step 9: Version Folder (SHA256 + Timestamp)

- **File:** `generator/version_manager.py`
- **Behaviour:**
  - Creates `artifacts/versions/<hash_12chars>_<YYYYMMDD_HHMMSS>/`
  - Copies the generated `.feature` file there
  - Updates `artifacts/latest.json` manifest with current hash

---

## 🚀 Phase 4: Automatic Test Execution

### Step 10: Auto-Execute Pytest

- **File:** `execution/runner.py` → `run_tests()`
- **Behaviour:**
  - Runs `pytest core/steps/test_generated.py` as a subprocess using the same Python interpreter
  - All `pytest.ini` settings apply (headed Chromium, slow_mo, viewport, etc.)
  - Streams output to console in real time
  - Parses pass/fail/error counts from a quiet re-run
  - Returns structured `TestResult` dataclass

### Step 11: Pipeline Exit

- `main.py` prints a final summary (Excel path, feature path, version folder, pass/fail counts)
- Exits with the pytest exit code (0 = all passed, non-zero = failures)

---

## 🔒 Frozen Core Files (Never Modified by Pipeline)

These files are manually maintained. The pipeline never touches them:

| File | Role |
|---|---|
| `core/pages/base_page.py` | Thin Playwright wrapper — `fill_field()`, `click_field()`, `verify_text()`, `navigate_to()` |
| `core/pages/login_page.py` | POM with `SUPPORTED_FIELDS` dict — maps UI element names to Playwright locators |
| `core/pages/page_registry.py` | `PAGE_REGISTRY` dict — maps Excel "Page" values to POM classes |
| `core/steps/conftest.py` | `BASE_URL`, Playwright browser fixtures, POM instantiation fixture |
| `core/steps/test_generated.py` | pytest-bdd step definitions (`@given`, `@when`, `@then`) matching generated Gherkin |

### How Step Definitions Work at Runtime

```
Feature file says:    When I fill "Username" with "student"
                              ↓
Step definition:      @when('I fill "{field}" with "{value}"')
                              ↓
POM lookup:           pom.SUPPORTED_FIELDS["Username"] → page.locator("#username")
                              ↓
Playwright:           locator.fill("student")
```

No AI involved at runtime — pure deterministic Playwright execution.

---

## ⚙️ Configuration

### `.env` (Credentials)
```
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com/
```

### `config/config.yaml` (Settings)
Contains Azure OpenAI deployment names, RAG parameters, embedding model config, and Qdrant settings.

### `pytest.ini` (Test Runner)
- `testpaths = tests core/steps`
- `bdd_features_base_dir = generated/features/`
- `addopts = --headed --browser chromium -v`
- `timeout = 300`

---

## 📊 Data Flow Summary

```
input/test_cases.xlsx
    │
    ▼
┌─────────────────────────┐
│  excel/excel_reader.py  │  Read .xlsx → list[dict]
└───────────┬─────────────┘
            ▼
┌──────────────────────────────┐
│  validator/                  │  Schema + Action + Workflow checks (hard stop)
│  schema_validator.py         │
│  action_validator.py         │
│  workflow_validator.py       │
└───────────┬──────────────────┘
            ▼
┌──────────────────────────────┐
│  ai/normalizer.py            │  Azure OpenAI + Qdrant RAG
│  ai/rag/embedder.py          │  Embed → Search → Normalise
│  ai/rag/retriever.py         │  Confidence gate at 0.85
│  ai/clients/azure_openai_client.py │
└───────────┬──────────────────┘
            ▼
┌──────────────────────────────┐
│  generator/                  │  Group by flow → Scenario Outline
│  feature_generator.py        │  Write .feature (auto-overwrite)
│  version_manager.py          │  SHA256 versioned folder
└───────────┬──────────────────┘
            ▼
┌──────────────────────────────┐
│  execution/runner.py         │  pytest subprocess → headed Chromium
│  core/steps/test_generated.py│  Step defs → POM → Playwright
│  core/pages/login_page.py    │  Locators (#username, #password, etc.)
└──────────────────────────────┘
            ▼
        TEST RESULTS
    (exit code 0 = all passed)
```
