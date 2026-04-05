#!/usr/bin/env python
"""Test script: Automation-Accelerator -> NeuraSan integration.

Verifies that AA can trigger NeuraSan agent execution through the server
and that the conversation appears in NSFlow UI.

Usage:
    python test_neurasan.py                  # Full test (server exec + CRUSE thread)
    python test_neurasan.py --check-only     # Health check only
    python test_neurasan.py --http-only      # Skip WebSocket, use HTTP only
    python test_neurasan.py --open-browser   # Open NSFlow UI for LIVE animation
    python test_neurasan.py --prompt "..."   # Custom prompt

To see live yellow-to-green animation in NSFlow UI:
    python test_neurasan.py --open-browser
    Then type your prompt in the NSFlow chat panel.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Fix Windows console encoding for Unicode symbols
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test NeuraSan integration")
    parser.add_argument("--check-only", action="store_true", help="Health check only")
    parser.add_argument("--http-only", action="store_true", help="Use HTTP (no WebSocket)")
    parser.add_argument("--open-browser", action="store_true",
                        help="Open NSFlow UI in browser for LIVE animation")
    parser.add_argument("--prompt", default=None, help="Custom prompt to send")
    parser.add_argument("--config", default="test-decision", help="Pipeline config name")
    parser.add_argument("--nsflow-port", type=int, default=4173, help="NSFlow port")
    parser.add_argument("--backend-port", type=int, default=8080, help="Backend port")
    args = parser.parse_args()

    from pipeline.integration.neurasan_bridge import (
        check_server,
        open_in_browser,
        run_neurasan_agent,
    )

    # == Step 1: Health check ==
    print("\n" + "=" * 64)
    print("  NeuraSan Integration Test")
    print("=" * 64)

    print("\n[1/3] Checking server health...")
    status = check_server(
        nsflow_port=args.nsflow_port,
        backend_port=args.backend_port,
    )

    nsflow_ok = status.get("nsflow", {}).get("ok", False)
    backend_ok = status.get("backend", {}).get("ok", False)
    agent_ok = status.get("agent_registered", {}).get("ok", False)

    print(f"  NSFlow (:{args.nsflow_port}):      {'PASS' if nsflow_ok else 'FAIL'}")
    print(f"  Backend (:{args.backend_port}):     {'PASS' if backend_ok else 'FAIL'}")
    print(f"  Agent registered:    {'PASS' if agent_ok else 'FAIL'}")

    if not status.get("all_ok"):
        print("\n  ** Server checks failed. Ensure NeuraSan is running:")
        print("     cd C:/workspace/neuro-san-studio && python -m run")
        if args.check_only:
            return 1
        print("  Continuing anyway...\n")

    if args.check_only:
        print("\n  All checks passed!")
        return 0

    # == Step 1b: Open browser mode ==
    if args.open_browser:
        prompt = args.prompt or f"Run the {args.config} pipeline and show me what decisions were made"
        print(f"\n[2/3] Opening NSFlow UI in browser...")
        print(f"  URL: http://localhost:{args.nsflow_port}")
        url = open_in_browser(nsflow_port=args.nsflow_port, prompt=prompt)
        print(f"\n  ** To see LIVE agent animation: **")
        print(f"  1. Select 'automation/pipeline_intelligence' from the dropdown")
        print(f"  2. Paste this into the chat box:")
        print(f"     {prompt}")
        print(f"  3. Watch the node graph — yellow = processing, green = done")
        print(f"\n  The animation only appears in the browser session.")
        return 0

    # == Step 2: Trigger agent execution ==
    prompt = args.prompt or f"Run the {args.config} pipeline and show me what decisions were made"

    print(f"\n[2/3] Sending prompt to NeuraSan server...")
    print(f"  Agent:  automation/pipeline_intelligence")
    print(f"  Config: {args.config}")
    print(f"  Mode:   {'HTTP' if args.http_only else 'WebSocket'}")
    print(f"  Prompt: {prompt}")

    result = run_neurasan_agent(
        prompt,
        config_name=args.config,
        nsflow_port=args.nsflow_port,
        backend_port=args.backend_port,
        prefer_websocket=not args.http_only,
    )

    # == Step 3: Display results ==
    ok = result.get("ok", False)
    print(f"\n[3/3] Results:")
    print(f"  Status:    {'SUCCESS' if ok else 'FAILED'}")
    print(f"  Method:    {result.get('method', 'unknown')}")

    if result.get("thread_id"):
        print(f"  Thread ID: {result['thread_id']}")
        print(f"  UI URL:    {result.get('ui_url', 'N/A')}")

    if ok:
        response_text = result.get("response", "")
        print(f"\n{'=' * 64}")
        print("Agent Response:")
        print(f"{'=' * 64}")
        if len(response_text) > 2000:
            print(response_text[:2000])
            print(f"\n... (truncated, {len(response_text)} chars total)")
        else:
            print(response_text)
        print(f"{'=' * 64}")

        if result.get("thread_id"):
            print(f"\n  Conversation saved to NSFlow UI.")
            print(f"  Open http://localhost:{args.nsflow_port}, select the agent,")
            print(f"  and look in the thread sidebar to view it.")

        print(f"\n  ** For LIVE animation, run: python test_neurasan.py --open-browser **")
    else:
        print(f"  Error:  {result.get('error', 'unknown')}")
        if result.get("partial_response"):
            print(f"  Partial: {result['partial_response'][:500]}")

    print()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
