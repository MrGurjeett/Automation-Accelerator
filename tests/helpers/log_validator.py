"""
Log Validator — assertions on structured pipeline events.

Provides helper functions to validate that expected events were emitted
during a pipeline run, without fragile regex-based log parsing.

Works with :class:`pipeline.events.EventManager` event lists.

Usage::

    from tests.helpers.log_validator import (
        assert_event_emitted,
        assert_event_not_emitted,
        assert_event_sequence,
        get_events_by_type,
        get_events_by_step,
        assert_step_failed,
        assert_recovery_triggered,
        assert_decision_taken,
        assert_retry_decision,
        assert_fallback_used,
    )

    events = event_manager.get_events()
    assert_step_failed(events, "validate")
    assert_recovery_triggered(events, "recover_validation")
    assert_decision_taken(events, source="mcp")
"""
from __future__ import annotations

from typing import Any

from pipeline.events import EventType, PipelineEvent


# ---------------------------------------------------------------------------
# Core query helpers
# ---------------------------------------------------------------------------

def get_events_by_type(
    events: list[PipelineEvent],
    event_type: EventType | str,
) -> list[PipelineEvent]:
    """Filter events by type."""
    target = event_type.value if isinstance(event_type, EventType) else event_type
    return [e for e in events if e.event_type == target]


def get_events_by_step(
    events: list[PipelineEvent],
    step_name: str,
) -> list[PipelineEvent]:
    """Filter events by step name."""
    return [e for e in events if e.step_name == step_name]


def get_events_by_type_and_step(
    events: list[PipelineEvent],
    event_type: EventType | str,
    step_name: str,
) -> list[PipelineEvent]:
    """Filter events by both type and step."""
    target = event_type.value if isinstance(event_type, EventType) else event_type
    return [e for e in events if e.event_type == target and e.step_name == step_name]


# ---------------------------------------------------------------------------
# Assertions — event presence
# ---------------------------------------------------------------------------

def assert_event_emitted(
    events: list[PipelineEvent],
    event_type: EventType | str,
    step_name: str | None = None,
    metadata_contains: dict[str, Any] | None = None,
    message: str = "",
) -> PipelineEvent:
    """Assert that at least one event of the given type was emitted.

    Optionally filter by step_name and/or metadata fields.
    Returns the first matching event.
    """
    target = event_type.value if isinstance(event_type, EventType) else event_type

    matches = [e for e in events if e.event_type == target]
    if step_name is not None:
        matches = [e for e in matches if e.step_name == step_name]
    if metadata_contains:
        matches = [
            e for e in matches
            if all(e.metadata.get(k) == v for k, v in metadata_contains.items())
        ]

    label = message or f"Expected event {target}"
    if step_name:
        label += f" for step '{step_name}'"
    if metadata_contains:
        label += f" with metadata {metadata_contains}"

    assert len(matches) > 0, f"{label} — not found in {len(events)} events"
    return matches[0]


def assert_event_not_emitted(
    events: list[PipelineEvent],
    event_type: EventType | str,
    step_name: str | None = None,
    message: str = "",
) -> None:
    """Assert that NO event of the given type was emitted."""
    target = event_type.value if isinstance(event_type, EventType) else event_type

    matches = [e for e in events if e.event_type == target]
    if step_name is not None:
        matches = [e for e in matches if e.step_name == step_name]

    label = message or f"Expected NO event {target}"
    if step_name:
        label += f" for step '{step_name}'"

    assert len(matches) == 0, f"{label} — found {len(matches)} events"


def assert_event_sequence(
    events: list[PipelineEvent],
    expected_types: list[EventType | str],
    message: str = "",
) -> None:
    """Assert that events appear in the given order (not necessarily contiguous).

    Checks that for each expected type, there's a matching event that comes
    after the position of the previous match.
    """
    actual_types = [e.event_type for e in events]
    search_from = 0

    for expected in expected_types:
        target = expected.value if isinstance(expected, EventType) else expected
        try:
            idx = actual_types.index(target, search_from)
            search_from = idx + 1
        except ValueError:
            label = message or f"Expected event sequence {[str(e) for e in expected_types]}"
            actual_str = [str(t) for t in actual_types]
            assert False, (
                f"{label} — could not find '{target}' at or after position "
                f"{search_from} in {actual_str}"
            )


# ---------------------------------------------------------------------------
# High-level semantic assertions
# ---------------------------------------------------------------------------

def assert_step_failed(
    events: list[PipelineEvent],
    step_name: str,
    error_contains: str | None = None,
) -> PipelineEvent:
    """Assert STEP_FAILED was emitted for the given step."""
    evt = assert_event_emitted(
        events, EventType.STEP_FAILED, step_name=step_name,
        message=f"Step '{step_name}' should have failed",
    )
    if error_contains:
        error = evt.metadata.get("error", "")
        assert error_contains.lower() in error.lower(), (
            f"STEP_FAILED error for '{step_name}' should contain '{error_contains}', "
            f"got: '{error}'"
        )
    return evt


