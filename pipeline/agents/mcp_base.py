"""
MCPAgentBase — reusable base class for MCP-powered agents.

Phase 4.2 GROUP 1 — provides a standardized foundation for agents that
use MCP (Model Context Protocol) for AI-powered reasoning, generation,
validation, and recovery.

Design principles:
  - Extends BaseAgent + ConnectorAwareMixin
  - Gets MCP connector from registry (never imports MCP directly)
  - Standardizes MCP call pattern and response handling
  - Centralizes retry awareness (already in connector), error handling, logging
  - Never contains pipeline orchestration logic

Usage::

    class MyMCPAgent(MCPAgentBase):
        name = "my_mcp_agent"
        mcp_task = "generate"

        def _build_mcp_arguments(self, context):
            return {"input": context.get("data")}

        def _process_mcp_result(self, mcp_data, context):
            return {"output": mcp_data.get("result")}
"""
from __future__ import annotations

import logging
import time
from typing import Any

from pipeline.agents.base import BaseAgent, AgentResult, ConnectorAwareMixin

logger = logging.getLogger(__name__)


class MCPAgentBase(ConnectorAwareMixin, BaseAgent):
    """Abstract base class for MCP-powered pipeline agents.

    Subclasses should override:
      - ``mcp_task``: the task name sent to MCP (e.g. "generate", "validate")
      - ``mcp_tool``: the MCP tool name (default: "pipeline_agent")
      - ``_build_mcp_arguments(context)``: construct MCP call arguments
      - ``_process_mcp_result(mcp_data, context)``: transform MCP output to agent data

    The base class handles:
      - MCP connector lookup from registry
      - Standardized call format: ``mcp.fetch({"type": "tool_call", "tool": ..., "arguments": ...})``
      - Response normalization to ``{ok, data, error}``
      - Error handling and logging
      - Metrics collection (call duration, success/failure)
    """

    # Subclasses should set these.
    mcp_task: str = ""
    mcp_tool: str = "pipeline_agent"

    def run(self, context: dict[str, Any]) -> AgentResult:
        """Execute the MCP-powered agent logic.

        Flow:
          1. Get MCP connector from registry
          2. Build MCP arguments via ``_build_mcp_arguments``
          3. Call MCP via connector
          4. Process response via ``_process_mcp_result``
          5. Return structured AgentResult

        If MCP is unavailable, delegates to ``_fallback(context)`` which
        subclasses can override for graceful degradation.
        """
        # Step 1: Get MCP connector
        mcp = self.get_connector("mcp", context)

        if not mcp or not mcp.is_connected:
            logger.warning(
                "[%s] MCP connector not available — using fallback",
                self.name,
            )
            return self._fallback(context)

        # Step 2: Build arguments
        try:
            arguments = self._build_mcp_arguments(context)
        except Exception as exc:
            logger.error("[%s] Failed to build MCP arguments: %s", self.name, exc)
            return AgentResult(
                ok=False,
                error=f"Failed to build MCP arguments: {exc}",
            )

        # Step 3: Call MCP
        t0 = time.monotonic()
        mcp_result = self._call_mcp(mcp, arguments, context)
        elapsed_ms = (time.monotonic() - t0) * 1000

        if not mcp_result.ok:
            logger.warning(
                "[%s] MCP call failed (%.0fms): %s — trying fallback",
                self.name, elapsed_ms, mcp_result.error,
            )
            fallback_result = self._fallback(context)
            fallback_result.warnings.append(f"MCP failed: {mcp_result.error}; used fallback")
            fallback_result.metrics["mcp_failed"] = True
            fallback_result.metrics["mcp_error"] = mcp_result.error
            return fallback_result

        # Step 4: Process MCP response
        try:
            mcp_data = mcp_result.data.get("result", {})
            processed = self._process_mcp_result(mcp_data, context)

            logger.info(
                "[%s] MCP task '%s' completed in %.0fms",
                self.name, self.mcp_task, elapsed_ms,
            )

            return AgentResult(
                ok=True,
                data=processed,
                metrics={
                    "mcp_used": True,
                    "mcp_task": self.mcp_task,
                    "mcp_duration_ms": round(elapsed_ms, 1),
                },
            )

        except Exception as exc:
            logger.error(
                "[%s] Failed to process MCP result: %s", self.name, exc
            )
            return AgentResult(
                ok=False,
                error=f"Failed to process MCP result: {exc}",
                metrics={"mcp_used": True, "mcp_duration_ms": round(elapsed_ms, 1)},
            )

    def _call_mcp(self, mcp: Any, arguments: dict, context: dict) -> Any:
        """Execute the MCP tool call via the connector.

        The standard call format wraps the task and arguments into
        the connector's ``fetch`` interface.

        Parameters
        ----------
        mcp : MCPConnector
            The MCP connector instance.
        arguments : dict
            Arguments built by ``_build_mcp_arguments``.
        context : dict
            The full execution context (for timeout overrides, etc.).

        Returns
        -------
        ConnectorResult
            The connector's response.
        """
        timeout = context.get("mcp_timeout")
        fetch_query: dict[str, Any] = {
            "type": "tool_call",
            "tool": self.mcp_tool,
            "arguments": {
                "task": self.mcp_task,
                **arguments,
            },
        }
        if timeout is not None:
            fetch_query["timeout"] = timeout

        return mcp.fetch(fetch_query)

    # ------------------------------------------------------------------
    # Hooks for subclasses
    # ------------------------------------------------------------------

    def _build_mcp_arguments(self, context: dict[str, Any]) -> dict[str, Any]:
        """Build the arguments dict for the MCP tool call.

        Subclasses must override this to extract relevant data from
        the pipeline context and structure it for the MCP tool.

        Parameters
        ----------
        context : dict
            The pipeline execution context.

        Returns
        -------
        dict
            Arguments to pass to the MCP tool (merged with ``task``).
        """
        return {"input": context}

    def _process_mcp_result(
        self, mcp_data: Any, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Transform the raw MCP response into agent output data.

        Subclasses should override this to extract and validate the
        relevant fields from the MCP tool's response.

        Parameters
        ----------
        mcp_data : Any
            The raw result from the MCP tool call.
        context : dict
            The pipeline execution context.

        Returns
        -------
        dict
            Processed data to include in the AgentResult.
        """
        if isinstance(mcp_data, dict):
            return mcp_data
        return {"result": mcp_data}

    def _fallback(self, context: dict[str, Any]) -> AgentResult:
        """Fallback when MCP is unavailable or fails.

        Subclasses can override this to provide deterministic fallback
        logic.  The default returns a failure result.

        Parameters
        ----------
        context : dict
            The pipeline execution context.

        Returns
        -------
        AgentResult
            A fallback result (may be ok=True if local logic suffices).
        """
        return AgentResult(
            ok=False,
            error=f"MCP unavailable for task '{self.mcp_task}' and no fallback defined",
            metrics={"mcp_used": False, "fallback": True},
        )
