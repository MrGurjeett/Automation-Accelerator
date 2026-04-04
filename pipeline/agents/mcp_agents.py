"""
MCP-powered agents — generation, validation/enrichment, and recovery.

Phase 4.2 GROUPS 2-4 — concrete MCP agent implementations built on
:class:`MCPAgentBase`.  Each agent delegates AI reasoning to MCP while
keeping all pipeline orchestration logic in the service layer.

Agents:
  - ``MCPGenerationAgent``  — generate structured outputs (test cases, steps, summaries)
  - ``MCPValidationAgent``  — validate or enrich data from previous steps
  - ``MCPEnrichmentAgent``  — enrich work items / test data via MCP reasoning
  - ``MCPRecoveryAgent``    — handle pipeline failures and produce corrected output

All agents:
  - Use MCP connector from registry (never import MCP directly)
  - Provide deterministic fallbacks when MCP is unavailable
  - Return structured AgentResult objects
  - Contain NO pipeline orchestration logic
"""
from __future__ import annotations

import logging
from typing import Any

from pipeline.agents.base import AgentResult
from pipeline.agents.mcp_base import MCPAgentBase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GROUP 2 — MCP Generation Agent
# ---------------------------------------------------------------------------

class MCPGenerationAgent(MCPAgentBase):
    """Generate structured outputs via MCP reasoning.

    Takes context data (test case descriptions, requirements, etc.) and
    uses MCP to produce structured outputs such as:
      - Test case steps
      - BDD scenarios
      - Test summaries
      - Documentation

    Context inputs:
      - ``generation_type`` (str): what to generate (e.g. "test_cases", "steps", "summary")
      - ``input_data`` (dict|list): source data to generate from
      - ``constraints`` (dict, optional): generation constraints / rules
      - ``template`` (str, optional): output template/format hint

    Output data:
      - ``generated`` (dict|list): the generated content
      - ``generation_type`` (str): echoed type for downstream reference
      - ``item_count`` (int): number of items generated
    """

    name = "mcp_generation"
    description = "Generate structured outputs via MCP reasoning"
    mcp_task = "generate"
    mcp_tool = "pipeline_generation"

    input_keys = ["generation_type", "input_data"]
    output_keys = ["generated", "generation_type", "item_count"]

    def _build_mcp_arguments(self, context: dict[str, Any]) -> dict[str, Any]:
        generation_type = context.get("generation_type", "generic")
        input_data = context.get("input_data", {})
        constraints = context.get("constraints", {})
        template = context.get("template")

        arguments: dict[str, Any] = {
            "generation_type": generation_type,
            "input_data": input_data,
        }
        if constraints:
            arguments["constraints"] = constraints
        if template:
            arguments["template"] = template

        return arguments

    def _process_mcp_result(
        self, mcp_data: Any, context: dict[str, Any]
    ) -> dict[str, Any]:
        generation_type = context.get("generation_type", "generic")

        if isinstance(mcp_data, dict):
            generated = mcp_data.get("generated", mcp_data.get("output", mcp_data))
        elif isinstance(mcp_data, list):
            generated = mcp_data
        else:
            generated = {"raw": mcp_data}

        item_count = len(generated) if isinstance(generated, (list, dict)) else 1

        return {
            "generated": generated,
            "generation_type": generation_type,
            "item_count": item_count,
        }

    def _fallback(self, context: dict[str, Any]) -> AgentResult:
        """Fallback: return empty generation with warning."""
        generation_type = context.get("generation_type", "generic")
        return AgentResult(
            ok=False,
            error=f"MCP unavailable — cannot generate '{generation_type}'",
            data={
                "generated": [],
                "generation_type": generation_type,
                "item_count": 0,
            },
            warnings=["MCP generation unavailable — no fallback generation possible"],
            metrics={"mcp_used": False, "fallback": True},
        )


# ---------------------------------------------------------------------------
# GROUP 3 — MCP Validation Agent
# ---------------------------------------------------------------------------

