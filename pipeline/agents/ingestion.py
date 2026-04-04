"""Ingestion agents — Excel detection, reading, and raw-step conversion.

These agents handle the data-ingestion stages of the pipeline.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pipeline.agents.base import BaseAgent, AgentResult

logger = logging.getLogger(__name__)


class ExcelDetectionAgent(BaseAgent):
    """Detect Excel files in the input/ directory."""

    name = "excel_detection"
    description = "Auto-detect Excel test-case files in the input folder"

    def run(self, context: dict[str, Any]) -> AgentResult:
        from pipeline.utils import detect_excel

        excel_path = context.get("excel_path")
        raw_path: str | None = None

        if excel_path is None:
            try:
                excel_path, raw_path = detect_excel()
            except (FileNotFoundError, ValueError) as exc:
                return AgentResult(ok=False, error=str(exc))

        return AgentResult(
            ok=True,
            data={"excel_path": excel_path, "raw_path": raw_path},
        )


class ExcelReaderAgent(BaseAgent):
    """Read and parse Excel test-case files."""

    name = "excel_reader"
    description = "Parse Excel file into structured test-case rows"

    def run(self, context: dict[str, Any]) -> AgentResult:
        from excel.excel_reader import read_excel

        excel_path = context.get("excel_path")
        if not excel_path:
            return AgentResult(ok=False, error="excel_path required")

        path = Path(excel_path).expanduser().resolve()
        rows = read_excel(path)
        return AgentResult(
            ok=True,
            data={"excel_path": str(path), "rows": rows, "row_count": len(rows)},
            metrics={"row_count": len(rows)},
        )


class RawStepConversionAgent(BaseAgent):
    """Convert raw free-text steps into structured template format."""

    name = "raw_step_converter"
    description = "AI-powered conversion of raw test steps to structured Excel format"

    def run(self, context: dict[str, Any]) -> AgentResult:
        raw_path = context.get("raw_path")
        excel_path = context.get("excel_path")
        if not raw_path:
            return AgentResult(ok=True, data={"skipped": True})

        import pandas as pd
        from ai.raw_step_converter import RawStepConverter

        # Requires AI stack from context
        config = context.get("_config")
        dom_store = context.get("_dom_store")
        if not config or not dom_store:
            return AgentResult(ok=False, error="AI stack (config, dom_store) required for raw conversion")

        converter = RawStepConverter(config, dom_store=dom_store)
        converter.convert_file(raw_path, excel_path)

        raw_count = len(pd.read_excel(raw_path, dtype=str))
        return AgentResult(
            ok=True,
            data={"raw_path": raw_path, "excel_path": excel_path, "rows_converted": raw_count},
            metrics={"raw_steps_converted": raw_count},
        )
