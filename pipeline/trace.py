"""
Trace context — unique trace_id generation and log-level propagation.

Every pipeline execution (whether started from ``main.py``, the dashboard,
or a Neuro-SAN agent) gets a unique ``trace_id`` that appears in:

- every structured event (``PipelineEvent.trace_id``)
- every log line (via :class:`TraceFilter`)
- persisted artifacts (``latest_run.json``, ``run_summary.json``)
- the ``TRACE_ID`` environment variable (cross-process propagation)

Trace IDs are short, readable, and collision-free::

    run-20260404-143201-a7f3   (date-time-random suffix)
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextvars import ContextVar
from datetime import datetime

# ContextVar allows async / threaded code to carry trace_id implicitly.
_current_trace_id: ContextVar[str] = ContextVar("trace_id", default="")

# Environment variable used to propagate trace_id across process boundaries
# (dashboard → subprocess, agent → pipeline subprocess).
TRACE_ID_ENV = "TRACE_ID"


def generate_trace_id() -> str:
    """Create a human-readable, collision-free trace ID.

    Format: ``run-YYYYMMDD-HHMMSS-<4-hex>``

    The 4-hex suffix is derived from uuid4, giving ~65 k unique IDs per
    second — more than enough to avoid collisions.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = uuid.uuid4().hex[:4]
    return f"run-{ts}-{suffix}"


def resolve_trace_id(explicit: str | None = None) -> str:
    """Determine the trace_id to use for the current execution.

    Resolution order:
    1. *explicit* argument (caller-supplied)
    2. ``TRACE_ID`` environment variable (cross-process propagation)
    3. Generate a new one

    Side-effects:
    - Sets the contextvars token so :func:`current_trace_id` works.
    - Sets ``TRACE_ID`` in ``os.environ`` so child processes inherit it.
    """
    tid = (explicit or "").strip()
    if not tid:
        tid = os.environ.get(TRACE_ID_ENV, "").strip()
    if not tid:
        tid = generate_trace_id()

    _current_trace_id.set(tid)
    os.environ[TRACE_ID_ENV] = tid
    return tid


def current_trace_id() -> str:
    """Return the trace_id for the current context (empty if none set)."""
    return _current_trace_id.get()


# ---------------------------------------------------------------------------
# Logging integration
# ---------------------------------------------------------------------------

class TraceFilter(logging.Filter):
    """Logging filter that injects ``trace_id`` into every LogRecord.

    Install once on the root logger::

        install_trace_logging()

    Then use ``%(trace_id)s`` in your format string::

        "%(asctime)s [%(levelname)s] %(name)s [%(trace_id)s] %(message)s"
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = _current_trace_id.get() or "-"  # type: ignore[attr-defined]
        return True


_TRACE_FILTER_INSTALLED = False


def install_trace_logging() -> None:
    """Add :class:`TraceFilter` to the root logger and its handlers (idempotent).

    Python's ``logging.Filter`` on a logger only applies to records emitted
    *directly* by that logger — records propagated from child loggers bypass
    the filter.  To ensure **every** log record gets ``trace_id`` injected
    (including records from third-party libraries like ``httpx``, ``openai``,
    etc.), we also add the filter to each root handler.
    """
    global _TRACE_FILTER_INSTALLED
    if _TRACE_FILTER_INSTALLED:
        return
    trace_filter = TraceFilter()
    root = logging.getLogger()
    # Filter on the root logger itself (for records it emits directly)
    root.addFilter(trace_filter)
    # Filter on every handler so propagated child-logger records also get trace_id
    for handler in root.handlers:
        handler.addFilter(trace_filter)
    _TRACE_FILTER_INSTALLED = True