def assert_step_completed(
    events: list[PipelineEvent],
    step_name: str,
) -> PipelineEvent:
    """Assert STEP_COMPLETED was emitted for the given step."""
    return assert_event_emitted(
        events, EventType.STEP_COMPLETED, step_name=step_name,
        message=f"Step '{step_name}' should have completed successfully",
    )


def assert_step_skipped(
    events: list[PipelineEvent],
    step_name: str,
) -> PipelineEvent:
    """Assert STEP_SKIPPED was emitted for the given step."""
    return assert_event_emitted(
        events, EventType.STEP_SKIPPED, step_name=step_name,
        message=f"Step '{step_name}' should have been skipped",
    )


def assert_recovery_triggered(
    events: list[PipelineEvent],
    recovery_step: str,
) -> PipelineEvent:
    """Assert that a recovery agent was started for the given step."""
    return assert_event_emitted(
        events, EventType.AGENT_STARTED, step_name=recovery_step,
        metadata_contains={"agent": "mcp_recovery"},
        message=f"MCPRecoveryAgent should have been triggered for '{recovery_step}'",
    )


def assert_decision_taken(
    events: list[PipelineEvent],
    source: str | None = None,
    from_step: str | None = None,
    selected: str | None = None,
) -> PipelineEvent:
    """Assert a DECISION_TAKEN event was emitted with optional filters."""
    metadata_filter: dict[str, Any] = {}
    if source:
        metadata_filter["source"] = source
    if from_step:
        metadata_filter["from_step"] = from_step
    if selected:
        metadata_filter["selected"] = selected

    return assert_event_emitted(
        events,
        EventType.DECISION_TAKEN,
        metadata_contains=metadata_filter or None,
        message="DECISION_TAKEN event expected",
    )


def assert_retry_decision(
    events: list[PipelineEvent],
    step_name: str | None = None,
    retry: bool | None = None,
    source: str | None = None,
) -> PipelineEvent:
    """Assert a RETRY_DECISION event was emitted with optional filters."""
    metadata_filter: dict[str, Any] = {}
    if step_name:
        metadata_filter["step"] = step_name
    if retry is not None:
        metadata_filter["retry"] = retry
    if source:
        metadata_filter["source"] = source

    return assert_event_emitted(
        events,
        EventType.RETRY_DECISION,
        metadata_contains=metadata_filter or None,
        message="RETRY_DECISION event expected",
    )


def assert_fallback_used(
    events: list[PipelineEvent],
    step_name: str | None = None,
) -> PipelineEvent:
    """Assert that deterministic fallback was used (DECISION_TAKEN with source='deterministic')."""
    metadata_filter: dict[str, Any] = {"source": "deterministic"}
    if step_name:
        metadata_filter["from_step"] = step_name

    return assert_event_emitted(
        events,
        EventType.DECISION_TAKEN,
        metadata_contains=metadata_filter,
        message="Deterministic fallback should have been used",
    )


def assert_branch_taken(
    events: list[PipelineEvent],
    from_step: str,
    to_step: str,
    branch_type: str | None = None,
) -> PipelineEvent:
    """Assert a BRANCH_TAKEN event connecting two steps."""
    metadata_filter: dict[str, Any] = {
        "from_step": from_step,
        "to_step": to_step,
    }
    if branch_type:
        metadata_filter["branch"] = branch_type

    return assert_event_emitted(
        events,
        EventType.BRANCH_TAKEN,
        metadata_contains=metadata_filter,
        message=f"Branch from '{from_step}' to '{to_step}' expected",
    )


def assert_no_mcp_decisions(events: list[PipelineEvent]) -> None:
    """Assert that no MCP-sourced decisions were made (all should be deterministic or absent)."""
    decision_events = get_events_by_type(events, EventType.DECISION_TAKEN)
    mcp_decisions = [
        e for e in decision_events if e.metadata.get("source") == "mcp"
    ]
    assert len(mcp_decisions) == 0, (
        f"Expected no MCP-sourced decisions, found {len(mcp_decisions)}: "
        f"{[(e.step_name, e.metadata) for e in mcp_decisions]}"
    )


def summarize_events(events: list[PipelineEvent]) -> str:
    """Return a human-readable summary of all events (for debugging)."""
    lines = []
    for e in events:
        meta = ", ".join(f"{k}={v}" for k, v in e.metadata.items() if k != "run_id")
        lines.append(f"  [{e.event_type}] {e.step_name or '(pipeline)'} {meta}")
    return f"Events ({len(events)}):\n" + "\n".join(lines)
