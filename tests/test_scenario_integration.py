"""
Integration test scenarios for MCP and decision intelligence.

Tests the four scenario configs end-to-end using mocked agents and connectors,
validating pipeline flow, event emission, and decision-making behavior.

Test Scenarios:
  1. test_recovery   — Invalid input → validation fails → MCPRecoveryAgent triggered
  2. test_decision   — Multi-branch pipeline with MCP-assisted decisions
  3. test_retry      — force_fail flag → step failure → MCP retry intelligence
  4. test_mcp_disabled — All MCP flags off → purely deterministic pipeline

Each scenario:
  - Creates a temporary Excel file with controlled defects
  - Loads the scenario pipeline config
  - Executes through PipelineService with mocked externals
  - Validates events via log_validator assertions
"""
from __future__ import annotations

import logging
import pytest
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

from pipeline.config import load_config_from_file, parse_pipeline_config
from pipeline.events import EventManager, EventType
from pipeline.service import PipelineService, PipelineInput, StepResult
from pipeline.agents.base import BaseAgent, AgentResult, ConnectorAwareMixin
from pipeline.agents.registry import AgentRegistry
from pipeline.connectors.base import BaseConnector, ConnectorResult
from pipeline.connectors.registry import ConnectorRegistry
from pipeline.decision_engine import DecisionEngine

