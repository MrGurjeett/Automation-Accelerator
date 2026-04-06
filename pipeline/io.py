"""Input/Output abstraction for the pipeline.

Standardizes how the pipeline reads input data and exports results,
supporting multiple formats (Excel, CSV, JSON) for both input and output.
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input Adapter
# ---------------------------------------------------------------------------

class PipelineInputAdapter:
    """Unified input loading — auto-detects format from file extension."""

    SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".json"}

    @staticmethod
    def detect_and_load(path: str | Path) -> list[dict[str, Any]]:
        """Auto-detect format and load rows from file.

        Returns a list of dicts (one per row/record).
        """
        p = Path(path).expanduser().resolve()
        ext = p.suffix.lower()

        if ext in (".xlsx", ".xls"):
            return PipelineInputAdapter.from_excel(p)
        elif ext == ".csv":
            return PipelineInputAdapter.from_csv(p)
        elif ext == ".json":
            return PipelineInputAdapter.from_json(p)
        else:
            raise ValueError(
                f"Unsupported input format: {ext}. "
                f"Supported: {sorted(PipelineInputAdapter.SUPPORTED_EXTENSIONS)}"
            )

    @staticmethod
    def from_excel(path: str | Path) -> list[dict[str, Any]]:
        """Load rows from an Excel file."""
        from excel.excel_reader import read_excel
        return read_excel(Path(path).expanduser().resolve())

    @staticmethod
    def from_csv(path: str | Path) -> list[dict[str, Any]]:
        """Load rows from a CSV file."""
        p = Path(path).expanduser().resolve()
        with p.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        logger.info("Loaded %d rows from CSV: %s", len(rows), p.name)
        return rows

    @staticmethod
    def from_json(path: str | Path) -> list[dict[str, Any]]:
        """Load rows from a JSON file.

        Supports:
          - Flat list of row dicts: [{"TC_ID":..., "Page":..., "Action":...}, ...]
          - Object wrappers: {"rows":[...]}, {"test_cases":[...]}, {"testCases":[...]},
            {"data":[...]}, {"items":[...]}
          - ADO nested format: [{"testCaseId":"TC01", "steps":[{"step":1, "action":"click", ...}]}]
            → flattened into one row per step with TC_ID, Page, Action, Locator, Value columns.
        """
        p = Path(path).expanduser().resolve()
        data = json.loads(p.read_text(encoding="utf-8"))

        # Unwrap common wrapper keys
        if isinstance(data, dict):
            for key in ("rows", "test_cases", "testCases", "data", "items"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                # Single test case dict with expected keys
                if any(k in data for k in ("TC_ID", "testCaseId", "Page")):
                    data = [data]
                else:
                    raise ValueError(
                        "JSON input must be an array of objects or a recognized wrapper object"
                    )

        if not isinstance(data, list) or not data:
            raise ValueError("JSON input resolved to an empty or non-array structure")

        # Check if this is ADO nested format (test cases with embedded steps arrays)
        # ADO format: [{"testCaseId": "TC01", "name": "...", "steps": [{"action":..., "target":...}]}]
        first = data[0] if data else {}
        if isinstance(first, dict) and "steps" in first and isinstance(first.get("steps"), list):
            rows = _flatten_nested_test_cases(data)
            logger.info("Loaded %d rows (flattened from nested test cases) from JSON: %s", len(rows), p.name)
        else:
            rows = data
            logger.info("Loaded %d rows from JSON: %s", len(rows), p.name)

        return rows

    @staticmethod
    def supported_extensions() -> list[str]:
        return sorted(PipelineInputAdapter.SUPPORTED_EXTENSIONS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flatten_nested_test_cases(test_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten ADO-style nested test cases into flat rows.

    ADO format (input):
        [{"testCaseId": "TC01", "name": "Login Test",
          "steps": [{"step": 1, "action": "navigate", "target": "Login Page"}, ...]}]

    Pipeline format (output — matches Excel column names):
        [{"TC_ID": "TC01", "Page": "Login", "Action": "navigate",
          "Target": "Login Page", "Value": "", "Expected": "-"}, ...]
    """
    # Page mapping: derive the Page name from the test case name or first navigation target
    rows: list[dict[str, Any]] = []
    for tc in test_cases:
        tc_id = tc.get("testCaseId") or tc.get("TC_ID") or tc.get("id", "")
        tc_name = tc.get("name", "")
        steps = tc.get("steps", [])

        if not steps:
            rows.append({"TC_ID": tc_id, "Page": "-", "Action": "-",
                         "Target": "-", "Value": "", "Expected": "-"})
            continue

        # Determine current page from navigation actions
        current_page = "-"
        for s in steps:
            action = s.get("action") or s.get("Action") or "-"
            target = s.get("target") or s.get("Target") or "-"
            value = s.get("value") or s.get("Value") or ""
            expected = s.get("expected") or s.get("Expected") or "-"

            # Navigation actions set the current page context
            if action.lower() in ("navigate", "goto", "open"):
                current_page = target

            rows.append({
                "TC_ID": tc_id,
                "Page": current_page,
                "Action": action,
                "Target": target,
                "Value": value,
                "Expected": expected,
            })

    logger.info("Flattened %d test cases into %d rows", len(test_cases), len(rows))
    return rows


