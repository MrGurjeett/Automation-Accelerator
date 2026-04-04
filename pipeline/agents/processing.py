"""Processing agents — validation, normalization, and feature generation.

These agents handle the core AI-driven processing stages.

Phase 4.2 GROUP 5 — ValidationAgent upgraded to hybrid pattern:
deterministic validation for simple cases, MCP for complex/semantic
validation when enabled and available.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from pipeline.agents.base import BaseAgent, AgentResult, ConnectorAwareMixin

logger = logging.getLogger(__name__)


class ValidationAgent(ConnectorAwareMixin, BaseAgent):
    """Validate test-case rows against schema and business rules.

    **Hybrid pattern (Phase 4.2):**
      - Always runs deterministic validation (schema, action, workflow)
      - When ``use_mcp_validation=True`` in context AND MCP is available,
        also runs semantic validation on rejected items via MCP
      - MCP can rescue borderline-rejected test cases
      - If MCP is unavailable, deterministic results stand as-is

    This avoids unnecessary MCP calls for the common case where all
    test cases pass deterministic validation.
    """

    name = "validation"
    description = "Schema, action, and workflow validation of test cases"

    def run(self, context: dict[str, Any]) -> AgentResult:
        from validator.schema_validator import validate_schema
        from validator.action_validator import validate_action
        from validator.workflow_validator import validate_workflow

        rows = context.get("rows", [])
        if not rows:
            return AgentResult(ok=False, error="No rows to validate (empty input)")

        validate_schema(rows[0].keys())

        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row["TC_ID"]].append(row)

        validated: dict[str, list[dict]] = {}
        rejected: list[str] = []
        rejected_data: dict[str, list[dict]] = {}
        warnings: list[str] = []

        for tc_id, tc_rows in grouped.items():
            try:
                validate_workflow(tc_id, tc_rows)
                for row in tc_rows:
                    validate_action(row)
                validated[tc_id] = tc_rows
            except (ValueError, TypeError, KeyError) as e:
                rejected.append(tc_id)
                rejected_data[tc_id] = tc_rows
                warnings.append(f"{tc_id}: {e}")
                logger.warning("[SKIP] %s validation failed: %s", tc_id, e)

        # ── Hybrid: MCP semantic validation for rejected items ──
        mcp_rescued = {}
        use_mcp = context.get("use_mcp_validation", False)

        if use_mcp and rejected_data:
            mcp_rescued = self._mcp_revalidate(context, rejected_data, warnings)
            if mcp_rescued:
                # Move rescued items from rejected to validated
                for tc_id, tc_rows in mcp_rescued.items():
                    validated[tc_id] = tc_rows
                    rejected.remove(tc_id)
                    del rejected_data[tc_id]
                logger.info(
                    "[ValidationAgent] MCP rescued %d test case(s): %s",
                    len(mcp_rescued), list(mcp_rescued.keys()),
                )

        if not validated:
            return AgentResult(
                ok=False,
                error="No test cases passed validation",
                data={"rejected": rejected},
                warnings=warnings,
            )

        return AgentResult(
            ok=True,
            data={
                "validated": validated,
                "validated_count": len(validated),
                "rejected": rejected,
                "rejected_count": len(rejected),
            },
            warnings=warnings,
            metrics={
                "validated": len(validated),
                "rejected": len(rejected),
                "mcp_rescued": len(mcp_rescued),
            },
        )

    def _mcp_revalidate(
        self,
        context: dict[str, Any],
        rejected_data: dict[str, list[dict]],
        warnings: list[str],
    ) -> dict[str, list[dict]]:
        """Attempt MCP-based semantic revalidation of rejected test cases.

        Returns a dict of tc_id → rows for items MCP considers valid.
        """
        mcp = self.get_connector("mcp", context)
        if not mcp or not mcp.is_connected:
            warnings.append("MCP validation requested but connector not available")
            return {}

        rescued: dict[str, list[dict]] = {}

        try:
            result = mcp.fetch({
                "type": "tool_call",
                "tool": "pipeline_validation",
                "arguments": {
                    "task": "revalidate",
                    "rejected_items": {
                        tc_id: [
                            {k: v for k, v in row.items() if not str(k).startswith("_")}
                            for row in rows
                        ]
                        for tc_id, rows in rejected_data.items()
                    },
                },
            })

            if result.ok:
                mcp_data = result.data.get("result", {})
                rescued_ids = mcp_data.get("rescued", []) if isinstance(mcp_data, dict) else []
                for tc_id in rescued_ids:
                    if tc_id in rejected_data:
                        rescued[tc_id] = rejected_data[tc_id]
            else:
                warnings.append(f"MCP revalidation failed: {result.error}")

        except Exception as exc:
            logger.warning("[ValidationAgent] MCP revalidation error: %s", exc)
            warnings.append(f"MCP revalidation error: {exc}")

        return rescued


class NormalizationAgent(BaseAgent):
    """AI-powered normalization of validated test cases."""

    name = "normalization"
    description = "Azure OpenAI + RAG normalization of test steps"

    def run(self, context: dict[str, Any]) -> AgentResult:
        from ai.normalizer import AINormaliser, GenerationError

        validated = context.get("validated", {})
        config = context.get("_config")
        dom_store = context.get("_dom_store")

        if not config or not dom_store:
            return AgentResult(ok=False, error="AI stack (config, dom_store) required")

        normaliser = AINormaliser(config, dom_store=dom_store)
        accepted: dict[str, list] = {}
        rejected: list[str] = []
        warnings: list[str] = []

        for tc_id, tc_rows in validated.items():
            logger.info("Normalising TC '%s' (%d steps)", tc_id, len(tc_rows))
            try:
                steps = normaliser.normalise_tc(tc_id, tc_rows)
                accepted[tc_id] = steps
            except GenerationError as e:
                rejected.append(tc_id)
                warnings.append(f"{tc_id}: {e}")
                logger.error("[FAIL] %s REJECTED: %s", tc_id, e)

        normaliser.close()

        if not accepted:
            return AgentResult(
                ok=False,
                error="No test cases passed normalisation",
                data={"rejected": rejected},
                warnings=warnings,
            )

        return AgentResult(
            ok=True,
            data={
                "accepted": accepted,
                "accepted_count": len(accepted),
                "rejected": rejected,
            },
            warnings=warnings,
            metrics={"accepted": len(accepted), "rejected": len(rejected)},
        )


class FeatureGenerationAgent(BaseAgent):
    """Generate BDD feature files from normalized test cases."""

    name = "feature_generation"
    description = "Generate parameterized Gherkin feature files"

    def run(self, context: dict[str, Any]) -> AgentResult:
        from generator.feature_generator import generate_feature, write_feature_file
        from generator.version_manager import create_version_folder, save_artifact

        accepted = context.get("accepted", {})
        feature_name = context.get("feature_name", "Login")
        excel_path = context.get("excel_path", "")

        content = generate_feature(feature_name, accepted)
        feature_path = write_feature_file(feature_name, content)

        version_folder = create_version_folder(excel_path)
        save_artifact(
            version_folder,
            f"{feature_name.lower().replace(' ', '_')}.feature",
            content,
        )

        return AgentResult(
            ok=True,
            data={
                "feature_path": feature_path,
                "feature_content": content,
                "version_folder": version_folder,
            },
            metrics={"scenarios_generated": len(accepted)},
        )
