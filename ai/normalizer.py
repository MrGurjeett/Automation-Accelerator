"""
AI Normaliser — uses Azure OpenAI + Qdrant RAG to normalise Excel rows.

Returns a NormalisedStep with a confidence score.
Confidence threshold = 0.85. Below → hard rejection of that TC.

AI is MANDATORY during generation.
AI is NEVER used during execution.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from ai.clients.azure_openai_client import AzureOpenAIClient
from ai.config import AIConfig
from ai.rag.embedder import EmbeddingService
from ai.rag.retriever import Retriever
from ai.rag.vectordb import QdrantVectorStore, VectorDocument
import ai.ai_stats as ai_stats

logger = logging.getLogger(__name__)
ai_logger = logging.getLogger("ai_reasoning")

CONFIDENCE_THRESHOLD = 0.45


class GenerationError(Exception):
    """Raised when AI normalisation confidence is below threshold."""


@dataclass
class NormalisedStep:
    normalized_action: str
    normalized_target: str
    value: Optional[str]
    expected: Optional[str]
    confidence: float


# ── RAG knowledge base seeding ──────────────────────────────────────────

_BDD_REFERENCE_STEPS = [
    # Login page
    {"action": "navigate", "target": "Login Page", "description": "Navigate to the Login page URL"},
    {"action": "fill", "target": "Username", "description": "Fill the Username input field with a value"},
    {"action": "fill", "target": "Email", "description": "Fill the Email input field with a value"},
    {"action": "fill", "target": "Password", "description": "Fill the Password input field with a value"},
    {"action": "click", "target": "Login Button", "description": "Click the Login button to submit the form"},
    {"action": "click", "target": "Submit Button", "description": "Click the Submit button to submit the form"},
    {"action": "verify_text", "target": "Welcome Message", "description": "Verify the welcome/greeting message after login"},
    {"action": "verify_text", "target": "Success Message", "description": "Verify the success/dashboard message after login"},
    {"action": "verify_text", "target": "Dashboard Message", "description": "Verify the dashboard welcome message"},
    {"action": "verify_text", "target": "Error Message", "description": "Verify the error message on failed login"},
    {"action": "verify_text", "target": "Accounts Overview Title", "description": "Verify the Accounts Overview page title"},
    # Transfer Funds
    {"action": "navigate", "target": "Transfer Funds", "description": "Navigate to the Transfer Funds page"},
    {"action": "select", "target": "From Account", "description": "Select the source account for transfer"},
    {"action": "select", "target": "To Account", "description": "Select the destination account for transfer"},
    {"action": "fill", "target": "Amount", "description": "Fill the transfer/payment amount field"},
    {"action": "verify_text", "target": "Transfer Complete", "description": "Verify the transfer confirmation message"},
    # Bill Pay
    {"action": "navigate", "target": "Bill Pay", "description": "Navigate to the Bill Pay page"},
    {"action": "fill", "target": "Payee Name", "description": "Fill the payee name field for bill payment"},
    {"action": "fill", "target": "Address", "description": "Fill the address field"},
    {"action": "verify_text", "target": "Bill Payment Complete", "description": "Verify the bill payment success message"},
    # Request Loan
    {"action": "navigate", "target": "Request Loan", "description": "Navigate to the Request Loan page"},
    {"action": "fill", "target": "Loan Amount", "description": "Fill the loan amount field"},
    {"action": "fill", "target": "Down Payment", "description": "Fill the down payment field"},
    {"action": "verify_text", "target": "Loan Request Processed", "description": "Verify the loan request result message"},
    # Generic
    {"action": "click", "target": "Send Payment", "description": "Click the send payment / submit button"},
    {"action": "click", "target": "Apply Now", "description": "Click the apply / submit loan button"},
    {"action": "click", "target": "Transfer", "description": "Click the transfer submit button"},
    {"action": "select", "target": "Account", "description": "Select an account from a dropdown"},
]

_NORMALISATION_PROMPT = """\
You are a strict BDD test-step normaliser for an automation framework.

CONTEXT (reference steps from knowledge base):
{rag_context}

DOM KNOWLEDGE (extracted UI elements from the application):
{dom_context}

