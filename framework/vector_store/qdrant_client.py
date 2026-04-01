"""
Vector Store — manages DOM element embeddings in Qdrant.

Responsibilities:
  • Connect to Qdrant (local persistent)
  • Create the DOM elements collection
  • Store element embeddings with rich metadata
  • Retrieve similar elements by query embedding

Uses Azure OpenAI text-embedding-3-large via the existing EmbeddingService.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from ai.rag.vectordb import QdrantVectorStore, VectorDocument
from ai.rag.embedder import EmbeddingService

logger = logging.getLogger(__name__)

# Qdrant collection dedicated to DOM elements (separate from BDD reference KB)
DOM_COLLECTION_NAME = "dom_elements"
DOM_PERSIST_PATH = ".qdrant"


class DOMVectorStore:
    """Manages DOM element storage and retrieval in Qdrant."""

    def __init__(
        self,
        embedder: EmbeddingService,
        persist_path: str = DOM_PERSIST_PATH,
        collection_name: str = DOM_COLLECTION_NAME,
    ) -> None:
        self.embedder = embedder
        self.store = QdrantVectorStore(
            persist_path=persist_path,
            collection_name=collection_name,
        )
        self._seeded = False

    def is_populated(self) -> bool:
        """Check if the DOM knowledge base already has stored elements."""
        try:
            n = self.count()
            if n > 0:
                logger.info("[DOM] Qdrant DOM collection already populated (%d docs)", n)
                return True
        except Exception:
            pass
        return False

    def store_elements(self, elements: list) -> int:
        """Embed and store DOM elements in Qdrant.

        Parameters
        ----------
        elements : list[DOMElement]
            Structured DOM elements from the extractor.

        Returns
        -------
        int
            Number of elements stored.
        """
        if not elements:
            return 0

        logger.info("[DOM] Embedding %d elements for Qdrant storage…", len(elements))

        # Create knowledge documents for embedding
        texts = [el.to_knowledge_doc() for el in elements]
        embeddings = self.embedder.embed_texts(texts)

        docs: List[VectorDocument] = []
        for i, el in enumerate(elements):
            doc = VectorDocument(
                id=f"dom_{el.page_name}_{el.element_name}_{i}".replace(" ", "_").lower(),
                text=texts[i],
                metadata={
                    "page": el.page_name,
                    "element_name": el.element_name,
                    "tag": el.tag,
                    "visible_text": el.visible_text,
                    "locator_candidates": "|".join(el.locator_candidates),
                    "type": "dom_element",
                    **{k: str(v) for k, v in el.attributes.items()},
                },
                embedding=embeddings[i],
            )
            docs.append(doc)

        count = self.store.upsert(docs)
        logger.info("[DOM] Stored %d DOM elements in Qdrant", count)
        self._seeded = True
        return count

    def clear(self) -> None:
        """Clear the DOM elements collection.

        This is important for a true "force scan"; otherwise upserts can leave
        stale elements behind and the RAG lookup may appear to use old data.
        """
        try:
            self.store.clear_collection()
        except Exception:
            # Best-effort. If Qdrant isn't initialised yet, nothing to clear.
            pass
        self._seeded = False

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.3,
        page_filter: str | None = None,
    ) -> List[dict]:
        """Search DOM elements by semantic similarity.

        Parameters
        ----------
        query : str
            Natural language query (e.g. "Submit Button", "Username field").
        top_k : int
            Max results to return.
        min_score : float
            Minimum similarity score.
        page_filter : str, optional
            If given, restrict results to this page name.

        Returns
        -------
        list[dict]
            Matching elements with metadata and score.
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        query_vector = self.embedder.embed_query(query)

        # Use Qdrant payload filtering when page_filter is set
        qfilter = None
        if page_filter:
            qfilter = Filter(
                must=[FieldCondition(key="metadata.page", match=MatchValue(value=page_filter))]
            )

        response = self.store.client.query_points(
            collection_name=self.store.collection_name,
            query=query_vector,
            query_filter=qfilter,
            limit=max(1, top_k),
            with_payload=True,
            with_vectors=False,
        )
        points = response.points if hasattr(response, "points") else response

        matches: List[dict] = []
        for item in points:
            score = float(item.score)
            if score < min_score:
                continue
            payload = item.payload or {}
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            matches.append({
                "id": str(payload.get("original_id") or item.id),
                "text": str(payload.get("text", "")),
                "metadata": {k: str(v) for k, v in metadata.items()},
                "score": round(score, 4),
            })

        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches

    def close(self) -> None:
        """Release Qdrant resources."""
        try:
            self.store.close()
        except Exception:
            pass

    def count(self) -> int:
        """Return the number of DOM elements stored in the collection."""
        try:
            info = self.store.client.get_collection(self.store.collection_name)
            return info.points_count or 0
        except Exception:
            return 0
