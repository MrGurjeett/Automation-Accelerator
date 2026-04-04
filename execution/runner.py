"""
Execution Runner — automatically runs pytest after feature generation.

Executes generated BDD scenarios via subprocess.
Returns structured result with pass/fail counts.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import ai.ai_stats as ai_stats

logger = logging.getLogger(__name__)

TEST_MODULE = "core/steps/test_generated.py"


@dataclass
class TestResult:
    """Structured test execution result."""

    exit_code: int
    passed: int
    failed: int
    errors: int
    total: int

    @property
    def success(self) -> bool:
        return self.exit_code == 0


def run_tests() -> TestResult:
    """Execute pytest on the generated feature tests.

    Uses the same Python interpreter to invoke pytest as a subprocess
    so that all pytest.ini settings (headed, chromium, etc.) are respected.

    Returns
    -------
    TestResult
        Structured result with pass/fail/error counts.
    """
    logger.info("═══════════════════════════════════════════════════════")
    logger.info("  Executing Generated Tests")
    logger.info("═══════════════════════════════════════════════════════")

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        TEST_MODULE,
        "-v",
        "--tb=short",
        "--no-header",
        "--run-e2e",
    ]

    logger.info("Command: %s", " ".join(cmd))

    # Ensure AA_ROOT is correct for the subprocess.  The .env file may
    # contain a stale value; we always override with the *actual* project
    # root (the directory containing main.py, i.e. our working directory).
    env = os.environ.copy()
    project_root = Path(__file__).resolve().parent.parent
    env["AA_ROOT"] = str(project_root)

    # Run pytest ONCE: stream output in real time AND capture for parsing.
    # (Previously we ran twice: once for streaming, once for parsing.)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(project_root),
    )

    captured: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        # Preserve pytest output in the console/UI log.
        print(line, end="")
        captured.append(line.rstrip("\n"))

    rc = proc.wait()

    passed = failed = errors = total = 0
    # Parse counts from the captured pytest summary.
    for raw in captured[::-1]:
        line = raw.strip()
        if not line:
            continue
        # Typical summary: "1 failed, 3 passed, 1 warning in 182.68s"
        if ("passed" in line) or ("failed" in line) or ("error" in line) or ("errors" in line):
            p = re.search(r"(\d+)\s+passed", line)
            f = re.search(r"(\d+)\s+failed", line)
            e = re.search(r"(\d+)\s+error(?:s)?", line)
            if p:
                passed = int(p.group(1))
            if f:
                failed = int(f.group(1))
            if e:
                errors = int(e.group(1))
            if p or f or e:
                total = passed + failed + errors
                break

    test_result = TestResult(
        exit_code=int(rc),
        passed=passed,
        failed=failed,
        errors=errors,
        total=total,
    )

    logger.info("───── Test Execution Summary ─────")
    if test_result.total > 0:
        logger.info("  Total:  %d", test_result.total)
        logger.info("  Passed: %d", test_result.passed)
        if test_result.failed:
            logger.error("  Failed: %d", test_result.failed)
        if test_result.errors:
            logger.error("  Errors: %d", test_result.errors)
    else:
        logger.warning("  Could not parse test counts from output.")

    if test_result.success:
        logger.info("  Status: ALL PASSED")
    else:
        logger.error("  Status: FAILURES DETECTED (exit code %d)", test_result.exit_code)

    # ── AI Execution Summary ────────────────────────────────────────
    print()
    print("=" * 60)
    print("  AI Execution Summary")
    print("-" * 60)
    print(f"  DOM elements indexed:    {ai_stats.get('dom_elements')}")
    raw_converted = ai_stats.get('raw_steps_converted')
    if raw_converted > 0:
        print(f"  Raw steps converted:     {raw_converted}")
    print(f"  AI steps normalized:     {ai_stats.get('normalized_steps')}")
    print(f"  RAG resolutions:         {ai_stats.get('rag_resolutions')}")
    print(f"  Locator healing used:    {ai_stats.get('locator_healing')}")
    print(f"  Tests executed:          {test_result.total}")
    print(f"  Tests passed:            {test_result.passed}")
    print(f"  Tests failed:            {test_result.failed}")
    print("=" * 60)
    print()

    return test_result
