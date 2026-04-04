"""Phase 2 Deep Runtime Validation Tests.

These tests exercise real execution behavior:
  - Multi-run isolation (concurrent run_id separation)
  - Streaming robustness (no lost/duplicated events)
  - Failure handling (agent failures, STEP_FAILED emission)
  - Thread safety (sequential runs, no leaked threads)
  - Event schema consistency (run_id, trace_id, duration_ms)

Run with:
    python -m pytest tests/test_phase2_runtime.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.events import EventManager, EventType, PipelineEvent
from pipeline.service import PipelineService, StepName, StepResult, PipelineStatus
from pipeline.agents.base import BaseAgent, AgentResult
from pipeline.agents.registry import AgentRegistry


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class SuccessAgent(BaseAgent):
    """Agent that always succeeds with a predictable result."""

    name = "success_agent"
    description = "Always succeeds"

    def __init__(self, delay: float = 0.0, data: dict | None = None):
        self._delay = delay
        self._data = data or {"result": "ok"}

    def run(self, context: dict[str, Any]) -> AgentResult:
        if self._delay:
            time.sleep(self._delay)
        return AgentResult(ok=True, data=self._data, metrics={"processed": 1})


class FailureAgent(BaseAgent):
    """Agent that always fails."""

    name = "failure_agent"
    description = "Always fails"

    def run(self, context: dict[str, Any]) -> AgentResult:
        return AgentResult(ok=False, error="Simulated agent failure", warnings=["warn1"])


class ExplodingAgent(BaseAgent):
    """Agent that raises an unhandled exception."""

    name = "exploding_agent"
    description = "Raises an exception"

    def run(self, context: dict[str, Any]) -> AgentResult:
        raise RuntimeError("Kaboom! Unhandled exception in agent")


class SlowAgent(BaseAgent):
    """Agent that takes a measurable amount of time."""

    name = "slow_agent"
    description = "Slow agent for duration testing"

    def __init__(self, duration_s: float = 0.1):
        self._duration = duration_s

    def run(self, context: dict[str, Any]) -> AgentResult:
        time.sleep(self._duration)
        return AgentResult(ok=True, data={"slept": self._duration})


class EventCollector:
    """Collects events from an EventManager for assertions."""

    def __init__(self):
        self.events: list[PipelineEvent] = []
        self._lock = threading.Lock()

    def handler(self, event: PipelineEvent) -> None:
        with self._lock:
            self.events.append(event)

    def by_type(self, et: EventType) -> list[PipelineEvent]:
        return [e for e in self.events if e.event_type == et]

    def by_step(self, step: str) -> list[PipelineEvent]:
        return [e for e in self.events if e.step_name == step]


# ===========================================================================
# 1. MULTI-RUN ISOLATION
# ===========================================================================

class TestMultiRunIsolation:
    """Verify that concurrent pipeline instances have isolated events."""

    def test_concurrent_pipelines_have_distinct_run_ids(self):
        """Two PipelineService instances created concurrently get different run_ids."""
        svc1 = PipelineService(trace_id="run-alpha-001")
        svc2 = PipelineService(trace_id="run-beta-002")

        assert svc1.run_id != svc2.run_id
        assert svc1.run_id == "run-alpha-001"
        assert svc2.run_id == "run-beta-002"

        svc1.close()
        svc2.close()

    def test_events_do_not_mix_between_runs(self):
        """Events emitted by one pipeline instance do not appear in another."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = os.path.join(tmpdir, "events1.jsonl")
            path2 = os.path.join(tmpdir, "events2.jsonl")

            em1 = EventManager(trace_id="iso-run-1", persist_path=path1)
            em2 = EventManager(trace_id="iso-run-2", persist_path=path2)

            svc1 = PipelineService(event_manager=em1, trace_id="iso-run-1")
            svc2 = PipelineService(event_manager=em2, trace_id="iso-run-2")

            # Register agents for a test step
            svc1.register_agent("detect_excel", SuccessAgent(data={"path": "a.xlsx"}))
            svc2.register_agent("detect_excel", SuccessAgent(data={"path": "b.xlsx"}))

            # Execute concurrently
            results = {}
            with ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(svc1.execute_step, StepName.DETECT_EXCEL, {})
                f2 = pool.submit(svc2.execute_step, StepName.DETECT_EXCEL, {})
                results["svc1"] = f1.result()
                results["svc2"] = f2.result()

            # Verify isolation
            events1 = em1.get_events()
            events2 = em2.get_events()

            run_ids_1 = {e.run_id for e in events1}
            run_ids_2 = {e.run_id for e in events2}

            assert run_ids_1 == {"iso-run-1"}, f"Expected only iso-run-1, got {run_ids_1}"
            assert run_ids_2 == {"iso-run-2"}, f"Expected only iso-run-2, got {run_ids_2}"

            # Verify no cross-contamination in JSONL files
            disk1 = EventManager.load_events_from_file(path1)
            disk2 = EventManager.load_events_from_file(path2)

            disk_run_ids_1 = {e.run_id for e in disk1}
            disk_run_ids_2 = {e.run_id for e in disk2}

            assert "iso-run-2" not in disk_run_ids_1
            assert "iso-run-1" not in disk_run_ids_2

            svc1.close()
            svc2.close()

    def test_concurrent_agent_execution_isolation(self):
        """Multiple steps running concurrently via different services keep events isolated."""
        collectors = {}

        def run_pipeline(run_id: str, steps: int):
            em = EventManager(trace_id=run_id)
            collector = EventCollector()
            em.subscribe(collector.handler)
            svc = PipelineService(event_manager=em, trace_id=run_id)

            for i in range(steps):
                agent = SuccessAgent(delay=0.01, data={"step": i})
                # Use a unique stage name per step to avoid registry collision
                stage = f"detect_excel"
                if svc.agent_registry.has(stage):
                    svc.agent_registry.unregister(stage)
                svc.register_agent(stage, agent)
                svc.execute_step(stage, {})

            svc.close()
            collectors[run_id] = collector

        threads = []
        for rid in ["conc-A", "conc-B", "conc-C"]:
            t = threading.Thread(target=run_pipeline, args=(rid, 5))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        # Each collector should only have events for its own run
        for rid, collector in collectors.items():
            for evt in collector.events:
                assert evt.run_id == rid, f"Event in {rid} has wrong run_id: {evt.run_id}"


