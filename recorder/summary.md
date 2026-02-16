# Summary: recorder/postprocess_codegen.py

## Purpose

This script post-processes Playwright codegen output, automatically generating robust BDD feature files, step definitions, and page object classes for a Python Playwright + pytest-bdd automation framework. It ensures all user actions and Playwright `expect` assertions are faithfully captured and mapped to maintainable, reusable test code.

---

## Main Sections & Functions

### 1. Configuration & Utilities

- **CONFIG_PATH**: Path to persistent config (`postprocess_config.json`) for storing settings like login step text and URL.

- **ask_file(prompt, ext, filetypes)**: Tkinter dialog to select or create a file.

- **ask_dir(prompt)**: Tkinter dialog to select a directory.

- **load_config()**: Loads persistent config or returns defaults.

---

### 2. AST & Code Parsing Helpers

- **_unparse_node(node)**: Converts an AST node back to source code.

- **_is_expect_call(node)**: Detects if an AST node is a Playwright `expect` assertion.

- **_normalize_assertion_line(line)**: Ensures assertion lines use `self.page` instead of `page`.

---

### 3. Action Mapping

- **ACTION_MAP**: Dict mapping action types (`click`, `fill`, etc.) to Gherkin step templates and step definition code.

---

### 4. Step Extraction

- **extract_steps_from_codegen(codegen_path)**:

  - Parses the Playwright codegen Python output.

  - Extracts user actions and `expect` assertions.

  - Normalizes assertion lines.

  - Builds a list of step dictionaries, each with action, selector, value, and assertions.

---

### 5. Feature File Generation

- **generate_feature_file(steps, feature_file, scenario_name)**:

  - Writes a Gherkin `.feature` file.

  - Uses extracted steps to create `Given` / `When` / `Then` lines.

  - Handles dynamic arguments (e.g., `{value}`).

---

### 6. Page Object Generation

- Generates/updates page object classes (e.g., `ngweb_page.py`).

- Each method corresponds to a user action.

- Injects assertion lines after relevant actions.

- Normalizes all Playwright `expect` assertions to use `self.page`.

- If a method already exists, it is overridden if assertions are present.

---

### 7. Step Definitions Generation

- **generate_step_defs_file(steps, steps_file, pages_package)**:

  - Generates/updates step definition files (e.g., `your_steps.py`).

  - Each step matches a Gherkin line and calls the corresponding page object method.

  - Includes logging and `set_default_timeout` for each step.

  - Handles dynamic arguments and error handling (fail-fast on `AssertionError`).

---

### 8. Main Script Logic

- **__main__**:

  - Parses CLI arguments for codegen file and scenario name.

  - Interactively asks for feature file, steps file, and pages directory.

  - Runs extraction and generation functions in sequence.

  - Prints summary of generated files.

---

## Output Format & Conventions

- **Feature Files**:

  - Gherkin syntax.

  - Scenario name provided by the user.

  - Steps mapped directly from codegen actions.

- **Step Definitions**:

  - Python, pytest-bdd.

  - One function per step.

  - Logging, timeouts, and error handling included.

- **Page Objects**:

  - Python class.

  - One method per action.

  - Assertions injected after actions.

  - All selectors defined as class attributes.

- **Assertions**:

  - All `expect` statements normalized to `self.page`.

  - Placed after the relevant action in the page method.

- **Persistent Config**:

  - Login step text and URL loaded from `postprocess_config.json` if present.

---

## Key Behaviors

- Duplicate steps (e.g., login) are removed.

- Step definitions match feature steps exactly, including dynamic arguments.

- All Playwright `expect` assertions are included and executed in generated code.

- Existing page methods are overridden if assertions are present.

- Logging and `set_default_timeout` are included in all step definitions for debugging.

- The script is interactive, using Tkinter dialogs for file/folder selection.

---

This summary provides a full breakdown of the script’s structure, logic, and output conventions, enabling another copilot agent to update or extend the file as per the current configuration and requirements.
 