# ---------------------------------------------------------------------------
# Output Exporter
# ---------------------------------------------------------------------------

class PipelineOutputExporter:
    """Export pipeline results in multiple formats."""

    @staticmethod
    def to_json(result: Any, path: str | Path) -> Path:
        """Export a PipelineResult to a JSON file.

        Parameters
        ----------
        result : PipelineResult
            The pipeline result to export.
        path : str | Path
            Output file path.

        Returns
        -------
        Path
            The written file path.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        if hasattr(result, "__dataclass_fields__"):
            payload = asdict(result)
        elif hasattr(result, "to_dict"):
            payload = result.to_dict()
        else:
            payload = dict(result) if isinstance(result, dict) else {"result": str(result)}

        # Clean non-serializable values
        def _clean(obj):
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_clean(v) for v in obj]
            if isinstance(obj, Path):
                return str(obj)
            return obj

        payload = _clean(payload)
        p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.info("Exported JSON result to %s", p)
        return p

    @staticmethod
    def to_summary(result: Any) -> dict[str, Any]:
        """Generate a condensed summary dict from a PipelineResult."""
        if hasattr(result, "__dataclass_fields__"):
            data = asdict(result)
        elif isinstance(result, dict):
            data = result
        else:
            return {"result": str(result)}

        steps = data.get("steps", [])
        return {
            "exit_code": data.get("exit_code", -1),
            "trace_id": data.get("trace_id", ""),
            "run_id": data.get("run_id", ""),
            "duration_ms": data.get("duration_ms", 0),
            "total_steps": len(steps),
            "passed_steps": sum(1 for s in steps if s.get("ok")),
            "failed_steps": sum(1 for s in steps if not s.get("ok")),
            "step_durations": {
                s.get("step", f"step_{i}"): s.get("duration_ms", 0)
                for i, s in enumerate(steps)
            },
        }

    @staticmethod
    def to_csv(steps: list[dict[str, Any]], path: str | Path) -> Path:
        """Export step results to a CSV file.

        Parameters
        ----------
        steps : list[dict]
            List of step result dicts (step, ok, error, duration_ms).
        path : str | Path
            Output file path.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = ["step", "ok", "error", "duration_ms"]
        with p.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for step in steps:
                writer.writerow({
                    "step": step.get("step", ""),
                    "ok": step.get("ok", False),
                    "error": step.get("error", ""),
                    "duration_ms": step.get("duration_ms", 0),
                })

        logger.info("Exported CSV results to %s (%d steps)", p, len(steps))
        return p
