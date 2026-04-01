from __future__ import annotations

import json
import mimetypes
import os
import socketserver
import base64
import glob
import re
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ai.security import validate_file_path

from ui.run_manager import (
    ARTIFACTS_DIR,
    LOG_PATH,
    RUN_MANAGER,
    STATE_PATH,
    STATS_PATH,
)


ROOT_DIR = Path(".").resolve()

WEB_STATIC_DIR = (ROOT_DIR / "ui" / "web_static").resolve()

_ALLOWED_FILE_ROOTS = [
    (ROOT_DIR / "artifacts").resolve(),
    (ROOT_DIR / "generated").resolve(),
    (ROOT_DIR / "docs").resolve(),
    (ROOT_DIR / "core").resolve(),
    (ROOT_DIR / "framework").resolve(),
]

_ALLOWED_TEXT_EXTS = {
    ".feature",
    ".json",
    ".log",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".mjs",
    ".ts",
    ".tsx",
    ".html",
    ".css",
    ".csv",
}

_ALLOWED_STATIC_EXTS = {
    ".html",
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".ico",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_allowed_root(path: Path) -> bool:
    rp = path.resolve()
    return any(str(rp).startswith(str(root) + os.sep) or rp == root for root in _ALLOWED_FILE_ROOTS)


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AutomationAcceleratorDashboard/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            # handled below
            pass
        else:
            # Serve any static file under ui/web_static (React SPA assets).
            rel = "index.html" if path in {"/", ""} else path.lstrip("/")
            self._serve_web_static(rel)
            return

        if path == "/api/status":
            self._handle_status()
            return
        if path == "/api/inputs":
            self._handle_inputs()
            return
        if path == "/api/logs":
            qs = parse_qs(parsed.query)
            lines = int(qs.get("lines", ["200"])[0])
            self._handle_logs(lines=lines)
            return
        if path == "/api/progress":
            self._handle_progress()
            return
        if path == "/api/runs":
            self._handle_runs()
            return
        if path == "/api/files":
            qs = parse_qs(parsed.query)
            root = qs.get("root", [""])[0]
            self._handle_files(root=root)
            return
        if path == "/api/file":
            qs = parse_qs(parsed.query)
            rel = qs.get("path", [""])[0]
            self._handle_file(path=rel)
            return

        self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/run":
            body = self._read_body_json()
            self._handle_run(body)
            return
        if parsed.path == "/api/clear_output":
            body = self._read_body_json() or {}
            self._handle_clear_output(body)
            return
        if parsed.path == "/api/upload_excel":
            body = self._read_body_json() or {}
            self._handle_upload_excel(body)
            return
        if parsed.path == "/api/stop":
            state = RUN_MANAGER.stop()
            self._json({"state": asdict(state)})
            return
        self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_status(self) -> None:
        state = RUN_MANAGER.status()

        status_payload: dict[str, Any] = {
            "state": asdict(state),
            "ui_state": _read_json(STATE_PATH) or {},
            "latest_run": _read_json(ARTIFACTS_DIR / "latest_run.json") or {},
            "latest_stats": _read_json(STATS_PATH) or _read_json(ARTIFACTS_DIR / "latest_stats.json") or {},
            "cumulative_stats": _read_json(ARTIFACTS_DIR / "cumulative_stats.json") or {},
        }
        self._json(status_payload)

    def _handle_inputs(self) -> None:
        """Return which Excel file the pipeline will use (best-effort).

        Mirrors main.detect_excel() logic at a high level.
        """
        input_dir = (ROOT_DIR / "input").resolve()
        if not input_dir.exists() or not input_dir.is_dir():
            self._json({"input_dir": "input", "files": [], "selected": None, "raw": None})
            return

        xlsx = sorted(glob.glob(str(input_dir / "*.xlsx")))
        files = [str(Path(p).resolve().relative_to(ROOT_DIR)) for p in xlsx]

        raw_files = [p for p in xlsx if "_raw" in os.path.basename(p)]
        template_files = [p for p in xlsx if "_raw" not in os.path.basename(p)]

        raw_path: str | None = None
        selected: str | None = None
        if raw_files:
            raw_path = raw_files[0] if len(raw_files) == 1 else raw_files[0]
            base = os.path.basename(raw_path).replace("_raw", "")
            selected = str((input_dir / base).resolve())
        elif template_files:
            selected = template_files[0] if len(template_files) == 1 else template_files[0]

        payload = {
            "input_dir": "input",
            "files": files,
            "selected": str(Path(selected).resolve().relative_to(ROOT_DIR)) if selected else None,
            "raw": str(Path(raw_path).resolve().relative_to(ROOT_DIR)) if raw_path else None,
        }
        self._json(payload)

    def _handle_clear_output(self, body: dict[str, Any]) -> None:
        state = RUN_MANAGER.status()
        if state.running:
            self._json({"error": "cannot clear while a run is active"}, status=HTTPStatus.CONFLICT)
            return

        cleared: list[str] = []

        def _rm(path: Path) -> None:
            try:
                if path.is_dir():
                    for p in sorted(path.rglob("*"), reverse=True):
                        if p.is_file():
                            p.unlink(missing_ok=True)
                    # remove empty dirs (but keep root)
                    for p in sorted(path.rglob("*"), reverse=True):
                        if p.is_dir():
                            try:
                                p.rmdir()
                            except Exception:
                                pass
                else:
                    path.unlink(missing_ok=True)
            except Exception:
                return

        # Generated feature files
        gen_features = (ROOT_DIR / "generated" / "features").resolve()
        if gen_features.exists():
            for f in gen_features.glob("*.feature"):
                try:
                    f.unlink(missing_ok=True)
                    cleared.append(str(f.relative_to(ROOT_DIR)))
                except Exception:
                    pass

        # Optional: generated step definitions from pipeline_cli (if used)
        steps_dir = (ROOT_DIR / "features" / "steps" / "step_definitions").resolve()
        for name in ["generated_steps.py", "generated_steps_enhanced.py"]:
            f = steps_dir / name
            if f.exists():
                try:
                    f.unlink(missing_ok=True)
                    cleared.append(str(f.relative_to(ROOT_DIR)))
                except Exception:
                    pass

        # UI run artifacts
        for p in [LOG_PATH, STATE_PATH, STATS_PATH, ARTIFACTS_DIR / "latest_run.json", ARTIFACTS_DIR / "latest_stats.json"]:
            if Path(p).exists():
                _rm(Path(p))
                try:
                    cleared.append(str(Path(p).resolve().relative_to(ROOT_DIR)))
                except Exception:
                    pass

        self._json({"cleared": cleared})

    def _handle_upload_excel(self, body: dict[str, Any]) -> None:
        state = RUN_MANAGER.status()
        if state.running:
            self._json({"error": "cannot upload while a run is active"}, status=HTTPStatus.CONFLICT)
            return

        filename = str(body.get("filename") or "").strip()
        content_b64 = str(body.get("content_base64") or "").strip()
        if not filename or not content_b64:
            self._json({"error": "missing filename or content_base64"}, status=HTTPStatus.BAD_REQUEST)
            return

        # Accept both raw base64 and data URLs.
        if "," in content_b64 and content_b64.lower().startswith("data:"):
            content_b64 = content_b64.split(",", 1)[1]

        if not filename.lower().endswith(".xlsx"):
            self._json({"error": "only .xlsx files are supported"}, status=HTTPStatus.BAD_REQUEST)
            return

        # Basic filename sanitization.
        safe_name = os.path.basename(filename)
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", safe_name)
        if not safe_name.lower().endswith(".xlsx"):
            safe_name += ".xlsx"

        input_dir = (ROOT_DIR / "input").resolve()
        input_dir.mkdir(parents=True, exist_ok=True)

        is_raw = "_raw" in os.path.splitext(safe_name)[0].lower()
        if is_raw:
            dest = input_dir / "ui_upload_raw.xlsx"
            keep = {"ui_upload_raw.xlsx", "ui_upload.xlsx"}
        else:
            dest = input_dir / "ui_upload.xlsx"
            keep = {"ui_upload.xlsx"}

        # Remove other Excel files so main.detect_excel() stays unambiguous.
        for p in input_dir.glob("*.xlsx"):
            if p.name in keep:
                continue
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

        try:
            raw = base64.b64decode(content_b64, validate=False)
        except Exception:
            self._json({"error": "invalid base64 payload"}, status=HTTPStatus.BAD_REQUEST)
            return

        # Simple size guard (25MB).
        if len(raw) > 25 * 1024 * 1024:
            self._json({"error": "file too large"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            dest.write_bytes(raw)
        except Exception as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._json(
            {
                "saved_as": str(dest.resolve().relative_to(ROOT_DIR)),
                "kind": "raw" if is_raw else "template",
            }
        )

    def _handle_logs(self, *, lines: int) -> None:
        lines = max(10, min(2000, int(lines)))
        self._json({"lines": RUN_MANAGER.tail(lines=lines), "log_path": str(LOG_PATH)})

    def _handle_progress(self) -> None:
        state = RUN_MANAGER.status()
        latest_run = _read_json(ARTIFACTS_DIR / "latest_run.json") or {}
        # Progress markers can appear early in the run; verbose AI logs can push them
        # out of a small tail window. Use a larger window for stable step detection.
        log_tail = RUN_MANAGER.tail(lines=8000)

        steps = _compute_progress_steps(state=state, latest_run=latest_run, log_lines=log_tail)
        self._json({"steps": steps, "running": bool(state.running), "mode": state.mode})

    def _handle_runs(self) -> None:
        versions_dir = (ROOT_DIR / "artifacts" / "versions").resolve()
        if not versions_dir.exists():
            self._json({"runs": []})
            return

        runs: list[dict[str, Any]] = []
        for folder in sorted(versions_dir.iterdir(), reverse=True):
            if not folder.is_dir():
                continue
            summary_path = folder / "run_summary.json"
            if not summary_path.exists():
                continue
            summary = _read_json(summary_path)
            if not isinstance(summary, dict):
                continue
            runs.append(
                {
                    "version_folder": str(folder.relative_to(ROOT_DIR)),
                    "completed_at": summary.get("completed_at"),
                    "mode": summary.get("mode"),
                    "regenerated": summary.get("regenerated"),
                    "excel": summary.get("excel"),
                    "feature": summary.get("feature"),
                    "tests": summary.get("tests", {}),
                    "stats": summary.get("stats", {}),
                }
            )

        self._json({"runs": runs})

    def _handle_files(self, *, root: str) -> None:
        roots = {
            "workspace": None,
            "artifacts": (ROOT_DIR / "artifacts").resolve(),
            "generated": (ROOT_DIR / "generated").resolve(),
            "docs": (ROOT_DIR / "docs").resolve(),
            "core": (ROOT_DIR / "core").resolve(),
            "framework": (ROOT_DIR / "framework").resolve(),
        }
        base = roots.get(root)
        if root != "workspace" and base is None:
            self._json({"error": "invalid root"}, status=HTTPStatus.BAD_REQUEST)
            return

        results: list[dict[str, Any]] = []
        bases = [b for b in roots.values() if isinstance(b, Path)] if root == "workspace" else [base]
        seen_paths: set[str] = set()

        for b in bases:
            if b is None:
                continue
            for p in sorted(b.rglob("*")):
                if p.is_dir():
                    continue
                try:
                    rel = str(p.resolve().relative_to(ROOT_DIR))
                except Exception:
                    continue
                if rel in seen_paths:
                    continue
                seen_paths.add(rel)

                # List everything under allowed roots; mark whether it can be opened.
                readable = p.suffix.lower() in _ALLOWED_TEXT_EXTS
                results.append({"path": rel, "size": p.stat().st_size, "readable": readable})

        self._json({"root": root, "files": results})

    def _handle_file(self, *, path: str) -> None:
        if not path:
            self._json({"error": "missing path"}, status=HTTPStatus.BAD_REQUEST)
            return

        # validate_file_path provides path traversal protection. Additionally, restrict
        # file reads to a small allow-list of roots and extensions.
        safe_abs = validate_file_path(path, allowed_root=ROOT_DIR)
        if safe_abs.suffix.lower() not in _ALLOWED_TEXT_EXTS:
            self._json({"error": "forbidden extension"}, status=HTTPStatus.FORBIDDEN)
            return
        if not _is_allowed_root(safe_abs):
            self._json({"error": "forbidden root"}, status=HTTPStatus.FORBIDDEN)
            return

        try:
            content = safe_abs.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        except Exception as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._json({"path": str(safe_abs.resolve().relative_to(ROOT_DIR)), "content": content})

    def _handle_run(self, body: dict[str, Any] | None) -> None:
        if not body:
            self._json({"error": "missing body"}, status=HTTPStatus.BAD_REQUEST)
            return

        mode = str(body.get("mode", "")).strip()
        force = bool(body.get("force", False))
        scan = bool(body.get("scan", False))
        env = body.get("env") if isinstance(body.get("env"), dict) else {}

        try:
            state = RUN_MANAGER.start(mode=mode, force=force, scan=scan, env=env)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._json({"state": asdict(state)})

    def _serve_web_static(self, rel_path: str) -> None:
        rel_path = (rel_path or "index.html").lstrip("/")
        abs_path = (WEB_STATIC_DIR / rel_path).resolve()

        if abs_path.suffix and abs_path.suffix.lower() not in _ALLOWED_STATIC_EXTS:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not str(abs_path).startswith(str(WEB_STATIC_DIR) + os.sep) and abs_path != WEB_STATIC_DIR:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not abs_path.exists() or abs_path.is_dir():
            # SPA fallback
            abs_path = (WEB_STATIC_DIR / "index.html").resolve()
            if not abs_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND)
                return

        ctype, _ = mimetypes.guess_type(str(abs_path))
        ctype = ctype or "application/octet-stream"

        data = abs_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except Exception:
            length = 0
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def _json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep terminal noise low; UI logs are in artifacts/ui_dashboard.log
        return


def serve(*, host: str = "127.0.0.1", port: int = 8123) -> None:
    Path("ui/web_static").mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    class _ReusableThreadingTCPServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    with _ReusableThreadingTCPServer((host, int(port)), DashboardHandler) as httpd:
        httpd.daemon_threads = True
        print(f"UI running on http://{host}:{port}")
        httpd.serve_forever()


def _compute_progress_steps(*, state, latest_run: dict[str, Any], log_lines: list[str]) -> list[dict[str, str]]:
    """Best-effort pipeline progress based on real logs + latest_run.json.

    Status values: pending | active | done | error
    """

    mode = (getattr(state, "mode", "") or "").strip()
    running = bool(getattr(state, "running", False))
    exit_code = getattr(state, "exit_code", None)

    text = "\n".join(log_lines or [])

    def seen(*needles: str) -> bool:
        return any(n in text for n in needles)

    steps: list[tuple[str, str]] = [
        ("upload", "Upload"),
        ("parse", "Parse"),
        ("dom", "DOM"),
        ("rag", "RAG"),
        ("generate", "Generate"),
        ("execute", "Execute"),
    ]

    # Markers in pipeline logs (main.py). Keep these intentionally broad.
    # IMPORTANT: some phrases indicate START of a stage (not completion).
    markers: dict[str, dict[str, tuple[str, ...]]] = {
        "upload": {
            "start": (
                "Raw Excel detected",
                "Excel detected",
                "Converting Raw Steps",
                "[RAW] Converting raw steps",
            ),
            "done": (
                "[RAW] Template generated:",
                "Template generated:",
                "[INFO] Excel detected:",
            ),
        },
        "parse": {
            "start": (
                "Validating schema",
            ),
            "done": (
                "Schema validated",
            ),
        },
        "dom": {
            "start": (
                "Building AI DOM Knowledge Base",
                "DOM Knowledge Extraction",
                "Scanning application pages",
                "Indexing UI elements",
                "DOM knowledge base not found",
                "AI DOM Knowledge Base Loaded From Cache",
                "DOM knowledge base exists — reusing stored knowledge",
                "running extraction",
                "Navigating to login",
            ),
            "done": (
                "AI DOM Knowledge Base Ready",
                "AI DOM Knowledge Base Loaded From Cache",
                "Total elements indexed",
                "re:Stored\\s+\\d+\\s+DOM elements",
                "DOM knowledge extracted and stored",
                "DOM knowledge base exists — reusing stored knowledge",
            ),
        },
        "rag": {
            "start": (
                "Initialising AI Normaliser",
                "Initializing AI Normalizer",
                "Normalising TC",
                "Normalizing",
                "Normalising",
            ),
            "done": (
                "Normalisation Summary",
                "AI steps normalized",
            ),
        },
        "generate": {
            "start": (
                "Generating feature file",
                "[INFO] Generating feature file",
            ),
            "done": (
                "Feature generated",
                "[INFO] Feature generated",
                "GENERATED FEATURE FILE",
            ),
        },
        "execute": {
            "start": (
                "[INFO] Executing tests",
                "Executing Generated Tests",
                "Fresh browser context created",
            ),
            "done": (
                "Pipeline Complete",
                "[exit ",
                "re:^=+.*(failed|passed).*$",
            ),
        },
    }

    # Compute last-seen line index of start/done markers.
    def last_pos(needles: tuple[str, ...]) -> int | None:
        if not needles:
            return None
        pos: int | None = None
        for idx, ln in enumerate(log_lines or []):
            for n in needles:
                if n.startswith("re:"):
                    # Regex marker
                    try:
                        import re

                        if re.search(n[3:], ln):
                            pos = idx
                            break
                    except Exception:
                        pass
                elif n in ln:
                    pos = idx
                    break
        return pos

    pos_start: dict[str, int | None] = {}
    pos_done: dict[str, int | None] = {}
    for key in (k for k, _ in steps):
        m = markers.get(key, {})
        pos_start[key] = last_pos(m.get("start", ()))
        pos_done[key] = last_pos(m.get("done", ()))

    def is_done(key: str) -> bool:
        # Upload has two variants:
        # - Raw Excel detected -> convert raw -> template generated (slower)
        # - Excel already present -> consider upload done immediately
        if key == "upload" and seen("Raw Excel detected"):
            return seen("[RAW] Template generated:") or seen("Template generated:")
        ds = pos_done.get(key)
        if ds is None:
            return False
        st = pos_start.get(key)
        # If we saw a done marker, treat as done.
        if st is None:
            return True
        return ds >= st

    done = {k: is_done(k) for k, _ in steps}

    # If we have a completed latest_run record and we're not currently running,
    # use it to set the final state.
    tests = latest_run.get("tests") if isinstance(latest_run, dict) else None
    if (not running) and isinstance(tests, dict) and ("exit_code" in tests or tests.get("skipped") is True):
        done["upload"] = True
        done["parse"] = True
        done["dom"] = True
        done["rag"] = True
        done["generate"] = True
        done["execute"] = tests.get("skipped") is not True

    # Decide which step is currently active (for blinking in UI).
    active_key: str | None = None

    # run-e2e mode is just Execute.
    if mode == "run-e2e":
        done = {k: False for k in done}
        # Consider execute complete when the process ends (exit_code set) or when
        # the UI watcher writes the exit marker.
        done["execute"] = (not running and exit_code is not None) or seen("[exit ")
        if running and not done.get("execute"):
            active_key = "execute"

    # Best-effort active stage selection for other modes.
    # This helps avoid the UI showing "Upload" active while DOM/test execution is actually running.
    if running and active_key is None:
        # Find the most recently started (not-yet-done) stage; that's active.
        active_pos: int = -1
        for key, _label in steps:
            stp = pos_start.get(key)
            if stp is None:
                continue
            if done.get(key):
                continue
            if stp > active_pos:
                active_pos = stp
                active_key = key

        # If nothing has started yet, default to first incomplete.
        if active_key is None:
            for key, _label in steps:
                if not done.get(key):
                    active_key = key
                    break

    has_error = False
    if running is False:
        if isinstance(tests, dict) and "exit_code" in tests and int(tests.get("exit_code") or 0) != 0:
            has_error = True
        if exit_code is not None and int(exit_code) != 0:
            has_error = True
    if seen("Traceback", "[ ERROR]", "[ERROR]"):
        has_error = True

    # Build final step list.
    result: list[dict[str, str]] = []
    for key, label in steps:
        status = "pending"
        if done.get(key):
            status = "done"
        elif running and active_key == key:
            status = "active"
        result.append({"key": key, "label": label, "status": status})

    # Safety: ensure exactly one active step while running.
    if running and not any(s.get("status") == "active" for s in result):
        for s in result:
            if s.get("status") == "pending":
                s["status"] = "active"
                break

    if has_error:
        # Attribute error to the last step for now.
        result[-1]["status"] = "error"

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Automation Accelerator browser UI")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8123, help="Bind port (default: 8123)")
    args = parser.parse_args()

    serve(host=args.host, port=args.port)
