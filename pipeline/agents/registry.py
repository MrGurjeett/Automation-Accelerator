"""AgentRegistry — central registry mapping stage names to agent instances.

The registry allows the pipeline orchestrator to look up which agent
handles a given stage, enabling dynamic pipeline composition and
extensibility.

Usage::

    registry = AgentRegistry()
    registry.register("validate", ValidationAgent())
    registry.register("normalize", NormalizationAgent())

    agent = registry.get("validate")
    result = agent.run(context)

Enhanced in Phase 3 with:
  - Auto-discovery of agents from packages
  - Lookup by agent type/name
  - Pipeline config validation
  - Default registry builder
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from pipeline.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Maps stage names to agent instances.

    Thread-safe for reads (dict lookup is atomic in CPython).
    Registration is expected to happen at startup, not at runtime.
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, stage_name: str, agent: BaseAgent) -> None:
        """Register an agent for a pipeline stage.

        Parameters
        ----------
        stage_name:
            The pipeline stage key (must match ``StepName`` values).
        agent:
            The agent instance to handle this stage.

        Raises
        ------
        ValueError
            If the stage is already registered (prevents silent overwrite).
        """
        if stage_name in self._agents:
            raise ValueError(
                f"Stage '{stage_name}' already registered to "
                f"{self._agents[stage_name]!r}. Unregister first."
            )
        self._agents[stage_name] = agent
        logger.debug("Registered agent %r for stage '%s'", agent, stage_name)

    def unregister(self, stage_name: str) -> BaseAgent | None:
        """Remove and return the agent for a stage, or None."""
        return self._agents.pop(stage_name, None)

    def get(self, stage_name: str) -> BaseAgent | None:
        """Look up the agent for a stage, or None if not registered."""
        return self._agents.get(stage_name)

    def has(self, stage_name: str) -> bool:
        """Check if a stage has a registered agent."""
        return stage_name in self._agents

    @property
    def stages(self) -> list[str]:
        """Return all registered stage names."""
        return list(self._agents.keys())

    def list_agents(self) -> list[dict[str, Any]]:
        """Return metadata for all registered agents."""
        return [
            {
                "stage": stage,
                "name": agent.name,
                "description": agent.description,
                "type": type(agent).__name__,
            }
            for stage, agent in self._agents.items()
        ]

    # ------------------------------------------------------------------
    # Phase 3: Enhanced capabilities
    # ------------------------------------------------------------------

    def get_by_type(self, agent_type: str) -> list[tuple[str, BaseAgent]]:
        """Find all agents whose class name matches ``agent_type``.

        Parameters
        ----------
        agent_type : str
            Class name to match (e.g. ``"ValidationAgent"``).

        Returns
        -------
        list[tuple[str, BaseAgent]]
            Pairs of (stage_name, agent_instance).
        """
        return [
            (stage, agent)
            for stage, agent in self._agents.items()
            if type(agent).__name__ == agent_type
        ]

    def get_by_name(self, agent_name: str) -> list[tuple[str, BaseAgent]]:
        """Find all agents whose ``name`` attribute matches.

        Parameters
        ----------
        agent_name : str
            Agent name to match (e.g. ``"validation"``).
        """
        return [
            (stage, agent)
            for stage, agent in self._agents.items()
            if agent.name == agent_name
        ]

    def validate_pipeline(
        self,
        step_names: list[str],
        builtin_handlers: set[str] | None = None,
    ) -> list[str]:
        """Validate that every step in a pipeline config can be executed.

        Parameters
        ----------
        step_names : list[str]
            The step names from a pipeline config.
        builtin_handlers : set[str] | None
            Set of step names that have built-in handlers (from PipelineService).
            If None, only agent registration is checked.

        Returns
        -------
        list[str]
            List of step names that cannot be resolved (empty = all valid).
        """
        handlers = builtin_handlers or set()
        unresolvable = []
        for name in step_names:
            if name not in self._agents and name not in handlers:
                unresolvable.append(name)
        return unresolvable

    def discover_agents(self, package_name: str = "pipeline.agents") -> int:
        """Auto-discover and register all BaseAgent subclasses in a package.

        Walks the package, imports all modules, finds concrete BaseAgent
        subclasses with a non-empty ``name`` attribute, and registers them
        using their ``name`` as the stage key.

        Parameters
        ----------
        package_name : str
            Dotted package name to scan.

        Returns
        -------
        int
            Number of agents discovered and registered.
        """
        count = 0
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            logger.warning("Cannot import package %s for agent discovery", package_name)
            return 0

        if not hasattr(package, "__path__"):
            return 0

        for finder, module_name, is_pkg in pkgutil.walk_packages(
            package.__path__, prefix=package.__name__ + "."
        ):
            try:
                mod = importlib.import_module(module_name)
            except Exception:
                logger.debug("Skipping module %s (import failed)", module_name)
                continue

            for attr_name in dir(mod):
                obj = getattr(mod, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseAgent)
                    and obj is not BaseAgent
                    and not getattr(obj, "__abstractmethods__", None)
                    and getattr(obj, "name", "")
                ):
                    stage_key = obj.name
                    if not self.has(stage_key):
                        try:
                            self.register(stage_key, obj())
                            count += 1
                            logger.debug(
                                "Auto-discovered agent %s -> %s",
                                stage_key, obj.__name__,
                            )
                        except Exception:
                            logger.debug(
                                "Failed to instantiate %s for auto-registration",
                                obj.__name__,
                            )

        logger.info("Agent discovery: registered %d agents from %s", count, package_name)
        return count

    def replace(self, stage_name: str, agent: BaseAgent) -> BaseAgent | None:
        """Replace the agent for a stage, returning the old one.

        Unlike ``register``, this does not raise on duplicates — it
        silently replaces the existing agent.  Useful for hot-swapping
        agents at runtime.
        """
        old = self._agents.get(stage_name)
        self._agents[stage_name] = agent
        if old:
            logger.debug("Replaced agent for '%s': %r -> %r", stage_name, old, agent)
        else:
            logger.debug("Registered agent %r for stage '%s'", agent, stage_name)
        return old

    def __len__(self) -> int:
        return len(self._agents)

    def __repr__(self) -> str:
        return f"<AgentRegistry stages={self.stages}>"


# ---------------------------------------------------------------------------
# Default registry builder
# ---------------------------------------------------------------------------

def build_default_registry() -> AgentRegistry:
    """Create an AgentRegistry pre-populated with all built-in agents.

    This uses auto-discovery to find all concrete BaseAgent subclasses
    in the ``pipeline.agents`` package.
    """
    registry = AgentRegistry()
    registry.discover_agents("pipeline.agents")
    return registry
