from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re


class IntentType(str, Enum):
    GENERATE_FEATURE = "generate_feature"
    GENERATE_STEPS = "generate_steps"
    INDEX_KNOWLEDGE = "index_knowledge"
    RAG_QUERY = "rag_query"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntentResult:
    intent: IntentType
    confidence: float
    entities: dict[str, str] = field(default_factory=dict)
    reason: str = ""


class IntentAgent:
    """Classifies user request into an actionable intent."""

    FEATURE_HINTS = ("feature", "gherkin", "scenario")
    STEP_HINTS = ("step definition", "steps", "pytest-bdd")
    INDEX_HINTS = ("index", "ingest", "load docs", "embed", "vector")
    QUERY_HINTS = ("what", "how", "explain", "search", "find")

    def classify(self, text: str) -> IntentResult:
        query = text.strip().lower()
        if not query:
            return IntentResult(IntentType.UNKNOWN, 0.0, reason="Empty input")

        if self._contains_any(query, self.INDEX_HINTS):
            return IntentResult(IntentType.INDEX_KNOWLEDGE, 0.92, reason="Indexing keywords matched")

        if self._contains_any(query, self.FEATURE_HINTS) and "generate" in query:
            return IntentResult(IntentType.GENERATE_FEATURE, 0.9, reason="Feature generation intent matched")

        if self._contains_any(query, self.STEP_HINTS) and "generate" in query:
            return IntentResult(IntentType.GENERATE_STEPS, 0.9, reason="Step generation intent matched")

        if self._contains_any(query, self.QUERY_HINTS):
            entities = self._extract_entities(query)
            return IntentResult(IntentType.RAG_QUERY, 0.75, entities=entities, reason="Question/query style request")

        return IntentResult(IntentType.UNKNOWN, 0.3, reason="No strong keyword match")

    @staticmethod
    def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
        return any(h in text for h in hints)

    @staticmethod
    def _extract_entities(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        scenario_match = re.search(r"scenario\s*[:=-]?\s*(.+)$", text)
        if scenario_match:
            result["scenario"] = scenario_match.group(1).strip()
        return result
