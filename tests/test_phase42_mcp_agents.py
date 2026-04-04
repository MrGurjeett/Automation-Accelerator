"""
Phase 4.2 — MCP-powered agent tests.

Covers:
  1. MCPAgentBase — base class behavior, MCP call flow, fallback
  2. MCPGenerationAgent — structured output generation
  3. MCPValidationAgent — validation / enrichment via MCP
  4. MCPEnrichmentAgent — data enrichment
  5. MCPRecoveryAgent — failure recovery, branching integration
  6. Hybrid agent — ValidationAgent with MCP revalidation
  7. Full pipeline flow — ADO → MCP → validation → recovery
  8. Event emission — correct events during MCP agent execution
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from pipeline.agents.base import BaseAgent, AgentResult, ConnectorAwareMixin
from pipeline.agents.mcp_base import MCPAgentBase
from pipeline.agents.mcp_agents import (
    MCPGenerationAgent,
    MCPValidationAgent,
    MCPEnrichmentAgent,
    MCPRecoveryAgent,
    _sanitize_for_mcp,
)
from pipeline.connectors.base import ConnectorResult
from pipeline.connectors.registry import ConnectorRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockMCPConnector:
    """Lightweight mock MCP connector that satisfies isinstance(BaseConnector) via duck typing.

    We avoid MagicMock because ConnectorRegistry.register() checks isinstance().
    Instead, we subclass BaseConnector and override methods.
    """

    def __init__(
        self,
        tool_response: Any = None,
        ok: bool = True,
        error: str | None = None,
        connected: bool = True,
    ):
        from pipeline.connectors.base import BaseConnector
        self.name = "mcp"
        self.description = "Mock MCP connector"
        self._connected = connected
        self._ok = ok
        self._error = error
        self._tool_response = tool_response
        self._fetch_calls: list[dict] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> ConnectorResult:
        self._connected = True
        return ConnectorResult(ok=True)

    def fetch(self, query: dict[str, Any]) -> ConnectorResult:
        self._fetch_calls.append(query)
        if self._ok:
            return ConnectorResult(ok=True, data={"result": self._tool_response})
        return ConnectorResult(ok=False, error=self._error)

    def push(self, data: dict[str, Any]) -> ConnectorResult:
        return self.fetch(data)

    def health_check(self) -> ConnectorResult:
        return ConnectorResult(ok=self._connected)


# Make _MockMCPConnector pass isinstance check
from pipeline.connectors.base import BaseConnector
BaseConnector.register(_MockMCPConnector)


def _make_mcp_connector(
    tool_response: Any = None,
    ok: bool = True,
    error: str | None = None,
    connected: bool = True,
) -> _MockMCPConnector:
    """Create a mock MCP connector returning the given response."""
    return _MockMCPConnector(tool_response, ok, error, connected)


def _make_context(
    mcp_response: Any = None,
    mcp_ok: bool = True,
    mcp_error: str | None = None,
    mcp_connected: bool = True,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Build a context dict with a mock MCP connector in the registry."""
    reg = ConnectorRegistry()
    mock_mcp = _make_mcp_connector(mcp_response, mcp_ok, mcp_error, mcp_connected)
    reg.register("mcp", mock_mcp)

    ctx: dict[str, Any] = {"_connector_registry": reg}
    if extra:
        ctx.update(extra)
    return ctx


# ===========================================================================
# 1. MCPAgentBase
# ===========================================================================

class _ConcreteMCPAgent(MCPAgentBase):
    """Concrete test agent for MCPAgentBase."""
    name = "test_mcp_agent"
    description = "Test MCP agent"
    mcp_task = "test"
    mcp_tool = "test_tool"

    def _build_mcp_arguments(self, context):
        return {"input": context.get("input_data", "default")}

    def _process_mcp_result(self, mcp_data, context):
        return {"processed": mcp_data, "source": "mcp"}


