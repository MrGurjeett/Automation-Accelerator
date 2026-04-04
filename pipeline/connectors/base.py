"""
BaseConnector — abstract interface for all external system connectors.

Phase 4A — provides a clean abstraction layer that decouples pipeline
agents from external systems (Azure DevOps, MCP, etc.).

Connectors:
- Encapsulate connection details and credentials
- Provide a uniform ``fetch`` / ``push`` interface
- Handle their own authentication and session management
- Return structured ``ConnectorResult`` objects
- Do NOT contain business logic (that belongs in agents)

This mirrors the design of ``BaseAgent`` — connectors are to external
systems what agents are to pipeline stages.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConnectorResult:
    """Structured output from a connector operation.

    Attributes
    ----------
    ok : bool
        Whether the operation completed successfully.
    data : dict
        The response payload (query results, push confirmation, etc.).
    error : str | None
        Human-readable error message if ``ok`` is False.
    status_code : int | None
        HTTP status code or equivalent (for debugging).
    metadata : dict
        Additional context (timing, pagination, request ID, etc.).
    """

    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    status_code: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Abstract base class for external system connectors.

    Subclasses must implement ``connect``, ``fetch``, ``push``, and
    ``health_check``.  The connector lifecycle is:

    1. ``connect()`` — establish credentials / session
    2. ``fetch(query)`` / ``push(data)`` — operations
    3. ``health_check()`` — verify availability

    Example::

        class ADOConnector(BaseConnector):
            name = "ado"
            description = "Azure DevOps REST API connector"

            def connect(self) -> ConnectorResult:
                # Store auth headers, verify access
                ...

            def fetch(self, query: dict) -> ConnectorResult:
                # Execute WIQL query or fetch work items
                ...
    """

    # Subclasses should set these class attributes.
    name: str = ""
    description: str = ""

    @abstractmethod
    def connect(self) -> ConnectorResult:
        """Establish connection / authenticate with the external system.

        Returns
        -------
        ConnectorResult
            Success with connection metadata, or failure with error.
        """
        ...

    @abstractmethod
    def fetch(self, query: dict[str, Any]) -> ConnectorResult:
        """Retrieve data from the external system.

        Parameters
        ----------
        query : dict
            System-specific query parameters.

        Returns
        -------
        ConnectorResult
            The fetched data or an error.
        """
        ...

    @abstractmethod
    def push(self, data: dict[str, Any]) -> ConnectorResult:
        """Send data to the external system.

        Parameters
        ----------
        data : dict
            The payload to send.

        Returns
        -------
        ConnectorResult
            Confirmation or error.
        """
        ...

    @abstractmethod
    def health_check(self) -> ConnectorResult:
        """Check if the external system is reachable and operational.

        Returns
        -------
        ConnectorResult
            ``ok=True`` if healthy, ``ok=False`` with diagnostics otherwise.
        """
        ...

    @property
    def is_connected(self) -> bool:
        """Whether the connector has been successfully connected.

        Subclasses can override for more precise state tracking.
        """
        return False

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name!r})>"
