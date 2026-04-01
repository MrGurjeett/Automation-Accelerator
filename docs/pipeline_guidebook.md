# Pipeline Guidebook (End-to-End)

This guide covers running the **Excel → AI normalisation → feature generation → E2E execution** pipeline.

The end-to-end pipeline entrypoint is `main.py`.

## What the pipeline does

1) Auto-detects an Excel file in `input/`
2) Builds (or reuses) a DOM Knowledge Base (KB) by scanning the target app
3) Stores DOM elements in local Qdrant persistence (`.qdrant/`)
4) Validates and normalises your Excel steps via Azure OpenAI + RAG
5) Generates a Gherkin feature under `generated/features/`
6) Runs the generated scenarios via pytest (E2E is enabled automatically by the pipeline)

## Prerequisites (already installed in this workspace)

You still need valid runtime configuration:

- Azure OpenAI env vars in `.env` (copy from `.env.example`)
- A reachable target app (UI) for DOM scan + E2E execution

Recommended:

- Lock down `.env` permissions on macOS/Linux:
  - `chmod 600 .env`

## Quick start

From the repo root:

- Full pipeline (generate + execute):
  - `python main.py`

- Generate only (no pytest run):
  - `python main.py --generate-only`

- Force regeneration even if Excel unchanged:
  - `python main.py --force`

- Force DOM re-scan (rebuild KB):
  - `python main.py --scan`

## Excel input rules

The pipeline auto-detects Excel files in `input/`:

- If a "raw" file exists (filename contains `_raw`, e.g. `test_cases_raw.xlsx`), it is converted into a structured template and written to the corresponding non-raw name (e.g. `test_cases.xlsx`).
- Keep exactly one relevant `.xlsx` (or one raw + its matching template name) in `input/`.

## Outputs

- Generated feature file: `generated/features/<feature>.feature`
- Versioned run artifacts: `artifacts/versions/...`
- DOM KB persistence: `.qdrant/`

## Target app configuration (URL + login credentials)

### 1) E2E test base URL

The generated E2E runner reads the base URL in this order:

1) `BASE_URL` environment variable
2) `config/config.yaml` → `environments.<environment>.base_url`
3) Default ParaBank URL (keeps the repo runnable out-of-the-box)

For ParaBank, set `BASE_URL` to the full login page URL, for example:

- `BASE_URL=https://parabank.parasoft.com/parabank/index.htm`

### 2) DOM scan (knowledge base) URL + credentials

DOM scanning defaults to ParaBank + demo credentials, but can be overridden:

- `DOM_BASE_URL` (preferred) or `BASE_URL`
- `DOM_USERNAME` (preferred) or `UI_USERNAME`
- `DOM_PASSWORD` (preferred) or `UI_PASSWORD`

Example (one-off run):

- `DOM_BASE_URL=https://your-parabank-host/parabank/ DOM_USERNAME=john DOM_PASSWORD=demo python main.py --scan`

Notes:

- `DOM_BASE_URL` can be either the base directory (ending in `/parabank/`) or the full login page URL (ending in `index.htm`).

## Running the generated E2E tests manually

The pipeline runs E2E automatically, but you can run them yourself.

Important: `python` must be the interpreter that has `pytest` installed.

In this repo, that is typically the workspace venv, so prefer:

- `.venv/bin/python -m pytest ...`

If you use `pyenv`, `python` may point to a different interpreter (and then `python -m pytest` can fail with `No module named pytest`).
Sanity check:

- `which python`

- Run generated E2E module (recommended):
  - `.venv/bin/python -m pytest core/steps/test_generated.py --run-e2e -v`

- Run full suite (local tests + E2E enabled):
  - `.venv/bin/python -m pytest --run-e2e`

If you want to run ONLY the generated E2E scenarios (4 tests), select them explicitly:

- `.venv/bin/python -m pytest core/steps/test_generated.py --run-e2e -q`

Or via marker selection:

- `.venv/bin/python -m pytest -m e2e --run-e2e -q`

## Interactive UI (Browser)

This repo includes a lightweight browser-based UI (no extra dependencies) to run common operations and view live status.

- Start the UI server:
  - `.venv/bin/python -m ui.web_server`

Run it from the repo root so it can serve static files and read `artifacts/` and `generated/`.

- Open in your browser:
  - `http://127.0.0.1:8123`

What it shows:

- Live run status and tail logs
- Latest stats and cumulative token savings (from `artifacts/latest_stats.json` and `artifacts/cumulative_stats.json`)
- Generated outputs/artifacts viewer (safe, read-only)

## Interactive UI (Terminal)

This repo includes a lightweight interactive terminal UI (no extra dependencies) to run the common operations and watch status/logs/stats.

- Start the terminal UI:
  - `.venv/bin/python -m ui.tui`

Inside the UI you can:

- Run **Generate only**, **Run E2E only**, or the **Full pipeline**
- View live RAG/locator stats and Azure OpenAI token usage (when usage is available from the SDK)
- Set common env vars like `BASE_URL` / `UI_USERNAME` / `UI_PASSWORD` for the run

## Common troubleshooting

### "pytest: command not found" (exit code 127)

Use one of these instead:

- `python -m pytest ...`
- Or run the venv script directly: `.venv/bin/pytest ...`

### ParaBank demo site errors

If the public ParaBank demo returns an internal error after login (e.g. "An internal error has occurred and has been logged."), the generated E2E suite will be skipped to avoid false negatives caused by an external dependency outage.

If you have a stable ParaBank deployment, set `BASE_URL` and `DOM_BASE_URL` to your stable host.
