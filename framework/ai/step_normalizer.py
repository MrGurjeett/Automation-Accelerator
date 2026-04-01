"""
AI Step Normalizer — converts raw human-readable test steps into
standardized automation steps using Azure OpenAI + RAG context.

Example:
    Input:  "Press login" → Output: "click Login Button"
    Input:  "Submit credentials" → Output: "click Login Button"

Uses:
  • Azure OpenAI GPT-4.1 for semantic understanding
  • Qdrant embeddings for semantic matching against known DOM elements
  • Strict output format: Action | Target
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from ai.clients.azure_openai_client import AzureOpenAIClient
from ai.rag.embedder import EmbeddingService
from framework.vector_store.qdrant_client import DOMVectorStore

logger = logging.getLogger(__name__)

SUPPORTED_ACTIONS = {"fill", "click", "navigate", "verify_text", "select"}

_STEP_NORMALISATION_PROMPT = """\
You are a strict BDD test-step normaliser for a web automation framework.

KNOWN UI ELEMENTS FROM DOM SCAN:
{dom_context}

REFERENCE STEPS FROM KNOWLEDGE BASE:
{rag_context}

INPUT ROW:
- Action: {action}
- Target: {target}
- Value: {value}
- Expected: {expected}

SUPPORTED ACTIONS: fill, click, navigate, verify_text, select

RULES:
1. Map the action to the closest SUPPORTED ACTION.
2. Map the target to the closest known UI element from the DOM scan or reference steps.
3. Do NOT invent new actions or targets. Use ONLY what exists in the DOM scan or references.
4. Assign a confidence score 0.0–1.0 based on how well the input matches known patterns.
5. If the input is ambiguous or does not match any reference, set confidence below 0.5.

Respond with ONLY this JSON (no markdown, no explanation):
{{"normalized_action": "...", "normalized_target": "...", "value": "...", "expected": "...", "confidence": 0.XX}}
"""


@dataclass
class NormalizedStep:
    """Result of AI step normalization."""
    action: str
    target: str
    value: Optional[str]
    expected: Optional[str]
    confidence: float
    original_action: str = ""
    original_target: str = ""


class AIStepNormalizer:
    """Normalizes Excel test steps using AI + DOM knowledge.

    Combines:
      1. DOM knowledge from Qdrant (element names, attributes)
      2. BDD reference steps (known patterns)
      3. Azure OpenAI for semantic understanding
    """

    def __init__(
        self,
        client: AzureOpenAIClient,
        embedder: EmbeddingService,
        dom_store: DOMVectorStore,
    ) -> None:
        self.client = client
        self.embedder = embedder
        self.dom_store = dom_store

    def normalize(self, row: dict[str, str], rag_context: str = "") -> NormalizedStep:
        """Normalize a single Excel row using AI + DOM context.

        Parameters
        ----------
        row : dict
            Excel row with Action, Target, Value, Expected.
        rag_context : str
            Pre-built RAG context from BDD reference steps.

        Returns
        -------
        NormalizedStep
        """
        action = row.get("Action", "")
        target = row.get("Target", "")
        value = row.get("Value", "-")
        expected = row.get("Expected", "-")

        # Search DOM knowledge base for relevant elements
        dom_results = self.dom_store.search(
            f"{action} {target}",
            top_k=5,
            min_score=0.3,
        )

        dom_context = ""
        if dom_results:
            dom_lines = []
            for r in dom_results:
                meta = r.get("metadata", {})
                dom_lines.append(
                    f"- Element: {meta.get('element_name', 'unknown')} | "
                    f"Page: {meta.get('page', 'unknown')} | "
                    f"Tag: {meta.get('tag', '')} | "
                    f"Locators: {meta.get('locator_candidates', '')} | "
                    f"Score: {r['score']}"
                )
            dom_context = "\n".join(dom_lines)
            logger.info(
                "[AI] DOM context for '%s/%s': %d matches (top score: %.2f)",
                action, target, len(dom_results),
                dom_results[0]["score"] if dom_results else 0,
            )
        else:
            dom_context = "No DOM elements found for this query."

        # Build prompt
        prompt = _STEP_NORMALISATION_PROMPT.format(
            dom_context=dom_context,
            rag_context=rag_context or "No reference steps available.",
            action=action,
            target=target,
            value=value,
            expected=expected,
        )

        messages = [
            {"role": "system", "content": "You are a strict BDD normaliser. Respond ONLY with valid JSON."},
            {"role": "user", "content": prompt},
        ]

        raw = self.client.chat_completion(messages, temperature=0.0, max_tokens=300)
        logger.info("[AI] Normalized step: '%s %s' → %s", action, target, raw.strip())

        return self._parse_response(raw, row)

    @staticmethod
    def _parse_response(raw: str, original_row: dict[str, str]) -> NormalizedStep:
        """Parse LLM response. Target/value/expected always come from Excel."""
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned)
        cleaned = cleaned.strip()

        orig_target = original_row.get("Target", "")
        orig_value = original_row.get("Value", "-")
        orig_expected = original_row.get("Expected", "-")

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("[AI] Failed to parse response: %s", raw)
            return NormalizedStep(
                action=original_row.get("Action", ""),
                target=orig_target,
                value=orig_value if orig_value != "-" else None,
                expected=orig_expected if orig_expected != "-" else None,
                confidence=0.0,
                original_action=original_row.get("Action", ""),
                original_target=orig_target,
            )

        return NormalizedStep(
            action=data.get("normalized_action", original_row.get("Action", "")),
            target=orig_target,
            value=orig_value if orig_value and orig_value != "-" else None,
            expected=orig_expected if orig_expected and orig_expected != "-" else None,
            confidence=float(data.get("confidence", 0.0)),
            original_action=original_row.get("Action", ""),
            original_target=orig_target,
        )
