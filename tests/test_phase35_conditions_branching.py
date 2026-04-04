"""
Phase 3.5 tests — structured conditions, dynamic branching, formalized context.

Tests cover all 5 groups:
  GROUP 1: Structured condition evaluator
  GROUP 2: Dynamic branching (on_success_step / on_failure_step)
  GROUP 3: Formalized context model ($steps.step_name.data.key)
  GROUP 4: Enhanced step skipping
  GROUP 5: BRANCH_TAKEN event type
"""
from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from typing import Any

from pipeline.conditions import (
    ConditionEvaluator,
    evaluate_condition,
    resolve_ref,
)
from pipeline.config import (
    PipelineConfig,
    PipelineStepConfig,
    parse_step_config,
    parse_pipeline_config,
)
from pipeline.events import EventType


# ---------------------------------------------------------------------------
# Helpers — lightweight StepResult stub for condition tests
# ---------------------------------------------------------------------------

@dataclass
class _MockStepResult:
    step: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0


def _make_results(**kwargs) -> dict[str, _MockStepResult]:
    """Build a results_map from keyword args of (step_name: {ok, data, error})."""
    out: dict[str, _MockStepResult] = {}
    for name, val in kwargs.items():
        if isinstance(val, dict):
            out[name] = _MockStepResult(
                step=name,
                ok=val.get("ok", True),
                data=val.get("data", {}),
                error=val.get("error"),
                duration_ms=val.get("duration_ms", 0.0),
            )
        else:
            out[name] = val
    return out


# ===================================================================
# GROUP 1: Structured condition evaluator
# ===================================================================


class TestConditionEvaluatorStructured:
    """Test operator-based condition objects."""

    def setup_method(self):
        self.results = _make_results(
            validate={"ok": True, "data": {"row_count": 10, "valid": True}},
            detect={"ok": True, "data": {"excel_path": "/tmp/test.xlsx", "type": "excel"}},
            failing={"ok": False, "data": {}, "error": "timeout"},
        )
        self.input_ns = {"force": True, "feature_name": "Login", "type": "excel"}

    def test_eq_operator(self):
        assert evaluate_condition({"eq": ["$input.type", "excel"]}, self.results, self.input_ns) is True
        assert evaluate_condition({"eq": ["$input.type", "csv"]}, self.results, self.input_ns) is False

    def test_neq_operator(self):
        assert evaluate_condition({"neq": ["$input.type", "csv"]}, self.results, self.input_ns) is True
        assert evaluate_condition({"neq": ["$input.type", "excel"]}, self.results, self.input_ns) is False

    def test_gt_gte_lt_lte(self):
        assert evaluate_condition({"gt": ["$validate.data.row_count", 5]}, self.results, self.input_ns) is True
        assert evaluate_condition({"gt": ["$validate.data.row_count", 10]}, self.results, self.input_ns) is False
        assert evaluate_condition({"gte": ["$validate.data.row_count", 10]}, self.results, self.input_ns) is True
        assert evaluate_condition({"lt": ["$validate.data.row_count", 20]}, self.results, self.input_ns) is True
        assert evaluate_condition({"lte": ["$validate.data.row_count", 10]}, self.results, self.input_ns) is True

    def test_truthy_operator(self):
        assert evaluate_condition({"truthy": "$input.force"}, self.results, self.input_ns) is True
        assert evaluate_condition({"truthy": "$validate.ok"}, self.results, self.input_ns) is True
        assert evaluate_condition({"truthy": "$failing.ok"}, self.results, self.input_ns) is False

    def test_falsy_operator(self):
        assert evaluate_condition({"falsy": "$failing.ok"}, self.results, self.input_ns) is True
        assert evaluate_condition({"falsy": "$validate.ok"}, self.results, self.input_ns) is False

    def test_exists_operator(self):
        assert evaluate_condition({"exists": "$validate.data.row_count"}, self.results, self.input_ns) is True
        assert evaluate_condition({"exists": "$validate.data.nonexistent"}, self.results, self.input_ns) is False
        assert evaluate_condition({"exists": "$nonexistent_step.ok"}, self.results, self.input_ns) is False

    def test_and_combinator(self):
        cond = {"and": [
            {"truthy": "$validate.ok"},
            {"gt": ["$validate.data.row_count", 5]},
        ]}
        assert evaluate_condition(cond, self.results, self.input_ns) is True

        cond_fail = {"and": [
            {"truthy": "$validate.ok"},
            {"gt": ["$validate.data.row_count", 50]},
        ]}
        assert evaluate_condition(cond_fail, self.results, self.input_ns) is False

    def test_or_combinator(self):
        cond = {"or": [
            {"eq": ["$input.type", "csv"]},
            {"eq": ["$input.type", "excel"]},
        ]}
        assert evaluate_condition(cond, self.results, self.input_ns) is True

        cond_fail = {"or": [
            {"eq": ["$input.type", "csv"]},
            {"eq": ["$input.type", "json"]},
        ]}
        assert evaluate_condition(cond_fail, self.results, self.input_ns) is False

    def test_not_combinator(self):
        assert evaluate_condition({"not": {"eq": ["$input.type", "csv"]}}, self.results, self.input_ns) is True
        assert evaluate_condition({"not": {"eq": ["$input.type", "excel"]}}, self.results, self.input_ns) is False

    def test_nested_logic(self):
        """Complex nested condition: (A AND B) OR (NOT C)."""
        cond = {"or": [
            {"and": [
                {"truthy": "$validate.ok"},
                {"eq": ["$input.type", "csv"]},  # False
            ]},
            {"not": {"truthy": "$failing.ok"}},  # True (not False = True)
        ]}
        assert evaluate_condition(cond, self.results, self.input_ns) is True

    def test_none_condition_is_true(self):
        assert evaluate_condition(None, self.results, self.input_ns) is True

    def test_bool_condition(self):
        assert evaluate_condition(True, self.results, self.input_ns) is True
        assert evaluate_condition(False, self.results, self.input_ns) is False

    def test_empty_dict_is_true(self):
        assert evaluate_condition({}, self.results, self.input_ns) is True


