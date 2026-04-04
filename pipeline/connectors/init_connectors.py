"""
init_connectors — bootstrap connector registration at system startup.

Phase 4A GROUP 4 — registers ADO and MCP connectors into the global
ConnectorRegistry singleton based on environment variables.

Call ``initialize_connectors()`` once during application startup (before
any pipeline runs) to make connectors globally available via::

    from pipeline.connectors import get_connector
    ado = get_connector("ado")

Environment variables:
  ADO:
    - ``ADO_ORGANIZATION`` / ``ADO_ORG``  — Azure DevOps organization
    - ``ADO_PROJECT``                      — default project name
    - ``ADO_PAT``                          — personal access token
    - ``ADO_BASE_URL``                     — optional custom base URL

  MCP:
    - ``MCP_SERVER_NAME``  — server identifier (default: "default")
    - ``MCP_TIMEOUT``      — call timeout in seconds (default: 30)
    - ``MCP_MAX_RETRIES``  — max retry attempts (default: 2)
    - ``MCP_RETRY_DELAY``  — seconds between retries (default: 1.0)

Connectors are only registered when their required environment
variables are present.  Missing variables result in a debug log
message, not an error — this keeps development environments clean.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

from pipeline.connectors.registry import get_default_registry, ConnectorRegistry
from pipeline.connectors.base import ConnectorResult

logger = logging.getLogger(__name__)


def initialize_connectors(
    registry: ConnectorRegistry | None = None,
    *,
    mcp_call_tool_fn: Callable[..., Any] | None = None,
    mcp_list_tools_fn: Callable[..., Any] | None = None,
    auto_connect: bool = True,
) -> ConnectorRegistry:
    """Bootstrap all connectors into the registry.

    Parameters
    ----------
    registry : ConnectorRegistry or None
        Registry to populate.  Uses the global singleton if omitted.
    mcp_call_tool_fn : callable or None
        The async/sync function for MCP tool calls.  If None and
        MCP env vars are set, the MCP connector is registered but
        cannot connect until ``set_call_tool_fn()`` is called.
    mcp_list_tools_fn : callable or None
        Optional MCP tool-listing function.
    auto_connect : bool
        If True, automatically call ``connect()`` on each connector
        after registration (failures are logged, not raised).

    Returns
    -------
    ConnectorRegistry
        The populated registry.
    """
    reg = registry if registry is not None else get_default_registry()

    _register_ado(reg, auto_connect=auto_connect)
    _register_mcp(
        reg,
        call_tool_fn=mcp_call_tool_fn,
        list_tools_fn=mcp_list_tools_fn,
        auto_connect=auto_connect,
    )

    logger.info(
        "Connector initialization complete: %d connector(s) registered %s",
        len(reg), reg.names,
    )
    return reg


def _register_ado(
    registry: ConnectorRegistry,
    *,
    auto_connect: bool = True,
) -> None:
    """Register ADOConnector if credentials are available."""
    org = os.environ.get("ADO_ORGANIZATION") or os.environ.get("ADO_ORG", "")
    pat = os.environ.get("ADO_PAT", "")

    if not org or not pat:
        logger.debug(
            "ADO connector skipped — ADO_ORGANIZATION and/or ADO_PAT not set"
        )
        return

    if registry.has("ado"):
        logger.debug("ADO connector already registered, skipping")
        return

    from pipeline.connectors.ado import ADOConnector

    connector = ADOConnector(
        organization=org,
        project=os.environ.get("ADO_PROJECT", ""),
        pat=pat,
        base_url=os.environ.get("ADO_BASE_URL"),
    )
    registry.register("ado", connector)

    if auto_connect:
        result = connector.connect()
        if result.ok:
            logger.info("ADO connector connected to '%s'", org)
        else:
            logger.warning("ADO connector registered but connect failed: %s", result.error)


def _register_mcp(
    registry: ConnectorRegistry,
    *,
    call_tool_fn: Callable[..., Any] | None = None,
    list_tools_fn: Callable[..., Any] | None = None,
    auto_connect: bool = True,
) -> None:
    """Register MCPConnector.

    The MCP connector is always registered (even without env vars)
    because it can be configured later via ``set_call_tool_fn()``.
    However, ``connect()`` is only called when a ``call_tool_fn``
    is provided.
    """
    if registry.has("mcp"):
        logger.debug("MCP connector already registered, skipping")
        return

    from pipeline.connectors.mcp import MCPConnector

    connector = MCPConnector(
        server_name=os.environ.get("MCP_SERVER_NAME", "default"),
        call_tool_fn=call_tool_fn,
        list_tools_fn=list_tools_fn,
    )
    registry.register("mcp", connector)

    if auto_connect and call_tool_fn:
        result = connector.connect()
        if result.ok:
            logger.info("MCP connector connected to '%s'", connector._server_name)
        else:
            logger.warning("MCP connector registered but connect failed: %s", result.error)
    elif not call_tool_fn:
        logger.debug(
            "MCP connector registered (deferred — no call_tool_fn yet)"
        )
