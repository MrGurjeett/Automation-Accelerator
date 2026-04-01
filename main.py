#!/usr/bin/env python3
"""
main.py — AI-Driven Automation Framework

Fully automatic pipeline with DOM Knowledge Extraction + RAG.  Run with:
    python main.py              # auto-detect Excel in input/
    python main.py --force      # force regeneration even if unchanged
    python main.py --scan       # force DOM re-scan

Pipeline (zero manual intervention):
  1. Auto-detect Excel in input/
  2. DOM Knowledge Extraction (scan-once — ParaBank pages)
  3. Store DOM elements in Qdrant vector database
  4. Change Detection (mtime-based — regenerate if Excel modified)
  5. Schema Validation (hard stop)
  6. Group rows by TC_ID
  7. Action & Workflow Validation (hard stop, per TC)
  8. AI Normalisation via Azure OpenAI + Qdrant RAG + DOM Knowledge
  9. RAG Element Resolution + Locator Generation
  10. Confidence Threshold Gate (0.85, per TC)
  11. Generate Parameterized Feature File (auto-overwrite)
  12. Versioned Storage (mtime + hash-based, auto)
  13. Auto-execute pytest (headed Chromium, fresh context per test)
  14. Structured log output with AI demo visibility
  15. Exit with pytest exit code
"""
from __future__ import annotations

import glob
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd

from ai.normalizer import AINormaliser, GenerationError, NormalisedStep
from ai.config import AIConfig
from ai.raw_step_converter import RawStepConverter
from excel.excel_reader import read_excel
from validator.schema_validator import validate_schema
from validator.action_validator import validate_action
from validator.workflow_validator import validate_workflow
from generator.feature_generator import generate_feature, write_feature_file
from generator.version_manager import (
    has_changed,
    create_version_folder,
    save_artifact,
    get_latest_version_folder,
)
from execution.runner import run_tests
import ai.ai_stats as ai_stats


def _read_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _get_shared_stats() -> dict[str, int]:
    """Get stats from the shared AI_STATS_PATH file (preferred), else in-memory."""
    stats_path = (os.environ.get("AI_STATS_PATH") or "").strip()
    if stats_path:
        loaded = ai_stats.load_from_file(stats_path)
        if loaded:
            return loaded
    return ai_stats.snapshot()


def _update_cumulative_stats(run_stats: dict[str, int]) -> dict:
    """Update cumulative counters stored under artifacts/cumulative_stats.json."""
    path = Path("artifacts/cumulative_stats.json")
    existing = _read_json(path)
    cumulative = existing.get("cumulative", {}) if isinstance(existing, dict) else {}

    def _inc(key: str, amount: int) -> None:
        cumulative[key] = int(cumulative.get(key, 0) or 0) + int(amount or 0)

    _inc("runs", 1)
    _inc("tokens_total", run_stats.get("tokens_total", 0))
    _inc("tokens_saved_total", run_stats.get("tokens_saved_total", 0))
    _inc("aoai_chat_calls", run_stats.get("aoai_chat_calls", 0))
    _inc("aoai_embedding_calls", run_stats.get("aoai_embedding_calls", 0))
    _inc("aoai_cache_hits", run_stats.get("aoai_cache_hits", 0))
    _inc("rag_resolutions", run_stats.get("rag_resolutions", 0))
    _inc("locator_healing", run_stats.get("locator_healing", 0))

    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "cumulative": cumulative,
    }
    _write_json(path, payload)
    return payload

# ── Logging ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("compiler")


# ── Auto-detect Excel ───────────────────────────────────────────────────

INPUT_DIR = "input"
RAW_SUFFIX = "_raw"  # e.g. test_cases_raw.xlsx


