"""
Phase 4.3 — MCP-assisted decision making tests.

Covers:
  1. DecisionEngine — decide_next_step, should_retry, enhance_condition
  2. Safe MCP wrapper — response validation, malformed output handling
  3. Deterministic fallback — MCP disabled, unavailable, or low confidence
  4. Retry intelligence — MCP suggests retry/skip
  5. Condition enhancement — MCP override only when explicitly enabled
  6. Pipeline integration — DecisionEngine used in PipelineService
  7. Config support — new flags parse correctly, defaults are backward compatible
  8. Observability — DECISION_TAKEN, RETRY_DECISION events emitted
  9. End-to-end — full pipeline flow with MCP decisions
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pipeline.decision_engine import DecisionEngine, _summarize_context
from pipeline.connectors.base import BaseConnector, ConnectorResult
from pipeline.connectors.registry import ConnectorRegistry
from pipeline.events import EventType, EventManager


# ---------------------------------------------------------------------------
# Mock MCP connector for DecisionEngine tests
# ---------------------------------------------------------------------------

class _DecisionMCPConnector:
    """Mock MCP connector for decision tests."""

    name = "mcp"
    description = "Mock decision MCP"

    def __init__(self, response: dict | None = None, ok: bool = True, connected: bool = True):
        self._response = response
        self._ok = ok
        self._connected = connected
        self._calls: list[dict] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> ConnectorResult:
        return ConnectorResult(ok=True)

    def fetch(self, query: dict[str, Any]) -> ConnectorResult:
        self._calls.append(query)
        if self._ok:
            return ConnectorResult(ok=True, data={"result": self._response})
        return ConnectorResult(ok=False, error="MCP call failed")

    def push(self, data: dict[str, Any]) -> ConnectorResult:
        return self.fetch(data)

    def health_check(self) -> ConnectorResult:
        return ConnectorResult(ok=self._connected)


# Register as virtual subclass of BaseConnector
BaseConnector.register(_DecisionMCPConnector)


def _make_engine(
    mcp_response: dict | None = None,
    mcp_ok: bool = True,
    mcp_connected: bool = True,
    min_confidence: float = 0.5,
    with_events: bool = False,
) -> tuple[DecisionEngine, ConnectorRegistry, EventManager | None]:
    """Create a DecisionEngine with a mock MCP connector."""
    reg = ConnectorRegistry()
    mock = _DecisionMCPConnector(mcp_response, mcp_ok, mcp_connected)
    reg.register("mcp", mock)

    events = EventManager(trace_id="test") if with_events else None
    engine = DecisionEngine(
        connector_registry=reg,
        events=events,
        min_confidence=min_confidence,
    )
    return engine, reg, events


# ===========================================================================
# 1. DecisionEngine.decide_next_step
# ===========================================================================

class TestDecideNextStep:
    """decide_next_step method."""

    def test_single_candidate_returns_immediately(self):
        """No MCP call when only one candidate."""
        engine, reg, _ = _make_engine(mcp_response={"selected_step": "other"})
        result = engine.decide_next_step(
            context={}, current_step="a", candidates=["b"],
        )
        assert result == "b"
        # MCP should NOT have been called
        mcp = reg.get("mcp")
        assert len(mcp._calls) == 0

    def test_empty_candidates_returns_empty(self):
        engine, _, _ = _make_engine()
        result = engine.decide_next_step(context={}, current_step="a", candidates=[])
        assert result == ""

    def test_mcp_selects_valid_candidate(self):
        engine, _, _ = _make_engine(mcp_response={
            "selected_step": "recover",
            "confidence": 0.9,
            "reason": "Error suggests recovery needed",
        })
        result = engine.decide_next_step(
            context={}, current_step="validate",
            candidates=["normalize", "recover"],
        )
        assert result == "recover"

    def test_mcp_low_confidence_falls_back(self):
        engine, _, _ = _make_engine(
            mcp_response={
                "selected_step": "recover",
                "confidence": 0.3,  # Below default 0.5 threshold
            },
            min_confidence=0.5,
        )
        result = engine.decide_next_step(
            context={}, current_step="validate",
            candidates=["normalize", "recover"],
        )
        assert result == "normalize"  # First candidate (deterministic)

    def test_mcp_invalid_step_falls_back(self):
        engine, _, _ = _make_engine(mcp_response={
            "selected_step": "nonexistent_step",
            "confidence": 0.95,
        })
        result = engine.decide_next_step(
            context={}, current_step="validate",
            candidates=["normalize", "recover"],
        )
        assert result == "normalize"  # Deterministic fallback

    def test_mcp_step_not_in_valid_steps(self):
        engine, _, _ = _make_engine(mcp_response={
            "selected_step": "recover",
            "confidence": 0.9,
        })
        result = engine.decide_next_step(
            context={}, current_step="validate",
            candidates=["normalize", "recover"],
            valid_steps={"normalize", "generate"},  # "recover" not valid
        )
        assert result == "normalize"

    def test_mcp_failure_falls_back(self):
        engine, _, _ = _make_engine(mcp_ok=False)
        result = engine.decide_next_step(
            context={}, current_step="validate",
            candidates=["normalize", "recover"],
        )
        assert result == "normalize"

    def test_mcp_disconnected_falls_back(self):
        engine, _, _ = _make_engine(mcp_connected=False)
        result = engine.decide_next_step(
            context={}, current_step="validate",
            candidates=["normalize", "recover"],
        )
        assert result == "normalize"


# ===========================================================================
# 2. Safe MCP wrapper
# ===========================================================================

class TestSafeMCPWrapper:
    """_safe_mcp_decision response validation."""

    def test_valid_dict_response(self):
        engine, _, _ = _make_engine(mcp_response={"selected_step": "a", "confidence": 0.8})
        result = engine._safe_mcp_decision("test", {"key": "val"})
        assert result is not None
        assert result["selected_step"] == "a"
        assert result["confidence"] == 0.8

    def test_non_dict_response_returns_none(self):
        engine, _, _ = _make_engine(mcp_response="not a dict")
        result = engine._safe_mcp_decision("test", {})
        assert result is None

    def test_invalid_confidence_normalized(self):
        engine, _, _ = _make_engine(mcp_response={"confidence": "invalid"})
        result = engine._safe_mcp_decision("test", {})
        assert result is not None
        assert result["confidence"] == 0.0

    def test_none_registry_returns_none(self):
        engine = DecisionEngine(connector_registry=None)
        result = engine._safe_mcp_decision("test", {})
        assert result is None

    def test_no_mcp_in_registry_returns_none(self):
        engine = DecisionEngine(connector_registry=ConnectorRegistry())
        result = engine._safe_mcp_decision("test", {})
        assert result is None

    def test_mcp_exception_returns_none(self):
        """MCP connector that raises should not crash."""
        reg = ConnectorRegistry()
        mock = _DecisionMCPConnector(connected=True)
        # Override fetch to raise
        original_fetch = mock.fetch
        def raising_fetch(query):
            raise RuntimeError("boom")
        mock.fetch = raising_fetch
        reg.register("mcp", mock)

        engine = DecisionEngine(connector_registry=reg)
        result = engine._safe_mcp_decision("test", {})
        assert result is None


# ===========================================================================
# 3. Deterministic fallback
# ===========================================================================

class TestDeterministicFallback:
    """All decisions fall back correctly when MCP is unavailable."""

    def test_decide_without_engine(self):
        engine = DecisionEngine()  # No registry
        result = engine.decide_next_step(
            context={}, current_step="a",
            candidates=["b", "c"],
        )
        assert result == "b"  # First candidate

    def test_retry_without_engine(self):
        engine = DecisionEngine()
        # max_retries=2, attempt=1 → should retry
        assert engine.should_retry({}, "step", "err", attempt=1, max_retries=2) is True
        # attempt=3 > max_retries=2 → should not retry
        assert engine.should_retry({}, "step", "err", attempt=3, max_retries=2) is False

    def test_condition_without_engine(self):
        engine = DecisionEngine()
        # Should return deterministic result unchanged
        assert engine.enhance_condition({}, True, "cond", "step") is True
        assert engine.enhance_condition({}, False, "cond", "step") is False


# ===========================================================================
# 4. Retry intelligence
# ===========================================================================

class TestRetryIntelligence:
    """DecisionEngine.should_retry with MCP."""

    def test_mcp_recommends_retry(self):
        engine, _, _ = _make_engine(mcp_response={
            "retry": True,
            "confidence": 0.85,
            "reason": "Transient network error — retry likely to succeed",
        })
        result = engine.should_retry(
            context={}, step_name="normalize",
            error="Connection timeout", attempt=1, max_retries=0,
        )
        assert result is True

    def test_mcp_recommends_no_retry(self):
        engine, _, _ = _make_engine(mcp_response={
            "retry": False,
            "confidence": 0.9,
            "reason": "Data corruption — retry won't help",
        })
        result = engine.should_retry(
            context={}, step_name="validate",
            error="Schema validation failed", attempt=1, max_retries=2,
        )
        assert result is False

    def test_mcp_low_confidence_uses_deterministic(self):
        engine, _, _ = _make_engine(mcp_response={
            "retry": True,
            "confidence": 0.2,  # Too low
        })
        # Deterministic: attempt=2 > max_retries=1 → no retry
        result = engine.should_retry(
            context={}, step_name="step",
            error="err", attempt=2, max_retries=1,
        )
        assert result is False

    def test_deterministic_retry_logic(self):
        engine, _, _ = _make_engine(mcp_ok=False)
        assert engine.should_retry({}, "s", "e", attempt=1, max_retries=2) is True
        assert engine.should_retry({}, "s", "e", attempt=2, max_retries=2) is True
        assert engine.should_retry({}, "s", "e", attempt=3, max_retries=2) is False


# ===========================================================================
# 5. Condition enhancement
# ===========================================================================

class TestConditionEnhancement:
    """DecisionEngine.enhance_condition with MCP override."""

    def test_mcp_overrides_false_to_true(self):
        engine, _, _ = _make_engine(mcp_response={
            "result": True,
            "confidence": 0.85,
            "reason": "Semantic analysis shows condition should be True",
        })
        result = engine.enhance_condition(
            context={}, condition_result=False,
            condition_expr={"eq": ["$steps.validate.ok", True]},
            step_name="normalize",
        )
        assert result is True

    def test_mcp_overrides_true_to_false(self):
        engine, _, _ = _make_engine(mcp_response={
            "result": False,
            "confidence": 0.9,
            "reason": "Data quality too low despite passing validation",
        })
        result = engine.enhance_condition(
            context={}, condition_result=True,
            condition_expr="$validate.ok == true",
            step_name="normalize",
        )
        assert result is False

    def test_mcp_agrees_with_deterministic(self):
        """When MCP agrees, no override needed."""
        engine, _, _ = _make_engine(mcp_response={
            "result": True,  # Same as deterministic
            "confidence": 0.95,
        })
        result = engine.enhance_condition(
            context={}, condition_result=True,
            condition_expr="cond", step_name="step",
        )
        assert result is True

    def test_mcp_low_confidence_no_override(self):
        engine, _, _ = _make_engine(mcp_response={
            "result": True,
            "confidence": 0.3,
        })
        result = engine.enhance_condition(
            context={}, condition_result=False,
            condition_expr="cond", step_name="step",
        )
        assert result is False  # Keeps deterministic

    def test_mcp_non_bool_result_no_override(self):
        engine, _, _ = _make_engine(mcp_response={
            "result": "maybe",  # Not a bool
            "confidence": 0.9,
        })
        result = engine.enhance_condition(
            context={}, condition_result=False,
            condition_expr="cond", step_name="step",
        )
        assert result is False  # Keeps deterministic


# ===========================================================================
# 6. Pipeline integration
# ===========================================================================

class TestPipelineIntegration:
    """DecisionEngine integration with PipelineService."""

    def test_service_creates_engine_when_enabled(self):
        from pipeline.service import PipelineService
        from pipeline.config import PipelineConfig, PipelineStepConfig

        svc = PipelineService()
        config = PipelineConfig(
            name="test",
            steps=[PipelineStepConfig(name="a")],
            use_mcp_decision=True,
        )
        svc._ensure_decision_engine(config)
        assert svc.decision_engine is not None

    def test_service_no_engine_when_disabled(self):
        from pipeline.service import PipelineService
        from pipeline.config import PipelineConfig, PipelineStepConfig

        svc = PipelineService()
        config = PipelineConfig(
            name="test",
            steps=[PipelineStepConfig(name="a")],
            use_mcp_decision=False,
            use_mcp_retry=False,
            use_mcp_condition=False,
        )
        svc._ensure_decision_engine(config)
        assert svc.decision_engine is None

    def test_service_engine_with_retry(self):
        from pipeline.service import PipelineService
        from pipeline.config import PipelineConfig, PipelineStepConfig

        svc = PipelineService()
        config = PipelineConfig(
            name="test",
            steps=[PipelineStepConfig(name="a")],
            use_mcp_retry=True,
        )
        svc._ensure_decision_engine(config)
        assert svc.decision_engine is not None

    def test_service_engine_with_condition(self):
        from pipeline.service import PipelineService
        from pipeline.config import PipelineConfig, PipelineStepConfig

        svc = PipelineService()
        config = PipelineConfig(
            name="test",
            steps=[PipelineStepConfig(name="a")],
            use_mcp_condition=True,
        )
        svc._ensure_decision_engine(config)
        assert svc.decision_engine is not None


# ===========================================================================
# 7. Config support
# ===========================================================================

class TestConfigSupport:
    """Pipeline config MCP decision flags."""

    def test_default_flags_all_false(self):
        from pipeline.config import PipelineConfig, PipelineStepConfig

        config = PipelineConfig(name="test", steps=[PipelineStepConfig(name="a")])
        assert config.use_mcp_decision is False
        assert config.use_mcp_retry is False
        assert config.use_mcp_condition is False

    def test_parse_with_flags(self):
        from pipeline.config import parse_pipeline_config

        raw = {
            "name": "test",
            "steps": [{"name": "a"}],
            "use_mcp_decision": True,
            "use_mcp_retry": True,
            "use_mcp_condition": True,
        }
        config = parse_pipeline_config(raw)
        assert config.use_mcp_decision is True
        assert config.use_mcp_retry is True
        assert config.use_mcp_condition is True

    def test_parse_without_flags_backward_compatible(self):
        from pipeline.config import parse_pipeline_config

        raw = {"name": "test", "steps": [{"name": "a"}]}
        config = parse_pipeline_config(raw)
        assert config.use_mcp_decision is False
        assert config.use_mcp_retry is False
        assert config.use_mcp_condition is False

    def test_decision_pipeline_config_loads(self):
        from pipeline.config import load_builtin_config

        cfg = load_builtin_config("mcp-decision-pipeline")
        assert cfg.use_mcp_decision is True
        assert cfg.use_mcp_retry is True
        assert cfg.use_mcp_condition is False


# ===========================================================================
# 8. Observability — events
# ===========================================================================

class TestObservability:
    """DECISION_TAKEN and RETRY_DECISION event emission."""

    def test_decision_event_types_exist(self):
        assert hasattr(EventType, "DECISION_TAKEN")
        assert hasattr(EventType, "RETRY_DECISION")
        assert EventType.DECISION_TAKEN.value == "DECISION_TAKEN"
        assert EventType.RETRY_DECISION.value == "RETRY_DECISION"

    def test_decision_taken_event_emitted(self):
        engine, _, events = _make_engine(
            mcp_response={"selected_step": "recover", "confidence": 0.9, "reason": "test"},
            with_events=True,
        )
        engine.decide_next_step(
            context={}, current_step="validate",
            candidates=["normalize", "recover"],
        )

        decision_events = events.get_events(event_type=EventType.DECISION_TAKEN)
        assert len(decision_events) == 1
        e = decision_events[0]
        assert e.metadata["from_step"] == "validate"
        assert e.metadata["selected"] == "recover"
        assert e.metadata["source"] == "mcp"
        assert e.metadata["confidence"] == 0.9

    def test_deterministic_decision_event(self):
        engine, _, events = _make_engine(mcp_ok=False, with_events=True)
        engine.decide_next_step(
            context={}, current_step="validate",
            candidates=["normalize", "recover"],
        )

        decision_events = events.get_events(event_type=EventType.DECISION_TAKEN)
        assert len(decision_events) == 1
        assert decision_events[0].metadata["source"] == "deterministic"

    def test_retry_decision_event_emitted(self):
        engine, _, events = _make_engine(
            mcp_response={"retry": True, "confidence": 0.8, "reason": "transient"},
            with_events=True,
        )
        engine.should_retry(
            context={}, step_name="normalize",
            error="timeout", attempt=1,
        )

        retry_events = events.get_events(event_type=EventType.RETRY_DECISION)
        assert len(retry_events) == 1
        e = retry_events[0]
        assert e.metadata["step"] == "normalize"
        assert e.metadata["retry"] is True
        assert e.metadata["source"] == "mcp"

    def test_no_events_when_no_manager(self):
        """No crash when events=None."""
        engine, _, _ = _make_engine(
            mcp_response={"selected_step": "a", "confidence": 0.9},
        )
        # events is None — should not crash
        engine.decide_next_step(
            context={}, current_step="validate",
            candidates=["a", "b"],
        )


# ===========================================================================
# 9. End-to-end simulation
# ===========================================================================

class TestEndToEnd:
    """Full pipeline flow with MCP decisions."""

    def test_multi_branch_with_mcp_decision(self):
        """Simulate: step completes → MCP selects among candidates."""
        engine, _, events = _make_engine(
            mcp_response={
                "selected_step": "enrich",
                "confidence": 0.88,
                "reason": "Data needs enrichment before validation",
            },
            with_events=True,
        )

        selected = engine.decide_next_step(
            context={"data": [1, 2, 3]},
            current_step="read_excel",
            candidates=["validate", "enrich", "skip_to_generate"],
            valid_steps={"validate", "enrich", "skip_to_generate"},
        )
        assert selected == "enrich"

    def test_recovery_with_retry_then_continue(self):
        """Simulate: fail → retry → fail → continue."""
        # First call: recommend retry
        engine1, _, _ = _make_engine(mcp_response={
            "retry": True, "confidence": 0.8, "reason": "transient",
        })
        should_retry = engine1.should_retry(
            context={}, step_name="normalize",
            error="API timeout", attempt=1,
        )
        assert should_retry is True

        # Second call: do not retry
        engine2, _, _ = _make_engine(mcp_response={
            "retry": False, "confidence": 0.9, "reason": "same error persists",
        })
        should_retry = engine2.should_retry(
            context={}, step_name="normalize",
            error="API timeout", attempt=2,
        )
        assert should_retry is False

    def test_full_flow_deterministic_when_disabled(self):
        """With all flags False, behavior is purely deterministic."""
        engine = DecisionEngine()  # No registry, no events

        # Decisions always return first candidate
        assert engine.decide_next_step({}, "a", ["b", "c"]) == "b"
        # Retry follows max_retries
        assert engine.should_retry({}, "s", "e", 1, 1) is True
        assert engine.should_retry({}, "s", "e", 2, 1) is False
        # Conditions unchanged
        assert engine.enhance_condition({}, True, "c", "s") is True
        assert engine.enhance_condition({}, False, "c", "s") is False


# ===========================================================================
# 10. Context summarization
# ===========================================================================

class TestContextSummarization:
    """_summarize_context helper."""

    def test_strips_private_keys(self):
        ctx = {"public": "yes", "_private": "no", "_connector_registry": "strip"}
        result = _summarize_context(ctx)
        assert "public" in result
        assert "_private" not in result

    def test_includes_step_results(self):
        class FakeResult:
            ok = True
            error = None

        results_map = {"validate": FakeResult()}
        result = _summarize_context({}, results_map)
        assert "_step_results" in result
        assert result["_step_results"]["validate"]["ok"] is True

    def test_handles_large_values(self):
        ctx = {"big": list(range(1000))}
        result = _summarize_context(ctx)
        assert isinstance(result["big"], str)  # Converted to type name


# ===========================================================================
# 11. No existing behavior breakage
# ===========================================================================

class TestNoBreakage:
    """Verify existing pipeline behavior is unchanged."""

    def test_phase35_conditions_still_work(self):
        """Structured conditions still evaluate correctly."""
        from pipeline.conditions import evaluate_condition

        results = {
            "validate": type("SR", (), {"ok": True, "data": {"count": 5}, "error": None})(),
        }
        assert evaluate_condition({"eq": ["$steps.validate.ok", True]}, results, {}) is True
        assert evaluate_condition({"gt": ["$steps.validate.data.count", 3]}, results, {}) is True

    def test_phase4a_connectors_still_work(self):
        """Connector registry still functional."""
        reg = ConnectorRegistry()
        assert len(reg) == 0
        assert reg.names == []

    def test_event_types_complete(self):
        """All expected event types exist."""
        expected = [
            "PIPELINE_STARTED", "PIPELINE_COMPLETED", "PIPELINE_FAILED",
            "STEP_STARTED", "STEP_COMPLETED", "STEP_FAILED", "STEP_SKIPPED",
            "BRANCH_TAKEN", "DECISION_TAKEN", "RETRY_DECISION",
            "AGENT_STARTED", "AGENT_COMPLETED", "ERROR_OCCURRED",
        ]
        for name in expected:
            assert hasattr(EventType, name), f"Missing EventType.{name}"
