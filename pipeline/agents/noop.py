"""NoopAgent — pass-through agent for testing pipeline flow.

Returns ok=True with the input context echoed back as data.
Useful for test configs that need a placeholder step to verify
branching, decision, and recovery flows without executing real logic.

If ``force_fail`` is truthy in context, the agent raises an exception
to simulate step failure (used by test_retry.json).
"""
from __future__ import annotations

import logging
from typing import Any

from pipeline.agents.base import BaseAgent, AgentResult

logger = logging.getLogger(__name__)


class NoopAgent(BaseAgent):
    """No-operation agent — echoes inputs back and succeeds.

    Context keys
    ------------
    force_fail : bool
        If truthy, raises RuntimeError to simulate failure.
        Used by retry intelligence test scenarios.
    force_fail_message : str
        Custom error message for the simulated failure.
    """

    name = "noop"
    description = "Pass-through agent for testing (echoes inputs)"

    def run(self, context: dict[str, Any]) -> AgentResult:
        # Check for forced failure (test_retry scenario)
        if context.get("force_fail"):
            msg = context.get("force_fail_message", "Simulated failure (force_fail=True)")
            logger.warning("[NoopAgent] Forced failure: %s", msg)
            raise RuntimeError(msg)

        # Echo non-private context keys back as data
        data = {
            k: v for k, v in context.items()
            if isinstance(k, str) and not k.startswith("_")
        }
        data["noop"] = True

        logger.info("[NoopAgent] Pass-through with %d context keys", len(data))
        return AgentResult(ok=True, data=data)
