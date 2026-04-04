"""
pipeline.connectors — external system connector abstraction layer.

Phase 4A — provides a uniform interface for integrating with external
systems (Azure DevOps, MCP, etc.) without coupling pipeline agents to
specific APIs.

Public API::

    from pipeline.connectors import (
        BaseConnector,
        ConnectorResult,
        ConnectorRegistry,
        get_connector,
        get_default_registry,
        ADOConnector,
        MCPConnector,
    )
"""
from pipeline.connectors.base import BaseConnector, ConnectorResult
from pipeline.connectors.registry import (
    ConnectorRegistry,
    get_connector,
    get_default_registry,
    set_default_registry,
)
from pipeline.connectors.ado import ADOConnector
from pipeline.connectors.mcp import MCPConnector
from pipeline.connectors.init_connectors import initialize_connectors

__all__ = [
    "BaseConnector",
    "ConnectorResult",
    "ConnectorRegistry",
    "get_connector",
    "get_default_registry",
    "set_default_registry",
    "ADOConnector",
    "MCPConnector",
    "initialize_connectors",
]
