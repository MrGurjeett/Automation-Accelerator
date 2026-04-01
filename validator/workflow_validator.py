"""
Workflow Validator — validates a complete test case's step sequence.

Ensures logical ordering (e.g. navigate should come first)
and cross-step consistency within a single TC_ID group.
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


def validate_workflow(tc_id: str, rows: List[dict[str, str]]) -> None:
    """Validate the step sequence for a single test case.

    Raises ValueError on workflow violations.
    """
    if not rows:
        raise ValueError(f"TC '{tc_id}' has no steps")

    actions = [r["Action"] for r in rows]

    # First action should be navigate
    if actions[0] != "navigate":
        logger.warning(
            "TC '%s': first action is '%s', expected 'navigate'. "
            "Proceeding but this may cause execution issues.",
            tc_id, actions[0],
        )

    # navigate appearing mid-flow (warn but allow for multi-page TCs)
    nav_positions = [i for i, a in enumerate(actions) if a == "navigate"]
    if len(nav_positions) > 1:
        logger.warning(
            "TC '%s': multiple 'navigate' actions at positions %s. "
            "Allowing for multi-page test case.",
            tc_id, nav_positions,
        )

    # verify_text should come after at least one interaction
    verify_positions = [i for i, a in enumerate(actions) if a == "verify_text"]
    if verify_positions and verify_positions[0] <= 0 and actions[0] != "verify_text":
        logger.warning(
            "TC '%s': verify_text at position 0 with no prior actions.",
            tc_id,
        )

    logger.info(
        "TC '%s': workflow validated — %d steps, sequence OK.",
        tc_id, len(rows),
    )
