"""
EventManager — structured event system for pipeline observability.

Replaces fragile regex-based log parsing with first-class events.
Existing logging is preserved — events are an additional, structured
layer that becomes the source of truth for progress tracking.

Example event JSON::

    {
        "event_type": "STEP_COMPLETED",
        "timestamp": "2026-04-04T14:32:01",
        "trace_id": "run_1743782400",
        "step_name": "validate",
        "metadata": {
            "validated_count": 3,
            "rejected_count": 1
        }
    }
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("pipeline.events")


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    PIPELINE_STARTED = "PIPELINE_STARTED"
    PIPELINE_COMPLETED = "PIPELINE_COMPLETED"
    PIPELINE_FAILED = "PIPELINE_FAILED"
    PIPELINE_PAUSED = "PIPELINE_PAUSED"
    PIPELINE_RESUMED = "PIPELINE_RESUMED"
    STEP_STARTED = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    STEP_FAILED = "STEP_FAILED"
    STEP_SKIPPED = "STEP_SKIPPED"
    BRANCH_TAKEN = "BRANCH_TAKEN"
    DECISION_TAKEN = "DECISION_TAKEN"
    RETRY_DECISION = "RETRY_DECISION"
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    ERROR_OCCURRED = "ERROR_OCCURRED"


# ---------------------------------------------------------------------------
# Event data class
# ---------------------------------------------------------------------------

@dataclass
class PipelineEvent:
    """Single structured event emitted during pipeline execution.

    Attributes
    ----------
    event_type : EventType
        Classification of the event.
    trace_id : str
        Cross-process trace identifier for correlation.
    step_name : str
        Pipeline stage that emitted this event (empty for pipeline-level events).
    metadata : dict
        Arbitrary payload (step-specific data, error details, metrics).
    timestamp : str
        ISO-8601 timestamp of when the event was created.
    run_id : str
        Unique identifier for the pipeline execution instance.
        Typically equals trace_id but kept separate for future multi-run support.
    duration_ms : float
        Elapsed time for the operation (populated on COMPLETED/FAILED events).
    """

    event_type: EventType
    trace_id: str
    step_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    run_id: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# Type alias for subscriber callbacks
EventHandler = Callable[[PipelineEvent], None]


# ---------------------------------------------------------------------------
# EventManager
# ---------------------------------------------------------------------------

class EventManager:
    """Central hub for emitting and consuming pipeline events.

    Supports:
      - In-memory event log (queryable via ``get_events()``)
      - Subscriber callbacks (for real-time broadcasting, e.g. WebSocket)
      - Optional file persistence (append-only JSON lines)

    Usage::

        em = EventManager(trace_id="run_123")
        em.subscribe(lambda e: print(e.to_json()))
        em.emit(EventType.PIPELINE_STARTED, metadata={"mode": "pipeline"})
    """

    def __init__(
        self,
        trace_id: str | None = None,
        persist_path: str | Path | None = None,
    ) -> None:
        self._trace_id = trace_id or f"run_{int(time.time())}"
        self._events: list[PipelineEvent] = []
        self._subscribers: list[EventHandler] = []
        self._persist_path = Path(persist_path) if persist_path else None
        self._lock = threading.Lock()

        if self._persist_path:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def trace_id(self) -> str:
        return self._trace_id

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: EventType,
        step_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PipelineEvent:
        """Create, store, and broadcast an event.

        If ``metadata`` contains ``run_id`` or ``duration_ms``, those values
        are promoted to first-class fields on the :class:`PipelineEvent`.
        """
        meta = dict(metadata) if metadata else {}
        run_id = meta.pop("run_id", "")
        duration_ms = meta.pop("duration_ms", 0.0)

        event = PipelineEvent(
            event_type=event_type,
            trace_id=self._trace_id,
            step_name=step_name,
            metadata=meta,
            run_id=run_id or self._trace_id,
            duration_ms=duration_ms,
        )

        with self._lock:
            self._events.append(event)

            # Persist to file (JSON lines) — under the lock to prevent
            # interleaved writes from concurrent threads.
            if self._persist_path:
                try:
                    with self._persist_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(event.to_dict(), default=str) + "\n")
                except Exception:
                    logger.warning("Failed to persist event to %s", self._persist_path, exc_info=True)

        # Notify subscribers (outside lock to avoid deadlocks with
        # subscribers that call back into EventManager).
        for handler in self._subscribers:
            try:
                handler(event)
            except Exception:
                logger.warning("Event handler failed", exc_info=True)

        # Also log for backward compatibility
        logger.info("[EVENT] %s step=%s trace=%s", event_type.value, step_name, self._trace_id)

        return event

    def subscribe(self, handler: EventHandler) -> None:
        """Register a callback that receives every future event."""
        self._subscribers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a previously registered callback."""
        try:
            self._subscribers.remove(handler)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_events(
        self,
        event_type: EventType | None = None,
        step_name: str | None = None,
    ) -> list[PipelineEvent]:
        """Return stored events, optionally filtered."""
        result = self._events
        if event_type is not None:
            result = [e for e in result if e.event_type == event_type]
        if step_name is not None:
            result = [e for e in result if e.step_name == step_name]
        return list(result)

    def get_progress(self) -> list[dict[str, Any]]:
        """Derive pipeline progress from in-memory events.

        Returns a list of step dicts with status: pending | active | done | error.
        """
        return EventManager._derive_progress(self._events)

    @property
    def event_count(self) -> int:
        return len(self._events)

    def clear(self) -> None:
        """Clear in-memory event log."""
        self._events.clear()

    # ------------------------------------------------------------------
    # Cross-process support (file-based)
    # ------------------------------------------------------------------

    @staticmethod
    def load_events_from_file(path: str | Path) -> list[PipelineEvent]:
        """Load events from a JSONL file written by another process.

        This is the bridge that lets the dashboard process (RunManager)
        read events emitted by the pipeline subprocess.
        """
        p = Path(path)
        if not p.exists():
            return []

        events: list[PipelineEvent] = []
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    events.append(PipelineEvent(
                        event_type=EventType(d["event_type"]),
                        trace_id=d.get("trace_id", ""),
                        step_name=d.get("step_name", ""),
                        metadata=d.get("metadata", {}),
                        timestamp=d.get("timestamp", ""),
                        run_id=d.get("run_id", ""),
                        duration_ms=float(d.get("duration_ms", 0.0)),
                    ))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        except Exception:
            logger.warning("Failed to load events from %s", path, exc_info=True)

        return events

    @staticmethod
    def get_progress_from_file(path: str | Path) -> list[dict[str, Any]]:
        """Derive pipeline progress by reading a JSONL event file.

        Returns the same format as ``get_progress()`` but reads from disk
        instead of in-memory state — designed for cross-process use.
        """
        events = EventManager.load_events_from_file(path)
        return EventManager._derive_progress(events)

    # Default step list for backward compatibility (pre-config runs)
    _DEFAULT_ORDERED_STEPS = [
        ("detect_excel", "Upload & Parse"),
        ("read_excel", "Read Excel"),
        ("validate", "Schema Validation"),
        ("init_dom", "DOM Extraction"),
        ("normalize", "AI Normalisation"),
        ("generate", "Feature Generation"),
        ("execute", "Test Execution"),
    ]

    @staticmethod
    def _derive_progress(events: list[PipelineEvent]) -> list[dict[str, Any]]:
        """Shared logic: turn a list of events into a progress array.

        Each entry includes ``duration_ms`` when available (from STEP_COMPLETED
        or STEP_FAILED events).

        If a PIPELINE_STARTED event contains a ``steps`` metadata field
        (from config-driven pipelines), that defines the step list.
        Otherwise falls back to the hardcoded default for backward compat.
        """
        # Try to extract step list from PIPELINE_STARTED event
        ordered_steps = None
        for e in events:
            if e.event_type == EventType.PIPELINE_STARTED:
                config_steps = e.metadata.get("steps")
                if config_steps and isinstance(config_steps, list):
                    ordered_steps = [
                        (s.get("key", ""), s.get("label", ""))
                        for s in config_steps
                        if s.get("key")
                    ]
                break

        if not ordered_steps:
            ordered_steps = EventManager._DEFAULT_ORDERED_STEPS

        started: set[str] = set()
        completed: set[str] = set()
        failed: set[str] = set()
        skipped: set[str] = set()
        durations: dict[str, float] = {}

        for e in events:
            if e.event_type == EventType.STEP_STARTED:
                started.add(e.step_name)
            elif e.event_type == EventType.STEP_COMPLETED:
                completed.add(e.step_name)
                if e.duration_ms:
                    durations[e.step_name] = e.duration_ms
            elif e.event_type == EventType.STEP_FAILED:
                failed.add(e.step_name)
                if e.duration_ms:
                    durations[e.step_name] = e.duration_ms
            elif e.event_type == EventType.STEP_SKIPPED:
                skipped.add(e.step_name)

        progress = []
        for key, label in ordered_steps:
            if key in failed:
                status = "error"
            elif key in completed:
                status = "done"
            elif key in skipped:
                status = "skipped"
            elif key in started:
                status = "active"
            else:
                status = "pending"
            entry: dict[str, Any] = {"key": key, "label": label, "status": status}
            if key in durations:
                entry["duration_ms"] = round(durations[key], 1)
            progress.append(entry)

        return progress

    @staticmethod
    def has_events(path: str | Path) -> bool:
        """Check if a JSONL event file exists and is non-empty."""
        p = Path(path)
        return p.exists() and p.stat().st_size > 0

    @staticmethod
    def clear_file(path: str | Path) -> None:
        """Truncate the JSONL event file (for new runs)."""
        p = Path(path)
        if p.exists():
            p.write_text("", encoding="utf-8")
