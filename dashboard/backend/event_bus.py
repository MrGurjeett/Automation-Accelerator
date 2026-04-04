"""Thread-safe in-process pub/sub event bus for WebSocket broadcasting.

IMPORTANT: publish() is called from background threads (e.g. the RunManager
log-streaming thread) while subscribers are asyncio.Queues consumed on the
event loop.  We must use loop.call_soon_threadsafe() to bridge the gap.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """Thread-safe async pub/sub for broadcasting events to WebSocket clients."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the running event loop (call once from an async context)."""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
        self._subscribers.append(q)
        # Capture event loop on first subscription if not set
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def publish(self, event: dict[str, Any]) -> None:
        """Publish an event — safe to call from ANY thread."""
        loop = self._loop

        # If we have a loop and we're NOT in that loop's thread,
        # use call_soon_threadsafe to schedule the puts.
        if loop is not None and not self._is_in_loop_thread(loop):
            loop.call_soon_threadsafe(self._do_publish, event)
        else:
            self._do_publish(event)

    def _do_publish(self, event: dict[str, Any]) -> None:
        """Actually enqueue the event (must run on the event-loop thread)."""
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("EventBus: subscriber queue full, dropping event")

    @staticmethod
    def _is_in_loop_thread(loop: asyncio.AbstractEventLoop) -> bool:
        """Check if we're currently running inside the event loop's thread."""
        try:
            running = asyncio.get_running_loop()
            return running is loop
        except RuntimeError:
            return False

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Global singleton
event_bus = EventBus()
