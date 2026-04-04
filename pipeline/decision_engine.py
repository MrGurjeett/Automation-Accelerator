"""
DecisionEngine — MCP-assisted decision making for the pipeline.

Phase 4.3 — provides optional MCP-powered intelligence for pipeline
decisions WITHOUT replacing deterministic control.

CRITICAL RULE: MCP can ADVISE decisions, NOT control the pipeline.
PipelineService remains the final decision authority.

The DecisionEngine wraps all MCP decision calls safely:
  - Strict timeout (default 5s — decisions must be fast)
  - Response validation (format, step existence, confidence)
  - Fallback to deterministic logic on any failure
  - No blocking behavior — always returns a valid decision
  - Observability via event emission

Usage::

    engine = DecisionEngine(connector_registry=reg, events=event_manager)

    # Multi-branch decision
    selected = engine.decide_next_step(
        context=ctx,
        current_step="validate",
        candidates=["normalize", "recover", "skip_to_generate"],
        results_map=results_map,
    )

    # Retry decision
    should_retry = engine.should_retry(
        context=ctx,
        step_name="normalize",
        error="API rate limit exceeded",
        attempt=1,
    )

    # Condition enhancement (only when explicitly enabled)
    final = engine.enhance_condition(
        context=ctx,
        condition_result=False,
        condition_expr={"eq": ["$steps.validate.ok", True]},
        step_name="normalize",
    )
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Decision timeout — must be short to avoid blocking the pipeline
_DECISION_TIMEOUT = 5.0  # seconds
_MIN_CONFIDENCE = 0.5  # minimum MCP confidence to accept a decision


class DecisionEngine:
    """Optional MCP-assisted decision evaluator for the pipeline.

    The engine provides three decision capabilities:
      1. **decide_next_step** — select among multiple candidate steps
      2. **should_retry** — decide whether to retry a failed step
      3. **enhance_condition** — optionally override condition results

    All methods follow the same safety contract:
      - If MCP is unavailable/fails → return deterministic default
      - If MCP response is malformed → return deterministic default
      - If MCP confidence is too low → return deterministic default
      - Never block, never crash, always return a valid result

    Parameters
    ----------
    connector_registry : ConnectorRegistry or None
        Registry to look up the MCP connector.  If None, all decisions
        are deterministic.
    events : EventManager or None
        Event manager for emitting DECISION_TAKEN / RETRY_DECISION events.
    decision_timeout : float
        Timeout for MCP decision calls (default: 5s).
    min_confidence : float
        Minimum confidence (0.0-1.0) to accept an MCP decision.
    """

    def __init__(
        self,
        connector_registry: Any = None,
        events: Any = None,
        decision_timeout: float = _DECISION_TIMEOUT,
        min_confidence: float = _MIN_CONFIDENCE,
    ) -> None:
        self._registry = connector_registry
        self._events = events
        self._timeout = decision_timeout
        self._min_confidence = min_confidence

    # ------------------------------------------------------------------
    # 1. decide_next_step
    # ------------------------------------------------------------------

    def decide_next_step(
        self,
        context: dict[str, Any],
        current_step: str,
        candidates: list[str],
        results_map: dict[str, Any] | None = None,
        *,
        valid_steps: set[str] | None = None,
    ) -> str:
        """Select the next step from a list of candidates.

        This method is ONLY called when there are multiple viable paths
        (e.g., both on_success_step and a linear next step exist, or
        a recovery scenario with multiple options).

        Parameters
        ----------
        context : dict
            Current pipeline execution context.
        current_step : str
            The step that just completed.
        candidates : list[str]
            Ordered list of possible next steps.  The first candidate
            is the deterministic default.
        results_map : dict or None
            Map of step_name → StepResult for reference.
        valid_steps : set[str] or None
            Set of valid step names in the config.  Used to validate
            MCP's recommendation.

        Returns
        -------
        str
            The selected step name (always from candidates).
        """
        if not candidates:
            return ""

        # Deterministic default: first candidate
        deterministic = candidates[0]

        # Single candidate — no decision needed
        if len(candidates) <= 1:
            return deterministic

        # Try MCP-assisted decision
        mcp_result = self._safe_mcp_decision(
            task="decide_next_step",
            arguments={
                "current_step": current_step,
                "candidates": candidates,
                "context_summary": _summarize_context(context, results_map),
            },
        )

        if mcp_result is not None:
            selected = mcp_result.get("selected_step", "")
            confidence = float(mcp_result.get("confidence", 0.0))
            reason = mcp_result.get("reason", "")

            # Validate: must be in candidates AND meet confidence threshold
            if selected in candidates and confidence >= self._min_confidence:
                # Additional check: must be in valid_steps if provided
                if valid_steps is None or selected in valid_steps:
                    self._emit_decision_event(
                        from_step=current_step,
                        candidates=candidates,
                        selected=selected,
                        source="mcp",
                        confidence=confidence,
                        reason=reason,
                    )
                    logger.info(
                        "[DecisionEngine] MCP selected '%s' (confidence=%.2f): %s",
                        selected, confidence, reason,
                    )
                    return selected
                else:
                    logger.warning(
                        "[DecisionEngine] MCP selected '%s' but not in valid_steps — using deterministic",
                        selected,
                    )
            else:
                if selected and selected not in candidates:
                    logger.warning(
                        "[DecisionEngine] MCP selected '%s' not in candidates %s — using deterministic",
                        selected, candidates,
                    )
                elif confidence < self._min_confidence:
                    logger.info(
                        "[DecisionEngine] MCP confidence %.2f < %.2f — using deterministic",
                        confidence, self._min_confidence,
                    )

        # Fallback to deterministic
        self._emit_decision_event(
            from_step=current_step,
            candidates=candidates,
            selected=deterministic,
            source="deterministic",
        )
        return deterministic

    # ------------------------------------------------------------------
    # 2. should_retry
    # ------------------------------------------------------------------

    def should_retry(
        self,
        context: dict[str, Any],
        step_name: str,
        error: str,
        attempt: int = 1,
        max_retries: int = 0,
        *,
        results_map: dict[str, Any] | None = None,
    ) -> bool:
        """Decide whether to retry a failed step.

        Parameters
        ----------
        context : dict
            Current pipeline context.
        step_name : str
            The step that failed.
        error : str
            The error message.
        attempt : int
            Current attempt number (1-based).
        max_retries : int
            Maximum retries allowed by config (0 = no retries).

        Returns
        -------
        bool
            True if the step should be retried.
        """
        # Deterministic default: retry if under max_retries
        deterministic = attempt <= max_retries

        # Try MCP-assisted retry decision
        mcp_result = self._safe_mcp_decision(
            task="should_retry",
            arguments={
                "step_name": step_name,
                "error": error,
                "attempt": attempt,
                "max_retries": max_retries,
                "context_summary": _summarize_context(context, results_map),
            },
        )

        if mcp_result is not None:
            mcp_retry = bool(mcp_result.get("retry", False))
            confidence = float(mcp_result.get("confidence", 0.0))
            reason = mcp_result.get("reason", "")

            if confidence >= self._min_confidence:
                self._emit_retry_event(
                    step_name=step_name,
                    retry=mcp_retry,
                    source="mcp",
                    confidence=confidence,
                    reason=reason,
                    attempt=attempt,
                )
                logger.info(
                    "[DecisionEngine] MCP retry=%s for '%s' (confidence=%.2f): %s",
                    mcp_retry, step_name, confidence, reason,
                )
                return mcp_retry

        # Fallback
        self._emit_retry_event(
            step_name=step_name,
            retry=deterministic,
            source="deterministic",
            attempt=attempt,
        )
        return deterministic

    # ------------------------------------------------------------------
    # 3. enhance_condition
    # ------------------------------------------------------------------

    def enhance_condition(
        self,
        context: dict[str, Any],
        condition_result: bool,
        condition_expr: Any,
        step_name: str,
        *,
        results_map: dict[str, Any] | None = None,
    ) -> bool:
        """Optionally enhance a condition evaluation with MCP insight.

        RULE: This is only called when ``use_mcp_condition=True`` is
        explicitly set in the pipeline config.  The deterministic result
        is always the primary answer.

        Parameters
        ----------
        context : dict
            Current pipeline context.
        condition_result : bool
            The deterministic condition evaluation result.
        condition_expr : Any
            The original condition expression (for MCP context).
        step_name : str
            The step being evaluated.

        Returns
        -------
        bool
            The final condition result (may differ from deterministic).
        """
        # Try MCP enhancement
        mcp_result = self._safe_mcp_decision(
            task="enhance_condition",
            arguments={
                "step_name": step_name,
                "condition": str(condition_expr),
                "deterministic_result": condition_result,
                "context_summary": _summarize_context(context, results_map),
            },
        )

        if mcp_result is not None:
            mcp_override = mcp_result.get("result")
            confidence = float(mcp_result.get("confidence", 0.0))
            reason = mcp_result.get("reason", "")

            if (
                isinstance(mcp_override, bool)
                and mcp_override != condition_result
                and confidence >= self._min_confidence
            ):
                logger.info(
                    "[DecisionEngine] MCP overrides condition for '%s': %s → %s (confidence=%.2f): %s",
                    step_name, condition_result, mcp_override, confidence, reason,
                )
                return mcp_override

        return condition_result

    # ------------------------------------------------------------------
    # GROUP 2 — Safe MCP decision wrapper
    # ------------------------------------------------------------------

    def _safe_mcp_decision(
        self,
        task: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Call MCP for a decision, with full safety wrapping.

        Returns the parsed MCP response dict, or None if:
          - MCP connector not available
          - MCP call fails
          - Response is malformed
          - Timeout exceeded

        Expected MCP response format::

            {
                "selected_step": "step_name",  # for decide_next_step
                "retry": true/false,           # for should_retry
                "result": true/false,          # for enhance_condition
                "confidence": 0.0-1.0,
                "reason": "explanation"
            }
        """
        if self._registry is None:
            return None

        mcp = self._registry.get("mcp")
        if mcp is None or not mcp.is_connected:
            return None

        try:
            t0 = time.monotonic()
            result = mcp.fetch({
                "type": "tool_call",
                "tool": "pipeline_decision",
                "arguments": {
                    "task": task,
                    **arguments,
                },
                "timeout": self._timeout,
            })
            elapsed = time.monotonic() - t0

            if not result.ok:
                logger.debug(
                    "[DecisionEngine] MCP decision '%s' failed (%.1fms): %s",
                    task, elapsed * 1000, result.error,
                )
                return None

            # Extract and validate the response
            mcp_data = result.data.get("result", {})

            if not isinstance(mcp_data, dict):
                logger.debug(
                    "[DecisionEngine] MCP decision '%s' returned non-dict: %s",
                    task, type(mcp_data).__name__,
                )
                return None

            # Validate confidence is numeric
            confidence = mcp_data.get("confidence")
            if confidence is not None:
                try:
                    mcp_data["confidence"] = float(confidence)
                except (ValueError, TypeError):
                    mcp_data["confidence"] = 0.0

            logger.debug(
                "[DecisionEngine] MCP decision '%s' received (%.1fms): %s",
                task, elapsed * 1000, mcp_data,
            )
            return mcp_data

        except Exception as exc:
            logger.warning(
                "[DecisionEngine] MCP decision '%s' error: %s",
                task, exc,
            )
            return None

    # ------------------------------------------------------------------
    # GROUP 7 — Observability
    # ------------------------------------------------------------------

    def _emit_decision_event(
        self,
        from_step: str,
        candidates: list[str],
        selected: str,
        source: str,
        confidence: float = 0.0,
        reason: str = "",
    ) -> None:
        """Emit a DECISION_TAKEN event."""
        if self._events is None:
            return

        try:
            from pipeline.events import EventType
            metadata: dict[str, Any] = {
                "from_step": from_step,
                "candidates": candidates,
                "selected": selected,
                "source": source,
            }
            if confidence:
                metadata["confidence"] = round(confidence, 3)
            if reason:
                metadata["reason"] = reason

            self._events.emit(
                EventType.DECISION_TAKEN,
                step_name=from_step,
                metadata=metadata,
            )
        except Exception:
            pass  # Never let event emission break decisions

    def _emit_retry_event(
        self,
        step_name: str,
        retry: bool,
        source: str,
        confidence: float = 0.0,
        reason: str = "",
        attempt: int = 0,
    ) -> None:
        """Emit a RETRY_DECISION event."""
        if self._events is None:
            return

        try:
            from pipeline.events import EventType
            metadata: dict[str, Any] = {
                "step": step_name,
                "retry": retry,
                "source": source,
                "attempt": attempt,
            }
            if confidence:
                metadata["confidence"] = round(confidence, 3)
            if reason:
                metadata["reason"] = reason

            self._events.emit(
                EventType.RETRY_DECISION,
                step_name=step_name,
                metadata=metadata,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarize_context(
    context: dict[str, Any],
    results_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact summary for MCP decision context.

    Strips private keys, limits size, includes step result summaries.
    """
    summary: dict[str, Any] = {}

    # Include non-private context keys (limited)
    for k, v in context.items():
        if isinstance(k, str) and k.startswith("_"):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            summary[k] = v
        elif isinstance(v, dict) and len(str(v)) < 500:
            summary[k] = v
        else:
            summary[k] = f"<{type(v).__name__}>"

    # Include step result summaries
    if results_map:
        steps_summary = {}
        for name, sr in results_map.items():
            steps_summary[name] = {
                "ok": getattr(sr, "ok", None),
                "error": getattr(sr, "error", None),
            }
        summary["_step_results"] = steps_summary

    return summary
