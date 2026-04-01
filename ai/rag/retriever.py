from __future__ import annotations

import re

from ai.rag.embedder import EmbeddingService
from ai.rag.vectordb import VectorStore


class Retriever:
    """Embeds the query and retrieves semantically relevant context chunks."""

    def __init__(self, embedder: EmbeddingService, vector_store: VectorStore) -> None:
        self.embedder = embedder
        self.vector_store = vector_store

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.2,
        mode: str = "semantic",
        semantic_weight: float = 0.8,
        keyword_weight: float = 0.2,
    ) -> list[dict[str, object]]:
        query_vector = self.embedder.embed_query(query)
        results = self.vector_store.similarity_search(query_vector, top_k=top_k)
        mode = (mode or "semantic").strip().lower()

        payload: list[dict[str, object]] = []
        for doc, score in results:
            final_score = score
            if mode == "hybrid":
                keyword_score = self._keyword_overlap(query, doc.text)
                final_score = (semantic_weight * score) + (keyword_weight * keyword_score)

            if final_score < min_score:
                continue
            payload.append(
                {
                    "id": doc.id,
                    "text": doc.text,
                    "metadata": doc.metadata,
                    "score": round(final_score, 4),
                }
            )
        payload.sort(key=lambda x: float(x["score"]), reverse=True)
        return payload

    @staticmethod
    def _keyword_overlap(query: str, text: str) -> float:
        q_tokens = set(re.findall(r"[a-zA-Z0-9_]+", query.lower()))
        t_tokens = set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))
        if not q_tokens or not t_tokens:
            return 0.0
        intersection = len(q_tokens.intersection(t_tokens))
        return intersection / max(1, len(q_tokens))

    @staticmethod
    def build_context(retrieved: list[dict[str, object]], max_chars: int = 12000) -> str:
        lines: list[str] = []
        current = 0
        for item in retrieved:
            metadata = item.get("metadata") or {}
            source = str(metadata.get("source", "unknown"))
            entry_type = str(metadata.get("type", ""))
            feature_domain = str(metadata.get("feature", ""))
            text = str(item.get("text", ""))

            # Structured KB entries get a domain header for clarity
            if entry_type == "bdd_reference" and feature_domain:
                block = f"[Reference Pattern — {feature_domain}]\n{text}\n"
            else:
                block = f"Source: {source}\n{text}\n"

            if current + len(block) > max_chars:
                break
            lines.append(block)
            current += len(block)
        return "\n".join(lines)
