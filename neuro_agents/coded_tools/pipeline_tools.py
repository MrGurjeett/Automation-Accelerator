from __future__ import annotations

import logging
import sys
import os
import json
from pathlib import Path
from typing import Any

try:
    from neuro_san.interfaces.coded_tool import CodedTool  # type: ignore
except Exception:  # pragma: no cover - optional dependency in this repo
    class CodedTool:  # type: ignore
        def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> Any:  # noqa: D401
            raise NotImplementedError

logger = logging.getLogger(__name__)


_OUTPUT_FILE_ENV = "NEURO_PIPELINE_OUTPUT_FILE"


def _ensure_project_root_on_path() -> Path:
    """Ensure the repo root is importable regardless of current working dir."""
    # Bootstrap: project_root.py may not be importable yet if the root isn't
    # on sys.path, so we do a minimal bootstrap first, then delegate.
    root = Path(__file__).resolve().parents[2]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from project_root import ensure_importable
    return ensure_importable()


def run_pipeline_tool(excel_path: str, trace_id: str | None = None) -> dict[str, Any]:
    """Neuro-SAN coded tool: orchestrate Excel -> DOM enrichment -> Execution.

    Now delegates to the unified :class:`pipeline.service.PipelineService`
    instead of chaining individual coded tools directly.  This eliminates
    duplicated AI-stack initialisation and DOM extraction logic.

    Parameters
    ----------
    excel_path:
        Path to the Excel file.
    trace_id:
        Optional caller-supplied trace ID for correlation.

    Returns
    -------
    dict
        {"ok": ..., "excel": ..., "dom": ..., "execution": ..., "trace_id": ...}
    """
    _ensure_project_root_on_path()

    from pipeline.service import PipelineService, StepName

    logger.info("[neuro] Pipeline start (via PipelineService): %s", excel_path)

    with PipelineService(trace_id=trace_id) as svc:
        # ── 1. Read Excel (via shared service) ─────────────────────────
        excel_sr = svc.execute_step(StepName.READ_EXCEL, {"excel_path": excel_path})
        excel_out = excel_sr.data
        if not excel_sr.ok:
            return {
                "ok": False,
                "excel": excel_out,
                "dom": None,
                "execution": None,
                "trace_id": svc.trace_id,
            }

        # ── 2. Initialise DOM KB (via shared service) ──────────────────
        dom_init_sr = svc.execute_step(StepName.INIT_DOM, {"force_scan": False})
        if not dom_init_sr.ok:
            return {
                "ok": False,
                "excel": excel_out,
                "dom": {"ok": False, "error": dom_init_sr.error},
                "execution": None,
                "trace_id": svc.trace_id,
            }

        # ── 3. Enrich rows with DOM/RAG locators (via shared service) ──
        dom_sr = svc.execute_step(StepName.EXTRACT_DOM, {"rows": excel_out.get("rows", [])})
        dom_out = dom_sr.data
        dom_out["ok"] = dom_sr.ok

        if not dom_sr.ok:
            return {
                "ok": False,
                "excel": excel_out,
                "dom": dom_out,
                "execution": None,
                "trace_id": svc.trace_id,
            }

        # ── 4. Execute tests (via shared service) ─────────────────────
        svc.close()  # Release Qdrant before pytest subprocess
        exec_sr = svc.execute_step(StepName.EXECUTE, {})
        exec_out = exec_sr.data
        exec_out["success"] = exec_sr.ok

        payload = {
            "ok": exec_sr.ok,
            "excel": excel_out,
            "dom": dom_out,
            "execution": exec_out,
            "trace_id": svc.trace_id,
        }

    _maybe_write_output_file(payload)
    return payload


def _maybe_write_output_file(payload: dict[str, Any]) -> None:
    output_path = (os.getenv(_OUTPUT_FILE_ENV) or "").strip()
    if not output_path:
        return

    try:
        path = Path(output_path)
        if not path.is_absolute():
            # Resolve relative paths against repo root.
            from project_root import get_project_root
            repo_root = get_project_root()
            path = repo_root / path

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("[neuro] Wrote pipeline output to %s (via %s)", path, _OUTPUT_FILE_ENV)
    except Exception as exc:
        logger.warning("[neuro] Failed writing %s to '%s': %s", _OUTPUT_FILE_ENV, output_path, exc)


class RunPipelineTool(CodedTool):
    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any]:
        excel_path = args.get("excel_path")
        if not isinstance(excel_path, str) or not excel_path.strip():
            raise ValueError("Missing required argument: excel_path")

        trace_id = (sly_data or {}).get("trace_id")
        return run_pipeline_tool(excel_path, trace_id=trace_id)
