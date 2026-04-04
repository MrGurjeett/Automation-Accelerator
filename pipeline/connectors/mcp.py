"""
MCPConnector — Model Context Protocol connector wrapper.

Phase 4A GROUP 3 — wraps MCP tool calls through the BaseConnector
interface, adding timeout handling, basic retry (up to 2 retries),
and structured failure logging.

The connector acts as a **wrapper layer** — it does not implement the
MCP protocol itself but delegates to an MCP client (callable) provided
at construction time.  This keeps the connector focused on reliability
and interface standardisation.

Supported fetch types:
  - ``tool_call``  — invoke an MCP tool and return its result
  - ``list_tools`` — list available MCP tools

Supported push types:
  - ``tool_call``  — alias for fetch (MCP tools are bidirectional)

Example::

    from pipeline.connectors.mcp import MCPConnector

    async def my_mcp_client(tool_name, arguments, timeout):
        # Your MCP SDK call here
        ...

    mcp = MCPConnector(
        server_name="my-server",
        call_tool_fn=my_mcp_client,
        timeout=30,
        max_retries=2,
    )
    mcp.connect()

    result = mcp.fetch({
        "type": "tool_call",
        "tool": "read_file",
        "arguments": {"path": "/some/file.txt"},
    })
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable

from pipeline.connectors.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)

# Defaults
_DEFAULT_TIMEOUT = 30  # seconds
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_RETRY_DELAY = 1.0  # seconds between retries
_DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 5  # consecutive failures to trip circuit
_DEFAULT_CIRCUIT_BREAKER_RESET = 60.0  # seconds before attempting recovery


class MCPConnector(BaseConnector):
    """Model Context Protocol connector wrapper with reliability features.

    Wraps an MCP tool-calling function with:
      - Configurable timeout (default 30s)
      - Retry logic with exponential backoff (default 2 retries)
      - Circuit breaker (trips after consecutive failures, auto-resets)
      - Structured failure logging and error reporting
      - Graceful degradation (never raises — always returns ConnectorResult)
      - Uniform BaseConnector interface

    Parameters
    ----------
    server_name : str
        Identifier for the MCP server (for logging and registry).
    call_tool_fn : callable or None
        The async or sync function that performs the actual MCP tool call.
        Signature: ``(tool_name: str, arguments: dict, timeout: float) -> dict``
        If None, uses environment-based configuration or must be set later.
    list_tools_fn : callable or None
        Optional function to list available MCP tools.
        Signature: ``() -> list[dict]``
    timeout : float
        Per-call timeout in seconds.
    max_retries : int
        Maximum number of retry attempts on failure (0 = no retries).
    retry_delay : float
        Base delay in seconds between retry attempts (doubles each retry).
    circuit_breaker_threshold : int
        Number of consecutive failures before the circuit breaker trips.
        Set to 0 to disable the circuit breaker.
    circuit_breaker_reset : float
        Seconds to wait before attempting recovery after circuit trips.
    """

    name = "mcp"
    description = "Model Context Protocol connector wrapper"

    def __init__(
        self,
        server_name: str = "",
        call_tool_fn: Callable[..., Any] | None = None,
        list_tools_fn: Callable[..., Any] | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_delay: float | None = None,
        circuit_breaker_threshold: int | None = None,
        circuit_breaker_reset: float | None = None,
    ) -> None:
        self._server_name = server_name or os.environ.get("MCP_SERVER_NAME", "default")
        self._call_tool_fn = call_tool_fn
        self._list_tools_fn = list_tools_fn
        self._timeout = timeout or float(os.environ.get("MCP_TIMEOUT", _DEFAULT_TIMEOUT))
        self._max_retries = max_retries if max_retries is not None else int(
            os.environ.get("MCP_MAX_RETRIES", _DEFAULT_MAX_RETRIES)
        )
        self._retry_delay = retry_delay if retry_delay is not None else float(
            os.environ.get("MCP_RETRY_DELAY", _DEFAULT_RETRY_DELAY)
        )
        self._connected = False

        # Statistics
        self._call_count = 0
        self._failure_count = 0
        self._retry_count = 0

        # Circuit breaker state
        self._cb_threshold = (
            circuit_breaker_threshold
            if circuit_breaker_threshold is not None
            else int(os.environ.get("MCP_CB_THRESHOLD", _DEFAULT_CIRCUIT_BREAKER_THRESHOLD))
        )
        self._cb_reset_seconds = (
            circuit_breaker_reset
            if circuit_breaker_reset is not None
            else float(os.environ.get("MCP_CB_RESET", _DEFAULT_CIRCUIT_BREAKER_RESET))
        )
        self._cb_consecutive_failures = 0
        self._cb_tripped_at: float | None = None  # monotonic timestamp

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def stats(self) -> dict[str, Any]:
        """Return call/failure/retry/circuit-breaker statistics."""
        return {
            "calls": self._call_count,
            "failures": self._failure_count,
            "retries": self._retry_count,
            "circuit_breaker": {
                "state": self._cb_state,
                "consecutive_failures": self._cb_consecutive_failures,
                "threshold": self._cb_threshold,
            },
        }

    @property
    def _cb_state(self) -> str:
        """Current circuit breaker state: 'closed', 'open', or 'half_open'."""
        if self._cb_threshold <= 0:
            return "disabled"
        if self._cb_tripped_at is None:
            return "closed"
        elapsed = time.monotonic() - self._cb_tripped_at
        if elapsed >= self._cb_reset_seconds:
            return "half_open"  # recovery window
        return "open"

    def _cb_record_success(self) -> None:
        """Record a successful call — reset circuit breaker."""
        self._cb_consecutive_failures = 0
        if self._cb_tripped_at is not None:
            logger.info("[MCP] Circuit breaker reset (recovered) for '%s'", self._server_name)
            self._cb_tripped_at = None

    def _cb_record_failure(self) -> None:
        """Record a failed call — potentially trip circuit breaker."""
        if self._cb_threshold <= 0:
            return
        self._cb_consecutive_failures += 1
        if self._cb_consecutive_failures >= self._cb_threshold and self._cb_tripped_at is None:
            self._cb_tripped_at = time.monotonic()
            logger.error(
                "[MCP] Circuit breaker TRIPPED for '%s' after %d consecutive failures. "
                "Will retry after %.0fs.",
                self._server_name, self._cb_consecutive_failures, self._cb_reset_seconds,
            )

    def _cb_should_block(self) -> bool:
        """Check if the circuit breaker should block the call."""
        state = self._cb_state
        if state == "open":
            return True
        return False

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def connect(self) -> ConnectorResult:
        """Validate MCP configuration and mark as connected."""
        if not self._call_tool_fn:
            return ConnectorResult(
                ok=False,
                error="MCP call_tool_fn not configured. Provide a callable at construction.",
            )

        self._connected = True
        logger.info(
            "[MCP] Connected to server '%s' (timeout=%ss, retries=%d)",
            self._server_name, self._timeout, self._max_retries,
        )
        return ConnectorResult(
            ok=True,
            data={
                "server_name": self._server_name,
                "timeout": self._timeout,
                "max_retries": self._max_retries,
            },
        )

    def fetch(self, query: dict[str, Any]) -> ConnectorResult:
        """Fetch data via MCP tool call.

        Supported query types:
          - ``{"type": "tool_call", "tool": "<name>", "arguments": {...}}``
          - ``{"type": "list_tools"}``
        """
        if not self._connected:
            return ConnectorResult(ok=False, error="Not connected. Call connect() first.")

        fetch_type = query.get("type", "")

        if fetch_type == "tool_call":
            return self._execute_tool_call(
                tool_name=query.get("tool", ""),
                arguments=query.get("arguments", {}),
                timeout_override=query.get("timeout"),
            )
        elif fetch_type == "list_tools":
            return self._list_tools()
        else:
            return ConnectorResult(
                ok=False,
                error=f"Unknown MCP fetch type: {fetch_type!r}. Supported: tool_call, list_tools",
            )

    def push(self, data: dict[str, Any]) -> ConnectorResult:
        """Push data via MCP tool call (alias for fetch/tool_call).

        Supported push types:
          - ``{"type": "tool_call", "tool": "<name>", "arguments": {...}}``
        """
        if not self._connected:
            return ConnectorResult(ok=False, error="Not connected. Call connect() first.")

        push_type = data.get("type", "")

        if push_type == "tool_call":
            return self._execute_tool_call(
                tool_name=data.get("tool", ""),
                arguments=data.get("arguments", {}),
                timeout_override=data.get("timeout"),
            )
        else:
            return ConnectorResult(
                ok=False,
                error=f"Unknown MCP push type: {push_type!r}. Supported: tool_call",
            )

    def health_check(self) -> ConnectorResult:
        """Check MCP server availability by listing tools."""
        if not self._connected:
            return ConnectorResult(ok=False, error="Not connected")

        if self._list_tools_fn:
            result = self._list_tools()
            if result.ok:
                return ConnectorResult(ok=True, data={"status": "healthy", **result.data})
            return result

        # If no list_tools_fn, just verify the callable is present
        if self._call_tool_fn:
            return ConnectorResult(ok=True, data={"status": "healthy", "note": "callable present"})

        return ConnectorResult(ok=False, error="No MCP callable configured")

    # ------------------------------------------------------------------
    # Core execution with retry + timeout
    # ------------------------------------------------------------------

    def _execute_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_override: float | None = None,
    ) -> ConnectorResult:
        """Execute an MCP tool call with retry and timeout handling.

        Parameters
        ----------
        tool_name : str
            The MCP tool to invoke.
        arguments : dict
            Tool arguments.
        timeout_override : float or None
            Override the default timeout for this call.

        Returns
        -------
        ConnectorResult
            The tool result or a structured error.
        """
        if not tool_name:
            return ConnectorResult(ok=False, error="MCP tool_call requires 'tool' name")

        # Circuit breaker check — fail fast if circuit is open
        if self._cb_should_block():
            elapsed_since_trip = time.monotonic() - (self._cb_tripped_at or 0)
            remaining = max(0, self._cb_reset_seconds - elapsed_since_trip)
            logger.warning(
                "[MCP] Circuit breaker OPEN for '%s' — blocking call to '%s' (reset in %.0fs)",
                self._server_name, tool_name, remaining,
            )
            return ConnectorResult(
                ok=False,
                error=(
                    f"Circuit breaker open for server '{self._server_name}'. "
                    f"Too many consecutive failures ({self._cb_consecutive_failures}). "
                    f"Will retry after {remaining:.0f}s."
                ),
                metadata={
                    "tool": tool_name,
                    "circuit_breaker": "open",
                    "server": self._server_name,
                },
            )

        timeout = timeout_override or self._timeout
        self._call_count += 1
        last_error: str = ""
        attempts_made = 0

        for attempt in range(1 + self._max_retries):
            attempts_made = attempt + 1

            if attempt > 0:
                self._retry_count += 1
                # Exponential backoff: delay * 2^(attempt-1)
                backoff_delay = self._retry_delay * (2 ** (attempt - 1))
                logger.warning(
                    "[MCP] Retry %d/%d for tool '%s' on server '%s' (backoff %.1fs)",
                    attempt, self._max_retries, tool_name, self._server_name, backoff_delay,
                )
                time.sleep(backoff_delay)

            try:
                start = time.monotonic()
                raw_result = self._invoke_callable(
                    self._call_tool_fn, tool_name, arguments, timeout
                )
                elapsed = time.monotonic() - start

                logger.info(
                    "[MCP] Tool '%s' succeeded in %.2fs (attempt %d)",
                    tool_name, elapsed, attempts_made,
                )

                # Success — reset circuit breaker
                self._cb_record_success()

                return ConnectorResult(
                    ok=True,
                    data={
                        "tool": tool_name,
                        "result": raw_result,
                    },
                    metadata={
                        "elapsed_seconds": round(elapsed, 3),
                        "attempt": attempts_made,
                        "server": self._server_name,
                    },
                )

            except TimeoutError as exc:
                last_error = f"Timeout after {timeout}s calling tool '{tool_name}': {exc}"
                logger.warning("[MCP] %s (attempt %d/%d)", last_error, attempts_made, 1 + self._max_retries)

            except ConnectionError as exc:
                last_error = f"Connection error calling tool '{tool_name}': {exc}"
                logger.warning("[MCP] %s (attempt %d/%d)", last_error, attempts_made, 1 + self._max_retries)

            except Exception as exc:
                last_error = f"Error calling tool '{tool_name}': {type(exc).__name__}: {exc}"
                logger.error("[MCP] %s (attempt %d/%d)", last_error, attempts_made, 1 + self._max_retries)
                # Non-retryable errors break immediately
                if not self._is_retryable(exc):
                    break

        # All attempts exhausted — record failure for circuit breaker
        self._failure_count += 1
        self._cb_record_failure()

        logger.error(
            "[MCP] Tool '%s' failed after %d attempt(s) on server '%s': %s",
            tool_name, attempts_made, self._server_name, last_error,
        )

        return ConnectorResult(
            ok=False,
            error=last_error,
            metadata={
                "tool": tool_name,
                "attempts": attempts_made,
                "server": self._server_name,
                "circuit_breaker": self._cb_state,
                "consecutive_failures": self._cb_consecutive_failures,
            },
        )

    def _invoke_callable(
        self,
        fn: Callable[..., Any],
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float,
    ) -> Any:
        """Invoke the MCP callable, handling both sync and async functions.

        Wraps async callables with asyncio timeout.  Sync callables are
        called directly (timeout enforced by the callable itself or by
        threading if needed in future).

        Raises TimeoutError if the call exceeds the timeout.
        """
        if asyncio.iscoroutinefunction(fn):
            return self._invoke_async(fn, tool_name, arguments, timeout)
        else:
            # Sync callable — call directly with timeout param
            return fn(tool_name, arguments, timeout=timeout)

    def _invoke_async(
        self,
        fn: Callable[..., Any],
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float,
    ) -> Any:
        """Invoke an async MCP callable with asyncio.wait_for timeout."""
        async def _run() -> Any:
            return await asyncio.wait_for(
                fn(tool_name, arguments, timeout=timeout),
                timeout=timeout,
            )

        # Get or create an event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an existing event loop — create a task
            # This handles the FastAPI / async pipeline case
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _run())
                try:
                    return future.result(timeout=timeout + 5)
                except concurrent.futures.TimeoutError:
                    raise TimeoutError(f"MCP tool '{tool_name}' timed out after {timeout}s")
        else:
            # No running loop — safe to use asyncio.run
            try:
                return asyncio.run(_run())
            except asyncio.TimeoutError:
                raise TimeoutError(f"MCP tool '{tool_name}' timed out after {timeout}s")

    # ------------------------------------------------------------------
    # List tools
    # ------------------------------------------------------------------

    def _list_tools(self) -> ConnectorResult:
        """List available MCP tools."""
        if not self._list_tools_fn:
            return ConnectorResult(
                ok=False,
                error="list_tools not supported — no list_tools_fn configured",
            )

        try:
            result = self._list_tools_fn()
            # Handle async list_tools_fn
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        result = pool.submit(asyncio.run, result).result(timeout=self._timeout)
                else:
                    result = asyncio.run(result)

            tools = result if isinstance(result, list) else []
            return ConnectorResult(
                ok=True,
                data={"tools": tools, "count": len(tools)},
            )
        except Exception as exc:
            logger.error("[MCP] list_tools failed: %s", exc)
            return ConnectorResult(ok=False, error=f"list_tools failed: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Determine if an exception is worth retrying."""
        retryable_types = (
            TimeoutError,
            ConnectionError,
            OSError,
            asyncio.TimeoutError,
        )
        return isinstance(exc, retryable_types)

    def set_call_tool_fn(self, fn: Callable[..., Any]) -> None:
        """Set or replace the MCP tool-calling function."""
        self._call_tool_fn = fn

    def set_list_tools_fn(self, fn: Callable[..., Any]) -> None:
        """Set or replace the MCP tool-listing function."""
        self._list_tools_fn = fn

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker."""
        self._cb_consecutive_failures = 0
        self._cb_tripped_at = None
        logger.info("[MCP] Circuit breaker manually reset for '%s'", self._server_name)

    def __repr__(self) -> str:
        return (
            f"<MCPConnector(server={self._server_name!r}, "
            f"timeout={self._timeout}s, retries={self._max_retries}, "
            f"cb={self._cb_state}, connected={self._connected})>"
        )
