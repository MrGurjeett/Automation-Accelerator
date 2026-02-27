from __future__ import annotations

from typing import Callable

from ai.agents.planner_agent import PlanStep


class ExecutionAgent:
    """Executes plan steps by resolving actions to callables."""

    def __init__(self, action_registry: dict[str, Callable[..., object]]) -> None:
        self.action_registry = action_registry

    def execute(self, plan: list[PlanStep]) -> dict[str, object]:
        state: dict[str, object] = {}
        for step in plan:
            action = self.action_registry.get(step.action)
            if not action:
                raise KeyError(f"No action registered for '{step.action}'")
            output = action(state=state, **step.params)
            state[step.name] = output
            state[step.action] = output
        return state