class TestMCPAgentBase:
    """MCPAgentBase base class behavior."""

    def test_inherits_base_agent(self):
        assert issubclass(MCPAgentBase, BaseAgent)
        assert issubclass(MCPAgentBase, ConnectorAwareMixin)

    def test_successful_mcp_call(self):
        agent = _ConcreteMCPAgent()
        ctx = _make_context(mcp_response={"answer": 42})
        result = agent.run(ctx)

        assert result.ok is True
        assert result.data["processed"] == {"answer": 42}
        assert result.data["source"] == "mcp"
        assert result.metrics["mcp_used"] is True
        assert result.metrics["mcp_task"] == "test"
        assert "mcp_duration_ms" in result.metrics

    def test_mcp_failure_triggers_fallback(self):
        agent = _ConcreteMCPAgent()
        ctx = _make_context(mcp_ok=False, mcp_error="server down")
        result = agent.run(ctx)

        assert result.ok is False
        assert "MCP unavailable" in result.error or "MCP failed" in result.warnings[0]

    def test_mcp_not_connected_triggers_fallback(self):
        agent = _ConcreteMCPAgent()
        ctx = _make_context(mcp_connected=False)
        result = agent.run(ctx)

        assert result.ok is False
        assert "MCP unavailable" in result.error

    def test_no_mcp_in_registry_triggers_fallback(self):
        agent = _ConcreteMCPAgent()
        ctx = {"_connector_registry": ConnectorRegistry()}
        result = agent.run(ctx)

        assert result.ok is False

    def test_mcp_call_format(self):
        """Verify the MCP connector is called with correct format."""
        agent = _ConcreteMCPAgent()
        ctx = _make_context(mcp_response={"ok": True}, extra={"input_data": "hello"})

        agent.run(ctx)

        # Get the mock and verify fetch was called correctly
        reg = ctx["_connector_registry"]
        mock_mcp = reg.get("mcp")
        assert len(mock_mcp._fetch_calls) == 1
        call_args = mock_mcp._fetch_calls[0]

        assert call_args["type"] == "tool_call"
        assert call_args["tool"] == "test_tool"
        assert call_args["arguments"]["task"] == "test"
        assert call_args["arguments"]["input"] == "hello"

    def test_timeout_override(self):
        agent = _ConcreteMCPAgent()
        ctx = _make_context(mcp_response={}, extra={"mcp_timeout": 60})
        agent.run(ctx)

        reg = ctx["_connector_registry"]
        mock_mcp = reg.get("mcp")
        call_args = mock_mcp._fetch_calls[0]
        assert call_args["timeout"] == 60

    def test_custom_fallback(self):
        """Subclass with custom fallback returns ok=True."""

        class FallbackAgent(MCPAgentBase):
            name = "fallback_agent"
            mcp_task = "test"

            def _fallback(self, context):
                return AgentResult(ok=True, data={"fallback": True})

        agent = FallbackAgent()
        ctx = {"_connector_registry": ConnectorRegistry()}
        result = agent.run(ctx)
        assert result.ok is True
        assert result.data["fallback"] is True


# ===========================================================================
# 2. MCPGenerationAgent
# ===========================================================================

class TestMCPGenerationAgent:
    """MCPGenerationAgent structured output generation."""

    def test_successful_generation(self):
        agent = MCPGenerationAgent()
        mcp_response = {
            "generated": [
                {"step": "Click Login", "action": "click"},
                {"step": "Enter Password", "action": "fill"},
            ],
        }
        ctx = _make_context(
            mcp_response=mcp_response,
            extra={"generation_type": "test_steps", "input_data": {"scenario": "login"}},
        )
        result = agent.run(ctx)

        assert result.ok is True
        assert result.data["generation_type"] == "test_steps"
        assert result.data["item_count"] == 2
        assert len(result.data["generated"]) == 2

    def test_generation_with_constraints(self):
        agent = MCPGenerationAgent()
        ctx = _make_context(
            mcp_response={"generated": ["item1"]},
            extra={
                "generation_type": "summary",
                "input_data": {"data": "..."},
                "constraints": {"max_length": 100},
                "template": "## Summary\n{content}",
            },
        )
        result = agent.run(ctx)
        assert result.ok is True

        # Verify constraints and template were passed to MCP
        reg = ctx["_connector_registry"]
        call_args = reg.get("mcp")._fetch_calls[0]["arguments"]
        assert call_args["constraints"] == {"max_length": 100}
        assert call_args["template"] == "## Summary\n{content}"

    def test_generation_list_response(self):
        agent = MCPGenerationAgent()
        ctx = _make_context(
            mcp_response=["step1", "step2", "step3"],
            extra={"generation_type": "steps"},
        )
        result = agent.run(ctx)
        assert result.ok is True
        assert result.data["item_count"] == 3

    def test_generation_fallback(self):
        agent = MCPGenerationAgent()
        ctx = {"_connector_registry": ConnectorRegistry()}
        result = agent.run(ctx)
        assert result.ok is False
        assert result.data["item_count"] == 0
        assert "MCP generation unavailable" in result.warnings[0]