class TestConditionEvaluatorStringBackcompat:
    """Ensure Phase 3 string conditions still work."""

    def setup_method(self):
        self.results = _make_results(
            validate={"ok": True, "data": {"row_count": 10}},
        )
        self.input_ns = {"force": True}

    def test_string_true_false(self):
        assert evaluate_condition("true", self.results, self.input_ns) is True
        assert evaluate_condition("false", self.results, self.input_ns) is False

    def test_string_eq(self):
        assert evaluate_condition("$validate.ok == true", self.results, self.input_ns) is True
        assert evaluate_condition("$validate.data.row_count == 10", self.results, self.input_ns) is True
        assert evaluate_condition("$validate.data.row_count == 5", self.results, self.input_ns) is False

    def test_string_neq(self):
        assert evaluate_condition("$validate.data.row_count != 5", self.results, self.input_ns) is True

    def test_string_bare_ref(self):
        assert evaluate_condition("$validate.ok", self.results, self.input_ns) is True
        assert evaluate_condition("$input.force", self.results, self.input_ns) is True

    def test_string_gt_gte_lt_lte(self):
        """Phase 3.5 enhancement: string conditions now support >, >=, <, <=."""
        assert evaluate_condition("$validate.data.row_count > 5", self.results, self.input_ns) is True
        assert evaluate_condition("$validate.data.row_count >= 10", self.results, self.input_ns) is True
        assert evaluate_condition("$validate.data.row_count < 20", self.results, self.input_ns) is True
        assert evaluate_condition("$validate.data.row_count <= 10", self.results, self.input_ns) is True


# ===================================================================
# GROUP 3: Formalized context model ($steps.step_name.data.key)
# ===================================================================


