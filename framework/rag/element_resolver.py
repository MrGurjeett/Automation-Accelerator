"""
RAG Element Resolver — resolves Excel target names to actual DOM elements.

Input:  Excel target name (e.g., "Submit Button")
Process:
  1. Embed query
  2. Search Qdrant DOM knowledge base
  3. Retrieve best matching UI element

Output: Best matching DOM element with locator information.

Example:
    "Submit Button" → Login Button → [data-test="login-button"] or input[value='Log In']
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, List

from framework.vector_store.qdrant_client import DOMVectorStore
import ai.ai_stats as ai_stats

logger = logging.getLogger(__name__)
ai_logger = logging.getLogger("ai_reasoning")


@dataclass
class ResolvedElement:
    """Result of RAG element resolution."""
    original_query: str
    matched_element: str
    page: str
    tag: str
    score: float
    locator_candidates: List[str]
    attributes: dict


class RAGElementResolver:
    """Resolves Excel target names to DOM elements via Qdrant similarity search."""

    def __init__(self, dom_store: DOMVectorStore) -> None:
        self.dom_store = dom_store
        self._cache: dict[str, Optional[ResolvedElement]] = {}

    def resolve(
        self,
        target: str,
        page_filter: Optional[str] = None,
        min_score: float = 0.3,
    ) -> Optional[ResolvedElement]:
        """Resolve an Excel target name to the best matching DOM element.

        Parameters
        ----------
        target : str
            The target name from Excel (e.g., "Submit Button", "Username").
        page_filter : str, optional
            If given, prefer elements from this page.
        min_score : float
            Minimum similarity score to accept a match.

        Returns
        -------
        ResolvedElement or None
            Best matching element, or None if no match above threshold.
        """
        cache_key = f"{target}:{page_filter or ''}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if cached:
                logger.info(
                    "[RAG] Cache hit for '%s' → '%s' (score: %.2f)",
                    target, cached.matched_element, cached.score,
                )
            return cached

        logger.info("[RAG] Searching element for '%s'…", target)
        ai_logger.info("")
        ai_logger.info("[RAG] Searching element: %s", target)

        # Try page-filtered search first (with lower threshold), then fall back to unfiltered
        page_min = min(min_score, 0.15) if page_filter else min_score
        results = self.dom_store.search(
            target, top_k=10, min_score=page_min, page_filter=page_filter,
        )
        if not results and page_filter:
            logger.info("[RAG] No page-filtered results for '%s', trying all pages", target)
            results = self.dom_store.search(target, top_k=10, min_score=min_score)

        if not results:
            logger.warning("[RAG] No match found for '%s'", target)
            self._cache[cache_key] = None
            return None

        # Pick the best result (already page-filtered at search level)
        best = None
        for r in results:
            meta = r.get("metadata", {})
            element_name = meta.get("element_name", "")
            page = meta.get("page", "")
            tag = meta.get("tag", "")
            locator_str = meta.get("locator_candidates", "")
            locators = [l.strip() for l in locator_str.split("|") if l.strip()]

            candidate = ResolvedElement(
                original_query=target,
                matched_element=element_name,
                page=page,
                tag=tag,
                score=r["score"],
                locator_candidates=locators,
                attributes={k: v for k, v in meta.items()
                            if k not in ("element_name", "page", "tag",
                                         "locator_candidates", "type")},
            )

            if best is None:
                best = candidate
                break

        if best:
            logger.info(
                "[RAG] Match found: '%s' → '%s' (page: %s, score: %.2f)",
                target, best.matched_element, best.page, best.score,
            )
            ai_logger.info("[RAG] Top match: %s (similarity %.2f)", best.matched_element, best.score)
            if best.locator_candidates:
                ai_logger.info("[LOCATOR] Generated selector: %s", best.locator_candidates[0])
            ai_stats.increment("rag_resolutions")
        else:
            logger.warning("[RAG] No suitable match for '%s' above threshold", target)
            ai_logger.info("[RAG] No match found above threshold for '%s'", target)

        self._cache[cache_key] = best
        return best

    def resolve_batch(
        self,
        targets: List[str],
        page_filter: Optional[str] = None,
    ) -> dict[str, Optional[ResolvedElement]]:
        """Resolve multiple targets. Returns dict of target → resolved element."""
        return {t: self.resolve(t, page_filter) for t in targets}