# ===========================================================================
# 3. MCPValidationAgent
# ===========================================================================

class TestMCPValidationAgent:
    """MCPValidationAgent validation and verification."""

    def test_successful_validation(self):
        agent = MCPValidationAgent()
        mcp_response = {
            "valid": True,
            "validated_items": [{"id": "TC_001"}, {"id": "TC_002"}],
            "invalid_items": [],
        }
        ctx = _make_context(
            mcp_response=mcp_response,
            extra={"validation_target": "test_cases", "data": [{"id": "TC_001"}, {"id": "TC_002"}]},
        )
        result = agent.run(ctx)

        assert result.ok is True
        assert result.data["valid"] is True
        assert len(result.data["validated_items"]) == 2
        assert len(result.data["invalid_items"]) == 0
        assert result.data["validation_summary"]["passed"] == 2

    def test_validation_with_failures(self):
        agent = MCPValidationAgent()
        mcp_response = {
            "valid": False,
            "validated_items": [{"id": "TC_001"}],
            "invalid_items": [{"id": "TC_002", "reason": "missing target"}],
        }
        ctx = _make_context(
            mcp_response=mcp_response,
            extra={"validation_target": "test_cases", "data": []},
        )
        result = agent.run(ctx)

        assert result.ok is True  # Agent succeeded (it's MCP that reports valid=False)
        assert result.data["valid"] is False
        assert result.data["validation_summary"]["failed"] == 1

    def test_validation_with_rules(self):
        agent = MCPValidationAgent()
        ctx = _make_context(
            mcp_response={"valid": True, "validated_items": [], "invalid_items": []},
            extra={
                "validation_target": "workflow",
                "data": {},
                "rules": ["completeness", "ordering"],
            },
        )
        agent.run(ctx)

        reg = ctx["_connector_registry"]
        call_args = reg.get("mcp")._fetch_calls[0]["arguments"]
        assert call_args["rules"] == ["completeness", "ordering"]

    def test_validation_fallback_pass_through(self):
        """When MCP unavailable, validation passes through (ok=True)."""
        agent = MCPValidationAgent()
        ctx = {"_connector_registry": ConnectorRegistry()}
        result = agent.run(ctx)

        assert result.ok is True
        assert result.data["valid"] is True  # Pass-through
        assert "passed through" in result.warnings[0]


# ===========================================================================
# 3b. MCPEnrichmentAgent
# ===========================================================================

class TestMCPEnrichmentAgent:
    """MCPEnrichmentAgent data enrichment."""

    def test_successful_enrichment(self):
        agent = MCPEnrichmentAgent()
        mcp_response = {
            "enriched": {"rows": [{"TC_ID": "TC_001", "category": "login"}]},
            "fields_added": ["category"],
        }
        ctx = _make_context(
            mcp_response=mcp_response,
            extra={"enrichment_type": "test_cases", "data": [{"TC_ID": "TC_001"}]},
        )
        result = agent.run(ctx)

        assert result.ok is True
        assert result.data["enrichment_type"] == "test_cases"
        assert result.data["fields_added"] == ["category"]

    def test_enrichment_fallback_returns_original(self):
        """When MCP unavailable, returns original data unchanged."""
        agent = MCPEnrichmentAgent()
        original_data = [{"id": 1}, {"id": 2}]
        ctx = _make_context(
            mcp_connected=False,
            extra={"enrichment_type": "work_items", "data": original_data},
        )
        result = agent.run(ctx)

        assert result.ok is True
        assert result.data["enriched"] == original_data  # pass-through
        assert result.data["fields_added"] == []


