"""
Feature Generator — produces parameterized Gherkin feature files.

Groups TCs by flow signature → Scenario Outline with Examples table.
Feature file is OVERWRITTEN on every regeneration.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Dict, List, Tuple

from ai.normalizer import NormalisedStep

logger = logging.getLogger(__name__)

GENERATED_FEATURES_DIR = "generated/features"


def compute_flow_signature(steps: List[NormalisedStep]) -> Tuple[Tuple[str, str], ...]:
    """Ordered sequence of (action, target) — excludes data values.

    TCs with the same signature share a Scenario Outline.
    """
    return tuple((s.normalized_action, s.normalized_target) for s in steps)


def generate_feature(
    feature_name: str,
    tc_map: Dict[str, List[NormalisedStep]],
) -> str:
    """Generate a complete .feature file content from normalised TC data.

    Parameters
    ----------
    feature_name : str
        The Feature title.
    tc_map : dict
        Mapping of TC_ID → list of NormalisedStep.

    Returns
    -------
    str
        Complete Gherkin feature file content.
    """
    # Group TCs by flow signature
    sig_groups: Dict[Tuple, List[Tuple[str, List[NormalisedStep]]]] = defaultdict(list)
    for tc_id, steps in tc_map.items():
        sig = compute_flow_signature(steps)
        sig_groups[sig].append((tc_id, steps))

    lines: list[str] = []
    lines.append(f"Feature: {feature_name}")
    lines.append("")

    for sig_idx, (sig, tcs) in enumerate(sig_groups.items(), start=1):
        # Use first TC as template for step shapes
        first_tc_id, first_steps = tcs[0]

        scenario_name = f"{feature_name} — Flow {sig_idx}"
        lines.append(f"  Scenario Outline: {scenario_name}")

        # Build step lines
        param_slots: list[dict] = []  # track parameterized slots
        for step in first_steps:
            action = step.normalized_action
            target = step.normalized_target
            safe_target = target.replace(" ", "_")

            if action == "navigate":
                lines.append(f"    Given I navigate to \"{target}\"")
            elif action == "fill":
                param_name = f"{safe_target}"
                lines.append(f"    When I fill \"{target}\" with \"<{param_name}>\"")
                param_slots.append({"header": param_name, "type": "value", "target": target})
            elif action == "click":
                lines.append(f"    And I click \"{target}\"")
            elif action == "select":
                param_name = f"{safe_target}"
                lines.append(f"    When I select \"{target}\" with \"<{param_name}>\"")
                param_slots.append({"header": param_name, "type": "value", "target": target})
            elif action == "verify_text":
                param_name = f"{safe_target}_expected"
                lines.append(f"    Then I verify \"{target}\" shows \"<{param_name}>\"")
                param_slots.append({"header": param_name, "type": "expected", "target": target})

        lines.append("")
        lines.append("    Examples:")

        # Build Examples table
        headers = ["TC_ID"] + [s["header"] for s in param_slots]
        lines.append("      | " + " | ".join(headers) + " |")

        for tc_id, steps in tcs:
            row_vals = [tc_id]
            for slot in param_slots:
                found = "[EMPTY]"
                for st in steps:
                    if st.normalized_target == slot["target"]:
                        if slot["type"] == "value" and st.value not in (None, "-", ""):
                            found = st.value
                        elif slot["type"] == "expected" and st.expected not in (None, "-", ""):
                            found = st.expected
                row_vals.append(found)
            lines.append("      | " + " | ".join(row_vals) + " |")

        lines.append("")

    return "\n".join(lines)


def write_feature_file(feature_name: str, content: str) -> str:
    """Write the feature file to generated/features/. Overwrites existing.

    Returns the path to the written file.
    """
    os.makedirs(GENERATED_FEATURES_DIR, exist_ok=True)
    safe_name = feature_name.lower().replace(" ", "_")
    file_path = os.path.join(GENERATED_FEATURES_DIR, f"{safe_name}.feature")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("Feature file written: %s", file_path)
    return file_path