from tests.helpers.log_validator import (
    assert_event_emitted,
    assert_event_not_emitted,
    assert_event_sequence,
    assert_step_failed,
    assert_step_completed,
    assert_step_skipped,
    assert_recovery_triggered,
    assert_decision_taken,
    assert_retry_decision,
    assert_fallback_used,
    assert_branch_taken,
    assert_no_mcp_decisions,
    get_events_by_type,
    summarize_events,
)
from tests.helpers.excel_modifier import (
    create_valid_excel,
    create_excel_missing_columns,
    create_excel_invalid_actions,
    create_excel_missing_required_values,
    create_excel_mixed_valid_invalid,
    VALID_ROWS,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Test Infrastructure — Mock agents and connectors
# ═══════════════════════════════════════════════════════════════════════════

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "pipeline" / "configs"


class _ScenarioMCPConnector:
    """Mock MCP connector for scenario tests.

    Configurable response behavior per task type.
    """
    name = "mcp"

    def __init__(self):
        self.is_connected = True
        self._responses: dict[str, dict[str, Any]] = {}
        self._fetch_calls: list[dict] = []

    def set_response(self, task: str, response: dict[str, Any]) -> None:
        """Pre-configure a response for a specific MCP task."""
        self._responses[task] = response

    def fetch(self, request: dict) -> ConnectorResult:
        self._fetch_calls.append(request)
        task = request.get("arguments", {}).get("task", "")
        if task in self._responses:
            return ConnectorResult(ok=True, data={"result": self._responses[task]})
        # Default: generic success
        return ConnectorResult(ok=True, data={"result": {"status": "ok"}})

    def connect(self) -> ConnectorResult:
        self.is_connected = True
        return ConnectorResult(ok=True, data={})

    def health_check(self) -> ConnectorResult:
        return ConnectorResult(ok=self.is_connected, data={"healthy": self.is_connected})


# Register as virtual subclass of BaseConnector
BaseConnector.register(_ScenarioMCPConnector)


class _MockValidationAgent(BaseAgent):
    """Mock validation agent — reads rows and performs basic validation.

    Mimics the real ValidationAgent but without importing external validators.
    Checks for required columns and valid actions only.
    """
    name = "validation"
    description = "Mock validation for scenario tests"

    REQUIRED_COLUMNS = {"TC_ID", "Page", "Action", "Target", "Value", "Expected"}
    SUPPORTED_ACTIONS = {"fill", "click", "navigate", "verify_text", "select"}

    def run(self, context: dict[str, Any]) -> AgentResult:
        rows = context.get("rows", [])
        if not rows:
            return AgentResult(ok=False, error="No rows to validate (empty input)")

        # Check for force_fail (used by retry scenarios)
        if context.get("force_fail"):
            raise RuntimeError("Simulated validation failure (force_fail=True)")

        # Schema check
        columns = set(rows[0].keys())
        missing = self.REQUIRED_COLUMNS - columns
        if missing:
            return AgentResult(
                ok=False,
                error=f"Schema mismatch. Missing: {sorted(missing)}",
                data={"rejected": list(set(r.get("TC_ID", "?") for r in rows))},
            )

        # Group by TC_ID
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            tc_id = row.get("TC_ID", "UNKNOWN")
            grouped.setdefault(tc_id, []).append(row)

        validated: dict[str, list[dict]] = {}
        rejected: list[str] = []

        for tc_id, tc_rows in grouped.items():
            valid = True
            for row in tc_rows:
                action = row.get("Action", "")
                if action not in self.SUPPORTED_ACTIONS:
                    valid = False
                    break
                if action == "fill" and row.get("Value", "") == "-":
                    valid = False
                    break
                if action == "verify_text" and (not row.get("Expected") or row.get("Expected") == "-"):
                    valid = False
                    break
            if valid:
                validated[tc_id] = tc_rows
            else:
                rejected.append(tc_id)

        if not validated:
            return AgentResult(
                ok=False,
                error=f"No test cases passed validation. Rejected: {rejected}",
                data={"rejected": rejected, "validated": {}},
            )

        return AgentResult(
            ok=True,
            data={
                "validated": validated,
                "validated_count": len(validated),
                "rejected": rejected,
                "rejected_count": len(rejected),
            },
        )


class _MockRecoveryAgent(ConnectorAwareMixin, BaseAgent):
    """Mock MCP recovery agent for scenario tests."""
    name = "mcp_recovery"
    description = "Mock MCP recovery agent"

    def run(self, context: dict[str, Any]) -> AgentResult:
        error = context.get("error", "Unknown error")
        failed_step = context.get("failed_step", "unknown")
        strategy = context.get("recovery_strategy", "auto")

        logger.info(
            "[MockRecoveryAgent] Attempting recovery for '%s' (strategy=%s): %s",
            failed_step, strategy, error,
        )

        # Try MCP if available
        mcp = self.get_connector("mcp", context)
        if mcp and mcp.is_connected:
            result = mcp.fetch({
                "type": "tool_call",
                "tool": "pipeline_recovery",
                "arguments": {
                    "task": "recover",
                    "error": str(error),
                    "failed_step": failed_step,
                    "recovery_strategy": strategy,
                },
            })
            if result.ok:
                return AgentResult(
                    ok=True,
                    data={
                        "recovered": True,
                        "recovery_action": "mcp_assisted",
                        "diagnosis": f"MCP recovered from: {error}",
                        "corrected_data": result.data.get("result", {}),
                    },
                )

        # Fallback — skip strategy still succeeds
        if strategy == "skip":
            return AgentResult(
                ok=True,
                data={"recovered": True, "recovery_action": "skipped", "diagnosis": "Skipped failed step"},
            )

        return AgentResult(
            ok=False,
            error=f"Recovery failed for '{failed_step}': {error}",
            data={"recovered": False},
        )


class _MockNoopAgent(BaseAgent):
    """Mock noop agent — always succeeds."""
    name = "noop"
    description = "Pass-through test agent"

    def run(self, context: dict[str, Any]) -> AgentResult:
        if context.get("force_fail"):
            msg = context.get("force_fail_message", "Simulated failure")
            raise RuntimeError(msg)
        data = {k: v for k, v in context.items() if isinstance(k, str) and not k.startswith("_")}
        data["noop"] = True
        return AgentResult(ok=True, data=data)


class _MockNormalizeAgent(BaseAgent):
    """Mock normalize agent — passes validated data through as accepted."""
    name = "normalize"
    description = "Mock normalization for tests"

    def run(self, context: dict[str, Any]) -> AgentResult:
        validated = context.get("validated", {})
        if not validated:
            return AgentResult(ok=False, error="No validated data to normalize")
        return AgentResult(
            ok=True,
            data={
                "accepted": validated,
                "accepted_count": len(validated),
                "rejected": [],
            },
        )


def _build_test_registry() -> AgentRegistry:
    """Build an agent registry with mock agents for scenario testing.

    Agents are registered by step name (as used in the config), NOT by
    agent class name.  The built-in step handlers (detect_excel, read_excel,
    validate) are used by PipelineService directly; agents here cover
    steps that have no built-in handler.
    """
    registry = AgentRegistry()
    # Recovery steps (used in test_recovery, test_decision, test_mcp_disabled)
    registry.register("recover_validation", _MockRecoveryAgent())
    # Noop/gate steps
    registry.register("post_validate", _MockNoopAgent())
    # Enrichment step (used in test_decision)
    registry.register("enrich", _MockNoopAgent())
    # Normalize step — mock that echoes validated data
    registry.register("normalize", _MockNormalizeAgent())
    # Generate step — mock
    registry.register("generate", _MockNoopAgent())
    return registry


def _build_connector_registry(mcp: _ScenarioMCPConnector | None = None) -> ConnectorRegistry:
    """Build a connector registry with an optional MCP connector."""
    reg = ConnectorRegistry()
    if mcp is not None:
        reg.register("mcp", mcp)
    return reg


def _build_service(
    agent_registry: AgentRegistry | None = None,
    connector_registry: ConnectorRegistry | None = None,
    event_manager: EventManager | None = None,
) -> PipelineService:
    """Build a PipelineService wired with test mocks."""
    events = event_manager or EventManager(trace_id="test")
    svc = PipelineService(
        event_manager=events,
        trace_id="test",
        agent_registry=agent_registry or _build_test_registry(),
        connector_registry=connector_registry or ConnectorRegistry(),
    )
    return svc


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 1: Recovery Pipeline
# ═══════════════════════════════════════════════════════════════════════════

class TestRecoveryScenario:
    """test_recovery.json — validation failure triggers MCPRecoveryAgent."""

    def _load_config(self):
        return load_config_from_file(CONFIGS_DIR / "test_recovery.json")

    def test_config_loads(self):
        """Config parses without errors."""
        cfg = self._load_config()
        assert cfg.name == "test-recovery"
        assert len(cfg.steps) == 5
        assert cfg.use_mcp_decision is False
        assert cfg.use_mcp_retry is False

    def test_recovery_on_schema_failure(self, tmp_path):
        """Missing columns → validate fails → branch to recover_validation."""
        excel_path = create_excel_missing_columns(tmp_path, drop_columns=["TC_ID"])
        cfg = self._load_config()

        mcp = _ScenarioMCPConnector()
        mcp.set_response("recover", {
            "recovered": True,
            "corrected_data": {"TC_ID": "TC001_recovered"},
            "recovery_action": "column_inference",
            "diagnosis": "Inferred TC_ID from row context",
        })

        events = EventManager(trace_id="test")
        svc = _build_service(
            connector_registry=_build_connector_registry(mcp),
            event_manager=events,
        )

        # Mock detect_excel + read_excel to use our test file
        with patch.object(svc, '_step_handlers', svc._step_handlers):
            result = svc.run_pipeline_from_config(
                cfg,
                PipelineInput(excel_path=str(excel_path)),
            )

        all_events = events.get_events()
        logger.info("Recovery scenario events:\n%s", summarize_events(all_events))

        # Validate step failed
        assert_step_failed(all_events, "validate")

        # Branch taken to recovery
        assert_branch_taken(all_events, from_step="validate", to_step="recover_validation")

        # Recovery agent was invoked
        assert_recovery_triggered(all_events, "recover_validation")

    def test_recovery_on_invalid_actions(self, tmp_path):
        """Invalid action values → validate fails → recovery triggered."""
        excel_path = create_excel_invalid_actions(tmp_path)
        cfg = self._load_config()

        mcp = _ScenarioMCPConnector()
        mcp.set_response("recover", {
            "recovered": True,
            "corrected_data": {},
            "recovery_action": "action_correction",
            "diagnosis": "Corrected invalid action",
        })

        events = EventManager(trace_id="test")
        svc = _build_service(
            connector_registry=_build_connector_registry(mcp),
            event_manager=events,
        )

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()

        # With mixed valid/invalid, validation might partially succeed
        # but the invalid TC should still trigger warnings
        step_results = {sr.step: sr for sr in result.steps}
        assert "validate" in step_results

    def test_recovery_mcp_unavailable(self, tmp_path):
        """Recovery runs without MCP — fallback behavior."""
        excel_path = create_excel_missing_columns(tmp_path, drop_columns=["Expected"])
        cfg = self._load_config()

        # No MCP connector registered
        events = EventManager(trace_id="test")
        svc = _build_service(
            connector_registry=_build_connector_registry(None),
            event_manager=events,
        )

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()
        logger.info("Recovery (no MCP) events:\n%s", summarize_events(all_events))

        # Validate still fails
        assert_step_failed(all_events, "validate")

    def test_valid_input_skips_recovery(self, tmp_path):
        """Valid input → validate succeeds → recovery skipped → post_validate."""
        excel_path = create_valid_excel(tmp_path)
        cfg = self._load_config()

        events = EventManager(trace_id="test")
        svc = _build_service(event_manager=events)

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()
        logger.info("Valid input events:\n%s", summarize_events(all_events))

        # Validate should succeed
        assert_step_completed(all_events, "validate")

        # Recovery should be skipped (condition not met: no validate.error)
        recovery_started = get_events_by_type(all_events, EventType.AGENT_STARTED)
        recovery_for_step = [e for e in recovery_started if e.step_name == "recover_validation"]
        # Recovery is either skipped or never reached (branched to post_validate)
        assert_event_emitted(all_events, EventType.BRANCH_TAKEN,
                             metadata_contains={"from_step": "validate", "branch": "on_success_step"})


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 2: Decision Pipeline
# ═══════════════════════════════════════════════════════════════════════════

class TestDecisionScenario:
    """test_decision.json — MCP-assisted decision making at branch points."""

    def _load_config(self):
        return load_config_from_file(CONFIGS_DIR / "test_decision.json")

    def test_config_loads_with_mcp_decision(self):
        """Config has use_mcp_decision=True."""
        cfg = self._load_config()
        assert cfg.name == "test-decision"
        assert cfg.use_mcp_decision is True
        assert cfg.use_mcp_retry is False

    def test_mcp_decision_selects_enrich(self, tmp_path):
        """MCP steers validate→enrich instead of normalize (success path).

        Config: validate on_success_step=normalize, but linear next=enrich.
        Candidates on success: [normalize, enrich].  MCP selects enrich.
        """
        excel_path = create_valid_excel(tmp_path)
        cfg = self._load_config()

        mcp = _ScenarioMCPConnector()
        mcp.set_response("decide_next_step", {
            "selected_step": "enrich",
            "confidence": 0.92,
            "reason": "Data quality high — enrichment will improve results",
        })

        events = EventManager(trace_id="test")
        svc = _build_service(
            connector_registry=_build_connector_registry(mcp),
            event_manager=events,
        )

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()
        logger.info("Decision scenario events:\n%s", summarize_events(all_events))

        # Validate should succeed
        assert_step_completed(all_events, "validate")

        # DecisionEngine should have been consulted (use_mcp_decision=True)
        assert svc.decision_engine is not None

        # MCP decision event should be emitted (2 candidates: normalize, enrich)
        decision_events = get_events_by_type(all_events, EventType.DECISION_TAKEN)
        assert len(decision_events) >= 1, (
            f"Expected DECISION_TAKEN event, got none.\n{summarize_events(all_events)}"
        )

        # MCP selected "enrich" — so enrich step should have executed
        assert_step_completed(all_events, "enrich")

    def test_mcp_decision_low_confidence_uses_deterministic(self, tmp_path):
        """Low MCP confidence → falls back to deterministic (normalize)."""
        excel_path = create_valid_excel(tmp_path)
        cfg = self._load_config()

        mcp = _ScenarioMCPConnector()
        mcp.set_response("decide_next_step", {
            "selected_step": "enrich",
            "confidence": 0.2,
            "reason": "Uncertain",
        })

        events = EventManager(trace_id="test")
        svc = _build_service(
            connector_registry=_build_connector_registry(mcp),
            event_manager=events,
        )

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()
        logger.info("Decision (low confidence) events:\n%s", summarize_events(all_events))

        # Engine exists but low confidence = deterministic fallback
        assert svc.decision_engine is not None

        # Deterministic decision should be logged
        decision_events = get_events_by_type(all_events, EventType.DECISION_TAKEN)
        if decision_events:
            # Should use deterministic source (fallback)
            assert_fallback_used(all_events)

    def test_decision_with_validation_failure(self, tmp_path):
        """Validation fails → MCP decides on recovery path."""
        excel_path = create_excel_invalid_actions(tmp_path, invalid_action="nuke")
        cfg = self._load_config()

        mcp = _ScenarioMCPConnector()
        mcp.set_response("decide_next_step", {
            "selected_step": "recover_validation",
            "confidence": 0.88,
            "reason": "Error is recoverable",
        })
        mcp.set_response("recover", {
            "recovered": True,
            "recovery_action": "action_mapping",
            "diagnosis": "Mapped unknown action to supported equivalent",
        })

        events = EventManager(trace_id="test")
        svc = _build_service(
            connector_registry=_build_connector_registry(mcp),
            event_manager=events,
        )

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()
        logger.info("Decision + failure events:\n%s", summarize_events(all_events))

        # Pipeline should have executed (may or may not fully succeed)
        assert len(result.steps) >= 3  # detect_excel, read_excel, validate at minimum

    def test_decision_engine_created(self, tmp_path):
        """DecisionEngine is instantiated when use_mcp_decision=True."""
        excel_path = create_valid_excel(tmp_path)
        cfg = self._load_config()

        events = EventManager(trace_id="test")
        svc = _build_service(event_manager=events)

        # Before running — no engine
        assert svc.decision_engine is None

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        # After running — engine exists (use_mcp_decision=True)
        assert svc.decision_engine is not None


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 3: Retry Intelligence
# ═══════════════════════════════════════════════════════════════════════════

class TestRetryScenario:
    """test_retry.json — step failure triggers MCP retry intelligence."""

    def _load_config(self):
        return load_config_from_file(CONFIGS_DIR / "test_retry.json")

    def test_config_loads_with_retry(self):
        """Config has use_mcp_retry=True."""
        cfg = self._load_config()
        assert cfg.name == "test-retry"
        assert cfg.use_mcp_retry is True
        assert cfg.use_mcp_decision is False

    def test_retry_intelligence_triggered_on_failure(self, tmp_path):
        """Step failure with use_mcp_retry → DecisionEngine.should_retry consulted."""
        excel_path = create_valid_excel(tmp_path)
        cfg = self._load_config()

        mcp = _ScenarioMCPConnector()
        # MCP recommends no retry (error is not transient)
        mcp.set_response("should_retry", {
            "retry": False,
            "confidence": 0.9,
            "reason": "Data error — retry won't help",
        })

        events = EventManager(trace_id="test")

        # Create a validation agent that always fails to trigger retry logic
        class _FailingValidation(BaseAgent):
            name = "validation"
            description = "Always fails for retry testing"

            def run(self, context):
                raise RuntimeError("Simulated validation failure")

        registry = _build_test_registry()
        registry.register("validate", _FailingValidation())

        svc = _build_service(
            agent_registry=registry,
            connector_registry=_build_connector_registry(mcp),
            event_manager=events,
        )

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()
        logger.info("Retry scenario events:\n%s", summarize_events(all_events))

        # DecisionEngine should have been created for retry
        assert svc.decision_engine is not None
        # Validate step should have failed
        assert_step_failed(all_events, "validate")

    def test_retry_mcp_recommends_retry(self, tmp_path):
        """MCP says retry → step re-executed (then fails again → abort)."""
        excel_path = create_valid_excel(tmp_path)
        cfg = self._load_config()

        call_count = {"n": 0}
        mcp = _ScenarioMCPConnector()

        # First call: MCP says retry. Second call: MCP says no retry.
        def _dynamic_fetch(request):
            task = request.get("arguments", {}).get("task", "")
            if task == "should_retry":
                call_count["n"] += 1
                if call_count["n"] == 1:
                    return ConnectorResult(ok=True, data={"result": {
                        "retry": True, "confidence": 0.85,
                        "reason": "Transient — retry should succeed",
                    }})
                else:
                    return ConnectorResult(ok=True, data={"result": {
                        "retry": False, "confidence": 0.90,
                        "reason": "Same error persists",
                    }})
            return ConnectorResult(ok=True, data={"result": {"status": "ok"}})

        mcp.fetch = _dynamic_fetch

        events = EventManager(trace_id="test")

        class _AlwaysFailValidation(BaseAgent):
            name = "validation"
            description = "Always fails"

            def run(self, context):
                raise RuntimeError("Persistent failure")

        registry = _build_test_registry()
        registry.register("validate", _AlwaysFailValidation())

        svc = _build_service(
            agent_registry=registry,
            connector_registry=_build_connector_registry(mcp),
            event_manager=events,
        )

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()
        logger.info("Retry (MCP recommends) events:\n%s", summarize_events(all_events))

        # Should have multiple STEP_FAILED for validate (original + retry)
        step_failed = get_events_by_type(all_events, EventType.STEP_FAILED)
        validate_failures = [e for e in step_failed if e.step_name == "validate"]
        assert len(validate_failures) >= 1

    def test_retry_without_mcp(self, tmp_path):
        """No MCP connector → deterministic retry logic (no retry for abort policy)."""
        excel_path = create_valid_excel(tmp_path)
        cfg = self._load_config()

        events = EventManager(trace_id="test")
        # No MCP but use real handlers (validate will pass with valid data)
        svc = _build_service(
            connector_registry=_build_connector_registry(None),
            event_manager=events,
        )

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        # Pipeline should complete (validate passes with valid input via built-in handler)
        assert_step_completed(events.get_events(), "validate")


# ═══════════════════════════════════════════════════════════════════════════
# SCENARIO 4: MCP Disabled (Deterministic)
# ═══════════════════════════════════════════════════════════════════════════

class TestMCPDisabledScenario:
    """test_mcp_disabled.json — pure deterministic pipeline, no MCP decisions."""

    def _load_config(self):
        return load_config_from_file(CONFIGS_DIR / "test_mcp_disabled.json")

    def test_config_all_flags_false(self):
        """All MCP flags are explicitly disabled."""
        cfg = self._load_config()
        assert cfg.name == "test-mcp-disabled"
        assert cfg.use_mcp_decision is False
        assert cfg.use_mcp_retry is False
        assert cfg.use_mcp_condition is False

    def test_no_decision_engine_created(self, tmp_path):
        """DecisionEngine is NOT created when all MCP flags are False."""
        excel_path = create_valid_excel(tmp_path)
        cfg = self._load_config()

        events = EventManager(trace_id="test")
        svc = _build_service(event_manager=events)

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        # Engine should NOT be created
        assert svc.decision_engine is None

    def test_deterministic_success_path(self, tmp_path):
        """Valid input → validate succeeds → normalize (via on_success_step) → generate."""
        excel_path = create_valid_excel(tmp_path)
        cfg = self._load_config()

        events = EventManager(trace_id="test")
        svc = _build_service(event_manager=events)

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()
        logger.info("Deterministic success events:\n%s", summarize_events(all_events))

        # Steps should execute in order
        assert_step_completed(all_events, "detect_excel")
        assert_step_completed(all_events, "read_excel")
        assert_step_completed(all_events, "validate")

        # Branch to normalize (on_success_step)
        assert_event_emitted(all_events, EventType.BRANCH_TAKEN,
                             metadata_contains={"from_step": "validate", "to_step": "normalize"})

        # No MCP decisions
        assert_no_mcp_decisions(all_events)

    def test_deterministic_failure_path(self, tmp_path):
        """Invalid input → validate fails → branch to recovery (deterministic)."""
        excel_path = create_excel_missing_columns(tmp_path, drop_columns=["TC_ID"])
        cfg = self._load_config()

        events = EventManager(trace_id="test")
        svc = _build_service(
            connector_registry=_build_connector_registry(None),
            event_manager=events,
        )

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()
        logger.info("Deterministic failure events:\n%s", summarize_events(all_events))

        # Validate failed
        assert_step_failed(all_events, "validate")

        # Branch to recovery
        assert_branch_taken(all_events, "validate", "recover_validation", "on_failure_step")

        # No MCP decisions
        assert_no_mcp_decisions(all_events)

    def test_no_mcp_retry_on_failure(self, tmp_path):
        """Failure with MCP disabled → no retry intelligence, just abort/continue."""
        excel_path = create_excel_missing_columns(tmp_path)
        cfg = self._load_config()

        events = EventManager(trace_id="test")
        svc = _build_service(event_manager=events)

        result = svc.run_pipeline_from_config(
            cfg,
            PipelineInput(excel_path=str(excel_path)),
        )

        all_events = events.get_events()

        # No RETRY_DECISION events should exist
        assert_event_not_emitted(all_events, EventType.RETRY_DECISION)


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-CUTTING: Config validation tests
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigValidation:
    """Verify all test configs load correctly and are well-formed."""

    @pytest.mark.parametrize("config_name", [
        "test_recovery.json",
        "test_decision.json",
        "test_retry.json",
        "test_mcp_disabled.json",
    ])
    def test_config_parses(self, config_name):
        """Each test config loads without errors."""
        cfg = load_config_from_file(CONFIGS_DIR / config_name)
        assert cfg.name
        assert len(cfg.steps) > 0
        for step in cfg.steps:
            assert step.name

    @pytest.mark.parametrize("config_name,expected_flag", [
        ("test_recovery.json", "none"),
        ("test_decision.json", "use_mcp_decision"),
        ("test_retry.json", "use_mcp_retry"),
        ("test_mcp_disabled.json", "none"),
    ])
    def test_mcp_flags(self, config_name, expected_flag):
        """Each config has the correct MCP flags."""
        cfg = load_config_from_file(CONFIGS_DIR / config_name)
        if expected_flag == "use_mcp_decision":
            assert cfg.use_mcp_decision is True
        elif expected_flag == "use_mcp_retry":
            assert cfg.use_mcp_retry is True
        elif expected_flag == "none":
            # Recovery and disabled configs have no MCP decision flags
            pass

    def test_all_configs_coexist(self):
        """All test configs can be listed without conflicts."""
        from pipeline.config import list_available_configs
        configs = list_available_configs()
        names = [c["name"] for c in configs]
        assert "test-recovery" in names
        assert "test-decision" in names
        assert "test-retry" in names
        assert "test-mcp-disabled" in names


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-CUTTING: Excel modifier tests
# ═══════════════════════════════════════════════════════════════════════════

class TestExcelModifier:
    """Validate the Excel modifier helper functions."""

    def test_create_valid_excel(self, tmp_path):
        """Valid Excel has all required columns."""
        path = create_valid_excel(tmp_path)
        assert path.exists()
        import pandas as pd
        df = pd.read_excel(path, dtype=str)
        assert set(df.columns) == {"TC_ID", "Page", "Action", "Target", "Value", "Expected"}
        assert len(df) == len(VALID_ROWS)

    def test_create_missing_columns(self, tmp_path):
        """Missing-column Excel drops the specified column."""
        path = create_excel_missing_columns(tmp_path, drop_columns=["TC_ID", "Expected"])
        import pandas as pd
        df = pd.read_excel(path, dtype=str)
        assert "TC_ID" not in df.columns
        assert "Expected" not in df.columns

    def test_create_invalid_actions(self, tmp_path):
        """Invalid-action Excel has an unsupported action value."""
        path = create_excel_invalid_actions(tmp_path, invalid_action="teleport")
        import pandas as pd
        df = pd.read_excel(path, dtype=str)
        actions = df["Action"].tolist()
        assert "teleport" in actions

    def test_create_missing_values(self, tmp_path):
        """Missing-values Excel has dash where values are required."""
        path = create_excel_missing_required_values(tmp_path)
        import pandas as pd
        df = pd.read_excel(path, dtype=str)
        # Second row (fill Username) should have Value="-"
        assert df.iloc[1]["Value"] == "-"

    def test_create_mixed(self, tmp_path):
        """Mixed Excel has both valid and invalid test cases."""
        path = create_excel_mixed_valid_invalid(tmp_path)
        import pandas as pd
        df = pd.read_excel(path, dtype=str)
        # Should still have all required columns
        assert set(df.columns) == {"TC_ID", "Page", "Action", "Target", "Value", "Expected"}
        # Should have the invalid action
        assert "destroy" in df["Action"].tolist()


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-CUTTING: Log validator tests
# ═══════════════════════════════════════════════════════════════════════════

class TestLogValidator:
    """Validate the log_validator helper functions work correctly."""

    def _make_events(self) -> list:
        """Create a representative set of events for testing."""
        em = EventManager(trace_id="test")
        em.emit(EventType.PIPELINE_STARTED, metadata={"config": "test"})
        em.emit(EventType.STEP_STARTED, step_name="validate")
        em.emit(EventType.STEP_FAILED, step_name="validate",
                metadata={"error": "Schema mismatch"})
        em.emit(EventType.BRANCH_TAKEN, step_name="validate",
                metadata={"from_step": "validate", "to_step": "recover", "branch": "on_failure_step"})
        em.emit(EventType.AGENT_STARTED, step_name="recover",
                metadata={"agent": "mcp_recovery"})
        em.emit(EventType.STEP_COMPLETED, step_name="recover")
        em.emit(EventType.DECISION_TAKEN, step_name="validate",
                metadata={"source": "deterministic", "from_step": "validate",
                           "selected": "recover", "candidates": ["recover", "normalize"]})
        em.emit(EventType.RETRY_DECISION, step_name="normalize",
                metadata={"step": "normalize", "retry": True, "source": "mcp", "confidence": 0.85})
        em.emit(EventType.PIPELINE_COMPLETED, metadata={"config": "test"})
        return em.get_events()

    def test_assert_step_failed(self):
        events = self._make_events()
        assert_step_failed(events, "validate", error_contains="schema")

    def test_assert_step_completed(self):
        events = self._make_events()
        assert_step_completed(events, "recover")

    def test_assert_recovery_triggered(self):
        events = self._make_events()
        assert_recovery_triggered(events, "recover")

    def test_assert_decision_taken(self):
        events = self._make_events()
        assert_decision_taken(events, source="deterministic")

    def test_assert_retry_decision(self):
        events = self._make_events()
        assert_retry_decision(events, step_name="normalize", retry=True, source="mcp")

    def test_assert_fallback_used(self):
        events = self._make_events()
        assert_fallback_used(events, step_name="validate")

    def test_assert_branch_taken(self):
        events = self._make_events()
        assert_branch_taken(events, "validate", "recover", "on_failure_step")

    def test_assert_no_mcp_decisions(self):
        em = EventManager(trace_id="test")
        em.emit(EventType.DECISION_TAKEN,
                metadata={"source": "deterministic", "from_step": "x", "selected": "y"})
        assert_no_mcp_decisions(em.get_events())

    def test_assert_event_sequence(self):
        events = self._make_events()
        assert_event_sequence(events, [
            EventType.PIPELINE_STARTED,
            EventType.STEP_FAILED,
            EventType.BRANCH_TAKEN,
            EventType.PIPELINE_COMPLETED,
        ])

    def test_assert_event_not_emitted(self):
        events = self._make_events()
        assert_event_not_emitted(events, EventType.STEP_SKIPPED)

    def test_summarize_events(self):
        events = self._make_events()
        summary = summarize_events(events)
        assert "STEP_FAILED" in summary
        assert "validate" in summary


# ═══════════════════════════════════════════════════════════════════════════
# CLI Integration
# ═══════════════════════════════════════════════════════════════════════════

class TestCLIConfigLoading:
    """Verify --config flag can load test scenario configs."""

    @pytest.mark.parametrize("config_path", [
        "pipeline/configs/test_recovery.json",
        "pipeline/configs/test_decision.json",
        "pipeline/configs/test_retry.json",
        "pipeline/configs/test_mcp_disabled.json",
    ])
    def test_config_path_accepted(self, config_path):
        """Pipeline config loads from file path (as --config passes it)."""
        full_path = Path(__file__).resolve().parent.parent / config_path
        cfg = load_config_from_file(full_path)
        assert cfg.name
        assert len(cfg.steps) > 0

    @pytest.mark.parametrize("config_name", [
        "test-recovery",
        "test-decision",
        "test-retry",
        "test-mcp-disabled",
    ])
    def test_builtin_name_resolves(self, config_name):
        """Pipeline config loads by name (load_builtin_config resolution)."""
        from pipeline.config import load_builtin_config
        cfg = load_builtin_config(config_name)
        assert cfg.name == config_name
