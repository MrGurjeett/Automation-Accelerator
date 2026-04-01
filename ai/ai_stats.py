"""
AI Stats — shared counters for the AI Execution Summary.

Tracks DOM indexing, AI normalisation, RAG resolution, and locator healing
counts across the pipeline. Read-only consumers call get(); producers call
increment().

Thread-safe via simple dict (CPython GIL sufficient for this use case).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


ai_stats: dict[str, int] = {
    "dom_elements": 0,
    "pages_scanned": 0,
    "raw_steps_converted": 0,
    "normalized_steps": 0,
    "rag_resolutions": 0,
    "locator_healing": 0,

    # Azure OpenAI usage (when available)
    "aoai_chat_calls": 0,
    "aoai_embedding_calls": 0,
    "aoai_cache_hits": 0,

    # Token accounting
    "tokens_prompt": 0,
    "tokens_completion": 0,
    "tokens_total": 0,
    # Tokens avoided due to cache hits (cumulative within a run)
    "tokens_saved_total": 0,
}


def _stats_path() -> Path | None:
    path = (os.environ.get("AI_STATS_PATH") or "").strip()
    if not path:
        return None
    return Path(path)


def _persist() -> None:
    """Persist current stats to AI_STATS_PATH (if set).

    Uses atomic replace to avoid partial reads.
    """
    path = _stats_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "updated_at": int(time.time()),
        "stats": dict(ai_stats),
    }
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def snapshot() -> dict[str, int]:
    """Get a point-in-time copy of all counters."""
    return dict(ai_stats)


def load_from_file(path: str | os.PathLike) -> dict[str, int]:
    """Load stats from a persisted JSON file."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("stats"), dict):
            return {str(k): int(v) for k, v in data["stats"].items()}
    except Exception:
        return {}
    return {}


def increment(key: str, amount: int = 1) -> None:
    """Increment a counter by the given amount."""
    ai_stats[key] = ai_stats.get(key, 0) + amount
    _persist()


def get(key: str) -> int:
    """Get the current value of a counter."""
    return ai_stats.get(key, 0)


def reset() -> None:
    """Reset all counters to zero."""
    for key in ai_stats:
        ai_stats[key] = 0
    _persist()