def detect_excel() -> tuple[str, str | None]:
    """Auto-detect Excel files in the input/ folder.

    Returns
    -------
    tuple[str, str | None]
        (template_path, raw_path).
        - If only a structured template exists: (template, None)
        - If only a raw file exists: (generated_template, raw_path)
        - If both exist: (template, raw_path)  — raw takes priority and
          will overwrite the template during conversion.

    Raises
    ------
    FileNotFoundError
        If input/ does not exist or contains no .xlsx files.
    """
    if not os.path.isdir(INPUT_DIR):
        raise FileNotFoundError(
            f"Input folder '{INPUT_DIR}/' not found. "
            f"Create it and place your Excel file there."
        )

    xlsx_files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.xlsx")))
    if not xlsx_files:
        raise FileNotFoundError(
            f"No .xlsx files found in '{INPUT_DIR}/'. "
            f"Place your test-case Excel file there."
        )

    # Separate raw files from template files
    raw_files = [f for f in xlsx_files if RAW_SUFFIX in os.path.basename(f)]
    template_files = [f for f in xlsx_files if RAW_SUFFIX not in os.path.basename(f)]

    raw_path: str | None = None
    template_path: str

    if raw_files:
        if len(raw_files) > 1:
            raise ValueError(
                f"Multiple raw .xlsx files in '{INPUT_DIR}/': {raw_files}. "
                f"Keep exactly one raw file."
            )
        raw_path = raw_files[0]
        # Derive template name: test_cases_raw.xlsx → test_cases.xlsx
        base = os.path.basename(raw_path).replace(RAW_SUFFIX, "")
        template_path = os.path.join(INPUT_DIR, base)
    elif template_files:
        if len(template_files) > 1:
            raise ValueError(
                f"Multiple .xlsx files in '{INPUT_DIR}/': {template_files}. "
                f"Keep exactly one."
            )
        template_path = template_files[0]
    else:
        raise FileNotFoundError(
            f"No valid .xlsx files found in '{INPUT_DIR}/'."
        )

    return template_path, raw_path


def _discover_dom_pages(dom_store) -> set[str]:
    """Discover unique page names stored in the DOM Knowledge Base.

    Queries the DOM vector store and extracts distinct page names from
    the stored elements' metadata.  These become dynamic pages that can
    be handled without hand-crafted POMs.
    """
    try:
        # Use a broad search to get elements from all pages
        results = dom_store.search("page navigation menu link button input", top_k=200, min_score=0.0)
        page_names: set[str] = set()
        for r in results:
            page = r.get("metadata", {}).get("page", "")
            if page:
                page_names.add(page)
        logger.info("[DOM] Discovered %d page(s) in DOM KB: %s", len(page_names), sorted(page_names))
        return page_names
    except Exception as exc:
        logger.warning("[DOM] Could not discover pages from DOM KB: %s", exc)
        return set()


# ── Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    excel_path: str | None = None,
    feature_name: str = "Login",
    *,
    force: bool = False,
    generate_only: bool = False,
    force_scan: bool = False,
) -> int:
    """Execute the full compiler pipeline.  Returns pytest exit code.

    Parameters
    ----------
    excel_path : str, optional
        Explicit path to .xlsx.  Auto-detected from input/ if omitted.
    feature_name : str
        Feature title for the generated .feature file.
    force : bool
        If True, regenerate even when the Excel hash is unchanged.
    generate_only : bool
        If True, only generate the feature file — do NOT execute tests.
    force_scan : bool
        If True, force DOM re-extraction even if knowledge base exists.

    Returns
    -------
    int
        0 if all tests passed (or generation-only succeeded), non-zero otherwise.
    """

    # ── 0. Shared stats file (cross-process) ────────────────────────────
    # This allows the pytest subprocess to contribute RAG/healing/token stats
    # that can be displayed in an interactive UI.
    os.environ.setdefault("AI_STATS_PATH", "artifacts/latest_stats.json")
    ai_stats.reset()

    # ── 1. Detect Excel ─────────────────────────────────────────────────
    raw_path: str | None = None
    if excel_path is None:
        excel_path, raw_path = detect_excel()
    logger.info("═══════════════════════════════════════════════════════")
    logger.info("  AI-Driven Automation Framework — Pipeline Start")
    logger.info("═══════════════════════════════════════════════════════")
    if raw_path:
        logger.info("[INFO] Raw Excel detected: %s", raw_path)
        logger.info("[INFO] Template target:    %s", excel_path)
    else:
        logger.info("[INFO] Excel detected: %s", excel_path)

    # ── 2. DOM Knowledge Extraction (Scan-Once Policy) ──────────────────
    config = AIConfig.load()

    from ai.clients.azure_openai_client import AzureOpenAIClient
    from ai.rag.embedder import EmbeddingService
    from framework.vector_store.qdrant_client import DOMVectorStore
    from framework.dom_extractor import extract_all_pages

    ai_client = AzureOpenAIClient(config.azure_openai)
    embedder = EmbeddingService(ai_client)
    dom_store = DOMVectorStore(embedder)

    dom_base_url = (
        os.environ.get("DOM_BASE_URL")
        or os.environ.get("BASE_URL")
        or "https://parabank.parasoft.com/parabank/"
    ).strip()
    dom_username = (
        os.environ.get("DOM_USERNAME")
        or os.environ.get("UI_USERNAME")
        or "john"
    ).strip()
    dom_password = (
        os.environ.get("DOM_PASSWORD")
        or os.environ.get("UI_PASSWORD")
        or "demo"
    ).strip()

    if force_scan or not dom_store.is_populated():
        if force_scan:
            try:
                dom_store.clear()
            except Exception as exc:
                logger.warning("[DOM] Force-scan requested but could not clear DOM KB: %s", exc)
        print()
        print("=" * 60)
        print("  Building AI DOM Knowledge Base...")
        print("-" * 60)
        print("  Scanning application pages...")
        print("  Indexing UI elements into vector database...")
        print("=" * 60)
        logger.info("[DOM] DOM knowledge base not found — running extraction…")
        logger.info("[DOM] Target base URL: %s", dom_base_url)
        logger.info("[DOM] Target username: %s", dom_username or "<empty>")
        elements = extract_all_pages(base_url=dom_base_url, username=dom_username, password=dom_password)
        dom_store.store_elements(elements)

        # Count unique pages from extracted elements
        pages_scanned = len({e.page_name for e in elements})
        ai_stats.increment("dom_elements", len(elements))
        ai_stats.increment("pages_scanned", pages_scanned)

        print()
        print("=" * 60)
        print("  AI DOM Knowledge Base Ready")
        print("-" * 60)
        print(f"  Total elements indexed: {len(elements)}")
        print(f"  Pages scanned:          {pages_scanned}")
        print(f"  Vector DB:              Qdrant (local)")
        print("=" * 60)
        print()
        logger.info("[DOM] DOM knowledge extracted and stored in Qdrant")
    else:
        # Retrieve count from store for the cached path
        cached_count = dom_store.count()
        ai_stats.increment("dom_elements", cached_count)
        print()
        print("=" * 60)
        print("  AI DOM Knowledge Base Loaded From Cache")
        print("-" * 60)
        print(f"  Total elements indexed: {cached_count}")
        print(f"  Vector DB:              Qdrant (local)")
        print("=" * 60)
        print()
        logger.info("[DOM] DOM knowledge base exists — reusing stored knowledge")

    # ── 2a. Register Dynamic Pages from DOM KB ──────────────────────────
    from core.pages.page_registry import register_dynamic_pages
    dom_pages = _discover_dom_pages(dom_store)
    register_dynamic_pages(dom_pages)

    # ── 2b. Raw Step Conversion (if raw file detected) ───────────────────
    if raw_path is not None:
        print()
        print("=" * 60)
        print("  Converting Raw Steps → Structured Template")
        print("-" * 60)
        logger.info("[RAW] Converting raw steps from %s", raw_path)

        converter = RawStepConverter(config, dom_store=dom_store)
        converter.convert_file(raw_path, excel_path)

        raw_count = len(pd.read_excel(raw_path, dtype=str))
        ai_stats.increment("raw_steps_converted", raw_count)

        print(f"  Raw steps converted:    {raw_count}")
        print(f"  Output:                 {excel_path}")
        print("=" * 60)
        print()
        logger.info("[RAW] Template generated: %s", excel_path)

        # Force regeneration since we just created a new template
        force = True

    # ── 3. Version check (mtime-based) ──────────────────────────────────
    if not force and not has_changed(excel_path):
        logger.info("Excel unchanged (same mtime). Skipping regeneration.")
        if generate_only:
            logger.info("Generation-only mode — nothing to regenerate.")
            run_stats = _get_shared_stats()
            _write_json(
                "artifacts/latest_run.json",
                {
                    "completed_at": datetime.now().isoformat(timespec="seconds"),
                    "mode": "generate-only",
                    "regenerated": False,
                    "excel": excel_path,
                    "version_folder": get_latest_version_folder(),
                    "stats": run_stats,
                    "cumulative": _update_cumulative_stats(run_stats).get("cumulative", {}),
                },
            )
            return 0
        logger.info("Executing tests from existing generated feature…")
        result = run_tests()
        run_stats = _get_shared_stats()
        _write_json(
            "artifacts/latest_run.json",
            {
                "completed_at": datetime.now().isoformat(timespec="seconds"),
                "mode": "run-only",
                "regenerated": False,
                "excel": excel_path,
                "version_folder": get_latest_version_folder(),
                "tests": {
                    "exit_code": result.exit_code,
                    "passed": result.passed,
                    "failed": result.failed,
                    "errors": result.errors,
                    "total": result.total,
                },
                "stats": run_stats,
                "cumulative": _update_cumulative_stats(run_stats).get("cumulative", {}),
            },
        )
        return result.exit_code

    if force:
        # Clear manifest to force regeneration
        manifest = "artifacts/latest.json"
        if os.path.exists(manifest):
            os.remove(manifest)
        logger.info("Force flag set — regenerating regardless of mtime.")

    # ── 3. Read Excel ───────────────────────────────────────────────────
    rows = read_excel(excel_path)

    # ── 4. Schema validation (hard stop) ────────────────────────────────
    logger.info("[INFO] Validating schema…")
    validate_schema(rows[0].keys())
    logger.info("[INFO] Schema validated")

    # ── 5. Group by TC_ID ───────────────────────────────────────────────
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["TC_ID"]].append(row)

    logger.info("Found %d test case(s): %s", len(grouped), sorted(grouped.keys()))

    # ── 6. Validate actions & workflows (per TC, soft rejection) ──────────
    validated_grouped: Dict[str, List[dict]] = {}
    validation_rejected: List[str] = []

    for tc_id, tc_rows in grouped.items():
        try:
            validate_workflow(tc_id, tc_rows)
            for row in tc_rows:
                validate_action(row)
            validated_grouped[tc_id] = tc_rows
            logger.info("[INFO] %s validated (%d steps)", tc_id, len(tc_rows))
        except ValueError as e:
            validation_rejected.append(tc_id)
            logger.warning("[SKIP] %s validation failed: %s", tc_id, e)

    if validation_rejected:
        logger.warning(
            "Validation rejected %d TC(s): %s — they reference pages/targets "
            "without Page Object Models. Create POMs and add them to the page registry.",
            len(validation_rejected), sorted(validation_rejected),
        )

    if not validated_grouped:
        logger.error("No test cases passed validation. Aborting.")
        return 1

    logger.info(
        "Validation passed: %d TC(s) — %s",
        len(validated_grouped), sorted(validated_grouped.keys()),
    )

    # ── 7. AI Normalisation (mandatory, per TC) ─────────────────────────
    logger.info("Initialising AI Normaliser (Azure OpenAI + Qdrant RAG + DOM Knowledge)…")
    normaliser = AINormaliser(config, dom_store=dom_store)

    accepted_tcs: Dict[str, List[NormalisedStep]] = {}
    rejected_tcs: List[str] = []

    for tc_id, tc_rows in validated_grouped.items():
        logger.info("── Normalising TC '%s' (%d steps) ──", tc_id, len(tc_rows))
        try:
            steps = normaliser.normalise_tc(tc_id, tc_rows)
            accepted_tcs[tc_id] = steps
            logger.info("[INFO] %s normalised (confidence OK)", tc_id)
        except GenerationError as e:
            rejected_tcs.append(tc_id)
            logger.error("[FAIL] %s REJECTED: %s", tc_id, e)

    normaliser.close()

    # ── 8. Normalisation summary ────────────────────────────────────────
    logger.info("───── Normalisation Summary ─────")
    logger.info("  Accepted: %d — %s", len(accepted_tcs), sorted(accepted_tcs.keys()))
    logger.info("  Rejected: %d — %s", len(rejected_tcs), sorted(rejected_tcs))
    if validation_rejected:
        logger.info("  Skipped (no POM): %d — %s", len(validation_rejected), sorted(validation_rejected))

    if not accepted_tcs:
        logger.error("No test cases passed normalisation. Aborting.")
        return 1

    # ── 9. Generate parameterized feature file (auto-overwrite) ─────────
    logger.info("[INFO] Generating feature file: %s", feature_name)
    content = generate_feature(feature_name, accepted_tcs)
    feature_path = write_feature_file(feature_name, content)
    logger.info("[INFO] Feature generated: %s", feature_path)

    # ── 10. Version folder (auto) ───────────────────────────────────────
    version_folder = create_version_folder(excel_path)
    save_artifact(
        version_folder,
        f"{feature_name.lower().replace(' ', '_')}.feature",
        content,
    )
    # Persist a baseline run summary right after generation.
    # NOTE: Do NOT update cumulative stats here — only at run completion.
    run_stats = _get_shared_stats()
    _write_json(
        "artifacts/latest_run.json",
        {
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "generate" if generate_only else "pipeline",
            "regenerated": True,
            "excel": excel_path,
            "feature": feature_path,
            "version_folder": version_folder,
            "stats": run_stats,
            "cumulative": _read_json("artifacts/cumulative_stats.json").get("cumulative", {}),
        },
    )
    save_artifact(
        version_folder,
        "run_summary.json",
        json.dumps(_read_json("artifacts/latest_run.json"), indent=2),
    )
    logger.info("[INFO] Version folder created: %s", version_folder)

    # Print generated feature for visibility
    print("\n" + "=" * 60)
    print("GENERATED FEATURE FILE:")
    print("=" * 60)
    print(content)
    print("=" * 60 + "\n")

    # ── 11. Auto-execute pytest (unless --generate-only) ────────────────
    if generate_only:
        logger.info("═══════════════════════════════════════════════════════")
        logger.info("  Generation Complete (--generate-only)")
        logger.info("  Excel:    %s", excel_path)
        logger.info("  Feature:  %s", feature_path)
        logger.info("  Version:  %s", version_folder)
        logger.info("  Tests:    skipped")
        logger.info("═══════════════════════════════════════════════════════")
        # Ensure the latest summary is persisted for UI consumption.
        run_stats = _get_shared_stats()
        _write_json(
            "artifacts/latest_run.json",
            {
                "completed_at": datetime.now().isoformat(timespec="seconds"),
                "mode": "generate-only",
                "regenerated": True,
                "excel": excel_path,
                "feature": feature_path,
                "version_folder": version_folder,
                "tests": {"skipped": True},
                "stats": run_stats,
                "cumulative": _update_cumulative_stats(run_stats).get("cumulative", {}),
            },
        )
        save_artifact(
            version_folder,
            "run_summary.json",
            json.dumps(_read_json("artifacts/latest_run.json"), indent=2),
        )
        return 0

    # Close Qdrant connections so the pytest subprocess can access the DB
    dom_store.close()
    logger.info("[INFO] DOM store released — Qdrant available for test subprocess")

    logger.info("[INFO] Executing tests…")
    result = run_tests()

    # Persist final summary after tests (pytest runs in a subprocess).
    run_stats = _get_shared_stats()
    _write_json(
        "artifacts/latest_run.json",
        {
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "pipeline",
            "regenerated": True,
            "excel": excel_path,
            "feature": feature_path,
            "version_folder": version_folder,
            "tests": {
                "exit_code": result.exit_code,
                "passed": result.passed,
                "failed": result.failed,
                "errors": result.errors,
                "total": result.total,
            },
            "stats": run_stats,
            "cumulative": _update_cumulative_stats(run_stats).get("cumulative", {}),
        },
    )
    save_artifact(
        version_folder,
        "run_summary.json",
        json.dumps(_read_json("artifacts/latest_run.json"), indent=2),
    )

    # ── 12. Final summary & exit ────────────────────────────────────────
    logger.info("═══════════════════════════════════════════════════════")
    logger.info("  Pipeline Complete")
    logger.info("  Excel:    %s", excel_path)
    logger.info("  Feature:  %s", feature_path)
    logger.info("  Version:  %s", version_folder)
    logger.info("  Tests:    %d passed, %d failed", result.passed, result.failed)
    logger.info("═══════════════════════════════════════════════════════")

    return result.exit_code


# ── Entrypoint ──────────────────────────────────────────────────────────

def main() -> None:
    """Single entrypoint — parses args and runs full pipeline."""
    import argparse

    parser = argparse.ArgumentParser(
        description="AI-Driven Automation Framework"
    )
    parser.add_argument(
        "--excel",
        default=None,
        help="Path to .xlsx (auto-detected from input/ if omitted)",
    )
    parser.add_argument(
        "--feature",
        default="Login",
        help="Feature name (default: Login)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regeneration even if Excel hash is unchanged",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Force DOM re-extraction even if knowledge base exists",
    )
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="Only generate the feature file — do NOT execute tests",
    )
    args = parser.parse_args()

    exit_code = run_pipeline(
        excel_path=args.excel,
        feature_name=args.feature,
        force=args.force,
        generate_only=args.generate_only,
        force_scan=args.scan,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
