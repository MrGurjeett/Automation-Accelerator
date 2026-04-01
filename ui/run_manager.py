from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.security import safe_subprocess_args, validate_url


ARTIFACTS_DIR = Path("artifacts")
LOG_PATH = ARTIFACTS_DIR / "ui_dashboard.log"
STATE_PATH = ARTIFACTS_DIR / "ui_state.json"
STATS_PATH = ARTIFACTS_DIR / "latest_stats.json"

_ALLOWED_ENV_KEYS = {
    "BASE_URL",
    "UI_USERNAME",
    "UI_PASSWORD",
    "DOM_BASE_URL",
    "DOM_USERNAME",
    "DOM_PASSWORD",
}

_URL_KEYS = {"BASE_URL", "DOM_BASE_URL"}


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


class RunManager:
    """Manages a single background run and streams logs to a file."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._state = RunState()

        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    def start(
        self,
        *,
        mode: str,
        force: bool = False,
        scan: bool = False,
        env: dict[str, str] | None = None,
    ) -> RunState:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return self._state

            cleaned_env = self._clean_env(env or {})
            cmd = self._build_cmd(mode=mode, force=force, scan=scan)

            # Ensure stats file is for this run.
            try:
                STATS_PATH.unlink(missing_ok=True)
            except Exception:
                pass

            merged_env = dict(os.environ)
            merged_env.update(cleaned_env)
            merged_env.setdefault("AI_STATS_PATH", str(STATS_PATH))
            # Ensure Python prints/logs stream to the UI log file in real time.
            merged_env.setdefault("PYTHONUNBUFFERED", "1")

            # Safety checks (defense in depth)
            cmd = safe_subprocess_args(cmd)

            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            log_fh = open(LOG_PATH, "w", encoding="utf-8")
            log_fh.write("$ " + " ".join(cmd) + "\n")
            log_fh.flush()

            self._state = RunState(
                running=True,
                mode=mode,
                started_at=time.time(),
                command=cmd,
                exit_code=None,
                pid=None,
                error=None,
            )

            self._proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                text=True,
                env=merged_env,
            )
            self._state.pid = self._proc.pid
            self._persist_state()

            t = threading.Thread(target=self._watch, args=(log_fh,), daemon=True)
            t.start()
            return self._state

    def stop(self) -> RunState:
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return self._state
            try:
                self._proc.terminate()
            except Exception:
                pass
            return self._state

    def status(self) -> RunState:
        with self._lock:
            if self._proc is not None:
                rc = self._proc.poll()
                if rc is not None and self._state.running:
                    self._state.running = False
                    self._state.exit_code = int(rc)
                    self._state.finished_at = time.time()
                    self._persist_state()
            return self._state

    def tail(self, *, lines: int = 200) -> list[str]:
        try:
            text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []
        all_lines = text.splitlines()
        return all_lines[-max(1, int(lines)) :]

    def _watch(self, log_fh) -> None:
        try:
            rc = self._proc.wait() if self._proc is not None else 0
        except Exception as exc:
            with self._lock:
                self._state.error = str(exc)
                self._state.running = False
                self._state.exit_code = 1
                self._state.finished_at = time.time()
                self._persist_state()
            try:
                log_fh.write(f"\n[ui] watcher exception: {exc}\n")
            except Exception:
                pass
            try:
                log_fh.close()
            except Exception:
                pass
            return

        with self._lock:
            self._state.running = False
            self._state.exit_code = int(rc)
            self._state.finished_at = time.time()
            self._persist_state()
        try:
            log_fh.write(f"\n[exit {rc}]\n")
            log_fh.close()
        except Exception:
            pass

    def _build_cmd(self, *, mode: str, force: bool, scan: bool) -> list[str]:
        py = sys.executable
        if mode == "generate-only":
            cmd = [py, "-u", "main.py", "--generate-only"]
        elif mode == "pipeline":
            cmd = [py, "-u", "main.py"]
        elif mode == "run-e2e":
            cmd = [py, "-u", "-m", "pytest", "core/steps/test_generated.py", "--run-e2e", "-q"]
        elif mode == "run-only":
            # Run from existing generated feature (pipeline logic handles reuse)
            cmd = [py, "-u", "main.py"]
        else:
            raise ValueError(f"Unknown mode: {mode}")

        if mode in {"generate-only", "pipeline", "run-only"}:
            if force:
                cmd.append("--force")
            if scan:
                cmd.append("--scan")
        return cmd

    def _clean_env(self, env: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for k, v in (env or {}).items():
            if k not in _ALLOWED_ENV_KEYS:
                continue
            if v is None:
                continue
            v = str(v).strip()
            if not v:
                continue
            if k in _URL_KEYS:
                v = validate_url(v)
            cleaned[k] = v
        return cleaned

    def _persist_state(self) -> None:
        import json

        payload: dict[str, Any] = {
            "running": self._state.running,
            "mode": self._state.mode,
            "started_at": self._state.started_at,
            "finished_at": self._state.finished_at,
            "command": self._state.command,
            "exit_code": self._state.exit_code,
            "pid": self._state.pid,
            "error": self._state.error,
            "log_path": str(LOG_PATH),
            "stats_path": str(STATS_PATH),
        }
        STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


RUN_MANAGER = RunManager()