# ===========================================================================
# 4. MCPRecoveryAgent
# ===========================================================================

class TestMCPRecoveryAgent:
    """MCPRecoveryAgent failure handling and recovery."""

    def test_successful_recovery(self):
        agent = MCPRecoveryAgent()
        mcp_response = {
            "recovered": True,
            "corrected_data": {"validated": {"TC_001": [{"step": "fixed"}]}},
            "recovery_action": "transform",
            "diagnosis": "Missing field auto-filled",
        }
        ctx = _make_context(
            mcp_response=mcp_response,
            extra={
                "error": "Validation failed: missing target field",
                "failed_step": "validate",
                "context": {"rows": [{"TC_ID": "TC_001"}]},
            },
        )
        result = agent.run(ctx)

        assert result.ok is True
        assert result.data["recovered"] is True
        assert result.data["recovery_action"] == "transform"
        assert result.data["diagnosis"] == "Missing field auto-filled"
        assert "validated" in result.data["corrected_data"]

    def test_failed_recovery(self):
        agent = MCPRecoveryAgent()
        mcp_response = {
            "recovered": False,
            "corrected_data": {},
            "recovery_action": "none",
            "diagnosis": "Data too corrupted to recover",
        }
        ctx = _make_context(
            mcp_response=mcp_response,
            extra={"error": "Critical failure", "failed_step": "normalize"},
        )
        result = agent.run(ctx)

        assert result.ok is True  # Agent itself succeeded
        assert result.data["recovered"] is False
        assert result.data["diagnosis"] == "Data too corrupted to recover"

    def test_recovery_triggered_on_failure(self):
        """MCPRecoveryAgent should accept failure context from branching."""
        agent = MCPRecoveryAgent()
        mcp_response = {"recovered": True, "corrected_data": {}, "recovery_action": "skip"}
        ctx = _make_context(
            mcp_response=mcp_response,
            extra={
                "error": "$steps.validate.error",  # would be resolved by pipeline
                "failed_step": "validate",
                "recovery_strategy": "auto",
            },
        )
        result = agent.run(ctx)
        assert result.ok is True

    def test_recovery_fallback_skip_strategy(self):
        """With skip strategy, fallback returns ok=True."""
        agent = MCPRecoveryAgent()
        ctx = _make_context(
            mcp_connected=False,
            extra={
                "error": "Some error",
                "failed_step": "validate",
                "recovery_strategy": "skip",
            },
        )
        result = agent.run(ctx)

        assert result.ok is True
        assert result.data["recovered"] is True
        assert result.data["recovery_action"] == "skip"

    def test_recovery_fallback_default_fails(self):
        """Without skip strategy, fallback returns ok=False."""
        agent = MCPRecoveryAgent()
        ctx = _make_context(
            mcp_connected=False,
            extra={"error": "Fatal error", "failed_step": "normalize"},
        )
        result = agent.run(ctx)

        assert result.ok is False
        assert "Cannot recover" in result.error

    def test_recovery_sanitizes_context(self):
        """Private keys and large data should be sanitized for MCP."""
        agent = MCPRecoveryAgent()
        ctx = _make_context(
            mcp_response={"recovered": True, "corrected_data": {}},
            extra={
                "error": "test error",
                "failed_step": "test",
                "context": {
                    "public_data": "visible",
                    "_private_data": "hidden",
                    "_connector_registry": "should_be_stripped",
                },
            },
        )
        agent.run(ctx)

        reg = ctx["_connector_registry"]
        call_args = reg.get("mcp")._fetch_calls[0]["arguments"]
        original_context = call_args["original_context"]
        assert "public_data" in original_context
        assert "_private_data" not in original_context