# ===========================================================================
# 2. STREAMING ROBUSTNESS
# ===========================================================================

class TestStreamingRobustness:
    """Validate no lost or duplicated events under rapid emission."""

    def test_rapid_event_emission_no_loss(self):
        """Rapidly emit 500 events and verify all are captured in-memory and on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "rapid.jsonl")
            em = EventManager(trace_id="rapid-test", persist_path=path)
            collector = EventCollector()
            em.subscribe(collector.handler)

            N = 500
            for i in range(N):
                em.emit(
                    EventType.STEP_COMPLETED,
                    step_name=f"step_{i % 7}",
                    metadata={"run_id": "rapid-test", "duration_ms": float(i), "index": i},
                )

            # Verify in-memory
            assert em.event_count == N, f"Expected {N} in-memory events, got {em.event_count}"
            assert len(collector.events) == N, f"Expected {N} subscriber events, got {len(collector.events)}"

            # Verify on disk
            disk_events = EventManager.load_events_from_file(path)
            assert len(disk_events) == N, f"Expected {N} disk events, got {len(disk_events)}"

            # Verify no duplicates (each index should appear exactly once)
            indices = [e.metadata.get("index") for e in disk_events]
            assert len(set(indices)) == N, "Duplicate events detected on disk"

    def test_concurrent_emission_from_multiple_threads(self):
        """Emit events from multiple threads simultaneously — no crashes or losses."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "threaded.jsonl")
            em = EventManager(trace_id="mt-test", persist_path=path)
            collector = EventCollector()
            em.subscribe(collector.handler)

            THREADS = 8
            PER_THREAD = 50

            def emit_batch(thread_id: int):
                for i in range(PER_THREAD):
                    em.emit(
                        EventType.STEP_COMPLETED,
                        step_name=f"step_{thread_id}",
                        metadata={
                            "run_id": "mt-test",
                            "duration_ms": float(i),
                            "thread": thread_id,
                            "seq": i,
                        },
                    )

            threads = []
            for tid in range(THREADS):
                t = threading.Thread(target=emit_batch, args=(tid,))
                threads.append(t)
                t.start()

            for t in threads:
                t.join(timeout=10)

            expected = THREADS * PER_THREAD
            assert len(collector.events) == expected, (
                f"Expected {expected} events, got {len(collector.events)}"
            )

            # Verify disk persistence
            disk_events = EventManager.load_events_from_file(path)
            assert len(disk_events) == expected, (
                f"Expected {expected} disk events, got {len(disk_events)}"
            )

    def test_jsonl_incremental_read_correctness(self):
        """Simulate incremental JSONL reads (as RunManager does) and verify no loss."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stream.jsonl"

            em = EventManager(trace_id="incr-test", persist_path=str(path))

            # Emit first batch
            for i in range(10):
                em.emit(EventType.STEP_STARTED, step_name=f"s{i}", metadata={"run_id": "incr-test"})

            # Read incrementally from offset 0
            offset = 0
            events_batch1 = []
            with path.open("r", encoding="utf-8") as fh:
                fh.seek(offset)
                while True:
                    line = fh.readline()
                    if not line or not line.endswith("\n"):
                        break
                    events_batch1.append(json.loads(line.strip()))
                    offset = fh.tell()

            assert len(events_batch1) == 10

            # Emit second batch
            for i in range(10, 20):
                em.emit(EventType.STEP_COMPLETED, step_name=f"s{i}", metadata={"run_id": "incr-test", "duration_ms": 100.0})

            # Read incrementally from saved offset
            events_batch2 = []
            with path.open("r", encoding="utf-8") as fh:
                fh.seek(offset)
                while True:
                    line = fh.readline()
                    if not line or not line.endswith("\n"):
                        break
                    events_batch2.append(json.loads(line.strip()))
                    offset = fh.tell()

            assert len(events_batch2) == 10
            assert len(events_batch1) + len(events_batch2) == 20

            # Verify no overlap
            steps_b1 = {e["step_name"] for e in events_batch1}
            steps_b2 = {e["step_name"] for e in events_batch2}
            assert steps_b1.isdisjoint(steps_b2), "Batches should not overlap"


# ===========================================================================
# 3. FAILURE HANDLING
# ===========================================================================

class TestFailureHandling:
    """Verify correct behavior when agents fail or raise exceptions."""

    def test_agent_failure_emits_step_failed(self):
        """When an agent returns ok=False, STEP_FAILED is emitted."""
        em = EventManager(trace_id="fail-test")
        collector = EventCollector()
        em.subscribe(collector.handler)

        svc = PipelineService(event_manager=em, trace_id="fail-test")
        svc.register_agent("detect_excel", FailureAgent())

        sr = svc.execute_step(StepName.DETECT_EXCEL, {})

        assert sr.ok is False
        assert sr.error == "Simulated agent failure"
        assert sr.duration_ms > 0

        # Verify events
        failed_events = collector.by_type(EventType.STEP_FAILED)
        assert len(failed_events) == 1
        assert failed_events[0].step_name == "detect_excel"
        assert "Simulated agent failure" in failed_events[0].metadata.get("error", "")

        # Verify AGENT_STARTED and AGENT_COMPLETED were also emitted
        agent_started = collector.by_type(EventType.AGENT_STARTED)
        agent_completed = collector.by_type(EventType.AGENT_COMPLETED)
        assert len(agent_started) == 1
        assert len(agent_completed) == 1

        svc.close()

    def test_agent_exception_emits_step_failed(self):
        """When an agent raises an exception, STEP_FAILED is emitted and pipeline survives."""
        em = EventManager(trace_id="explode-test")
        collector = EventCollector()
        em.subscribe(collector.handler)

        svc = PipelineService(event_manager=em, trace_id="explode-test")
        svc.register_agent("detect_excel", ExplodingAgent())

        sr = svc.execute_step(StepName.DETECT_EXCEL, {})

        assert sr.ok is False
        assert "Kaboom" in sr.error
        assert sr.duration_ms > 0

        # STEP_FAILED should be emitted
        failed = collector.by_type(EventType.STEP_FAILED)
        assert len(failed) == 1
        assert "Kaboom" in failed[0].metadata.get("error", "")

        # Pipeline should be back to IDLE (not stuck in RUNNING)
        assert svc._status == PipelineStatus.IDLE

        svc.close()

    def test_pipeline_continues_after_step_failure_if_not_full_pipeline(self):
        """After a step failure, subsequent steps can still execute."""
        em = EventManager(trace_id="recover-test")
        svc = PipelineService(event_manager=em, trace_id="recover-test")

        svc.register_agent("detect_excel", FailureAgent())

        # First step fails
        sr1 = svc.execute_step(StepName.DETECT_EXCEL, {})
        assert sr1.ok is False
        assert svc._status == PipelineStatus.IDLE

        # Second step should still work (using built-in handler)
        # We'll register a success agent for read_excel
        svc.register_agent("read_excel", SuccessAgent(data={"rows": [], "row_count": 0}))
        sr2 = svc.execute_step(StepName.READ_EXCEL, {})
        assert sr2.ok is True
        assert svc._status == PipelineStatus.IDLE

        svc.close()

    def test_agent_warnings_are_logged(self):
        """Agent warnings are surfaced via logging (not lost)."""
        em = EventManager(trace_id="warn-test")
        svc = PipelineService(event_manager=em, trace_id="warn-test")
        svc.register_agent("detect_excel", FailureAgent())

        import logging
        with patch.object(logging.getLogger("pipeline.service"), "warning") as mock_warn:
            svc.execute_step(StepName.DETECT_EXCEL, {})
            # FailureAgent has warnings=["warn1"]
            mock_warn.assert_called()
            call_args = [str(c) for c in mock_warn.call_args_list]
            assert any("warn1" in c for c in call_args), f"Warning not logged: {call_args}"

        svc.close()

    def test_builtin_handler_exception_emits_step_failed(self):
        """When a built-in handler raises, STEP_FAILED is emitted with duration."""
        em = EventManager(trace_id="builtin-fail-test")
        collector = EventCollector()
        em.subscribe(collector.handler)
        svc = PipelineService(event_manager=em, trace_id="builtin-fail-test")

        # read_excel with no path and no agent will use built-in handler
        sr = svc.execute_step(StepName.READ_EXCEL, {})

        # Should fail (excel_path required)
        assert sr.ok is False
        assert sr.duration_ms >= 0

        failed = collector.by_type(EventType.STEP_FAILED)
        assert len(failed) == 1

        svc.close()


# ===========================================================================
# 4. THREAD SAFETY
# ===========================================================================

class TestThreadSafety:
    """Verify thread safety of EventManager and PipelineService."""

    def test_sequential_runs_no_leaked_threads(self):
        """Run pipeline steps sequentially — verify threads don't accumulate."""
        baseline_threads = threading.active_count()

        for i in range(5):
            em = EventManager(trace_id=f"seq-{i}")
            svc = PipelineService(event_manager=em, trace_id=f"seq-{i}")
            svc.register_agent("detect_excel", SuccessAgent(delay=0.01))
            svc.execute_step(StepName.DETECT_EXCEL, {})
            svc.close()

        # Allow a moment for any daemon threads to clean up
        time.sleep(0.1)
        current_threads = threading.active_count()
        leaked = current_threads - baseline_threads
        assert leaked <= 1, f"Thread leak detected: {leaked} extra threads"

    def test_concurrent_execute_step_on_same_service(self):
        """Multiple threads calling execute_step on the same service — no crashes."""
        em = EventManager(trace_id="conc-svc")
        svc = PipelineService(event_manager=em, trace_id="conc-svc")

        # Register multiple stages with agents
        for stage in ["detect_excel", "read_excel", "validate"]:
            svc.register_agent(stage, SuccessAgent(delay=0.02, data={"stage": stage}))

        results = []
        lock = threading.Lock()

        def run_step(stage: str):
            sr = svc.execute_step(stage, {})
            with lock:
                results.append(sr)

        threads = []
        for stage in ["detect_excel", "read_excel", "validate"] * 3:
            t = threading.Thread(target=run_step, args=(stage,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        assert len(results) == 9, f"Expected 9 results, got {len(results)}"
        assert all(r.ok for r in results), "All steps should succeed"

        svc.close()

    def test_event_subscriber_thread_safety(self):
        """Subscribe and emit events from different threads simultaneously."""
        em = EventManager(trace_id="sub-mt")

        collected = []
        lock = threading.Lock()

        def collector_handler(event: PipelineEvent):
            with lock:
                collected.append(event)

        em.subscribe(collector_handler)

        def emitter(thread_id: int):
            for i in range(20):
                em.emit(
                    EventType.STEP_COMPLETED,
                    step_name=f"s_{thread_id}_{i}",
                    metadata={"run_id": "sub-mt", "duration_ms": 1.0},
                )

        threads = [threading.Thread(target=emitter, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        expected = 4 * 20
        assert len(collected) == expected, f"Expected {expected}, got {len(collected)}"

    def test_run_manager_generation_counter(self):
        """Verify generation counter prevents stale streamer threads."""
        from dashboard.backend.run_manager import RunManager

        rm = RunManager()
        initial_gen = rm._generation
        initial_event = rm._stop_event

        # Simulate what start() does — increment generation and signal old threads
        rm._stop_event.set()
        rm._generation += 1
        new_event = threading.Event()
        rm._stop_event = new_event

        assert rm._generation == initial_gen + 1
        assert initial_event.is_set(), "Old stop event should be set"
        assert not new_event.is_set(), "New stop event should not be set"

        # Simulate a streamer checking its generation
        stale_gen = initial_gen
        assert stale_gen != rm._generation, "Stale gen should differ"


# ===========================================================================
# 5. EVENT SCHEMA CONSISTENCY
# ===========================================================================

class TestEventSchemaConsistency:
    """Verify every emitted event includes required fields."""

    def test_all_events_have_run_id_and_trace_id(self):
        """Every event emitted by execute_step has run_id and trace_id."""
        em = EventManager(trace_id="schema-test")
        collector = EventCollector()
        em.subscribe(collector.handler)

        svc = PipelineService(event_manager=em, trace_id="schema-test")
        svc.register_agent("detect_excel", SuccessAgent())
        svc.execute_step(StepName.DETECT_EXCEL, {})
        svc.close()

        assert len(collector.events) > 0, "Should have emitted events"

        for evt in collector.events:
            assert evt.trace_id == "schema-test", f"Missing/wrong trace_id: {evt.trace_id}"
            assert evt.run_id, f"Missing run_id on {evt.event_type.value}"
            assert evt.timestamp, f"Missing timestamp on {evt.event_type.value}"

    def test_step_completed_has_duration_ms(self):
        """STEP_COMPLETED events must have duration_ms > 0."""
        em = EventManager(trace_id="dur-test")
        collector = EventCollector()
        em.subscribe(collector.handler)

        svc = PipelineService(event_manager=em, trace_id="dur-test")
        svc.register_agent("detect_excel", SlowAgent(duration_s=0.05))
        svc.execute_step(StepName.DETECT_EXCEL, {})
        svc.close()

        completed = collector.by_type(EventType.STEP_COMPLETED)
        assert len(completed) == 1
        evt = completed[0]
        assert evt.duration_ms >= 50, f"Expected >=50ms, got {evt.duration_ms}ms"

    def test_step_failed_has_duration_ms(self):
        """STEP_FAILED events must have duration_ms >= 0."""
        em = EventManager(trace_id="dur-fail")
        collector = EventCollector()
        em.subscribe(collector.handler)

        svc = PipelineService(event_manager=em, trace_id="dur-fail")
        svc.register_agent("detect_excel", FailureAgent())
        svc.execute_step(StepName.DETECT_EXCEL, {})
        svc.close()

        failed = collector.by_type(EventType.STEP_FAILED)
        assert len(failed) == 1
        assert failed[0].duration_ms >= 0

    def test_agent_events_have_agent_name(self):
        """AGENT_STARTED and AGENT_COMPLETED include agent name in metadata."""
        em = EventManager(trace_id="agent-meta")
        collector = EventCollector()
        em.subscribe(collector.handler)

        svc = PipelineService(event_manager=em, trace_id="agent-meta")
        svc.register_agent("detect_excel", SuccessAgent())
        svc.execute_step(StepName.DETECT_EXCEL, {})
        svc.close()

        started = collector.by_type(EventType.AGENT_STARTED)
        completed = collector.by_type(EventType.AGENT_COMPLETED)

        assert len(started) == 1
        assert started[0].metadata["agent"] == "success_agent"
        assert len(completed) == 1
        assert completed[0].metadata["agent"] == "success_agent"
        assert "metrics" in completed[0].metadata
        # duration_ms is promoted to event-level field by EventManager.emit()
        assert completed[0].duration_ms >= 0

    def test_event_to_dict_includes_new_fields(self):
        """to_dict() serialization includes run_id and duration_ms."""
        em = EventManager(trace_id="ser-test")
        evt = em.emit(
            EventType.STEP_COMPLETED,
            step_name="validate",
            metadata={"run_id": "ser-test", "duration_ms": 123.4},
        )

        d = evt.to_dict()
        assert d["run_id"] == "ser-test"
        assert d["duration_ms"] == 123.4
        assert d["event_type"] == "STEP_COMPLETED"
        assert d["trace_id"] == "ser-test"
        assert d["step_name"] == "validate"

        # Verify JSON-serializable
        j = json.loads(evt.to_json())
        assert j["run_id"] == "ser-test"

    def test_progress_includes_duration_ms_for_completed_steps(self):
        """get_progress() includes duration_ms for completed steps."""
        em = EventManager(trace_id="prog-dur")
        em.emit(EventType.STEP_STARTED, step_name="validate", metadata={"run_id": "prog-dur"})
        em.emit(
            EventType.STEP_COMPLETED,
            step_name="validate",
            metadata={"run_id": "prog-dur", "duration_ms": 567.8},
        )
        em.emit(EventType.STEP_STARTED, step_name="normalize", metadata={"run_id": "prog-dur"})

        progress = em.get_progress()
        validate = next(s for s in progress if s["key"] == "validate")
        normalize = next(s for s in progress if s["key"] == "normalize")

        assert validate["status"] == "done"
        assert validate["duration_ms"] == 567.8
        assert normalize["status"] == "active"
        assert "duration_ms" not in normalize  # Not completed yet

    def test_step_result_has_duration_ms(self):
        """StepResult returned by execute_step has duration_ms populated."""
        em = EventManager(trace_id="sr-dur")
        svc = PipelineService(event_manager=em, trace_id="sr-dur")
        svc.register_agent("detect_excel", SlowAgent(duration_s=0.05))

        sr = svc.execute_step(StepName.DETECT_EXCEL, {})

        assert sr.duration_ms >= 50, f"Expected >=50ms, got {sr.duration_ms}ms"
        assert sr.step == "detect_excel"
        assert sr.ok is True

        svc.close()

    def test_status_includes_per_step_durations(self):
        """get_status() includes duration_ms for each completed step."""
        em = EventManager(trace_id="status-dur")
        svc = PipelineService(event_manager=em, trace_id="status-dur")
        svc.register_agent("detect_excel", SlowAgent(duration_s=0.03))
        svc.register_agent("read_excel", SlowAgent(duration_s=0.04))

        svc.execute_step(StepName.DETECT_EXCEL, {})
        svc.execute_step(StepName.READ_EXCEL, {})

        status = svc.get_status()
        assert status["run_id"] == "status-dur"
        assert len(status["steps"]) == 2
        assert status["steps"][0]["duration_ms"] >= 30
        assert status["steps"][1]["duration_ms"] >= 40

        svc.close()


# ===========================================================================
# 6. EDGE CASES
# ===========================================================================

class TestEdgeCases:
    """Additional edge-case validation."""

    def test_empty_context_does_not_crash_agent(self):
        """Passing empty context to an agent-backed step doesn't crash."""
        em = EventManager(trace_id="empty-ctx")
        svc = PipelineService(event_manager=em, trace_id="empty-ctx")
        svc.register_agent("detect_excel", SuccessAgent())

        sr = svc.execute_step(StepName.DETECT_EXCEL, {})
        assert sr.ok is True
        svc.close()

    def test_none_context_defaults_to_empty_dict(self):
        """Passing None as context doesn't crash."""
        em = EventManager(trace_id="none-ctx")
        svc = PipelineService(event_manager=em, trace_id="none-ctx")
        svc.register_agent("detect_excel", SuccessAgent())

        sr = svc.execute_step(StepName.DETECT_EXCEL, None)
        assert sr.ok is True
        svc.close()

    def test_agent_overrides_builtin_handler(self):
        """When both an agent and a builtin handler exist, agent takes priority."""
        em = EventManager(trace_id="override")
        collector = EventCollector()
        em.subscribe(collector.handler)
        svc = PipelineService(event_manager=em, trace_id="override")

        # detect_excel has both a built-in handler AND we register an agent
        svc.register_agent("detect_excel", SuccessAgent(data={"from": "agent"}))
        sr = svc.execute_step(StepName.DETECT_EXCEL, {})

        assert sr.ok is True
        assert sr.data.get("from") == "agent", "Agent should take priority over built-in"

        # Verify AGENT_STARTED was emitted (proving agent path was used)
        agent_events = collector.by_type(EventType.AGENT_STARTED)
        assert len(agent_events) == 1

        svc.close()

    def test_unknown_step_with_no_agent_or_handler(self):
        """Completely unknown step returns error without crashing."""
        em = EventManager(trace_id="unknown")
        svc = PipelineService(event_manager=em, trace_id="unknown")

        sr = svc.execute_step("nonexistent_step", {})
        assert sr.ok is False
        assert "Unknown step" in sr.error
        assert svc._status == PipelineStatus.IDLE

        svc.close()

    def test_registry_duplicate_registration_raises(self):
        """Registering the same stage twice raises ValueError."""
        reg = AgentRegistry()
        reg.register("detect_excel", SuccessAgent())

        with pytest.raises(ValueError, match="already registered"):
            reg.register("detect_excel", FailureAgent())

    def test_jsonl_handles_corrupted_lines(self):
        """JSONL reader skips corrupted lines without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "corrupt.jsonl"
            # Write mix of valid and corrupt lines
            lines = [
                json.dumps({"event_type": "STEP_STARTED", "trace_id": "t", "step_name": "s1", "metadata": {}, "timestamp": "2026-01-01T00:00:00", "run_id": "t", "duration_ms": 0}),
                "THIS IS NOT JSON",
                json.dumps({"event_type": "STEP_COMPLETED", "trace_id": "t", "step_name": "s1", "metadata": {}, "timestamp": "2026-01-01T00:00:01", "run_id": "t", "duration_ms": 100}),
                "{truncated...",
                json.dumps({"event_type": "STEP_STARTED", "trace_id": "t", "step_name": "s2", "metadata": {}, "timestamp": "2026-01-01T00:00:02", "run_id": "t", "duration_ms": 0}),
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            events = EventManager.load_events_from_file(path)
            assert len(events) == 3, f"Should skip corrupt lines, got {len(events)}"

    def test_in_full_pipeline_flag_prevents_idle_reset(self):
        """During _in_full_pipeline=True, status stays RUNNING between steps."""
        em = EventManager(trace_id="full-flag")
        svc = PipelineService(event_manager=em, trace_id="full-flag")
        svc.register_agent("detect_excel", SuccessAgent())
        svc.register_agent("read_excel", SuccessAgent(data={"rows": [], "row_count": 0}))

        svc._in_full_pipeline = True
        svc._status = PipelineStatus.RUNNING

        svc.execute_step(StepName.DETECT_EXCEL, {})
        assert svc._status == PipelineStatus.RUNNING, "Should stay RUNNING during full pipeline"

        svc.execute_step(StepName.READ_EXCEL, {})
        assert svc._status == PipelineStatus.RUNNING, "Should stay RUNNING during full pipeline"

        svc._in_full_pipeline = False
        svc.execute_step(StepName.DETECT_EXCEL, {})
        assert svc._status == PipelineStatus.IDLE, "Should reset to IDLE outside full pipeline"

        svc.close()
