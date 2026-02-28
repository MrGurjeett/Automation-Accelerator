# Automation Accelerator Framework - How It Works

This document provides a comprehensive, end-to-end breakdown of how the highly advanced Agentic AI Test Automation Framework operates. It traces the lifecycle of a request from the initial human input all the way down to script generation and test execution.

---

## ⏺️ Stage 1: UI Action Codegen & Recording (`stage1-codegen`)

The journey formally begins when the automation engineer initiates the codegen pipeline. Instead of writing tests from scratch, the framework is designed to *watch* you.

### Action Capture
If the `stage1-codegen` CLI command is called:
*   **Files Involved:**
    *   `ai/pipeline_cli.py`: Evaluates the command arguments.
    *   `recorder/launch_codegen.py`: Starts a background process invoking Playwright's native `codegen` inspector on your specified URL.
*   **What happens:** Playwright boots a live Chrome/Firefox viewport. As the engineer clicks buttons, types in text forms, and logs into the target website, Playwright actively synthesizes those interactions down into raw Python equivalents, generating a raw file typically designated as `codegen_output.py`.

---

## 🛠️ Stage 2: Baseline Post-Processing (`stage2-baseline`)

Raw codegen output is highly unstructured and unreadable. You do not want a 500-line script of raw `page.locator().click()` calls. The framework steps in here to convert raw recordings into standard Page Object Modals (POM) and baseline BDD features.

### AST Manipulation & Class Scaffolding
*   **Files Involved:**
    *   `recorder/postprocess_codegen.py`: A powerhouse analyzer that parses the `codegen_output.py` Python AST (Abstract Syntax Tree). 
    *   `postprocess_config.json`: Evaluates fallback locators and variable typings.
*   **What happens:** 
    1.  *Page Objects generated:* The script guesses the page names from the URL locators and parses actions into exact method bindings (like `def submit_login_button(self):`). It writes these directly to `pages/generated/`.
    2.  *Baseline File Spawning:* It extracts the narrative intent of those clicks and formulates a crude `features/generated.feature` file and matching step definitions `features/steps/step_definitions/generated_steps.py`.

---

## 🧠 Stage 3 & 4: RAG Knowledge Indexing and LLM Enhancement (`stage3-index` & `stage4-enhance`)

### Indexing the Baseline
The previously generated "dumb" baseline code needs to be indexed so the AI can understand *exactly* what UI elements currently exist.
*   **Files Involved:** `ai/rag/document_loader.py`, `ai/rag/vectordb.py` (Qdrant).
*   **What happens:** By running `stage3-index`, the framework takes your newly crafted `codegen_output.py`, `generated.feature`, and `pages/generated` classes, converts them into chunks, gets their Azure embeddings representations, and shoves those into the local Qdrant memory.

### Intent, Planning & Refinement Generation
This is the Agentic AI "Brain" at work. You pass a prompt parameter such as: *"Using my recorded actions, make the login robust to handle 3 types of bad passwords and add negative testing."*

*   **Files Involved:**
    *   `ai/agents/orchestrator.py` & `intent_agent.py`: Parses the fact you want to "enhance" the previous feature.
    *   `ai/rag/retriever.py`: Hits Qdrant database to dig up your generated base Page Objects and Locators from Stage 2.
    *   `ai/generator/feature_generator.py` & `step_generator.py`: Takes the parsed intent + the human's query + the retrieved codegen memory block and hits `Azure OpenAI` (`gpt-4.1`). 
*   **What happens:** Azure returns beautiful, fine-tuned, production-grade Gherkin BDD (`generated_enhanced.feature`) and robust Pytest Step Definitions (`generated_steps_enhanced.py`) that handles edge cases perfectly without the human having to do anything but click buttons in Stage 1!

---

## 🚀 Final Execute: Pytest Execution
Finally, with fine-tuned, enhanced files ready in `features/` directory...

*   **Files Involved:** `pytest.ini`, `features/steps/hooks.py`
*   **What happens:** Standard Pytest runner executes. Pytest-BDD maps the LLM-enhanced `.feature` file sentences accurately into the customized python step definitions that then drive standard Headless Playwright workers across the UI. Test results execute cleanly and pump out formatted Allure results!

### Step 1: Configuration Loading
When a script starts (like `pipeline_cli.py` or a custom test file), it boot-straps the system using the unified config layer.

*   **Files Involved:**
    *   `config/config.yaml`: Contains fallback settings for vector DB, timeout logic, reporting directories, and more.
    *   `.env`: Holds your sensitive API credentials (Azure OpenAI strings).
    *   `ai/config.py`: The `AIConfig` and `AzureOpenAISettings` classes parse both the yaml and the env file securely into python objects logic can use.
*   **What happens:** The system binds Azure credentials and figures out the RAG settings (e.g., semantic weights vs. keyword matching).

---

## 🤖 Phase 2: Agent Orchestration & Planning (The "Brain")

