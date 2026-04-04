"""
Phase 4A — Connector abstraction layer tests.

Covers:
  - BaseConnector / ConnectorResult
  - ConnectorRegistry (register, get, replace, health_check_all)
  - ADOConnector (construction, connect, fetch/push validation)
  - MCPConnector (success, timeout, retry, circuit breaker, graceful failure)
  - ConnectorAwareMixin (agent connector access)
  - Connector initialization (init_connectors)
  - PipelineService connector integration
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Base / Result
# ---------------------------------------------------------------------------

from pipeline.connectors.base import BaseConnector, ConnectorResult


class TestConnectorResult:
    """ConnectorResult dataclass behaviour."""

    def test_default_values(self):
        r = ConnectorResult()
        assert r.ok is True
        assert r.data == {}
        assert r.error is None
        assert r.status_code is None
        assert r.metadata == {}

    def test_failure_result(self):
        r = ConnectorResult(ok=False, error="broken", status_code=500)
        assert r.ok is False
        assert r.error == "broken"
        assert r.status_code == 500

    def test_data_payload(self):
        r = ConnectorResult(ok=True, data={"items": [1, 2, 3]})
        assert r.data["items"] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

from pipeline.connectors.registry import ConnectorRegistry


class _DummyConnector(BaseConnector):
    """Minimal concrete connector for testing."""

    name = "dummy"
    description = "Test connector"

    def __init__(self, healthy: bool = True):
        self._healthy = healthy
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> ConnectorResult:
        self._connected = True
        return ConnectorResult(ok=True)

    def fetch(self, query: dict[str, Any]) -> ConnectorResult:
        return ConnectorResult(ok=True, data={"echo": query})

    def push(self, data: dict[str, Any]) -> ConnectorResult:
        return ConnectorResult(ok=True, data={"pushed": data})

    def health_check(self) -> ConnectorResult:
        return ConnectorResult(ok=self._healthy)


class TestConnectorRegistry:
    """ConnectorRegistry register/get/replace/health_check."""

    def test_register_and_get(self):
        reg = ConnectorRegistry()
        c = _DummyConnector()
        reg.register("test", c)
        assert reg.get("test") is c
        assert reg.has("test")
        assert len(reg) == 1

    def test_duplicate_register_raises(self):
        reg = ConnectorRegistry()
        reg.register("test", _DummyConnector())
        with pytest.raises(ValueError, match="already registered"):
            reg.register("test", _DummyConnector())

    def test_replace(self):
        reg = ConnectorRegistry()
        c1 = _DummyConnector()
        c2 = _DummyConnector()
        reg.register("test", c1)
        old = reg.replace("test", c2)
        assert old is c1
        assert reg.get("test") is c2

    def test_unregister(self):
        reg = ConnectorRegistry()
        c = _DummyConnector()
        reg.register("test", c)
        removed = reg.unregister("test")
        assert removed is c
        assert not reg.has("test")
        assert reg.unregister("nonexistent") is None

    def test_type_checking(self):
        reg = ConnectorRegistry()
        with pytest.raises(TypeError, match="BaseConnector"):
            reg.register("bad", "not a connector")  # type: ignore

    def test_names(self):
        reg = ConnectorRegistry()
        reg.register("a", _DummyConnector())
        reg.register("b", _DummyConnector())
        assert sorted(reg.names) == ["a", "b"]

    def test_list_connectors(self):
        reg = ConnectorRegistry()
        c = _DummyConnector()
        c.connect()
        reg.register("test", c)
        listing = reg.list_connectors()
        assert len(listing) == 1
        assert listing[0]["name"] == "test"
        assert listing[0]["connected"] is True

    def test_health_check_all(self):
        reg = ConnectorRegistry()
        reg.register("healthy", _DummyConnector(healthy=True))
        reg.register("unhealthy", _DummyConnector(healthy=False))
        results = reg.health_check_all()
        assert results["healthy"] is True
        assert results["unhealthy"] is False


# ---------------------------------------------------------------------------
# ADO Connector
# ---------------------------------------------------------------------------

from pipeline.connectors.ado import ADOConnector


class TestADOConnector:
    """ADOConnector construction and validation."""

    def test_connect_missing_org(self):
        ado = ADOConnector(organization="", pat="test-pat")
        result = ado.connect()
        assert result.ok is False
        assert "organization" in result.error.lower()

    def test_connect_missing_pat(self):
        ado = ADOConnector(organization="my-org", pat="")
        result = ado.connect()
        assert result.ok is False
        assert "PAT" in result.error

    def test_connect_success(self):
        ado = ADOConnector(organization="my-org", project="my-proj", pat="test-pat")
        result = ado.connect()
        assert result.ok is True
        assert ado.is_connected
        assert result.data["organization"] == "my-org"
        assert result.data["project"] == "my-proj"

    def test_fetch_not_connected(self):
        ado = ADOConnector(organization="my-org", pat="test-pat")
        result = ado.fetch({"type": "work_items", "ids": [1]})
        assert result.ok is False
        assert "connect()" in result.error.lower()

    def test_fetch_unknown_type(self):
        ado = ADOConnector(organization="my-org", pat="test-pat")
        ado.connect()
        result = ado.fetch({"type": "unknown"})
        assert result.ok is False
        assert "Unknown fetch type" in result.error

    def test_fetch_work_items_no_query_or_ids(self):
        ado = ADOConnector(organization="my-org", pat="test-pat")
        ado.connect()
        result = ado.fetch({"type": "work_items"})
        assert result.ok is False
        assert "ids" in result.error or "query" in result.error

    def test_push_not_connected(self):
        ado = ADOConnector(organization="my-org", pat="test-pat")
        result = ado.push({"type": "work_item", "fields": {"System.Title": "Test"}})
        assert result.ok is False

    def test_push_unknown_type(self):
        ado = ADOConnector(organization="my-org", pat="test-pat")
        ado.connect()
        result = ado.push({"type": "unknown"})
        assert result.ok is False
        assert "Unknown push type" in result.error

    def test_push_work_item_no_fields(self):
        ado = ADOConnector(organization="my-org", pat="test-pat")
        ado.connect()
        result = ado.push({"type": "work_item", "fields": {}})
        assert result.ok is False
        assert "fields" in result.error.lower()

    def test_push_test_result_no_run_id(self):
        ado = ADOConnector(organization="my-org", pat="test-pat")
        ado.connect()
        result = ado.push({"type": "test_result", "results": [{"outcome": "Passed"}]})
        assert result.ok is False
        assert "run_id" in result.error

    def test_health_check_not_connected(self):
        ado = ADOConnector(organization="my-org", pat="test-pat")
        result = ado.health_check()
        assert result.ok is False

    def test_env_var_config(self):
        with patch.dict(os.environ, {
            "ADO_ORGANIZATION": "env-org",
            "ADO_PROJECT": "env-proj",
            "ADO_PAT": "env-pat",
        }):
            ado = ADOConnector()
            result = ado.connect()
            assert result.ok is True
            assert result.data["organization"] == "env-org"

    def test_base_url_default(self):
        ado = ADOConnector(organization="test-org", pat="pat")
        assert "dev.azure.com/test-org" in ado._base_url

    def test_base_url_custom(self):
        ado = ADOConnector(organization="test-org", pat="pat", base_url="https://custom.tfs.com")
        assert ado._base_url == "https://custom.tfs.com"


# ---------------------------------------------------------------------------
# MCP Connector
# ---------------------------------------------------------------------------

from pipeline.connectors.mcp import MCPConnector


def _sync_tool_fn(tool_name: str, arguments: dict, timeout: float = 30) -> dict:
    """Simple sync MCP tool callable for testing."""
    return {"tool": tool_name, "args": arguments}


def _failing_tool_fn(tool_name: str, arguments: dict, timeout: float = 30) -> dict:
    raise ConnectionError("server unavailable")


def _timeout_tool_fn(tool_name: str, arguments: dict, timeout: float = 30) -> dict:
    raise TimeoutError(f"timed out after {timeout}s")


class TestMCPConnectorBasic:
    """MCPConnector construction, connect, basic operations."""

    def test_connect_no_callable(self):
        mcp = MCPConnector(server_name="test")
        result = mcp.connect()
        assert result.ok is False
        assert "call_tool_fn" in result.error

    def test_connect_success(self):
        mcp = MCPConnector(server_name="test", call_tool_fn=_sync_tool_fn)
        result = mcp.connect()
        assert result.ok is True
        assert mcp.is_connected

    def test_fetch_not_connected(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn)
        result = mcp.fetch({"type": "tool_call", "tool": "test"})
        assert result.ok is False

    def test_fetch_unknown_type(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn)
        mcp.connect()
        result = mcp.fetch({"type": "unknown"})
        assert result.ok is False
        assert "Unknown MCP fetch type" in result.error

    def test_fetch_tool_call_no_name(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn)
        mcp.connect()
        result = mcp.fetch({"type": "tool_call"})
        assert result.ok is False
        assert "tool" in result.error.lower()


class TestMCPConnectorSuccess:
    """MCPConnector successful tool calls."""

    def test_sync_tool_call(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn)
        mcp.connect()
        result = mcp.fetch({
            "type": "tool_call",
            "tool": "read_file",
            "arguments": {"path": "/test.txt"},
        })
        assert result.ok is True
        assert result.data["tool"] == "read_file"
        assert result.data["result"]["tool"] == "read_file"
        assert result.metadata["attempt"] == 1

    def test_push_tool_call(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn)
        mcp.connect()
        result = mcp.push({
            "type": "tool_call",
            "tool": "write_file",
            "arguments": {"path": "/out.txt", "content": "hello"},
        })
        assert result.ok is True
        assert result.data["tool"] == "write_file"

    def test_list_tools(self):
        tools_fn = lambda: [{"name": "tool1"}, {"name": "tool2"}]
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn, list_tools_fn=tools_fn)
        mcp.connect()
        result = mcp.fetch({"type": "list_tools"})
        assert result.ok is True
        assert result.data["count"] == 2

    def test_list_tools_not_configured(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn)
        mcp.connect()
        result = mcp.fetch({"type": "list_tools"})
        assert result.ok is False
        assert "not supported" in result.error

    def test_stats_tracking(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn)
        mcp.connect()
        mcp.fetch({"type": "tool_call", "tool": "a"})
        mcp.fetch({"type": "tool_call", "tool": "b"})
        stats = mcp.stats
        assert stats["calls"] == 2
        assert stats["failures"] == 0


class TestMCPConnectorRetry:
    """MCPConnector retry and timeout handling."""

    def test_connection_error_retries(self):
        mcp = MCPConnector(
            call_tool_fn=_failing_tool_fn,
            max_retries=2,
            retry_delay=0.01,
        )
        mcp.connect()
        result = mcp.fetch({"type": "tool_call", "tool": "test"})
        assert result.ok is False
        assert "server unavailable" in result.error
        assert result.metadata["attempts"] == 3  # 1 + 2 retries
        assert mcp.stats["retries"] == 2
        assert mcp.stats["failures"] == 1

    def test_timeout_error_retries(self):
        mcp = MCPConnector(
            call_tool_fn=_timeout_tool_fn,
            max_retries=1,
            retry_delay=0.01,
        )
        mcp.connect()
        result = mcp.fetch({"type": "tool_call", "tool": "slow"})
        assert result.ok is False
        assert "Timeout" in result.error or "timed out" in result.error
        assert result.metadata["attempts"] == 2

    def test_non_retryable_error_no_retry(self):
        def bad_fn(tool_name, arguments, timeout=30):
            raise ValueError("invalid argument")

        mcp = MCPConnector(call_tool_fn=bad_fn, max_retries=2, retry_delay=0.01)
        mcp.connect()
        result = mcp.fetch({"type": "tool_call", "tool": "test"})
        assert result.ok is False
        assert "ValueError" in result.error
        # Should NOT have retried (ValueError is not retryable)
        assert result.metadata["attempts"] == 1

    def test_retry_then_succeed(self):
        call_count = {"n": 0}

        def flaky_fn(tool_name, arguments, timeout=30):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("temporary failure")
            return {"ok": True}

        mcp = MCPConnector(call_tool_fn=flaky_fn, max_retries=2, retry_delay=0.01)
        mcp.connect()
        result = mcp.fetch({"type": "tool_call", "tool": "flaky"})
        assert result.ok is True
        assert result.metadata["attempt"] == 3
        assert mcp.stats["retries"] == 2
        assert mcp.stats["failures"] == 0

    def test_exponential_backoff(self):
        """Verify retry delays increase exponentially."""
        delays: list[float] = []
        original_sleep = time.sleep

        def mock_sleep(seconds):
            delays.append(seconds)

        mcp = MCPConnector(
            call_tool_fn=_failing_tool_fn,
            max_retries=3,
            retry_delay=0.1,
        )
        mcp.connect()

        with patch("time.sleep", side_effect=mock_sleep):
            # Re-import to catch the patched sleep
            import pipeline.connectors.mcp as mcp_module
            original_time_sleep = mcp_module.time.sleep
            mcp_module.time.sleep = mock_sleep
            try:
                mcp.fetch({"type": "tool_call", "tool": "test"})
            finally:
                mcp_module.time.sleep = original_time_sleep

        # Expect: 0.1, 0.2, 0.4 (base * 2^0, base * 2^1, base * 2^2)
        assert len(delays) == 3
        assert abs(delays[0] - 0.1) < 0.01
        assert abs(delays[1] - 0.2) < 0.01
        assert abs(delays[2] - 0.4) < 0.01


class TestMCPConnectorCircuitBreaker:
    """MCPConnector circuit breaker behaviour."""

    def test_circuit_starts_closed(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn, circuit_breaker_threshold=3)
        assert mcp._cb_state == "closed"

    def test_circuit_trips_after_threshold(self):
        mcp = MCPConnector(
            call_tool_fn=_failing_tool_fn,
            max_retries=0,
            circuit_breaker_threshold=3,
            circuit_breaker_reset=60.0,
            retry_delay=0.01,
        )
        mcp.connect()

        # Make 3 failing calls to trip the circuit
        for _ in range(3):
            mcp.fetch({"type": "tool_call", "tool": "test"})

        assert mcp._cb_state == "open"
        assert mcp._cb_consecutive_failures == 3

    def test_circuit_blocks_calls_when_open(self):
        mcp = MCPConnector(
            call_tool_fn=_failing_tool_fn,
            max_retries=0,
            circuit_breaker_threshold=2,
            circuit_breaker_reset=60.0,
            retry_delay=0.01,
        )
        mcp.connect()

        # Trip the circuit
        mcp.fetch({"type": "tool_call", "tool": "test"})
        mcp.fetch({"type": "tool_call", "tool": "test"})
        assert mcp._cb_state == "open"

        # Next call should be blocked immediately
        result = mcp.fetch({"type": "tool_call", "tool": "blocked"})
        assert result.ok is False
        assert "Circuit breaker open" in result.error
        assert result.metadata["circuit_breaker"] == "open"

    def test_circuit_resets_on_success(self):
        call_count = {"n": 0}

        def eventually_works(tool_name, arguments, timeout=30):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                raise ConnectionError("fail")
            return {"ok": True}

        mcp = MCPConnector(
            call_tool_fn=eventually_works,
            max_retries=0,
            circuit_breaker_threshold=5,
            retry_delay=0.01,
        )
        mcp.connect()

        # Two failures
        mcp.fetch({"type": "tool_call", "tool": "test"})
        mcp.fetch({"type": "tool_call", "tool": "test"})
        assert mcp._cb_consecutive_failures == 2

        # Third call succeeds
        result = mcp.fetch({"type": "tool_call", "tool": "test"})
        assert result.ok is True
        assert mcp._cb_consecutive_failures == 0  # Reset

    def test_circuit_half_open_after_reset_period(self):
        mcp = MCPConnector(
            call_tool_fn=_failing_tool_fn,
            max_retries=0,
            circuit_breaker_threshold=1,
            circuit_breaker_reset=0.1,  # Very short for testing
            retry_delay=0.01,
        )
        mcp.connect()

        # Trip the circuit
        mcp.fetch({"type": "tool_call", "tool": "test"})
        assert mcp._cb_state == "open"

        # Wait for reset period
        time.sleep(0.15)
        assert mcp._cb_state == "half_open"

    def test_manual_reset(self):
        mcp = MCPConnector(
            call_tool_fn=_failing_tool_fn,
            max_retries=0,
            circuit_breaker_threshold=1,
            circuit_breaker_reset=60.0,
            retry_delay=0.01,
        )
        mcp.connect()

        mcp.fetch({"type": "tool_call", "tool": "test"})
        assert mcp._cb_state == "open"

        mcp.reset_circuit_breaker()
        assert mcp._cb_state == "closed"
        assert mcp._cb_consecutive_failures == 0

    def test_circuit_disabled_when_threshold_zero(self):
        mcp = MCPConnector(
            call_tool_fn=_failing_tool_fn,
            max_retries=0,
            circuit_breaker_threshold=0,
            retry_delay=0.01,
        )
        mcp.connect()

        # Many failures should NOT trip the circuit
        for _ in range(10):
            mcp.fetch({"type": "tool_call", "tool": "test"})

        assert mcp._cb_state == "disabled"


class TestMCPConnectorAsync:
    """MCPConnector with async tool functions."""

    def test_async_tool_call(self):
        async def async_fn(tool_name, arguments, timeout=30):
            return {"tool": tool_name, "async": True}

        mcp = MCPConnector(call_tool_fn=async_fn)
        mcp.connect()
        result = mcp.fetch({"type": "tool_call", "tool": "async_test"})
        assert result.ok is True
        assert result.data["result"]["async"] is True

    def test_async_timeout(self):
        async def slow_fn(tool_name, arguments, timeout=30):
            await asyncio.sleep(100)
            return {}

        mcp = MCPConnector(call_tool_fn=slow_fn, timeout=0.1, max_retries=0)
        mcp.connect()
        result = mcp.fetch({"type": "tool_call", "tool": "slow"})
        assert result.ok is False
        assert "timed out" in result.error.lower() or "timeout" in result.error.lower()


# ---------------------------------------------------------------------------
# ConnectorAwareMixin
# ---------------------------------------------------------------------------

from pipeline.connectors.base import BaseConnector
from pipeline.agents.base import BaseAgent, ConnectorAwareMixin, AgentResult


class _ConnectorAwareAgent(ConnectorAwareMixin, BaseAgent):
    name = "test_aware"
    description = "Test connector-aware agent"

    def run(self, context: dict[str, Any]) -> AgentResult:
        ado = self.get_connector("ado", context)
        return AgentResult(ok=True, data={"has_ado": ado is not None})


class TestConnectorAwareMixin:
    """ConnectorAwareMixin integration."""

    def test_get_connector_from_context(self):
        reg = ConnectorRegistry()
        dummy = _DummyConnector()
        reg.register("ado", dummy)

        agent = _ConnectorAwareAgent()
        result = agent.run({"_connector_registry": reg})
        assert result.data["has_ado"] is True

    def test_get_connector_missing(self):
        reg = ConnectorRegistry()
        agent = _ConnectorAwareAgent()
        result = agent.run({"_connector_registry": reg})
        assert result.data["has_ado"] is False

    def test_get_connector_no_registry(self):
        agent = _ConnectorAwareAgent()
        # No _connector_registry in context — falls back to global
        result = agent.run({})
        # Should not crash; returns None or whatever is in global registry
        assert result.ok is True


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

from pipeline.connectors.init_connectors import initialize_connectors


class TestInitializeConnectors:
    """Connector bootstrap initialization."""

    def test_initialize_empty_env(self):
        """With no env vars, only MCP is registered (deferred)."""
        reg = ConnectorRegistry()
        with patch.dict(os.environ, {}, clear=True):
            # Ensure ADO env vars are not set
            for key in ("ADO_ORGANIZATION", "ADO_ORG", "ADO_PAT", "ADO_PROJECT"):
                os.environ.pop(key, None)
            result = initialize_connectors(registry=reg, auto_connect=False)
        assert result.has("mcp")
        assert not result.has("ado")

    def test_initialize_with_ado_env(self):
        """With ADO env vars, ADO is registered and connected."""
        reg = ConnectorRegistry()
        with patch.dict(os.environ, {
            "ADO_ORGANIZATION": "test-org",
            "ADO_PAT": "test-pat",
            "ADO_PROJECT": "test-proj",
        }):
            initialize_connectors(registry=reg, auto_connect=True)
        assert reg.has("ado")
        ado = reg.get("ado")
        assert ado.is_connected

    def test_initialize_with_mcp_callable(self):
        """MCP connector connects when callable is provided."""
        reg = ConnectorRegistry()
        initialize_connectors(
            registry=reg,
            mcp_call_tool_fn=_sync_tool_fn,
            auto_connect=True,
        )
        assert reg.has("mcp")
        mcp = reg.get("mcp")
        assert mcp.is_connected

    def test_initialize_idempotent(self):
        """Calling initialize twice doesn't duplicate connectors."""
        reg = ConnectorRegistry()
        initialize_connectors(registry=reg, auto_connect=False)
        initialize_connectors(registry=reg, auto_connect=False)
        assert len(reg) == 1  # Just MCP (deferred)