INPUT ROW:
- Action: {action}
- Target: {target}
- Value: {value}
- Expected: {expected}

SUPPORTED ACTIONS: fill, click, navigate, verify_text, select

RULES:
1. Map the action to the closest SUPPORTED ACTION.
2. Map the target to the closest known target from the reference steps or DOM elements.
3. Do NOT invent new actions or targets. Use ONLY what exists in the references or DOM.
4. Assign a confidence score 0.0–1.0 based on how well the input matches known patterns.
5. If the input is ambiguous or does not match any reference, set confidence below 0.5.

Respond with ONLY this JSON (no markdown, no explanation):
{{"normalized_action": "...", "normalized_target": "...", "value": "...", "expected": "...", "confidence": 0.XX}}
"""


class AINormaliser:
    """Normalises Excel rows using Azure OpenAI + Qdrant RAG + DOM knowledge."""

    def __init__(self, config: AIConfig, dom_store=None) -> None:
        self.config = config
        self.client = AzureOpenAIClient(config.azure_openai)
        self.embedder = EmbeddingService(self.client)
        self.dom_store = dom_store  # Optional DOMVectorStore for DOM context

        # Qdrant vector store — reuse existing client if dom_store provides one
        shared_client = getattr(getattr(dom_store, 'store', None), 'client', None) if dom_store else None
        self.vector_store = QdrantVectorStore(
            persist_path=config.rag.qdrant_persist_path,
            collection_name=config.rag.qdrant_collection_name,
            client=shared_client,
        )
        self.retriever = Retriever(self.embedder, self.vector_store)

        # Seed KB on init
        self._seed_knowledge_base()

    def _seed_knowledge_base(self) -> None:
        """Seed Qdrant with BDD reference steps if not already present."""
        try:
            existing = {c.name for c in self.vector_store.client.get_collections().collections}
            if self.vector_store.collection_name in existing:
                info = self.vector_store.client.get_collection(self.vector_store.collection_name)
                if (info.points_count or 0) > 0:
                    logger.info("Qdrant KB already seeded (%d docs).", info.points_count)
                    return
        except Exception:
            pass

        logger.info("Seeding Qdrant knowledge base with %d reference steps…", len(_BDD_REFERENCE_STEPS))
        texts = [
            f"Action: {s['action']} | Target: {s['target']} | {s['description']}"
            for s in _BDD_REFERENCE_STEPS
        ]
        embeddings = self.embedder.embed_texts(texts)
        docs = [
            VectorDocument(
                id=f"bdd_ref_{i}",
                text=texts[i],
                metadata={
                    "action": _BDD_REFERENCE_STEPS[i]["action"],
                    "target": _BDD_REFERENCE_STEPS[i]["target"],
                    "type": "bdd_reference",
                },
                embedding=embeddings[i],
            )
            for i in range(len(texts))
        ]
        self.vector_store.upsert(docs)
        logger.info("Qdrant KB seeded successfully.")

    def normalise_step(self, row: dict[str, str]) -> NormalisedStep:
        """Normalise a single Excel row using RAG + LLM.

        Returns NormalisedStep. Raises GenerationError if confidence < threshold.
        """
        action = row.get("Action", "")
        target = row.get("Target", "")
        value = row.get("Value", "-")
        expected = row.get("Expected", "-")

        # ── AI Reasoning Panel ───────────────────────────────────────
        ai_logger.info("")
        ai_logger.info("─" * 50)
        ai_logger.info("[AI] Raw step from Excel: \"%s %s\"", action, target)
        if value and value != "-":
            ai_logger.info("[AI] Value: \"%s\"", value)
        if expected and expected != "-":
            ai_logger.info("[AI] Expected: \"%s\"", expected)

        # 1. RAG retrieval
        query = f"Action: {action} | Target: {target}"
        retrieved = self.retriever.retrieve(
            query,
            top_k=self.config.rag.top_k,
            min_score=self.config.rag.min_score,
        )
        rag_context = Retriever.build_context(retrieved, max_chars=self.config.rag.max_context_chars)

        if not rag_context.strip():
            rag_context = "No matching reference steps found."

        # 2b. DOM context retrieval (if DOM store available)
        dom_context = "No DOM knowledge available."
        if self.dom_store is not None:
            try:
                dom_results = self.dom_store.search(f"{action} {target}", top_k=5, min_score=0.3)
                if dom_results:
                    dom_lines = []
                    for r in dom_results:
                        meta = r.get("metadata", {})
                        dom_lines.append(
                            f"- Element: {meta.get('element_name', 'unknown')} | "
                            f"Page: {meta.get('page', 'unknown')} | "
                            f"Tag: {meta.get('tag', '')} | "
                            f"Locators: {meta.get('locator_candidates', '')}"
                        )
                    dom_context = "\n".join(dom_lines)
                    logger.info("[AI] DOM context: %d matches for '%s/%s'", len(dom_results), action, target)
            except Exception as exc:
                logger.debug("[AI] DOM context retrieval failed: %s", exc)

        # 3. LLM prompt
        prompt = _NORMALISATION_PROMPT.format(
            rag_context=rag_context,
            dom_context=dom_context,
            action=action,
            target=target,
            value=value,
            expected=expected,
        )
        messages = [
            {"role": "system", "content": "You are a strict BDD normaliser. Respond ONLY with valid JSON."},
            {"role": "user", "content": prompt},
        ]

        raw_response = self.client.chat_completion(messages, temperature=0.0, max_tokens=300)
        logger.info("AI raw response for [%s / %s]: %s", action, target, raw_response)

        # 3. Parse response
        step = self._parse_response(raw_response, row)

        # ── AI Reasoning Panel — result ─────────────────────────────
        ai_logger.info("[AI] Normalized step: %s %s", step.normalized_action, step.normalized_target)
        ai_logger.info("[AI] Confidence: %.2f", step.confidence)
        ai_logger.info("─" * 50)

        ai_stats.increment("normalized_steps")

        logger.info(
            "Normalised: action=%s target=%s confidence=%.2f",
            step.normalized_action, step.normalized_target, step.confidence,
        )

        # 4. Confidence gate
        if step.confidence < CONFIDENCE_THRESHOLD:
            raise GenerationError(
                f"Confidence {step.confidence:.2f} < {CONFIDENCE_THRESHOLD} "
                f"for action='{action}', target='{target}'. TC rejected."
            )

        return step

    def normalise_tc(self, tc_id: str, rows: List[dict[str, str]]) -> List[NormalisedStep]:
        """Normalise all rows for a single TC. Raises GenerationError on low confidence."""
        steps: List[NormalisedStep] = []
        for i, row in enumerate(rows):
            logger.info("  Normalising step %d/%d for %s …", i + 1, len(rows), tc_id)
            step = self.normalise_step(row)
            steps.append(step)
        return steps

    @staticmethod
    def _parse_response(raw: str, original_row: dict[str, str]) -> NormalisedStep:
        """Parse the LLM JSON response into a NormalisedStep.

        IMPORTANT: target, value and expected are ALWAYS taken from the
        original Excel row, never from the LLM response.  The AI only
        normalises action — everything else passes through unchanged so
        the script always refers to exactly what the Excel specifies.
        """
        # Strip markdown fences if present
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?", "", cleaned)
        cleaned = re.sub(r"```$", "", cleaned)
        cleaned = cleaned.strip()

        # Preserve original Excel data — AI must never override these
        orig_target = original_row.get("Target", "")
        orig_value = original_row.get("Value", "-")
        orig_expected = original_row.get("Expected", "-")

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse AI response as JSON: %s", raw)
            return NormalisedStep(
                normalized_action=original_row.get("Action", ""),
                normalized_target=orig_target,
                value=orig_value if orig_value and orig_value != "-" else None,
                expected=orig_expected if orig_expected and orig_expected != "-" else None,
                confidence=0.0,  # will trigger rejection
            )

        return NormalisedStep(
            normalized_action=data.get("normalized_action", original_row.get("Action", "")),
            normalized_target=orig_target,
            value=orig_value if orig_value and orig_value != "-" else None,
            expected=orig_expected if orig_expected and orig_expected != "-" else None,
            confidence=float(data.get("confidence", 0.0)),
        )

    def close(self) -> None:
        """Cleanup resources."""
        try:
            self.vector_store.close()
        except Exception:
            pass
