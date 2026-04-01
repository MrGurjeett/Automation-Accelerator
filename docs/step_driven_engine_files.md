# Step-Driven Execution Engine — Files Reference

This document lists the files added or modified as part of the Step-Driven Execution Engine refactor, with short descriptions and where they are used.

**Overview**
- Purpose: Map Gherkin steps to Page Object methods and execute them via Playwright.
- Entry points: pytest-bdd feature files under `features/` and step definitions under `features/steps/`.

**Key Files (new / modified)**
- **ai/execution/__init__.py**: Package initializer exporting the `StepDispatcher` and `IntentMapper` APIs.
- **ai/execution/intent_mapper.py**: Rule-based regex mapper that converts natural step text into `MappedAction` (action key, method name, params, optional POM hint).
- **ai/execution/step_dispatcher.py**: Orchestrator for a single step: RAG normalisation → intent mapping → POM resolution → parameter preparation → Playwright execution. Contains `_resolve_fill_locator`, `_execute_smart_fill`, and helper ID-pattern generator.
- **ai/agents/intent_agent.py**: Added `EXECUTE_STEP` intent and hints (minor change to integrate with agents).
- **ai/agents/planner_agent.py**: Planner updated with `EXECUTE_STEP` plan stages (normalise → map).
- **ai/agents/orchestrator.py**: Registered new actions (`normalise_step`, `map_step_to_pom`) used by orchestration flows.

- **ai/rag/embedder.py**: (existing) Embedding wrapper used by the Retriever.
- **ai/rag/retriever.py**: (existing) Retriever implementation used by `_normalise_via_rag()` in the dispatcher.
- **ai/rag/vectordb.py**: (existing) Vector store implementations (InMemory, PersistentInMemory, Qdrant).
- **ai/clients/azure_openai_client.py**: (existing) Client used for embeddings (may be called during RAG ops).

- **pages/registration_page.py**: A Page Object Model (POM) for the registration form with encapsulated locators/methods used in examples.
- **pages/base_page.py**: Base POM utilities (navigation, click, fill, expect_visible, etc.). Dispatcher calls these methods.

- **features/step_driven_demo.feature**: Example feature demonstrating step-driven scenarios (registration, upload, login).
- **features/steps/step_definitions/step_driven_steps.py**: Thin step-definition wrappers that delegate raw step text + Playwright `page` fixture to `StepDispatcher.dispatch()` and register POM instances per scenario.

- **test_step_engine.py**: Dry-run test harness for the mapper (20/20 mapper tests passing in dry run).
- **_verify_locators.py**: Small utility used during development to verify locator generation strategies.

**Configuration & Data**
- **config/config.yaml**: Holds configuration for RAG/vector store, Azure/OpenAI client settings, timeouts, and other AI-related configuration.
- **.qdrant/** (if using Qdrant backend): Persistent vector store directory (configured via `config.yaml`).

**Artifacts & Outputs**
- Playwright artifacts (traces, videos, downloads) are written according to `pytest-playwright` configuration (not changed by the refactor).
- Dispatcher debug logs are emitted to console/pytest capture. The dispatcher can take screenshots to `screenshots/step_screenshot.png` when requested.
- Temporary test-run captures (from manual runs) may be in `/tmp/reg_test*.txt` — these are not framework outputs by default.

**Where AI / RAG is used**
- The only AI-assisted stage is step normalisation: `StepDispatcher._normalise_via_rag()` calls the `Retriever` which uses `EmbeddingService` and the vector store to find canonical KB step phrasing. If a strong match is found the canonical phrasing is used; otherwise the original step text is used. This keeps mapping deterministic and rule-based.
- Components involved: `ai/clients/azure_openai_client.py`, `ai/rag/embedder.py`, `ai/rag/retriever.py`, `ai/rag/vectordb.py`.

**How to run the example feature locally**
1. Activate your venv and install dependencies from `requirements.txt`.
2. Run the step-driven feature (headed chromium):

```bash
source .venv/bin/activate
python -m pytest features/steps/step_definitions/step_driven_steps.py -k "Successful_student" --headed --browser chromium --no-header -v
```

This reproduces the registration scenario used during testing.

**Notes & Next Steps**
- The document above is a concise reference. If you want, I can extend this to include a file-by-file annotated walkthrough (showing important functions / class signatures), add inline links to code locations, or produce a single README summarising usage and how to add new step rules.

**Annotated Walkthrough (quick)**
- **Dispatcher & execution**: [ai/execution/step_dispatcher.py](ai/execution/step_dispatcher.py#L1-L40)
	- Key responsibilities: `_normalise_via_rag()`, `_resolve_pom()`, `_execute()`, `_execute_smart_fill()`, `_resolve_fill_locator()`.
	- Data record: `DispatchResult` (top of file) captures original/normalised step, mapped action, execution outcome.

- **Intent mapping**: [ai/execution/intent_mapper.py](ai/execution/intent_mapper.py#L1-L40)
	- Regex rules produce `MappedAction` objects (action_key, method_name, params, page_object_class).
	- Add new rules via `register_rule()` for project-specific phrases.

- **Base POM utilities**: [pages/base_page.py](pages/base_page.py#L1-L40)
	- Common methods: `navigate_to()`, `click()`, `fill()`, `expect_visible()`, `expect_text()` used by dispatcher-executed POM methods.

- **Example POM**: [pages/registration_page.py](pages/registration_page.py#L1-L120)
	- Encapsulates field locators and offers methods such as `fill_first_name()`, `select_gender()`, `upload_file()`, `click_submit()`, `assert_registration_success()`.

- **Feature / Step defs**: [features/step_driven_demo.feature](features/step_driven_demo.feature#L1-L40) and [features/steps/step_definitions/step_driven_steps.py](features/steps/step_definitions/step_driven_steps.py#L1-L120)
	- The step defs call `StepDispatcher.dispatch(step_text, page)` and register scenario POMs into the `PageObjectRegistry`.

- **RAG / Retriever stack**:
	- Embeddings: [ai/rag/embedder.py](ai/rag/embedder.py#L1-L80)
	- Retriever: [ai/rag/retriever.py](ai/rag/retriever.py#L1-L120) invoked by the dispatcher.
	- Vector stores: [ai/rag/vectordb.py](ai/rag/vectordb.py#L1-L140) (InMemory, PersistentInMemory, Qdrant).

- **AI client**: [ai/clients/azure_openai_client.py](ai/clients/azure_openai_client.py#L1-L120) — used for embeddings; configurable in `config/config.yaml`.

- **Agent integration points (optional flows)**: [ai/agents/orchestrator.py](ai/agents/orchestrator.py#L1-L60), [ai/agents/planner_agent.py](ai/agents/planner_agent.py#L1-L80), [ai/agents/intent_agent.py](ai/agents/intent_agent.py#L1-L60)
	- These are minimal wiring changes enabling the `EXECUTE_STEP` intent to be used by higher-level agent flows.

**Recommended next edits**
- Add more POM wrappers for frequently-used pages and expose small helper methods (e.g., `fill_email()`), which makes mapping simpler and keeps locators in one place.
- Expand `ai/execution/intent_mapper.py` with organisation-specific phrasings and test them via `test_step_engine.py`.

---

Updated: concise annotated walkthrough added.
