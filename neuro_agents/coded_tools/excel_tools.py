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


def read_excel_tool(file_path: str, trace_id: str | None = None) -> dict[str, Any]:
    """Neuro-SAN coded tool: read Excel test steps.

    Wraps: excel.excel_reader.read_excel

    Parameters
    ----------
    file_path:
        Path to the .xlsx file.
    trace_id:
        Optional caller-supplied trace ID for correlation.

    Returns
    -------
    dict
        {"excel_path": str, "rows": list[dict], "row_count": int, "trace_id": str}
    """
    _ensure_project_root_on_path()

    from excel.excel_reader import read_excel  # local import: keep tool import light
    from pipeline.trace import resolve_trace_id

    tid = resolve_trace_id(trace_id)

    path = Path(file_path).expanduser().resolve()
    logger.info("[neuro] Reading Excel: %s", path)

    rows = read_excel(path)
    return {
        "excel_path": str(path),
        "rows": rows,
        "row_count": len(rows),
        "trace_id": tid,
    }


class ReadExcelTool(CodedTool):
    def invoke(self, args: dict[str, Any], sly_data: dict[str, Any]) -> dict[str, Any]:
        file_path = args.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("Missing required argument: file_path")
        trace_id = (sly_data or {}).get("trace_id")
        return read_excel_tool(file_path, trace_id=trace_id)
