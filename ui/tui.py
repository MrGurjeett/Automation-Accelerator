from __future__ import annotations

import curses
import os
import shlex
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from queue import Queue, Empty


ARTIFACTS_DIR = Path("artifacts")
DEFAULT_STATS_PATH = ARTIFACTS_DIR / "latest_stats.json"
DEFAULT_RUN_PATH = ARTIFACTS_DIR / "latest_run.json"
DEFAULT_CUMULATIVE_PATH = ARTIFACTS_DIR / "cumulative_stats.json"


@dataclass
class RunConfig:
    force: bool = False
    scan: bool = False


class Dashboard:
    def __init__(self, stdscr) -> None:
        self.stdscr = stdscr
        self.log_lines: deque[str] = deque(maxlen=400)
        self.status: str = "Idle"
        self.last_command: str = ""
        self.last_exit_code: int | None = None
        self._proc: subprocess.Popen[str] | None = None
        self._q: Queue[str] = Queue()
        self._reader_thread: threading.Thread | None = None
        self._env: dict[str, str] = {}
        self.cfg = RunConfig()

        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        # Propagate shared stats path so subprocess + pytest can write live stats.
        os.environ.setdefault("AI_STATS_PATH", str(DEFAULT_STATS_PATH))

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _read_json_stats(self, path: Path) -> dict:
        import json

        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self._env)
        env.setdefault("AI_STATS_PATH", str(DEFAULT_STATS_PATH))
        return env

    def _prompt(self, label: str, current: str = "") -> str | None:
        h, w = self.stdscr.getmaxyx()
        prompt = f"{label} [{current}]: "
        self.stdscr.move(h - 2, 0)
        self.stdscr.clrtoeol()
        self.stdscr.addnstr(h - 2, 0, prompt, w - 1)
        curses.echo()
        try:
            value = self.stdscr.getstr(h - 2, min(len(prompt), w - 2)).decode("utf-8").strip()
        except Exception:
            value = ""
        finally:
            curses.noecho()
        self.stdscr.move(h - 2, 0)
        self.stdscr.clrtoeol()
        if value == "":
            return None
        return value

    def _start_process(self, args: list[str]) -> None:
        if self._proc is not None:
            return

        env = self._build_env()
        # Reset shared stats at the start of a run.
        try:
            DEFAULT_STATS_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        cmd_str = " ".join(shlex.quote(a) for a in args)
        self.last_command = cmd_str
        self.status = "Running"
        self.last_exit_code = None
        self.log_lines.append(f"$ {cmd_str}")

        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
        )

        def _reader() -> None:
            assert self._proc is not None
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                self._q.put(line.rstrip("\n"))

        self._reader_thread = threading.Thread(target=_reader, daemon=True)
        self._reader_thread.start()

    def _poll_process(self) -> None:
        if self._proc is None:
            return

        # Drain output queue.
        while True:
            try:
                line = self._q.get_nowait()
            except Empty:
                break
            self.log_lines.append(line)

        rc = self._proc.poll()
        if rc is not None:
            self.last_exit_code = int(rc)
            self.status = "Done" if rc == 0 else "Failed"
            self.log_lines.append(f"[exit {rc}]")
            self._proc = None
            self._reader_thread = None

    def _toggle_force(self) -> None:
        self.cfg.force = not self.cfg.force

    def _toggle_scan(self) -> None:
        self.cfg.scan = not self.cfg.scan

    def _cmd_generate_only(self) -> list[str]:
        args = [sys.executable, "main.py", "--generate-only"]
        if self.cfg.force:
            args.append("--force")
        if self.cfg.scan:
            args.append("--scan")
        return args

    def _cmd_full_pipeline(self) -> list[str]:
        args = [sys.executable, "main.py"]
        if self.cfg.force:
            args.append("--force")
        if self.cfg.scan:
            args.append("--scan")
        return args

    def _cmd_run_e2e_only(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "pytest",
            "core/steps/test_generated.py",
            "--run-e2e",
            "-q",
        ]

    def _set_env_var(self, key: str, label: str, secret: bool = False) -> None:
        current = self._env.get(key) or os.environ.get(key, "")
        shown = "***" if (secret and current) else current
        val = self._prompt(label, shown)
        if val is None:
            return
        self._env[key] = val

    def _render(self) -> None:
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()

        # Header
        header = f"Automation Accelerator (Terminal UI) | Status: {self.status} | force={self.cfg.force} scan={self.cfg.scan}"
        self.stdscr.addnstr(0, 0, header, w - 1, curses.A_REVERSE)

        # Menu
        menu_lines = [
            "Operations:",
            "  1) Generate only",
            "  2) Run E2E only",
            "  3) Full pipeline",
            "",
            "Toggles:",
            "  f) toggle --force",
            "  s) toggle --scan",
            "",
            "Env:",
            "  b) BASE_URL",
            "  u) UI_USERNAME",
            "  p) UI_PASSWORD",
            "  B) DOM_BASE_URL",
            "  U) DOM_USERNAME",
            "  P) DOM_PASSWORD",
            "",
            "Other:",
            "  c) clear logs",
            "  q) quit",
        ]

        left_w = min(36, max(28, w // 4))
        for i, line in enumerate(menu_lines, start=2):
            if i >= h - 2:
                break
            self.stdscr.addnstr(i, 1, line, left_w - 2)

        # Stats panel
        stats = self._read_json_stats(DEFAULT_STATS_PATH).get("stats", {})
        run = self._read_json_stats(DEFAULT_RUN_PATH)
        cum = self._read_json_stats(DEFAULT_CUMULATIVE_PATH).get("cumulative", {})

        stats_lines = [
            "Latest Stats:",
            f"  tokens_total:      {stats.get('tokens_total', 0)}",
            f"  tokens_saved:      {stats.get('tokens_saved_total', 0)}",
            f"  aoai_calls(chat):  {stats.get('aoai_chat_calls', 0)}",
            f"  aoai_calls(embed): {stats.get('aoai_embedding_calls', 0)}",
            f"  aoai_cache_hits:   {stats.get('aoai_cache_hits', 0)}",
            f"  rag_resolutions:   {stats.get('rag_resolutions', 0)}",
            f"  locator_healing:   {stats.get('locator_healing', 0)}",
            "",
            "Cumulative:",
            f"  runs:              {cum.get('runs', 0)}",
            f"  tokens_total:      {cum.get('tokens_total', 0)}",
            f"  tokens_saved:      {cum.get('tokens_saved_total', 0)}",
        ]

        stats_x = left_w + 1
        for i, line in enumerate(stats_lines, start=2):
            if i >= h - 2:
                break
            self.stdscr.addnstr(i, stats_x, line, w - stats_x - 1)

        # Artifacts panel (below stats, best-effort)
        artifacts_y = 2 + len(stats_lines) + 1
        if artifacts_y < h - 4:
            latest_folder = run.get("version_folder") or ""
            feature = run.get("feature") or ""
            mode = run.get("mode") or ""

            # Recent generated feature files
            recent_features: list[str] = []
            try:
                feats = sorted(Path("generated/features").glob("*.feature"), key=lambda p: p.stat().st_mtime, reverse=True)
                recent_features = [str(p) for p in feats[:3]]
            except Exception:
                recent_features = []

            artifacts = [
                "Latest Run:",
                f"  mode:   {mode}",
                f"  folder: {latest_folder}",
                f"  feature:{feature}",
                "  recent:",
                *[f"    - {p}" for p in recent_features],
            ]
            for i, line in enumerate(artifacts, start=artifacts_y):
                if i >= h - 2:
                    break
                self.stdscr.addnstr(i, stats_x, line, w - stats_x - 1)

        # Logs panel (right side, bottom)
        log_top = 2
        log_left = stats_x
        log_h = h - 2 - log_top
        log_w = w - log_left - 1

        # If stats panel is wide, logs share same column; show logs at bottom half
        # Keep it simple: render logs starting from mid-screen.
        log_start_row = max(artifacts_y + 6, h // 2)
        if log_start_row < h - 2:
            self.stdscr.addnstr(log_start_row, log_left, "Logs (tail):", log_w)
            visible = list(self.log_lines)[-(h - log_start_row - 3) :]
            for idx, line in enumerate(visible, start=log_start_row + 1):
                if idx >= h - 2:
                    break
                self.stdscr.addnstr(idx, log_left, line, log_w)

        # Footer
        footer = f"Last cmd: {self.last_command}"
        if self.last_exit_code is not None:
            footer += f" | exit={self.last_exit_code}"
        self.stdscr.addnstr(h - 1, 0, footer, w - 1, curses.A_REVERSE)

        self.stdscr.refresh()

    def loop(self) -> None:
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.timeout(150)

        while True:
            self._poll_process()
            self._render()

            ch = self.stdscr.getch()
            if ch == -1:
                continue

            if ch in (ord("q"), ord("Q")):
                break
            if ch == ord("c"):
                self.log_lines.clear()
                continue
            if ch == ord("f"):
                self._toggle_force()
                continue
            if ch == ord("s"):
                self._toggle_scan()
                continue

            if ch == ord("1"):
                self._start_process(self._cmd_generate_only())
                continue
            if ch == ord("2"):
                self._start_process(self._cmd_run_e2e_only())
                continue
            if ch == ord("3"):
                self._start_process(self._cmd_full_pipeline())
                continue

            # Env edits
            if ch == ord("b"):
                self._set_env_var("BASE_URL", "BASE_URL")
                continue
            if ch == ord("u"):
                self._set_env_var("UI_USERNAME", "UI_USERNAME")
                continue
            if ch == ord("p"):
                self._set_env_var("UI_PASSWORD", "UI_PASSWORD", secret=True)
                continue
            if ch == ord("B"):
                self._set_env_var("DOM_BASE_URL", "DOM_BASE_URL")
                continue
            if ch == ord("U"):
                self._set_env_var("DOM_USERNAME", "DOM_USERNAME")
                continue
            if ch == ord("P"):
                self._set_env_var("DOM_PASSWORD", "DOM_PASSWORD", secret=True)
                continue


def main() -> None:
    def _wrapped(stdscr):
        Dashboard(stdscr).loop()

    curses.wrapper(_wrapped)


if __name__ == "__main__":
    main()
