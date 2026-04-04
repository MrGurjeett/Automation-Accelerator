from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


try:
    from neuro_san.interfaces.coded_tool import CodedTool  # type: ignore
except Exception:  # pragma: no cover - optional dependency in this repo
    class CodedTool:  # type: ignore
        def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> Any:
            raise NotImplementedError


def _ensure_project_root_on_path() -> Path:
    """Ensure the repo root is importable regardless of current working dir."""
    root = Path(__file__).resolve().parents[2]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from project_root import ensure_importable
    return ensure_importable()


def _iter_rows(step_data: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(step_data.get("rows"), list):
        return list(step_data["rows"])
    if isinstance(step_data.get("steps"), list):
        return list(step_data["steps"])
    # Support passing a single Excel row dict.
    required = {"TC_ID", "Page", "Action", "Target", "Value", "Expected"}
    if required.issubset(set(step_data.keys())):
        return [step_data]
    raise ValueError(
        "extract_dom_tool expects step_data to contain 'rows' (Excel rows list) or 'steps', "
        "or be a single row dict with the strict columns."
    )


def extract_dom_tool(step_data: dict[str, Any], trace_id: str | None = None) -> dict[str, Any]:
    """Neuro-SAN coded tool: enrich steps with DOM/RAG locator info.

    Now delegates to :class:`pipeline.service.PipelineService` for both DOM
    initialisation and per-row enrichment, eliminating the duplicated AI-stack
    setup that previously lived here.

    Input
    -----
    step_data: dict
        Typically the output of read_excel_tool: {"rows": [...]}
    trace_id: str, optional
        Caller-supplied trace ID for correlation.

    Output
    ------
    dict
        {"ok": bool, "steps": [...], "unresolved": [...], "trace_id": ..., ...}

    Notes
    -----
    - Requires Azure OpenAI env vars configured (same as existing pipeline).
    - If the DOM KB is not populated yet, the PipelineService will populate it
      (unless NEURO_DOM_SKIP_SCAN=1).
    """
    _ensure_project_root_on_path()

    rows = _iter_rows(step_data)

    from pipeline.service import PipelineService, StepName

    with PipelineService(trace_id=trace_id) as svc:
        # Initialise DOM KB via the shared service.
        # PipelineService._step_init_dom already checks is_populated() and
        # skips scanning when the KB is cached — no need for a separate
        # NEURO_DOM_SKIP_SCAN check here (was duplicating service logic).
        init_sr = svc.execute_step(StepName.INIT_DOM, {"force_scan": False})
        if not init_sr.ok:
            return {
                "ok": False,
                "error": init_sr.error or "DOM init failed",
                "steps": [],
                "unresolved": [],
                "trace_id": svc.trace_id,
            }

        # Enrich rows via the shared service
        dom_sr = svc.execute_step(StepName.EXTRACT_DOM, {"rows": rows})
        result = dom_sr.data
        result["ok"] = dom_sr.ok
        result["trace_id"] = svc.trace_id
        if not dom_sr.ok:
            result["error"] = dom_sr.error
        return result


class ExtractDomTool(CodedTool):
    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any]:
        step_data = args.get("step_data")
        if not isinstance(step_data, dict):
            raise ValueError("Missing required argument: step_data (object)")
        trace_id = (sly_data or {}).get("trace_id")
        return extract_dom_tool(step_data, trace_id=trace_id)