When you provide a prompt like, *"Generate a login feature for demoqa"*, the system orchestrates sub-agents to dissect and act on the prompt.

### Step 2: Orchestrator Activation
The orchestrator spins up the internal database clients, embedding connections, and sub-agents. 

*   **Files Involved:**
    *   `ai/agents/orchestrator.py`: The primary engine.
    *   `ai/clients/azure_openai_client.py`: Establish connection to Azure endpoints with a robust retry mechanism.

### Step 3: Intent Classification
The orchestrator checks your request to figure out what you want.

*   **Files Involved:**
    *   `ai/agents/intent_agent.py`: Parses the raw prompt string (`query`) and maps it to `IntentType` (e.g., `GENERATE_FEATURE`, `INDEX_KNOWLEDGE`, `RAG_QUERY`, etc.). It uses keyword evaluations to rank the probability of an intent.

### Step 4: Plan Construction
Once the framework knows *what* you want, it details *how* to do it.

*   **Files Involved:**
    *   `ai/agents/planner_agent.py`: Receives the intent from Step 3 and constructs a sequential list of steps called a `PlanStep`. For standard generation, the plan is always: 1. `Retrieve context` -> 2. `Generate feature`.

---

## 📚 Phase 3: Retrieval-Augmented Generation (RAG Workflow)

LLMs sometimes hallucinate. This architecture counters that by indexing "Knowledge" directly from your codebase or specific framework documents to feed into Azure so it outputs correct code format.

### Step 5: Document Indexing (If running `INDEX_KNOWLEDGE`)
If adding contexts (or running `stage3-index` from CLI), raw text is converted to math variables (vectors).

*   **Files Involved:**
    *   `ai/rag/document_loader.py`: Reads baseline code (`.py`, `.md`, `.feature` files).
    *   `ai/rag/text_chunker.py`: Splits large documents safely into readable `900` token chunks.
    *   `ai/rag/embedder.py`: Sends chunks to Azure to get `text-embedding-3-large` mathematical arrays.
    *   `ai/rag/vectordb.py`: Saves these arrays permanently inside the `QdrantVectorStore`. 

### Step 6: Context Retrieval (If running Code Generation)
When you ask it to generate code, it searches the vector DB for similarities first. 

*   **Files Involved:**
    *   `ai/rag/retriever.py`: Converts your query into an embedding, checks `Qdrant` DB against closest math similarities, and pulls relevant past file logic directly from the DB. 

---

## 📝 Phase 4: Code Generation Strategy

Inside the Execution environment, passing the retrieved code blocks + your user prompt forward to the Azure GPT models to get actual syntax.

### Step 7: Executing The Generation
*   **Files Involved:**
    *   `ai/agents/execution_agent.py`: The `ExecutionAgent` steps through your `PlannerAgent`'s outline iteratively.
    *   `ai/generator/feature_generator.py`: Takes the context and prompt, adds system instructions limits (must generate valid BDD Gherkin), and builds the `.feature` file text.
    *   `ai/generator/step_generator.py`: Once the feature file completes, it uses that text internally to auto-generate identical `pytest-bdd` Python parser functions for `features/steps/`.
    *   `ai/transformers/normalizer.py`: Ensures outputs are clean and formats them stringently.

---

## 🚀 Phase 5: Pipeline Codegen & Execution (UI & End-to-End)

Optionally, you can use Playwright built-in configurations to record code or finally execute the full setup!

### Step 8: Playwright Code Generation (Optional CLI feature)
*   **Files Involved:**
    *   `recorder/launch_codegen.py` & `recorder/action_recorder.py`: If you run the `stage-all` pipeline, this module uses Playwright to open a browser and records human actions directly using AST/Python AST manipulations to output clean page object files.

### Step 9: Final Test Execution
Ultimately, the goal is always execution. Standard Pytest testing architecture dominates this side.

*   **Files Involved:**
    *   `pytest.ini`: Controls runner configurations.
    *   `features/steps/conftest.py` & `hooks.py`: Setup environment variables locally for Playwright browsers before executing feature files.
    *   `tests/test_api.py` or `.feature` runner files: Output is tested and validated natively here!

---

### Basic System Data Flow Summary
1.  **START:** Human executes CLI script `pipeline_cli.py` or custom script.
2.  **READ:** Framework loads `.env` and `config.yaml`.
3.  **THINK (`AgentOrchestrator`):**
    *   `IntentAgent` guesses what user wants.
    *   `PlannerAgent` creates the step-by-step pipeline state map.
4.  **SEARCH (`Retriever`):** Connects to `Qdrant` vector storage to find code snippets. 
5.  **ASK (`Generator`):** Sends Context -> Azure API -> Gets back code string.
6.  **SAVE (`PostProcess`)**: Turns raw LLM output into concrete directories (`pages/generated/`, `features/`).
7.  **EXECUTE (`pytest`)**: Pytest runs Playwright browser steps against generated code!
