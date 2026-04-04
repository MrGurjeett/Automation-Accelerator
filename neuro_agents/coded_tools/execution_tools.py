from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

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


def execute_steps_tool(steps: list, trace_id: str | None = None) -> dict[str, Any]:
    """Neuro-SAN coded tool: execute the automation run.

    Now delegates to :class:`pipeline.service.PipelineService` so that test
    execution follows the same code path as the CLI pipeline.

    Notes
    -----
    The provided ``steps`` are accepted for orchestration compatibility and
    basic observability, but execution is delegated to the shared service.
    """
    _ensure_project_root_on_path()

    from pipeline.service import PipelineService, StepName

    logger.info("[neuro] Executing automation (received %d step(s))", len(steps) if isinstance(steps, list) else 0)

    with PipelineService(trace_id=trace_id) as svc:
        sr = svc.execute_step(StepName.EXECUTE, {})
        payload = dict(sr.data)
        payload["success"] = sr.ok
        payload["trace_id"] = svc.trace_id
        return payload


class ExecuteStepsTool(CodedTool):
    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any]:
        steps = args.get("steps")
        if steps is None:
            steps = []
        if not isinstance(steps, list):
            raise ValueError("Argument 'steps' must be an array")
        trace_id = (sly_data or {}).get("trace_id")
        return execute_steps_tool(steps, trace_id=trace_id)
