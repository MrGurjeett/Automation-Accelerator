"""Launch the Automation Accelerator Dashboard.

Usage:
    python -m dashboard              # Start both backend (8200) and frontend dev (5173)
    python -m dashboard --backend    # Start backend only
    python -m dashboard --port 9000  # Custom port
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is importable
# Bootstrap: add parent so project_root module is findable
_bootstrap_root = Path(__file__).resolve().parents[1]
if str(_bootstrap_root) not in sys.path:
    sys.path.insert(0, str(_bootstrap_root))
from project_root import ensure_importable
PROJECT_ROOT = ensure_importable()


def main():
    parser = argparse.ArgumentParser(description="Automation Accelerator Dashboard")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DASHBOARD_PORT", "8200")))
    parser.add_argument("--host", default=os.environ.get("DASHBOARD_HOST", "0.0.0.0"))
    parser.add_argument("--backend", action="store_true", help="Start backend only (no frontend dev server)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    logger = logging.getLogger("dashboard")

    import uvicorn

    logger.info("=" * 60)
    logger.info("  Automation Accelerator Dashboard")
    logger.info("  Backend:  http://%s:%d", args.host, args.port)
    logger.info("  API Docs: http://%s:%d/docs", args.host, args.port)
    if not args.backend:
        logger.info("  Frontend: http://localhost:5173 (run 'npm run dev' in dashboard/frontend/)")
    logger.info("=" * 60)

    uvicorn.run(
        "dashboard.backend.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        **({"reload_dirs": [str(Path(__file__).parent / "backend")]} if args.reload else {}),
    )


if __name__ == "__main__":
    main()