class TestFormalizedContextReferences:
    """Test $steps.step_name.data.key reference format."""

    def setup_method(self):
        self.results = _make_results(
            validate={"ok": True, "data": {"row_count": 10, "rows": [1, 2, 3]}},
            detect_excel={"ok": True, "data": {"excel_path": "/tmp/test.xlsx"}},
        )
        self.input_ns = {"feature_name": "Login"}

    def test_formal_steps_data_key(self):
        val = resolve_ref("$steps.validate.data.row_count", self.results, self.input_ns)
        assert val == 10

    def test_formal_steps_data(self):
        val = resolve_ref("$steps.validate.data", self.results, self.input_ns)
        assert val == {"row_count": 10, "rows": [1, 2, 3]}

    def test_formal_steps_ok(self):
        val = resolve_ref("$steps.validate.ok", self.results, self.input_ns)
        assert val is True

    def test_formal_steps_error(self):
        val = resolve_ref("$steps.validate.error", self.results, self.input_ns)
        assert val is None

    def test_formal_steps_duration_ms(self):
        val = resolve_ref("$steps.validate.duration_ms", self.results, self.input_ns)
        assert val == 0.0

    def test_legacy_step_data_key_still_works(self):
        val = resolve_ref("$validate.data.row_count", self.results, self.input_ns)
        assert val == 10

    def test_legacy_step_ok_still_works(self):
        val = resolve_ref("$validate.ok", self.results, self.input_ns)
        assert val is True

    def test_input_ref(self):
        val = resolve_ref("$input.feature_name", self.results, self.input_ns)
        assert val == "Login"

    def test_literal_value(self):
        val = resolve_ref("just a string", self.results, self.input_ns)
        assert val == "just a string"

    def test_numeric_literal(self):
        val = resolve_ref(42, self.results, self.input_ns)
        assert val == 42

    def test_nonexistent_step(self):
        val = resolve_ref("$steps.nonexistent.data.key", self.results, self.input_ns)
        assert val is None

    def test_underscore_step_name(self):
        """Step names with underscores (detect_excel) resolve correctly."""
        val = resolve_ref("$steps.detect_excel.data.excel_path", self.results, self.input_ns)
        assert val == "/tmp/test.xlsx"

    def test_conditions_with_formal_refs(self):
        """Structured conditions using $steps.* references."""
        cond = {"eq": ["$steps.validate.data.row_count", 10]}
        assert evaluate_condition(cond, self.results, self.input_ns) is True


# ===================================================================
# GROUP 2: Dynamic branching config
# ===================================================================


class TestPipelineStepConfigBranching:
    """Test PipelineStepConfig with branching fields."""

    def test_parse_branching_fields(self):
        raw = {
            "name": "validate",
            "on_success_step": "normalize",
            "on_failure_step": "error_handler",
        }
        cfg = parse_step_config(raw)
        assert cfg.on_success_step == "normalize"
        assert cfg.on_failure_step == "error_handler"

    def test_parse_no_branching(self):
        raw = {"name": "validate"}
        cfg = parse_step_config(raw)
        assert cfg.on_success_step is None
        assert cfg.on_failure_step is None

    def test_parse_structured_condition(self):
        raw = {
            "name": "validate",
            "condition": {"eq": ["$input.type", "excel"]},
        }
        cfg = parse_step_config(raw)
        assert isinstance(cfg.condition, dict)
        assert cfg.condition["eq"] == ["$input.type", "excel"]

    def test_parse_string_condition_compat(self):
        raw = {
            "name": "validate",
            "condition": "$input.force == true",
        }
        cfg = parse_step_config(raw)
        assert isinstance(cfg.condition, str)


class TestPipelineConfigBranching:
    """Test full config parsing with branching."""

    def test_branching_config(self):
        raw = {
            "name": "branching-test",
            "steps": [
                {"name": "step_a"},
                {"name": "step_b", "on_success_step": "step_d", "on_failure_step": "step_c"},
                {"name": "step_c", "label": "Error Handler"},
                {"name": "step_d", "label": "Success Path"},
            ],
        }
        config = parse_pipeline_config(raw)
        assert len(config.steps) == 4
        assert config.steps[1].on_success_step == "step_d"
        assert config.steps[1].on_failure_step == "step_c"


# ===================================================================
# GROUP 5: BRANCH_TAKEN event type
# ===================================================================