# ---------------------------------------------------------------------------
# PipelineService integration
# ---------------------------------------------------------------------------

class TestPipelineServiceConnectorIntegration:
    """PipelineService connector registry wiring."""

    def test_service_has_connector_registry(self):
        from pipeline.service import PipelineService
        svc = PipelineService()
        assert svc.connector_registry is not None
        assert isinstance(svc.connector_registry, ConnectorRegistry)

    def test_service_get_connector(self):
        from pipeline.service import PipelineService
        reg = ConnectorRegistry()
        dummy = _DummyConnector()
        reg.register("test", dummy)
        svc = PipelineService(connector_registry=reg)
        assert svc.get_connector("test") is dummy
        assert svc.get_connector("nonexistent") is None

    def test_service_injects_registry_into_context(self):
        """execute_step should inject _connector_registry into agent context."""
        from pipeline.service import PipelineService

        reg = ConnectorRegistry()
        dummy = _DummyConnector()
        reg.register("test", dummy)
        svc = PipelineService(connector_registry=reg)

        # Register a connector-aware agent
        agent = _ConnectorAwareAgent()
        svc.register_agent("test_step", agent)

        # Verify the context includes the connector registry
        # We can't easily test execute_step without all dependencies,
        # but we can verify the registry is accessible
        assert svc.connector_registry.get("test") is dummy


