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

NOTE: As of the PipelineService refactor, all core pipeline logic lives in
``pipeline.service.PipelineService``.  The ``run_pipeline()`` function below
is a thin backward-compatible wrapper that delegates to the service.
"""
from __future__ import annotations

import logging
import sys

from pipeline.service import PipelineService, PipelineInput
from pipeline.trace import install_trace_logging

# ── Logging ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s [%(trace_id)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
install_trace_logging()
logger = logging.getLogger("compiler")


# ── Auto-detect Excel (now in pipeline.utils) ──────────────────────────
from pipeline.utils import detect_excel


# ── Pipeline ────────────────────────────────────────────────────────────

def run_pipeline(
    excel_path: str | None = None,
    feature_name: str = "Login",
    *,
    force: bool = False,
    generate_only: bool = False,
    force_scan: bool = False,
    config_name: str | None = None,
) -> int:
    """Execute the full compiler pipeline.  Returns pytest exit code.

    This is now a thin wrapper around :class:`pipeline.service.PipelineService`.
    All core logic lives there — this function preserves the original call
    signature for backward compatibility.

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
    config_name : str, optional
        Named pipeline config or path to config file.

    Returns
    -------
    int
        0 if all tests passed (or generation-only succeeded), non-zero otherwise.
    """
    with PipelineService() as svc:
        result = svc.run_pipeline(PipelineInput(
            excel_path=excel_path,
            feature_name=feature_name,
            force=force,
            generate_only=generate_only,
            force_scan=force_scan,
            config_name=config_name,
        ))
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
    parser.add_argument(
        "--config",
        default=None,
        help="Named pipeline config (e.g. 'full-pipeline', 'generate-only') or path to JSON/YAML",
    )
    args = parser.parse_args()

    exit_code = run_pipeline(
        excel_path=args.excel,
        feature_name=args.feature,
        force=args.force,
        generate_only=args.generate_only,
        force_scan=args.scan,
        config_name=args.config,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
