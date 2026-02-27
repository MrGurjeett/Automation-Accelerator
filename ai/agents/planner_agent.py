from __future__ import annotations

from dataclasses import dataclass, field

from ai.agents.intent_agent import IntentResult, IntentType


@dataclass(frozen=True)
class PlanStep:
    name: str
    action: str
    params: dict[str, object] = field(default_factory=dict)


class PlannerAgent:
    """Builds deterministic action plans from classified intent."""

    def build_plan(self, intent_result: IntentResult, user_input: str) -> list[PlanStep]:
        intent = intent_result.intent

        if intent == IntentType.INDEX_KNOWLEDGE:
            return [
                PlanStep("Load docs", "load_documents", {}),
                PlanStep("Chunk docs", "chunk_documents", {}),
                PlanStep("Embed chunks", "embed_chunks", {}),
                PlanStep("Upsert vectors", "upsert_vectors", {}),
            ]

        if intent == IntentType.GENERATE_FEATURE:
            return [
                PlanStep("Retrieve context", "retrieve_context", {"query": user_input}),
                PlanStep("Generate feature", "generate_feature", {"query": user_input}),
            ]

        if intent == IntentType.GENERATE_STEPS:
            return [
                PlanStep("Retrieve context", "retrieve_context", {"query": user_input}),
                PlanStep("Generate steps", "generate_steps", {"query": user_input}),
            ]

        if intent == IntentType.RAG_QUERY:
            return [
                PlanStep("Retrieve context", "retrieve_context", {"query": user_input}),
                PlanStep("Answer query", "answer_query", {"query": user_input}),
            ]

        return [PlanStep("Fallback", "fallback", {"query": user_input})]