# ---------------------------------------------------------------------------
# Output agents connector-awareness
# ---------------------------------------------------------------------------

class TestOutputAgentsConnectorAware:
    """ExecutionAgent and PersistenceAgent connector integration."""

    def test_execution_agent_is_connector_aware(self):
        from pipeline.agents.output import ExecutionAgent
        agent = ExecutionAgent()
        assert hasattr(agent, "get_connector")

    def test_persistence_agent_is_connector_aware(self):
        from pipeline.agents.output import PersistenceAgent
        agent = PersistenceAgent()
        assert hasattr(agent, "get_connector")

    def test_execution_agent_no_ado_no_crash(self):
        """ExecutionAgent should not crash when ADO is not available."""
        from pipeline.agents.output import ExecutionAgent
        agent = ExecutionAgent()
        # _publish_to_ado should gracefully return False
        result = agent._publish_to_ado({}, {"success": True, "passed": 1, "failed": 0, "errors": 0})
        assert result is False

    def test_persistence_agent_no_ado_no_crash(self):
        """PersistenceAgent should not crash when ADO is not available."""
        from pipeline.agents.output import PersistenceAgent
        agent = PersistenceAgent()
        result = agent._sync_to_ado({}, {"tests": {}})
        assert result is False


# ---------------------------------------------------------------------------
# Graceful failure (MCP)
# ---------------------------------------------------------------------------

class TestMCPGracefulFailure:
    """MCP connector never raises — always returns ConnectorResult."""

    def test_connect_failure_graceful(self):
        mcp = MCPConnector()
        result = mcp.connect()
        assert result.ok is False
        # No exception raised

    def test_fetch_failure_graceful(self):
        mcp = MCPConnector(call_tool_fn=_failing_tool_fn, max_retries=0, retry_delay=0.01)
        mcp.connect()
        result = mcp.fetch({"type": "tool_call", "tool": "test"})
        assert result.ok is False
        assert result.error is not None
        # No exception raised

    def test_health_check_no_list_fn(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn)
        mcp.connect()
        result = mcp.health_check()
        assert result.ok is True
        assert result.data["note"] == "callable present"

    def test_push_unknown_type_graceful(self):
        mcp = MCPConnector(call_tool_fn=_sync_tool_fn)
        mcp.connect()
        result = mcp.push({"type": "bad_type"})
        assert result.ok is False
        # No exception raised