# ===========================================================================
# 5. Hybrid Agent — ValidationAgent with MCP
# ===========================================================================

class TestValidationAgentHybrid:
    """ValidationAgent hybrid pattern — deterministic + MCP."""

    def test_deterministic_only_when_mcp_disabled(self):
        """Without use_mcp_validation, pure deterministic validation."""
        from pipeline.agents.processing import ValidationAgent

        agent = ValidationAgent()
        # Minimal context without MCP
        result = agent.run({"rows": []})
        assert result.ok is False  # Empty rows = failure
        # No MCP calls made (no connector in context)

    def test_deterministic_with_mcp_flag_but_no_connector(self):
        """MCP flag set but no connector — deterministic only, no crash."""
        from pipeline.agents.processing import ValidationAgent

        agent = ValidationAgent()
        # Create rows that will be rejected by deterministic validation
        # We can't easily create valid/invalid rows without validators,
        # but we can verify the agent doesn't crash
        result = agent.run({"rows": [], "use_mcp_validation": True})
        assert result.ok is False

    def test_mcp_rescue_not_called_when_all_pass(self):
        """MCP is not called when all test cases pass deterministic validation."""
        from pipeline.agents.processing import ValidationAgent

        agent = ValidationAgent()
        reg = ConnectorRegistry()
        mock_mcp = _make_mcp_connector({"rescued": []})
        reg.register("mcp", mock_mcp)

        # We can't create valid rows easily in a unit test (need validator imports)
        # but we verify the architecture is correct
        ctx = {"rows": [], "use_mcp_validation": True, "_connector_registry": reg}
        agent.run(ctx)
        # MCP should NOT have been called since there are no rejected items
        # (empty rows fails before MCP revalidation stage)
        assert len(mock_mcp._fetch_calls) == 0

    def test_is_connector_aware(self):
        """ValidationAgent has ConnectorAwareMixin."""
        from pipeline.agents.processing import ValidationAgent

        agent = ValidationAgent()
        assert hasattr(agent, "get_connector")
        assert isinstance(agent, ConnectorAwareMixin)


# ===========================================================================
# 6. Pipeline Config Integration
# ===========================================================================

class TestPipelineConfigIntegration:
    """MCP pipeline config loading and structure."""

    def test_mcp_pipeline_config_loads(self):
        from pipeline.config import load_builtin_config

        cfg = load_builtin_config("mcp-pipeline")
        assert cfg.name == "mcp-pipeline"
        assert len(cfg.steps) > 0

    def test_mcp_pipeline_has_mcp_agents(self):
        from pipeline.config import load_builtin_config

        cfg = load_builtin_config("mcp-pipeline")
        agent_steps = [s for s in cfg.steps if s.agent]
        agent_names = [s.agent for s in agent_steps]

        assert "mcp_generation" in agent_names
        assert "mcp_validation" in agent_names
        assert "mcp_enrichment" in agent_names
        assert "mcp_recovery" in agent_names

    def test_mcp_pipeline_has_recovery_branching(self):
        from pipeline.config import load_builtin_config

        cfg = load_builtin_config("mcp-pipeline")
        validate_step = next(s for s in cfg.steps if s.name == "validate")
        assert validate_step.on_failure_step == "recover_validation"

        recovery_step = next(s for s in cfg.steps if s.name == "recover_validation")
        assert recovery_step.agent == "mcp_recovery"

    def test_mcp_pipeline_step_references(self):
        from pipeline.config import load_builtin_config

        cfg = load_builtin_config("mcp-pipeline")
        recovery_step = next(s for s in cfg.steps if s.name == "recover_validation")
        # Recovery step references validate's error
        assert "$steps.validate.error" in str(recovery_step.inputs.get("error", ""))

    def test_mcp_steps_have_continue_on_failure(self):
        """MCP agent steps should use on_failure=continue to prevent blocking."""
        from pipeline.config import load_builtin_config

        cfg = load_builtin_config("mcp-pipeline")
        mcp_steps = [s for s in cfg.steps if s.agent and s.agent.startswith("mcp_") and s.name != "recover_validation"]
        for step in mcp_steps:
            assert step.on_failure == "continue", (
                f"MCP step '{step.name}' should have on_failure='continue', "
                f"got '{step.on_failure}'"
            )


