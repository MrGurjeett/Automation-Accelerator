"""DOM agents — initialisation, extraction, and page registration.

These agents handle the DOM Knowledge Base lifecycle.
"""
from __future__ import annotations

import logging
from typing import Any

from pipeline.agents.base import BaseAgent, AgentResult

logger = logging.getLogger(__name__)


class DOMInitAgent(BaseAgent):
    """Initialise AI stack and populate DOM KB if needed."""

    name = "dom_init"
    description = "Initialise AI stack and populate DOM Knowledge Base"

    def run(self, context: dict[str, Any]) -> AgentResult:
        import ai.ai_stats as ai_stats

        force_scan = context.get("force_scan", False)
        config = context.get("_config")
        dom_store = context.get("_dom_store")

        if not config or not dom_store:
            return AgentResult(ok=False, error="AI stack (config, dom_store) required")

        base_url = context.get("base_url", "")
        username = context.get("username", "")
        password = context.get("password", "")

        if force_scan or not dom_store.is_populated():
            if force_scan:
                try:
                    dom_store.clear()
                except Exception as exc:
                    logger.warning("[DOM] Could not clear DOM KB: %s", exc)

            logger.info("[DOM] DOM KB not populated — extracting from %s", base_url)
            from framework.dom_extractor import extract_all_pages

            elements = extract_all_pages(
                base_url=base_url, username=username, password=password,
            )
            dom_store.store_elements(elements)

            pages_scanned = len({e.page_name for e in elements})
            ai_stats.increment("dom_elements", len(elements))
            ai_stats.increment("pages_scanned", pages_scanned)

            return AgentResult(
                ok=True,
                data={
                    "source": "extracted",
                    "element_count": len(elements),
                    "pages_scanned": pages_scanned,
                },
                metrics={
                    "dom_elements": len(elements),
                    "pages_scanned": pages_scanned,
                },
            )
        else:
            cached_count = dom_store.count()
            ai_stats.increment("dom_elements", cached_count)
            return AgentResult(
                ok=True,
                data={"source": "cached", "element_count": cached_count},
                metrics={"dom_elements": cached_count},
            )


class DOMExtractionAgent(BaseAgent):
    """Enrich test-case rows with DOM/RAG locator information."""

    name = "dom_extraction"
    description = "Enrich rows with DOM element locators via RAG resolution"

    def run(self, context: dict[str, Any]) -> AgentResult:
        rows = context.get("rows", [])
        dom_store = context.get("_dom_store")

        if not dom_store:
            return AgentResult(ok=False, error="dom_store required")

        from framework.rag.element_resolver import RAGElementResolver
        from framework.locator_engine import get_best_selector

        resolver = RAGElementResolver(dom_store)
        enriched: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []

        for row in rows:
            page = str(row.get("Page") or "").strip() or None
            target = str(row.get("Target") or "").strip()

            dom_info: dict[str, Any] | None = None
            if target and target != "-":
                resolved = resolver.resolve(target, page_filter=page)
                if resolved is None:
                    unresolved.append({"page": page, "target": target})
                else:
                    selector = get_best_selector(resolved)
                    dom_info = {
                        "original_query": resolved.original_query,
                        "matched_element": resolved.matched_element,
                        "page": resolved.page,
                        "tag": resolved.tag,
                        "score": resolved.score,
                        "selector": selector,
                        "locator_candidates": list(resolved.locator_candidates),
                        "attributes": dict(resolved.attributes),
                    }

            enriched.append({
                "TC_ID": row.get("TC_ID"),
                "Page": row.get("Page"),
                "Action": row.get("Action"),
                "Target": row.get("Target"),
                "Value": row.get("Value"),
                "Expected": row.get("Expected"),
                "dom": dom_info,
            })

        return AgentResult(
            ok=True,
            data={
                "steps": enriched,
                "step_count": len(enriched),
                "unresolved": unresolved,
                "unresolved_count": len(unresolved),
            },
            metrics={
                "enriched": len(enriched),
                "unresolved": len(unresolved),
            },
        )


class PageRegistrationAgent(BaseAgent):
    """Register dynamic pages discovered from the DOM Knowledge Base."""

    name = "page_registration"
    description = "Discover and register dynamic pages from DOM KB"

    def run(self, context: dict[str, Any]) -> AgentResult:
        dom_store = context.get("_dom_store")

        if not dom_store:
            return AgentResult(ok=False, error="dom_store required")

        from pipeline.utils import discover_dom_pages
        from core.pages.page_registry import register_dynamic_pages

        dom_pages = discover_dom_pages(dom_store)
        register_dynamic_pages(dom_pages)

        return AgentResult(
            ok=True,
            data={"pages": sorted(dom_pages), "page_count": len(dom_pages)},
            metrics={"pages_registered": len(dom_pages)},
        )