class MCPValidationAgent(MCPAgentBase):
    """Validate data from previous pipeline steps via MCP reasoning.

    Uses MCP to perform intelligent validation that goes beyond
    deterministic rules — e.g., semantic validation of test steps,
    business logic verification, completeness checks.

    Context inputs:
      - ``validation_target`` (str): what to validate (e.g. "test_cases", "steps", "workflow")
      - ``data`` (dict|list): the data to validate
      - ``rules`` (list, optional): validation rules / criteria
      - ``reference_data`` (dict, optional): ground truth for comparison

    Output data:
      - ``valid`` (bool): overall validation result
      - ``validated_items`` (list): items that passed
      - ``invalid_items`` (list): items that failed with reasons
      - ``validation_summary`` (dict): counts and statistics
    """

    name = "mcp_validation"
    description = "Validate or verify data via MCP reasoning"
    mcp_task = "validate"
    mcp_tool = "pipeline_validation"

    input_keys = ["validation_target", "data"]
    output_keys = ["valid", "validated_items", "invalid_items", "validation_summary"]

    def _build_mcp_arguments(self, context: dict[str, Any]) -> dict[str, Any]:
        validation_target = context.get("validation_target", "generic")
        data = context.get("data", {})
        rules = context.get("rules", [])
        reference_data = context.get("reference_data")

        arguments: dict[str, Any] = {
            "validation_target": validation_target,
            "data": data,
        }
        if rules:
            arguments["rules"] = rules
        if reference_data:
            arguments["reference_data"] = reference_data

        return arguments

    def _process_mcp_result(
        self, mcp_data: Any, context: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(mcp_data, dict):
            # Treat non-dict response as opaque valid result
            return {
                "valid": True,
                "validated_items": [],
                "invalid_items": [],
                "validation_summary": {"raw_response": mcp_data},
            }

        valid = mcp_data.get("valid", mcp_data.get("ok", True))
        validated = mcp_data.get("validated_items", mcp_data.get("passed", []))
        invalid = mcp_data.get("invalid_items", mcp_data.get("failed", []))

        return {
            "valid": bool(valid),
            "validated_items": validated if isinstance(validated, list) else [],
            "invalid_items": invalid if isinstance(invalid, list) else [],
            "validation_summary": {
                "total": len(validated) + len(invalid) if isinstance(validated, list) and isinstance(invalid, list) else 0,
                "passed": len(validated) if isinstance(validated, list) else 0,
                "failed": len(invalid) if isinstance(invalid, list) else 0,
                **{k: v for k, v in mcp_data.items() if k not in ("valid", "ok", "validated_items", "passed", "invalid_items", "failed")},
            },
        }

    def _fallback(self, context: dict[str, Any]) -> AgentResult:
        """Fallback: pass-through (assume valid when MCP is unavailable)."""
        target = context.get("validation_target", "generic")
        logger.warning(
            "[%s] MCP unavailable — skipping validation for '%s' (pass-through)",
            self.name, target,
        )
        return AgentResult(
            ok=True,
            data={
                "valid": True,
                "validated_items": [],
                "invalid_items": [],
                "validation_summary": {"fallback": True, "note": "MCP unavailable — validation skipped"},
            },
            warnings=[f"MCP validation unavailable for '{target}' — passed through without validation"],
            metrics={"mcp_used": False, "fallback": True},
        )


# ---------------------------------------------------------------------------
# GROUP 3 (continued) — MCP Enrichment Agent
# ---------------------------------------------------------------------------

class MCPEnrichmentAgent(MCPAgentBase):
    """Enrich data from previous steps via MCP reasoning.

    Uses MCP to add context, annotations, metadata, or derived fields
    to existing data — e.g., enriching ADO work items with test coverage
    info, adding semantic tags, generating descriptions.

    Context inputs:
      - ``enrichment_type`` (str): what to enrich (e.g. "work_items", "test_cases")
      - ``data`` (dict|list): the data to enrich
      - ``enrichment_config`` (dict, optional): what enrichments to apply

    Output data:
      - ``enriched`` (dict|list): the enriched data
      - ``enrichment_type`` (str): echoed type
      - ``fields_added`` (list): new fields added by enrichment
    """

    name = "mcp_enrichment"
    description = "Enrich data with additional context via MCP reasoning"
    mcp_task = "enrich"
    mcp_tool = "pipeline_enrichment"

    input_keys = ["enrichment_type", "data"]
    output_keys = ["enriched", "enrichment_type", "fields_added"]

    def _build_mcp_arguments(self, context: dict[str, Any]) -> dict[str, Any]:
        enrichment_type = context.get("enrichment_type", "generic")
        data = context.get("data", {})
        enrichment_config = context.get("enrichment_config", {})

        arguments: dict[str, Any] = {
            "enrichment_type": enrichment_type,
            "data": data,
        }
        if enrichment_config:
            arguments["enrichment_config"] = enrichment_config

        return arguments

    def _process_mcp_result(
        self, mcp_data: Any, context: dict[str, Any]
    ) -> dict[str, Any]:
        enrichment_type = context.get("enrichment_type", "generic")

        if isinstance(mcp_data, dict):
            enriched = mcp_data.get("enriched", mcp_data.get("data", mcp_data))
            fields_added = mcp_data.get("fields_added", [])
        else:
            enriched = mcp_data
            fields_added = []

        return {
            "enriched": enriched,
            "enrichment_type": enrichment_type,
            "fields_added": fields_added,
        }

    def _fallback(self, context: dict[str, Any]) -> AgentResult:
        """Fallback: return original data unchanged."""
        data = context.get("data", {})
        enrichment_type = context.get("enrichment_type", "generic")
        return AgentResult(
            ok=True,
            data={
                "enriched": data,  # pass-through
                "enrichment_type": enrichment_type,
                "fields_added": [],
            },
            warnings=["MCP enrichment unavailable — returning original data"],
            metrics={"mcp_used": False, "fallback": True},
        )


# ---------------------------------------------------------------------------
# GROUP 4 — MCP Recovery Agent
# ---------------------------------------------------------------------------

class MCPRecoveryAgent(MCPAgentBase):
    """Handle pipeline failures via MCP-powered recovery.

    Triggered via branching (``on_failure_step``) when a previous step
    fails.  Uses MCP to analyze the error, diagnose the issue, and
    attempt to produce corrected output that allows the pipeline to
    continue.

    Context inputs:
      - ``error`` (str): the error message from the failed step
      - ``failed_step`` (str): name of the step that failed
      - ``context`` (dict): the original context that caused the failure
      - ``recovery_strategy`` (str, optional): hint for recovery approach
        ("retry", "transform", "fallback", "skip")

    Output data:
      - ``recovered`` (bool): whether recovery was successful
      - ``corrected_data`` (dict): corrected/transformed output
      - ``recovery_action`` (str): what action was taken
      - ``diagnosis`` (str): explanation of the failure and fix

    Branching integration::

        {
            "name": "validate",
            "on_failure_step": "recover",
            ...
        },
        {
            "name": "recover",
            "agent": "mcp_recovery",
            "inputs": {
                "error": "$steps.validate.error",
                "failed_step": "validate",
                "context": "$steps.validate.data"
            }
        }
    """

    name = "mcp_recovery"
    description = "Recover from pipeline failures via MCP-powered analysis"
    mcp_task = "recover"
    mcp_tool = "pipeline_recovery"

    input_keys = ["error", "failed_step"]
    output_keys = ["recovered", "corrected_data", "recovery_action", "diagnosis"]

    def _build_mcp_arguments(self, context: dict[str, Any]) -> dict[str, Any]:
        error = context.get("error", "Unknown error")
        failed_step = context.get("failed_step", "unknown")
        original_context = context.get("context", {})
        recovery_strategy = context.get("recovery_strategy", "auto")

        return {
            "error": str(error),
            "failed_step": failed_step,
            "original_context": _sanitize_for_mcp(original_context),
            "recovery_strategy": recovery_strategy,
        }

    def _process_mcp_result(
        self, mcp_data: Any, context: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(mcp_data, dict):
            return {
                "recovered": False,
                "corrected_data": {},
                "recovery_action": "none",
                "diagnosis": f"Unexpected MCP response: {mcp_data}",
            }

        recovered = mcp_data.get("recovered", mcp_data.get("ok", False))
        corrected = mcp_data.get("corrected_data", mcp_data.get("data", {}))
        action = mcp_data.get("recovery_action", mcp_data.get("action", "unknown"))
        diagnosis = mcp_data.get("diagnosis", mcp_data.get("explanation", ""))

        if recovered:
            logger.info(
                "[%s] Recovery successful for step '%s': %s",
                self.name, context.get("failed_step", "?"), action,
            )
        else:
            logger.warning(
                "[%s] Recovery failed for step '%s': %s",
                self.name, context.get("failed_step", "?"), diagnosis,
            )

        return {
            "recovered": bool(recovered),
            "corrected_data": corrected if isinstance(corrected, dict) else {},
            "recovery_action": str(action),
            "diagnosis": str(diagnosis),
        }

    def _fallback(self, context: dict[str, Any]) -> AgentResult:
        """Fallback: attempt basic recovery without MCP.

        Simple strategies:
          - If recovery_strategy is "skip", return ok=True to allow pipeline to continue
          - Otherwise, return the error as unrecoverable
        """
        error = context.get("error", "Unknown error")
        failed_step = context.get("failed_step", "unknown")
        strategy = context.get("recovery_strategy", "auto")

        if strategy == "skip":
            logger.warning(
                "[%s] MCP unavailable — skipping failed step '%s' per recovery strategy",
                self.name, failed_step,
            )
            return AgentResult(
                ok=True,
                data={
                    "recovered": True,
                    "corrected_data": {},
                    "recovery_action": "skip",
                    "diagnosis": f"MCP unavailable; skipped failed step '{failed_step}'",
                },
                warnings=[f"Recovery via skip (MCP unavailable): {error}"],
                metrics={"mcp_used": False, "fallback": True, "recovery_action": "skip"},
            )

        # Default: cannot recover without MCP
        return AgentResult(
            ok=False,
            error=f"Cannot recover from '{failed_step}' failure: {error} (MCP unavailable)",
            data={
                "recovered": False,
                "corrected_data": {},
                "recovery_action": "none",
                "diagnosis": "MCP unavailable and no local recovery strategy",
            },
            metrics={"mcp_used": False, "fallback": True},
        )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _sanitize_for_mcp(data: Any, max_depth: int = 5, max_items: int = 100) -> Any:
    """Sanitize context data before sending to MCP.

    Removes non-serializable objects, truncates large collections,
    and limits nesting depth to prevent oversized payloads.
    """
    if max_depth <= 0:
        return "<truncated>"

    if data is None or isinstance(data, (bool, int, float, str)):
        return data

    if isinstance(data, dict):
        result = {}
        for i, (k, v) in enumerate(data.items()):
            if i >= max_items:
                result["_truncated"] = f"{len(data) - max_items} more items"
                break
            # Skip private/internal keys
            if isinstance(k, str) and k.startswith("_"):
                continue
            result[str(k)] = _sanitize_for_mcp(v, max_depth - 1, max_items)
        return result

    if isinstance(data, (list, tuple)):
        items = [_sanitize_for_mcp(item, max_depth - 1, max_items) for item in data[:max_items]]
        if len(data) > max_items:
            items.append(f"<{len(data) - max_items} more items>")
        return items

    # Non-serializable: convert to string repr
    try:
        return str(data)
    except Exception:
        return "<non-serializable>"
