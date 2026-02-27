"""Backward compatibility shim. Prefer importing from ai.agents.intent_agent."""

from ai.agents.intent_agent import IntentAgent, IntentResult, IntentType


class IntentAgant(IntentAgent):
	"""Deprecated typo-compatible alias of IntentAgent."""