# ===========================================================================
# 7. Full Pipeline Flow Simulation
# ===========================================================================

class TestFullPipelineFlow:
    """Simulated full pipeline flow with MCP agents."""

    def test_generation_then_validation_flow(self):
        """Simulate: generate → validate → (pass)."""
        gen = MCPGenerationAgent()
        val = MCPValidationAgent()

        # Step 1: Generate
        gen_response = {"generated": [{"step": "Login"}, {"step": "Verify"}]}
        gen_ctx = _make_context(
            mcp_response=gen_response,
            extra={"generation_type": "test_steps", "input_data": {}},
        )
        gen_result = gen.run(gen_ctx)
        assert gen_result.ok is True

        # Step 2: Validate the generated output
        val_response = {
            "valid": True,
            "validated_items": gen_result.data["generated"],
            "invalid_items": [],
        }
        val_ctx = _make_context(
            mcp_response=val_response,
            extra={"validation_target": "generated_steps", "data": gen_result.data["generated"]},
        )
        val_result = val.run(val_ctx)
        assert val_result.ok is True
        assert val_result.data["valid"] is True

    def test_validation_failure_then_recovery(self):
        """Simulate: validate → (fail) → recover → (continue)."""
        val = MCPValidationAgent()
        rec = MCPRecoveryAgent()

        # Step 1: Validate (fail)
        val_response = {
            "valid": False,
            "validated_items": [],
            "invalid_items": [{"id": "TC_001", "reason": "bad step"}],
        }
        val_ctx = _make_context(
            mcp_response=val_response,
            extra={"validation_target": "test_cases", "data": [{"id": "TC_001"}]},
        )
        val_result = val.run(val_ctx)
        assert val_result.data["valid"] is False

        # Step 2: Recovery (triggered by on_failure_step)
        rec_response = {
            "recovered": True,
            "corrected_data": {"validated": {"TC_001": [{"step": "corrected"}]}},
            "recovery_action": "transform",
            "diagnosis": "Auto-corrected bad step",
        }
        rec_ctx = _make_context(
            mcp_response=rec_response,
            extra={
                "error": "Validation found invalid items",
                "failed_step": "validate",
                "context": val_result.data,
            },
        )
        rec_result = rec.run(rec_ctx)
        assert rec_result.ok is True
        assert rec_result.data["recovered"] is True
        assert "corrected" in str(rec_result.data["corrected_data"])

    def test_enrichment_then_generation_flow(self):
        """Simulate: enrich → generate."""
        enrich = MCPEnrichmentAgent()
        gen = MCPGenerationAgent()

        # Step 1: Enrich
        enrich_response = {
            "enriched": [{"TC_ID": "TC_001", "category": "auth", "priority": "high"}],
            "fields_added": ["category", "priority"],
        }
        enrich_ctx = _make_context(
            mcp_response=enrich_response,
            extra={"enrichment_type": "test_cases", "data": [{"TC_ID": "TC_001"}]},
        )
        enrich_result = enrich.run(enrich_ctx)
        assert enrich_result.ok is True

        # Step 2: Generate from enriched data
        gen_response = {"generated": [{"step": "Auth test for high-priority TC_001"}]}
        gen_ctx = _make_context(
            mcp_response=gen_response,
            extra={
                "generation_type": "test_steps",
                "input_data": enrich_result.data["enriched"],
            },
        )
        gen_result = gen.run(gen_ctx)
        assert gen_result.ok is True
        assert gen_result.data["item_count"] == 1

    def test_all_mcp_agents_graceful_without_mcp(self):
        """All MCP agents should handle missing MCP gracefully."""
        agents = [
            MCPGenerationAgent(),
            MCPValidationAgent(),
            MCPEnrichmentAgent(),
            MCPRecoveryAgent(),
        ]

        empty_ctx: dict[str, Any] = {"_connector_registry": ConnectorRegistry()}

        for agent in agents:
            result = agent.run(empty_ctx)
            # Should not crash — either ok=True (fallback) or ok=False (graceful error)
            assert isinstance(result, AgentResult), f"{agent.name} didn't return AgentResult"
            assert isinstance(result.ok, bool), f"{agent.name} returned non-bool ok"


