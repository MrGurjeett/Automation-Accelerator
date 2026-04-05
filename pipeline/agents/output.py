"""Output agents — version checking, test execution, and persistence.

These agents handle the output stages of the pipeline.

Phase 4A — ExecutionAgent and PersistenceAgent are connector-aware:
they can optionally publish test results and artifacts to external
systems (ADO, MCP) when connectors are registered.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.agents.base import BaseAgent, AgentResult, ConnectorAwareMixin

logger = logging.getLogger(__name__)


class VersionCheckAgent(BaseAgent):
    """Check whether the Excel input has changed since last generation."""

    name = "version_check"
    description = "Detect changes in Excel input to decide if regeneration is needed"

    def run(self, context: dict[str, Any]) -> AgentResult:
        from generator.version_manager import has_changed

        excel_path = context.get("excel_path")
        force = context.get("force", False)
        latest_manifest_path = context.get("latest_manifest_path")

        changed = force or has_changed(excel_path)
        if force and latest_manifest_path:
            p = Path(latest_manifest_path)
            if p.exists():
                p.unlink()

        return AgentResult(
            ok=True,
            data={"changed": changed, "forced": force},
        )


class ExecutionAgent(ConnectorAwareMixin, BaseAgent):
    """Execute BDD tests via pytest/Playwright.

    When an ADO connector is available and a ``run_id`` is provided in
    context, test results are automatically published to Azure DevOps.
    """

    name = "execution"
    description = "Run generated BDD feature files with pytest and Playwright"

    def run(self, context: dict[str, Any]) -> AgentResult:
        from execution.runner import run_tests

        result = run_tests()

        test_data = {
            "exit_code": result.exit_code,
            "passed": result.passed,
            "failed": result.failed,
            "errors": result.errors,
            "skipped": result.skipped,
            "total": result.total,
            "success": result.success,
        }

        # Optionally publish results to ADO if connector is available
        ado_published = self._publish_to_ado(context, test_data)
        if ado_published:
            test_data["ado_published"] = True

        return AgentResult(
            ok=True,
            data=test_data,
            metrics={
                "passed": result.passed,
                "failed": result.failed,
                "total": result.total,
            },
        )

    def _publish_to_ado(self, context: dict[str, Any], test_data: dict) -> bool:
        """Publish test results to ADO if connector and run_id are available."""
        ado_run_id = context.get("ado_run_id")
        if not ado_run_id:
            return False

        ado = self.get_connector("ado", context)
        if not ado or not ado.is_connected:
            return False

        try:
            results = [{
                "testCaseTitle": context.get("feature_name", "Generated BDD Tests"),
                "outcome": "Passed" if test_data.get("success") else "Failed",
                "state": "Completed",
                "comment": (
                    f"Passed: {test_data['passed']}, "
                    f"Failed: {test_data['failed']}, "
                    f"Errors: {test_data['errors']}"
                ),
            }]
            push_result = ado.push({
                "type": "test_result",
                "run_id": ado_run_id,
                "results": results,
            })
            if push_result.ok:
                logger.info("[ExecutionAgent] Published test results to ADO run %s", ado_run_id)
            else:
                logger.warning("[ExecutionAgent] ADO publish failed: %s", push_result.error)
            return push_result.ok
        except Exception as exc:
            logger.warning("[ExecutionAgent] ADO publish error: %s", exc)
            return False


class PersistenceAgent(ConnectorAwareMixin, BaseAgent):
    """Persist final run summary and cumulative statistics.

    When an ADO connector is available and ``ado_work_item_id`` is in
    context, a summary comment is posted to the corresponding ADO work item.
    """

    name = "persistence"
    description = "Save run summary, cumulative stats, and versioned artifacts"

    def run(self, context: dict[str, Any]) -> AgentResult:
        import ai.ai_stats as ai_stats
        from generator.version_manager import save_artifact, get_latest_version_folder

        latest_run_path = context.get("latest_run_path", "artifacts/latest_run.json")
        cumulative_stats_path = context.get("cumulative_stats_path", "artifacts/cumulative_stats.json")

        # Gather stats
        stats_path = context.get("ai_stats_path", "")
        if stats_path:
            loaded = ai_stats.load_from_file(stats_path)
            run_stats = loaded if loaded else ai_stats.snapshot()
        else:
            run_stats = ai_stats.snapshot()

        # Update cumulative
        cum_path = Path(cumulative_stats_path)
        existing = {}
        if cum_path.exists():
            try:
                existing = json.loads(cum_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        cumulative = existing.get("cumulative", {}) if isinstance(existing, dict) else {}

        def _inc(key: str, amount: int) -> None:
            cumulative[key] = int(cumulative.get(key, 0) or 0) + int(amount or 0)

        _inc("runs", 1)
        for k in (
            "tokens_total", "tokens_saved_total", "aoai_chat_calls",
            "aoai_embedding_calls", "aoai_cache_hits", "rag_resolutions",
            "locator_healing",
        ):
            _inc(k, run_stats.get(k, 0))

        cum_payload = {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "cumulative": cumulative,
        }
        cum_path.parent.mkdir(parents=True, exist_ok=True)
        cum_path.write_text(json.dumps(cum_payload, indent=2), encoding="utf-8")

        # Build run payload
        payload = {
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "trace_id": context.get("trace_id", ""),
            "mode": context.get("mode", "pipeline"),
            "regenerated": context.get("regenerated", True),
            "excel": context.get("excel_path", ""),
            "feature": context.get("feature_path", ""),
            "version_folder": context.get("version_folder", ""),
            "tests": context.get("tests", {}),
            "stats": run_stats,
            "cumulative": cumulative,
        }

        # Write latest_run.json
        run_path = Path(latest_run_path)
        run_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        # Write versioned run_summary
        version_folder = context.get("version_folder") or get_latest_version_folder()
        if version_folder:
            save_artifact(
                version_folder,
                "run_summary.json",
                json.dumps(payload, indent=2),
            )

        # Optionally sync summary to ADO work item
        ado_synced = self._sync_to_ado(context, payload)
        if ado_synced:
            payload["ado_synced"] = True

        return AgentResult(
            ok=True,
            data=payload,
            metrics={"persisted": True},
        )

    def _sync_to_ado(self, context: dict[str, Any], payload: dict) -> bool:
        """Update ADO work item with run summary if connector is available."""
        work_item_id = context.get("ado_work_item_id")
        if not work_item_id:
            return False

        ado = self.get_connector("ado", context)
        if not ado or not ado.is_connected:
            return False

        try:
            tests = payload.get("tests", {})
            summary = (
                f"Pipeline run completed at {payload.get('completed_at', 'N/A')}. "
                f"Tests: {tests.get('passed', 0)} passed, "
                f"{tests.get('failed', 0)} failed out of "
                f"{tests.get('total', 0)} total."
            )
            push_result = ado.push({
                "type": "work_item",
                "work_item_type": "Task",
                "fields": {
                    "System.Id": work_item_id,
                    "System.History": summary,
                },
            })
            if push_result.ok:
                logger.info("[PersistenceAgent] Synced summary to ADO work item %s", work_item_id)
            else:
                logger.warning("[PersistenceAgent] ADO sync failed: %s", push_result.error)
            return push_result.ok
        except Exception as exc:
            logger.warning("[PersistenceAgent] ADO sync error: %s", exc)
            return False