class TestBranchTakenEvent:
    """Test BRANCH_TAKEN is a valid EventType."""

    def test_branch_taken_exists(self):
        assert hasattr(EventType, "BRANCH_TAKEN")
        assert EventType.BRANCH_TAKEN.value == "BRANCH_TAKEN"

    def test_event_type_completeness(self):
        """All Phase 3.5 event types exist."""
        required = [
            "PIPELINE_STARTED", "PIPELINE_COMPLETED", "PIPELINE_FAILED",
            "PIPELINE_PAUSED", "PIPELINE_RESUMED",
            "STEP_STARTED", "STEP_COMPLETED", "STEP_FAILED", "STEP_SKIPPED",
            "BRANCH_TAKEN",
            "AGENT_STARTED", "AGENT_COMPLETED",
            "ERROR_OCCURRED",
        ]
        for name in required:
            assert hasattr(EventType, name), f"Missing EventType.{name}"


# ===================================================================
# Integration: branching execution with PipelineService
# ===================================================================


class TestBranchingExecution:
    """Integration tests for dynamic branching through PipelineService."""

    def _make_service_with_mock_agents(self, agent_behaviors: dict[str, tuple[bool, dict]]):
        """Create a PipelineService with mock agents for specified steps.

        agent_behaviors: {step_name: (ok, data)}
        """
        from pipeline.service import PipelineService, PipelineInput
        from pipeline.events import EventManager
        from pipeline.agents.base import BaseAgent, AgentResult
        from pipeline.agents.registry import AgentRegistry

        registry = AgentRegistry()

        for step_name, (ok, data) in agent_behaviors.items():
            class MockAgent(BaseAgent):
                _name = step_name
                _ok = ok
                _data = data

                def __init__(self, name, ok, data):
                    self._name = name
                    self._ok = ok
                    self._data = data

                @property
                def name(self):
                    return self._name

                def run(self, context):
                    return AgentResult(ok=self._ok, data=self._data)

            agent_instance = MockAgent(step_name, ok, data)
            registry.register(step_name, agent_instance)

        em = EventManager(trace_id="test_branching")
        svc = PipelineService(event_manager=em, agent_registry=registry)
        return svc, em

    def test_linear_execution(self):
        """Without branching, steps execute in order."""
        svc, em = self._make_service_with_mock_agents({
            "step_a": (True, {"val": 1}),
            "step_b": (True, {"val": 2}),
            "step_c": (True, {"val": 3}),
        })

        config = PipelineConfig(
            name="linear-test",
            steps=[
                PipelineStepConfig(name="step_a"),
                PipelineStepConfig(name="step_b"),
                PipelineStepConfig(name="step_c"),
            ],
        )

        result = svc.run_pipeline_from_config(config)
        assert result.ok
        assert [s.step for s in result.steps] == ["step_a", "step_b", "step_c"]

    def test_on_success_branch(self):
        """on_success_step skips intermediate steps."""
        svc, em = self._make_service_with_mock_agents({
            "step_a": (True, {}),
            "step_b": (True, {}),  # should be skipped
            "step_c": (True, {}),
        })

        config = PipelineConfig(
            name="branch-test",
            steps=[
                PipelineStepConfig(name="step_a", on_success_step="step_c"),
                PipelineStepConfig(name="step_b"),
                PipelineStepConfig(name="step_c"),
            ],
        )

        result = svc.run_pipeline_from_config(config)
        assert result.ok
        executed = [s.step for s in result.steps]
        assert executed == ["step_a", "step_c"]  # step_b skipped

        # Verify BRANCH_TAKEN event was emitted
        branch_events = em.get_events(event_type=EventType.BRANCH_TAKEN)
        assert len(branch_events) == 1
        assert branch_events[0].metadata["from_step"] == "step_a"
        assert branch_events[0].metadata["to_step"] == "step_c"
        assert branch_events[0].metadata["branch"] == "on_success_step"

    def test_on_failure_branch(self):
        """on_failure_step routes to error handler step."""
        svc, em = self._make_service_with_mock_agents({
            "step_a": (False, {}),
            "error_handler": (True, {"handled": True}),
            "step_b": (True, {}),
        })

        config = PipelineConfig(
            name="failure-branch",
            steps=[
                PipelineStepConfig(name="step_a", on_failure_step="error_handler"),
                PipelineStepConfig(name="step_b"),
                PipelineStepConfig(name="error_handler"),
            ],
        )

        result = svc.run_pipeline_from_config(config)
        assert result.ok
        executed = [s.step for s in result.steps]
        assert "step_a" in executed
        assert "error_handler" in executed

        branch_events = em.get_events(event_type=EventType.BRANCH_TAKEN)
        assert len(branch_events) == 1
        assert branch_events[0].metadata["branch"] == "on_failure_step"

    def test_condition_skip_with_stub_result(self):
        """Skipped steps get a stub result for later reference (GROUP 4)."""
        svc, em = self._make_service_with_mock_agents({
            "step_a": (True, {"val": 1}),
            "step_b": (True, {"val": 2}),
        })

        config = PipelineConfig(
            name="skip-test",
            steps=[
                PipelineStepConfig(name="step_a"),
                PipelineStepConfig(name="conditional", condition="false"),
                PipelineStepConfig(name="step_b"),
            ],
        )

        result = svc.run_pipeline_from_config(config)
        assert result.ok

        # Verify STEP_SKIPPED event
        skipped = em.get_events(event_type=EventType.STEP_SKIPPED)
        assert len(skipped) == 1
        assert skipped[0].step_name == "conditional"
        assert skipped[0].metadata.get("reason") == "condition_not_met"

    def test_structured_condition_in_config(self):
        """Structured dict conditions work in pipeline execution."""
        svc, em = self._make_service_with_mock_agents({
            "step_a": (True, {"count": 5}),
            "step_b": (True, {}),
            "step_c": (True, {}),
        })

        config = PipelineConfig(
            name="structured-cond",
            steps=[
                PipelineStepConfig(name="step_a"),
                PipelineStepConfig(
                    name="step_b",
                    condition={"gt": ["$step_a.data.count", 3]},
                ),
                PipelineStepConfig(
                    name="step_c",
                    condition={"gt": ["$step_a.data.count", 100]},
                ),
            ],
        )

        result = svc.run_pipeline_from_config(config)
        assert result.ok
        executed = [s.step for s in result.steps]
        assert "step_a" in executed
        assert "step_b" in executed
        assert "step_c" not in executed  # condition not met

    def test_loop_guard(self):
        """Infinite loop is caught by max execution guard."""
        svc, em = self._make_service_with_mock_agents({
            "step_a": (True, {}),
            "step_b": (True, {}),
        })

        # step_b always jumps back to step_a → infinite loop
        config = PipelineConfig(
            name="loop-test",
            steps=[
                PipelineStepConfig(name="step_a"),
                PipelineStepConfig(name="step_b", on_success_step="step_a"),
            ],
        )

        # Lower the guard for faster test
        original = svc._MAX_STEP_EXECUTIONS
        svc._MAX_STEP_EXECUTIONS = 20

        result = svc.run_pipeline_from_config(config)
        assert not result.ok
        assert result.exit_code == 1

        # Restore
        svc._MAX_STEP_EXECUTIONS = original

    def test_formal_refs_in_branching_pipeline(self):
        """$steps.step_name.data.key works in a real pipeline execution."""
        svc, em = self._make_service_with_mock_agents({
            "step_a": (True, {"score": 90}),
            "step_b": (True, {}),
        })

        config = PipelineConfig(
            name="formal-ref-test",
            steps=[
                PipelineStepConfig(name="step_a"),
                PipelineStepConfig(
                    name="step_b",
                    condition={"gte": ["$steps.step_a.data.score", 80]},
                ),
            ],
        )

        result = svc.run_pipeline_from_config(config)
        assert result.ok
        assert len(result.steps) == 2  # both executed

    def test_failure_abort_no_branch(self):
        """Without on_failure_step, on_failure=abort still works."""
        svc, em = self._make_service_with_mock_agents({
            "step_a": (False, {}),
            "step_b": (True, {}),
        })

        config = PipelineConfig(
            name="abort-test",
            steps=[
                PipelineStepConfig(name="step_a", on_failure="abort"),
                PipelineStepConfig(name="step_b"),
            ],
        )

        result = svc.run_pipeline_from_config(config)
        assert not result.ok
        assert len(result.steps) == 1  # step_b never ran
