"""
ConnectorRegistry — central registry for external system connectors.

Mirrors the design of ``AgentRegistry`` — provides a single place to
register, look up, and manage connector instances.

Usage::

    from pipeline.connectors.registry import ConnectorRegistry

    registry = ConnectorRegistry()
    registry.register("ado", ADOConnector(...))
    registry.register("mcp", MCPConnector(...))

    ado = registry.get("ado")
    result = ado.fetch({"type": "work_items", "project": "MyProject"})

The module-level ``_default_registry`` singleton provides global access
without requiring dependency injection everywhere::

    from pipeline.connectors.registry import get_connector

    ado = get_connector("ado")
"""
from __future__ import annotations

import logging
from typing import Any

from pipeline.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Maps connector names to connector instances.

    Thread-safe for reads (dict lookup is atomic in CPython).
    Registration is expected at startup, not during pipeline execution.
    """

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, name: str, connector: BaseConnector) -> None:
        """Register a connector by name.

        Parameters
        ----------
        name : str
            Unique connector identifier (e.g. ``"ado"``, ``"mcp"``).
        connector : BaseConnector
            The connector instance.

        Raises
        ------
        ValueError
            If the name is already registered (prevents silent overwrite).
        TypeError
            If the connector is not a BaseConnector subclass.
        """
        if not isinstance(connector, BaseConnector):
            raise TypeError(
                f"Expected BaseConnector instance, got {type(connector).__name__}"
            )
        if name in self._connectors:
            raise ValueError(
                f"Connector '{name}' already registered: "
                f"{self._connectors[name]!r}. Use replace() to override."
            )
        self._connectors[name] = connector
        logger.info("Registered connector '%s': %r", name, connector)

    def unregister(self, name: str) -> BaseConnector | None:
        """Remove and return a connector, or None if not registered."""
        removed = self._connectors.pop(name, None)
        if removed:
            logger.info("Unregistered connector '%s'", name)
        return removed

    def get(self, name: str) -> BaseConnector | None:
        """Look up a connector by name, or None if not registered."""
        return self._connectors.get(name)

    def has(self, name: str) -> bool:
        """Check if a connector is registered."""
        return name in self._connectors

    def replace(self, name: str, connector: BaseConnector) -> BaseConnector | None:
        """Replace a connector, returning the old one.

        Does not raise on duplicates — useful for hot-swapping.
        """
        if not isinstance(connector, BaseConnector):
            raise TypeError(
                f"Expected BaseConnector instance, got {type(connector).__name__}"
            )
        old = self._connectors.get(name)
        self._connectors[name] = connector
        if old:
            logger.info("Replaced connector '%s': %r -> %r", name, old, connector)
        else:
            logger.info("Registered connector '%s': %r", name, connector)
        return old

    @property
    def names(self) -> list[str]:
        """Return all registered connector names."""
        return list(self._connectors.keys())

    def list_connectors(self) -> list[dict[str, Any]]:
        """Return metadata for all registered connectors."""
        return [
            {
                "name": name,
                "type": type(c).__name__,
                "description": c.description,
                "connected": c.is_connected,
            }
            for name, c in self._connectors.items()
        ]

    def health_check_all(self) -> dict[str, bool]:
        """Run health checks on all connectors, return name -> healthy map."""
        results = {}
        for name, connector in self._connectors.items():
            try:
                result = connector.health_check()
                results[name] = result.ok
            except Exception as exc:
                logger.warning("Health check failed for '%s': %s", name, exc)
                results[name] = False
        return results

    def __len__(self) -> int:
        return len(self._connectors)

    def __repr__(self) -> str:
        return f"<ConnectorRegistry connectors={self.names}>"


# ---------------------------------------------------------------------------
# Module-level singleton for global access
# ---------------------------------------------------------------------------

_default_registry: ConnectorRegistry | None = None


def get_default_registry() -> ConnectorRegistry:
    """Return the global ConnectorRegistry singleton (lazy-created)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ConnectorRegistry()
    return _default_registry


def set_default_registry(registry: ConnectorRegistry) -> None:
    """Replace the global ConnectorRegistry singleton."""
    global _default_registry
    _default_registry = registry


def get_connector(name: str) -> BaseConnector | None:
    """Convenience: look up a connector from the global registry."""
    return get_default_registry().get(name)
