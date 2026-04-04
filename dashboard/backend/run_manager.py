"""Enhanced RunManager with event bus integration for WebSocket broadcasting.

Progress tracking uses the structured EventManager system as the primary
source of truth, with regex-based log parsing as a backward-compatible
fallback for runs that pre-date the event system.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dashboard.backend.event_bus import event_bus

logger = logging.getLogger(__name__)

from project_root import get_project_root

PROJECT_ROOT = get_project_root()
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
LOG_PATH = ARTIFACTS_DIR / "ui_dashboard.log"
STATE_PATH = ARTIFACTS_DIR / "ui_state.json"
STATS_PATH = ARTIFACTS_DIR / "latest_stats.json"
EVENTS_PATH = ARTIFACTS_DIR / "pipeline_events.jsonl"

ALLOWED_ENV_KEYS = {
    "BASE_URL", "UI_USERNAME", "UI_PASSWORD",
    "DOM_BASE_URL", "DOM_USERNAME", "DOM_PASSWORD",
}


@dataclass
class RunState:
    running: bool = False
    mode: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    command: list[str] | None = None
    exit_code: int | None = None
    pid: int | None = None
    error: str | None = None
    trace_id: str = ""
    run_id: str = ""
    paused: bool = False
    step_durations: dict[str, float] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_url(url: str) -> bool:
    try:
        r = urlparse(url)
        return r.scheme in ("http", "https") and bool(r.netloc)
    except Exception:
        return False


class RunManager:
    """Manages pipeline subprocess lifecycle with event broadcasting."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._state = RunState()
        self._lock = threading.Lock()
        # Byte offsets for incremental file reads (seek-based, not line-index).
        self._log_byte_offset: int = 0
        self._event_byte_offset: int = 0
        # Generation counter: incremented on every start().  Streamer threads
        # check this and exit when stale, preventing duplicate streaming.
        self._generation: int = 0
        self._stop_event = threading.Event()

        # Restore persisted state (including trace_id)
        if STATE_PATH.exists():
            try:
                data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                self._state.mode = data.get("mode", "")
                self._state.exit_code = data.get("exit_code")
                self._state.started_at = data.get("started_at", 0)
                self._state.finished_at = data.get("finished_at", 0)
                self._state.trace_id = data.get("trace_id", "")
            except Exception:
                pass

    def start(
        self,
        mode: str = "pipeline",
        force: bool = False,
        scan: bool = False,
        env: dict[str, str] | None = None,
        config: str | None = None,
    ) -> RunState:
        with self._lock:
            if self._state.running:
                self._state.error = "A run is already in progress"
                return self._state

            # Signal any leftover streamer threads from a previous run to exit.
            self._stop_event.set()
            self._generation += 1
            my_gen = self._generation
            self._stop_event = threading.Event()

            ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

            # Clear event file from previous run so progress starts fresh
            try:
                from pipeline.events import EventManager
                EventManager.clear_file(EVENTS_PATH)
            except Exception:
                # pipeline package may not be on path in all contexts
                if EVENTS_PATH.exists():
                    EVENTS_PATH.write_text("", encoding="utf-8")
            # Reset byte offsets for the new run
            self._log_byte_offset = 0
            self._event_byte_offset = 0

            # Generate a trace_id for this run and propagate to subprocess
            try:
                from pipeline.trace import generate_trace_id
                trace_id = generate_trace_id()
            except Exception:
                import uuid
                trace_id = f"run-{int(time.time())}-{uuid.uuid4().hex[:4]}"
            cmd = self._build_cmd(mode, force, scan, config)
            clean_env = self._clean_env(env or {})

            proc_env = {**os.environ, **clean_env}
            proc_env["PYTHONUNBUFFERED"] = "1"
            proc_env["DOTENV_OVERRIDE"] = "1"
            proc_env["AI_STATS_PATH"] = str(STATS_PATH)
            proc_env["TRACE_ID"] = trace_id

            log_fh = open(LOG_PATH, "w", encoding="utf-8")

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    cwd=str(PROJECT_ROOT),
                    env=proc_env,
                )
            except Exception as exc:
                log_fh.close()
                self._state.error = str(exc)
                return self._state

            self._state = RunState(
                running=True,
                mode=mode,
                started_at=time.time(),
                command=cmd,
                pid=self._proc.pid,
                trace_id=trace_id,
            )
            self._persist_state()

            event_bus.publish({
                "type": "status",
                "data": {"running": True, "mode": mode, "pid": self._proc.pid, "trace_id": trace_id},
            })

            watcher = threading.Thread(
                target=self._watch, args=(log_fh,), daemon=True
            )
            watcher.start()

            # Start log/event streamer — passes generation counter for
            # safe cancellation when a new run starts.
            streamer = threading.Thread(
                target=self._stream_logs,
                args=(my_gen, self._stop_event),
                daemon=True,
            )
            streamer.start()

            return self._state

    def stop(self) -> RunState:
        with self._lock:
            if self._proc and self._state.running:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                except Exception:
                    pass
                self._state.running = False
                self._state.finished_at = time.time()
                self._state.exit_code = -1
                self._state.error = "Stopped by user"
                self._persist_state()
                event_bus.publish({"type": "status", "data": self._state.to_dict()})
            return self._state

    # Pause file sentinel path — used for cross-process pause signaling.
    _PAUSE_SENTINEL = ARTIFACTS_DIR / "pipeline_pause"

    def pause(self) -> None:
        """Signal the pipeline subprocess to pause between steps.

        Creates a sentinel file that the PipelineService config-driven loop
        checks between steps.
        """
        with self._lock:
            if self._state.running:
                ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
                self._PAUSE_SENTINEL.write_text("paused", encoding="utf-8")
                self._state.paused = True
                self._persist_state()
                event_bus.publish({
                    "type": "status",
                    "data": self._state.to_dict(),
                })
                logger.info("Pipeline pause requested")

    def resume(self) -> None:
        """Resume a paused pipeline subprocess."""
        with self._lock:
            if self._PAUSE_SENTINEL.exists():
                self._PAUSE_SENTINEL.unlink()
            self._state.paused = False
            self._persist_state()
            event_bus.publish({
                "type": "status",
                "data": self._state.to_dict(),
            })
            logger.info("Pipeline resume requested")

    def status(self) -> RunState:
        with self._lock:
            if self._proc and self._state.running:
                rc = self._proc.poll()
                if rc is not None:
                    self._state.running = False
                    self._state.finished_at = time.time()
                    self._state.exit_code = rc
                    self._persist_state()
            return self._state

    def tail(self, lines: int = 200) -> list[str]:
        if not LOG_PATH.exists():
            return []
        try:
            text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
            all_lines = text.splitlines()
            return all_lines[-min(lines, len(all_lines)):]
        except Exception:
            return []

    def get_progress(self) -> dict[str, Any]:
        """Determine pipeline stage progress.

        Primary source: structured events from ``pipeline_events.jsonl``
        (written by PipelineService in the subprocess).

        Fallback: regex-based log parsing for runs that pre-date the
        event system or when the events file is missing/empty.
        """
        # ── Try event-driven progress first ────────────────────────────
        try:
            from pipeline.events import EventManager
            if EventManager.has_events(EVENTS_PATH):
                steps = EventManager.get_progress_from_file(EVENTS_PATH)
                return {
                    "steps": steps,
                    "running": self._state.running,
                    "mode": self._state.mode,
                    "trace_id": self._state.trace_id,
                    "source": "events",
                }
        except Exception:
            # pipeline package not importable, or file read failed
            logger.debug("Event-based progress unavailable, falling back to log parsing")

        # ── Fallback: regex log parsing (backward compatibility) ───────
        return self._get_progress_from_logs()

    def _get_progress_from_logs(self) -> dict[str, Any]:
        """Legacy progress derivation by parsing log text with regex.

        Kept as a fallback for runs started before the event system was
        introduced.  Will be removed once all active runs use events.
        """
        steps = [
            {"key": "detect_excel", "label": "Upload & Parse", "status": "pending"},
            {"key": "read_excel", "label": "Read Excel", "status": "pending"},
            {"key": "validate", "label": "Schema Validation", "status": "pending"},
            {"key": "init_dom", "label": "DOM Extraction", "status": "pending"},
            {"key": "normalize", "label": "AI Normalisation", "status": "pending"},
            {"key": "generate", "label": "Feature Generation", "status": "pending"},
            {"key": "execute", "label": "Test Execution", "status": "pending"},
        ]

        if not LOG_PATH.exists():
            return {"steps": steps, "running": self._state.running, "mode": self._state.mode, "source": "logs"}

        try:
            log_text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return {"steps": steps, "running": self._state.running, "mode": self._state.mode, "source": "logs"}

        # Stage detection patterns — keys now match event step names
        stage_patterns = [
            ("detect_excel", r"(?:Reading Excel|read_excel|Auto-detected|Loading input|Excel detected)"),
            ("read_excel", r"(?:read_excel|Reading Excel)"),
            ("validate", r"(?:Schema validation|validate_schema|Validating schema)"),
            ("init_dom", r"(?:DOM extraction|extract_all_pages|DOM scan|Scanning DOM|DOMVectorStore|DOM KB)"),
            ("normalize", r"(?:Normali[sz]|AINormali[sz]er|normali[sz]e_tc|RAG)"),
            ("generate", r"(?:generate_feature|write_feature_file|Feature generation|Writing feature|Generating feature)"),
            ("execute", r"(?:run_tests|pytest|Test execution|Running tests|Executing tests)"),
        ]

        completed_stages = set()
        active_stage = None
        error_stage = None

        for key, pattern in stage_patterns:
            if re.search(pattern, log_text, re.IGNORECASE):
                completed_stages.add(key)

        # Check for errors
        if re.search(r"(?:ERROR|FAILED|Traceback)", log_text):
            for key, pattern in reversed(stage_patterns):
                if key in completed_stages:
                    error_stage = key
                    break

        # Determine active stage
        if self._state.running:
            for key, _ in reversed(stage_patterns):
                if key in completed_stages:
                    active_stage = key
                    break

        # Update step statuses
        past_active = False
        for step in steps:
            if error_stage and step["key"] == error_stage and not self._state.running:
                step["status"] = "error"
                past_active = True
            elif active_stage and step["key"] == active_stage and self._state.running:
                step["status"] = "active"
                past_active = True
            elif step["key"] in completed_stages and not past_active:
                step["status"] = "done"
            elif step["key"] in completed_stages and past_active:
                step["status"] = "done" if not self._state.running else "pending"

        # If not running and no error, mark all completed as done
        if not self._state.running and not error_stage:
            for step in steps:
                if step["key"] in completed_stages:
                    step["status"] = "done"

        return {
            "steps": steps,
            "running": self._state.running,
            "mode": self._state.mode,
            "source": "logs",
        }

    def _build_cmd(self, mode: str, force: bool, scan: bool, config: str | None = None) -> list[str]:
        if mode == "run-e2e" and not config:
            return ["python", "-m", "pytest", "generated/features/", "-v", "--tb=short"]
        cmd = ["python", "-u", "main.py"]
        if config:
            cmd.extend(["--config", config])
        else:
            if force:
                cmd.append("--force")
            if scan:
                cmd.append("--scan")
            if mode == "generate-only":
                cmd.append("--generate-only")
        if force and config:
            cmd.append("--force")
        if scan and config:
            cmd.append("--scan")
        return cmd

    def _clean_env(self, env: dict[str, str]) -> dict[str, str]:
        clean = {}
        for k, v in env.items():
            if k in ALLOWED_ENV_KEYS and v:
                if "URL" in k:
                    if validate_url(v):
                        clean[k] = v
                else:
                    clean[k] = v
        return clean

    def _watch(self, log_fh) -> None:
        try:
            self._proc.wait()
            rc = self._proc.returncode
            log_fh.write(f"\n[exit {rc}]\n")
            log_fh.flush()
        except Exception:
            rc = -1
        finally:
            log_fh.close()

        with self._lock:
            self._state.running = False
            self._state.finished_at = time.time()
            self._state.exit_code = rc
            if self._state.started_at:
                self._state.duration_ms = (self._state.finished_at - self._state.started_at) * 1000
            self._persist_state()

        # Store run in database
        self._save_run_to_db()

        event_bus.publish({
            "type": "status",
            "data": self._state.to_dict(),
        })
        event_bus.publish({
            "type": "run_complete",
            "data": {
                "exit_code": rc,
                "mode": self._state.mode,
                "run_id": self._state.run_id,
                "duration_ms": self._state.duration_ms,
                "step_durations": self._state.step_durations,
            },
        })

        # Signal the streamer thread to exit now that the run is finished.
        self._stop_event.set()

    def _stream_logs(self, generation: int, stop: threading.Event) -> None:
        """Tail log file and event file using byte-offset seeking.

        Uses ``open`` + ``seek`` + ``readline`` instead of
        ``read_text().splitlines()`` to avoid O(total_file_size) per poll
        and to prevent event loss from torn lines.

        Parameters
        ----------
        generation:
            The run-generation counter at the time this thread was spawned.
            The thread exits immediately when a newer generation starts.
        stop:
            Event that is set when a new run starts or the run finishes.
        """
        while not stop.is_set():
            # Generation guard: exit if a newer run has started
            if generation != self._generation:
                return

            try:
                # ── Stream log lines ───────────────────────────────────
                self._log_byte_offset = self._read_new_lines(
                    LOG_PATH, self._log_byte_offset,
                    lambda line: event_bus.publish({"type": "log", "line": line}),
                )

                # Broadcast latest stats alongside log lines
                if STATS_PATH.exists():
                    try:
                        stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
                        event_bus.publish({"type": "stats", "data": stats})
                    except Exception:
                        pass

                # ── Stream pipeline events ─────────────────────────────
                self._event_byte_offset = self._read_new_jsonl_events(
                    EVENTS_PATH, self._event_byte_offset,
                )
            except Exception:
                pass
            stop.wait(timeout=0.3)

    @staticmethod
    def _read_new_lines(path: Path, byte_offset: int, handler) -> int:
        """Incrementally read new *complete* lines from *path* starting at
        *byte_offset*.  Returns the updated byte offset.

        Only complete lines (ending with ``\\n``) are delivered to *handler*
        so that partially-flushed writes are retried on the next poll.
        """
        if not path.exists():
            return byte_offset
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(byte_offset)
                while True:
                    line = fh.readline()
                    if not line:
                        # EOF — nothing more to read
                        break
                    if not line.endswith("\n"):
                        # Partial line — don't advance offset; retry next poll
                        break
                    handler(line.rstrip("\n"))
                    byte_offset = fh.tell()
        except Exception:
            pass
        return byte_offset

    def _read_new_jsonl_events(self, path: Path, byte_offset: int) -> int:
        """Incrementally read new complete JSONL events and broadcast them.

        Only lines that end with ``\\n`` *and* parse as valid JSON are
        considered complete.  Partially-flushed lines are retried on the
        next poll cycle — the byte offset is NOT advanced past them, so
        no events are ever lost.
        """
        if not path.exists():
            return byte_offset
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(byte_offset)
                while True:
                    line = fh.readline()
                    if not line:
                        break
                    if not line.endswith("\n"):
                        # Incomplete line — do not advance offset
                        break
                    raw = line.strip()
                    if not raw:
                        byte_offset = fh.tell()
                        continue
                    try:
                        evt = json.loads(raw)
                        event_bus.publish({"type": "pipeline_event", "data": evt})

                        # Track run_id and per-step durations on state
                        if evt.get("run_id") and not self._state.run_id:
                            self._state.run_id = evt["run_id"]
                        step_name = evt.get("step_name", "")
                        evt_type = evt.get("event_type", "")
                        duration = evt.get("duration_ms", 0.0)
                        if step_name and duration and evt_type in ("STEP_COMPLETED", "STEP_FAILED"):
                            self._state.step_durations[step_name] = duration

                        byte_offset = fh.tell()
                    except (json.JSONDecodeError, ValueError):
                        # Corrupted line — skip it but advance offset
                        byte_offset = fh.tell()
        except Exception:
            pass
        return byte_offset

    def _save_run_to_db(self) -> None:
        """Save completed run to SQLite."""
        try:
            from dashboard.backend.db import insert_run

            latest_run = {}
            latest_run_path = ARTIFACTS_DIR / "latest_run.json"
            if latest_run_path.exists():
                latest_run = json.loads(latest_run_path.read_text(encoding="utf-8"))

            tests = latest_run.get("tests", {})
            run_data = {
                "id": self._state.run_id or self._state.trace_id or f"run_{int(self._state.started_at)}",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self._state.started_at)),
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self._state.finished_at)),
                "mode": self._state.mode,
                "trace_id": self._state.trace_id,
                "run_id": self._state.run_id,
                "excel_path": latest_run.get("excel", ""),
                "feature_path": latest_run.get("feature", ""),
                "version_folder": latest_run.get("version_folder", ""),
                "exit_code": self._state.exit_code,
                "passed": tests.get("passed", 0),
                "failed": tests.get("failed", 0),
                "errors": tests.get("errors", 0),
                "total": tests.get("total", 0),
                "regenerated": latest_run.get("regenerated", False),
                "duration_s": round(self._state.finished_at - self._state.started_at, 2),
                "duration_ms": self._state.duration_ms,
                "stats": latest_run.get("stats", {}),
                "cumulative": latest_run.get("cumulative", {}),
                "stage_timings": latest_run.get("stage_timings", []),
                "step_durations": self._state.step_durations,
            }
            insert_run(run_data)
        except Exception:
            logger.warning("Failed to save run to DB", exc_info=True)

    def _persist_state(self) -> None:
        """Atomic state persistence via write-to-temp-then-rename."""
        try:
            ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
            data = self._state.to_dict()
            data["log_path"] = str(LOG_PATH)
            data["stats_path"] = str(STATS_PATH)
            tmp = STATE_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, STATE_PATH)
        except Exception:
            logger.warning("Failed to persist state", exc_info=True)


# Singleton
run_manager = RunManager()
