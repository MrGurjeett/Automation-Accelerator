"""BaseAgent — abstract interface for all pipeline agents.

Every pipeline stage can be backed by an agent that encapsulates the
domain logic for that stage.  Agents:

- Receive a context dict (stage-specific inputs)
- Return an :class:`AgentResult` (structured output)
- Do NOT emit events, touch the EventManager, or write artifacts
- Are stateless across invocations (no mutable instance state between runs)

This makes agents independently testable and reusable across different
orchestration flows (CLI pipeline, Neuro-SAN agent tools, dashboard).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Structured output from an agent execution.

    Attributes
    ----------
    ok : bool
        Whether the agent completed successfully.
    data : dict
        Arbitrary output data (stage-specific).
    error : str | None
        Human-readable error message if ``ok`` is False.
    warnings : list[str]
        Non-fatal issues encountered during execution.
    metrics : dict
        Optional performance/quality metrics (e.g. row counts, scores).
    """

    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base class for pipeline agents.

    Subclasses must implement :meth:`run`.  The pipeline orchestrator
    calls ``agent.run(context)`` and translates the :class:`AgentResult`
    into a :class:`StepResult` + events.

    Example::

        class ValidationAgent(BaseAgent):
            name = "validation"
            description = "Validates Excel rows against schema and business rules"

            def run(self, context: dict[str, Any]) -> AgentResult:
                rows = context.get("rows", [])
                # ... validation logic ...
                return AgentResult(ok=True, data={"validated": validated})
    """

    # Subclasses should set these class attributes.
    name: str = ""
    description: str = ""
    # Optional: declare expected context keys and output data keys.
    # Used by AgentRegistry.validate_pipeline() and config validation.
    input_keys: list[str] = []
    output_keys: list[str] = []

    @abstractmethod
    def run(self, context: dict[str, Any]) -> AgentResult:
        """Execute the agent's domain logic.

        Parameters
        ----------
        context : dict
            Stage-specific inputs.  The keys depend on which pipeline
            stage this agent is wired to.

        Returns
        -------
        AgentResult
            Structured output.  The orchestrator reads ``ok``, ``data``,
            and ``error`` to decide whether the pipeline continues.
        """
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name!r})>"


class ConnectorAwareMixin:
    """Mixin that gives an agent access to external system connectors.

    Agents that inherit this mixin can call ``self.get_connector(name, context)``
    to retrieve a connector from the registry passed in the execution context.

    The PipelineService injects a ``_connector_registry`` key into the
    context dict so that connector-aware agents can access it without
    a hard dependency on any global state.

    Example::

        class MyAgent(ConnectorAwareMixin, BaseAgent):
            def run(self, context):
                ado = self.get_connector("ado", context)
                if ado and ado.is_connected:
                    result = ado.fetch({"type": "work_items", "ids": [123]})
                ...
    """

    def get_connector(self, name: str, context: dict) -> Any:
        """Look up a connector by name from the context's registry.

        Parameters
        ----------
        name : str
            Connector name (e.g. ``"ado"``, ``"mcp"``).
        context : dict
            The execution context dict passed to ``run()``.

        Returns
        -------
        BaseConnector or None
            The connector instance, or None if not found / not registered.
        """
        registry = context.get("_connector_registry")
        if registry is not None:
            return registry.get(name)

        # Fallback: try the global singleton
        try:
            from pipeline.connectors.registry import get_connector as _global_get
            return _global_get(name)
        except Exception:
            return None
