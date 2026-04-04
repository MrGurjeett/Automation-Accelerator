"""SQLite database for run history and stage timing persistence."""
from __future__ import annotations

import json
import sqlite3
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from project_root import get_project_root

_PROJECT_ROOT = get_project_root()
DB_PATH = _PROJECT_ROOT / "artifacts" / "runs.db"


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                started_at TEXT,
                completed_at TEXT,
                mode TEXT,
                excel_path TEXT,
                feature_path TEXT,
                version_folder TEXT,
                exit_code INTEGER,
                passed INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                regenerated INTEGER DEFAULT 0,
                duration_s REAL DEFAULT 0,
                stats_json TEXT DEFAULT '{}',
                cumulative_json TEXT DEFAULT '{}',
                stage_timings_json TEXT DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS stage_timings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT REFERENCES runs(id),
                stage TEXT,
                started_at REAL,
                completed_at REAL,
                duration_s REAL,
                status TEXT DEFAULT 'done'
            );

            CREATE INDEX IF NOT EXISTS idx_runs_completed ON runs(completed_at);
            CREATE INDEX IF NOT EXISTS idx_stage_run ON stage_timings(run_id);
        """)
        conn.commit()
    finally:
        conn.close()


def insert_run(run_data: dict[str, Any]) -> None:
    """Insert a run record."""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO runs
            (id, started_at, completed_at, mode, excel_path, feature_path,
             version_folder, exit_code, passed, failed, errors, total,
             regenerated, duration_s, stats_json, cumulative_json, stage_timings_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_data.get("id", ""),
            run_data.get("started_at", ""),
            run_data.get("completed_at", ""),
            run_data.get("mode", ""),
            run_data.get("excel_path", ""),
            run_data.get("feature_path", ""),
            run_data.get("version_folder", ""),
            run_data.get("exit_code"),
            run_data.get("passed", 0),
            run_data.get("failed", 0),
            run_data.get("errors", 0),
            run_data.get("total", 0),
            1 if run_data.get("regenerated") else 0,
            run_data.get("duration_s", 0),
            json.dumps(run_data.get("stats", {})),
            json.dumps(run_data.get("cumulative", {})),
            json.dumps(run_data.get("stage_timings", [])),
        ))
        conn.commit()
    finally:
        conn.close()


def get_all_runs(limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    """Return all runs ordered by most recent first."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY completed_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_run(run_id: str) -> dict[str, Any] | None:
    """Return a single run by ID."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_analytics() -> dict[str, Any]:
    """Return aggregate analytics data for charts."""
    conn = _get_conn()
    try:
        # Recent runs for charts
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY completed_at DESC LIMIT 50"
        ).fetchall()
        runs = [_row_to_dict(r) for r in rows]

        # Aggregates
        agg = conn.execute("""
            SELECT
                COUNT(*) as total_runs,
                AVG(duration_s) as avg_duration,
                SUM(passed) as total_passed,
                SUM(failed) as total_failed,
                SUM(total) as total_tests,
                ROUND(100.0 * SUM(CASE WHEN exit_code = 0 THEN 1 ELSE 0 END) / MAX(COUNT(*), 1), 1) as success_rate
            FROM runs
        """).fetchone()

        return {
            "runs": runs,
            "summary": dict(agg) if agg else {},
        }
    finally:
        conn.close()


def migrate_from_versions() -> int:
    """Backfill runs table from existing artifacts/versions/ folders."""
    versions_dir = _PROJECT_ROOT / "artifacts" / "versions"
    if not versions_dir.exists():
        return 0

    count = 0
    for folder in sorted(versions_dir.iterdir()):
        if not folder.is_dir():
            continue
        summary_path = folder / "run_summary.json"
        if not summary_path.exists():
            continue

        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            run_id = folder.name
            tests = data.get("tests") or {}
            run_data = {
                "id": run_id,
                "started_at": data.get("started_at", ""),
                "completed_at": data.get("completed_at", ""),
                "mode": data.get("mode", "pipeline"),
                "excel_path": data.get("excel", ""),
                "feature_path": data.get("feature", ""),
                "version_folder": str(folder),
                "exit_code": tests.get("exit_code"),
                "passed": tests.get("passed", 0),
                "failed": tests.get("failed", 0),
                "errors": tests.get("errors", 0),
                "total": tests.get("total", 0),
                "regenerated": data.get("regenerated", False),
                "duration_s": data.get("duration_s", 0),
                "stats": data.get("stats", {}),
                "cumulative": data.get("cumulative", {}),
                "stage_timings": data.get("stage_timings", []),
            }
            insert_run(run_data)
            count += 1
        except Exception:
            logger.warning("Failed to migrate %s", folder.name, exc_info=True)

    return count


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for key in ("stats_json", "cumulative_json", "stage_timings_json"):
        if key in d and isinstance(d[key], str):
            try:
                d[key.replace("_json", "")] = json.loads(d[key])
            except json.JSONDecodeError:
                d[key.replace("_json", "")] = {}
            del d[key]
    return d