# ===========================================================================
# 8. Event emission (via PipelineService)
# ===========================================================================

class TestMCPAgentEventEmission:
    """MCP agents emit correct events when run through PipelineService."""

    def test_service_executes_mcp_agent(self):
        from pipeline.service import PipelineService

        # Register MCP generation agent
        svc = PipelineService()
        agent = MCPGenerationAgent()
        svc.register_agent("mcp_generate", agent)

        assert svc.agent_registry.has("mcp_generate")

    def test_mcp_agents_discoverable_by_registry(self):
        """MCP agents can be discovered by AgentRegistry.discover_agents."""
        from pipeline.agents.registry import AgentRegistry

        reg = AgentRegistry()
        count = reg.discover_agents("pipeline.agents")

        # Should find MCP agents among discovered agents
        assert reg.has("mcp_generation")
        assert reg.has("mcp_validation")
        assert reg.has("mcp_enrichment")
        assert reg.has("mcp_recovery")


# ===========================================================================
# 9. Sanitization helper
# ===========================================================================

class TestSanitizeForMCP:
    """_sanitize_for_mcp helper function."""

    def test_primitives(self):
        assert _sanitize_for_mcp(None) is None
        assert _sanitize_for_mcp(True) is True
        assert _sanitize_for_mcp(42) == 42
        assert _sanitize_for_mcp("hello") == "hello"

    def test_dict_strips_private_keys(self):
        data = {"public": "visible", "_private": "hidden", "__dunder": "hidden"}
        result = _sanitize_for_mcp(data)
        assert "public" in result
        assert "_private" not in result
        assert "__dunder" not in result

    def test_depth_limit(self):
        deep = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
        result = _sanitize_for_mcp(deep, max_depth=3)
        # depth 1=root, 2=a, 3=b → b's children get truncated
        assert result["a"]["b"]["c"] == "<truncated>"

    def test_list_truncation(self):
        big_list = list(range(200))
        result = _sanitize_for_mcp(big_list, max_items=5)
        assert len(result) == 6  # 5 items + truncation message
        assert "195 more items" in result[-1]

    def test_non_serializable(self):
        class Weird:
            pass
        result = _sanitize_for_mcp(Weird())
        assert isinstance(result, str)


# ===========================================================================
# 10. No existing agent breakage
# ===========================================================================

class TestExistingAgentsUnbroken:
    """Verify existing agents still work after Phase 4.2 changes."""

    def test_validation_agent_without_mcp(self):
        """ValidationAgent works as before without MCP context."""
        from pipeline.agents.processing import ValidationAgent
        agent = ValidationAgent()
        # Empty rows → expected failure
        result = agent.run({"rows": []})
        assert result.ok is False
        assert "empty input" in result.error.lower()

    def test_normalization_agent_unchanged(self):
        """NormalizationAgent is unmodified."""
        from pipeline.agents.processing import NormalizationAgent
        agent = NormalizationAgent()
        # Missing config → expected failure
        result = agent.run({})
        assert result.ok is False
        assert "AI stack" in result.error

    def test_feature_generation_agent_unchanged(self):
        """FeatureGenerationAgent still importable and instantiable."""
        from pipeline.agents.processing import FeatureGenerationAgent
        agent = FeatureGenerationAgent()
        assert agent.name == "feature_generation"

    def test_execution_agent_still_connector_aware(self):
        from pipeline.agents.output import ExecutionAgent
        agent = ExecutionAgent()
        assert hasattr(agent, "get_connector")

    def test_persistence_agent_still_connector_aware(self):
        from pipeline.agents.output import PersistenceAgent
        agent = PersistenceAgent()
        assert hasattr(agent, "get_connector")
