"""
PipelineService — unified orchestration layer for all execution flows.

Both ``main.py`` (CLI / sequential) and Neuro-SAN agent tools delegate to
this service so that pipeline logic lives in exactly one place.

Design principles:
  - Backward-compatible: existing callers keep working with zero changes
    required on day-one (main.py and agent tools are updated to *call*
    this service, but the service honours every existing contract).
  - Observable: ``get_status()`` returns the current pipeline state at any
    time, useful for the dashboard and agent introspection.
  - Step-level granularity: ``execute_step()`` lets agent flows cherry-pick
    individual stages (e.g. DOM extraction only) without running the full
    pipeline.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import ai.ai_stats as ai_stats
from pipeline.events import EventManager, EventType
from pipeline.trace import resolve_trace_id, install_trace_logging, current_trace_id
from pipeline.agents.registry import AgentRegistry
from pipeline.config import PipelineConfig, PipelineStepConfig, load_builtin_config
from pipeline.conditions import ConditionEvaluator, resolve_ref, evaluate_condition as _eval_condition_structured
from pipeline.connectors.registry import ConnectorRegistry, get_default_registry as _get_default_connector_registry
from pipeline.decision_engine import DecisionEngine

logger = logging.getLogger("pipeline.service")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class StepName(str, Enum):
    DETECT_EXCEL = "detect_excel"
    INIT_DOM = "init_dom"
    EXTRACT_DOM = "extract_dom"
    REGISTER_PAGES = "register_pages"
    CONVERT_RAW = "convert_raw"
    VERSION_CHECK = "version_check"
    READ_EXCEL = "read_excel"
    VALIDATE = "validate"
    NORMALIZE = "normalize"
    GENERATE = "generate"
    EXECUTE = "execute"
    PERSIST = "persist"


@dataclass
class PipelineInput:
    """All inputs that a pipeline run may need."""

    excel_path: str | None = None
    feature_name: str = "Login"
    force: bool = False
    generate_only: bool = False
    force_scan: bool = False
    trace_id: str | None = None  # caller-supplied; auto-generated if omitted
    config_name: str | None = None  # named pipeline config (overrides mode flags)
    input_format: str = "auto"  # input format: auto, excel, csv, json


@dataclass
class StepResult:
    """Outcome of a single pipeline step."""

    step: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class PipelineResult:
    """Outcome of a full pipeline run."""

    exit_code: int = 0
    trace_id: str = ""
    run_id: str = ""
    steps: list[StepResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class PipelineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


# ---------------------------------------------------------------------------
# Artifact path constants — single definitions, no scattered string literals
# ---------------------------------------------------------------------------

ARTIFACTS_DIR = Path("artifacts")
LATEST_RUN_PATH = ARTIFACTS_DIR / "latest_run.json"
CUMULATIVE_STATS_PATH = ARTIFACTS_DIR / "cumulative_stats.json"
EVENTS_JSONL_PATH = ARTIFACTS_DIR / "pipeline_events.jsonl"
LATEST_MANIFEST_PATH = ARTIFACTS_DIR / "latest.json"


# ---------------------------------------------------------------------------
# Helpers (moved from main.py — single copy)
# ---------------------------------------------------------------------------

def _read_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _get_shared_stats() -> dict[str, int]:
    stats_path = (os.environ.get("AI_STATS_PATH") or "").strip()
    if stats_path:
        loaded = ai_stats.load_from_file(stats_path)
        if loaded:
            return loaded
    return ai_stats.snapshot()


def _update_cumulative_stats(run_stats: dict[str, int]) -> dict:
    path = CUMULATIVE_STATS_PATH
    existing = _read_json(path)
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

    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "cumulative": cumulative,
    }
    _write_json(path, payload)
    return payload


# ---------------------------------------------------------------------------
# Shared infrastructure initialisation (was duplicated in main.py AND
# dom_tools.py — now lives here exactly once)
# ---------------------------------------------------------------------------

def _resolve_dom_env() -> tuple[str, str, str]:
    """Resolve DOM connection parameters from environment variables.

    Fallback chain (identical to what both main.py and dom_tools.py used):
        DOM_BASE_URL  -> BASE_URL  -> default
        DOM_USERNAME  -> UI_USERNAME -> "john"
        DOM_PASSWORD  -> UI_PASSWORD -> "demo"
    """
    base_url = (
        os.environ.get("DOM_BASE_URL")
        or os.environ.get("BASE_URL")
        or "https://parabank.parasoft.com/parabank/"
    ).strip()
    username = (
        os.environ.get("DOM_USERNAME")
        or os.environ.get("UI_USERNAME")
        or "john"
    ).strip()
    password = (
        os.environ.get("DOM_PASSWORD")
        or os.environ.get("UI_PASSWORD")
        or "demo"
    ).strip()
    return base_url, username, password


def _init_ai_stack():
    """Initialise the AI / vector-store stack (was duplicated in main.py
    lines 263-272 and dom_tools.py lines 73-85).

    Returns (ai_client, embedder, dom_store, config).
    """
    from ai.config import AIConfig
    from ai.clients.azure_openai_client import AzureOpenAIClient
    from ai.rag.embedder import EmbeddingService
    from framework.vector_store.qdrant_client import DOMVectorStore

    config = AIConfig.load()
    ai_client = AzureOpenAIClient(config.azure_openai)
    embedder = EmbeddingService(ai_client)
    dom_store = DOMVectorStore(embedder)
    return ai_client, embedder, dom_store, config


# ---------------------------------------------------------------------------
# Config-driven execution helpers
# ---------------------------------------------------------------------------

def _resolve_reference(ref: str, results_map: dict[str, Any], input_ns: dict[str, Any]) -> Any:
    """Resolve a ``$step.data.key`` or ``$input.key`` reference.

    Phase 3.5: delegates to ``pipeline.conditions.resolve_ref`` which
    supports both legacy ``$step_name.data.key`` and the formalized
    ``$steps.step_name.data.key`` format.
    """
    return resolve_ref(ref, results_map, input_ns)


def _resolve_step_context(
    step_cfg: Any,
    results_map: dict[str, Any],
    input_ns: dict[str, Any],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Build the context dict for a step by resolving input references.

    Priority: step_cfg.inputs > input_ns > defaults

    When a ``$reference`` resolves to ``None`` (e.g. ``$input.excel_path``
    when no Excel path was provided), the key is set to ``None`` rather
    than keeping the raw ``$reference`` string — which would be mistakenly
    treated as a literal value (e.g. a file path) by downstream handlers.
    """
    ctx: dict[str, Any] = dict(defaults)

    # Merge input namespace (non-None values)
    for k, v in input_ns.items():
        if v is not None:
            ctx[k] = v

    # Resolve step-specific inputs (may contain $references)
    for key, value in step_cfg.inputs.items():
        resolved = _resolve_reference(value, results_map, input_ns)
        if resolved is not None:
            ctx[key] = resolved
        elif isinstance(value, str) and value.startswith("$"):
            # $reference resolved to None — store None, NOT the raw string.
            # Keeping "$input.excel_path" as a literal would cause handlers
            # to treat it as an actual file path.
            ctx[key] = None
        elif key not in ctx:
            ctx[key] = value  # keep actual literal values (non-$ref)

    return ctx


def _evaluate_condition(
    condition: Any,
    results_map: dict[str, Any],
    input_ns: dict[str, Any],
) -> bool:
    """Evaluate a condition expression (string or structured dict).

    Phase 3.5: delegates to ``pipeline.conditions.evaluate_condition``
    which supports both legacy string conditions and structured operator
    dicts (``{"eq": [...]}``, ``{"and": [...]}``, etc.).
    """
    return _eval_condition_structured(condition, results_map, input_ns)


# ---------------------------------------------------------------------------
# PipelineService
# ---------------------------------------------------------------------------

class PipelineService:
    """Unified pipeline orchestration — the single source of truth.

    Usage from main.py (full sequential run)::

        svc = PipelineService()
        result = svc.run_pipeline(PipelineInput(feature_name="Login"))
        sys.exit(result.exit_code)

    Usage from Neuro-SAN agent tools (step-level)::

        svc = PipelineService()
        excel_result  = svc.execute_step(StepName.READ_EXCEL, {"excel_path": "input/tc.xlsx"})
        dom_result    = svc.execute_step(StepName.INIT_DOM, {"force_scan": False})
        exec_result   = svc.execute_step(StepName.EXECUTE, {})
    """

    def __init__(
        self,
        event_manager: EventManager | None = None,
        trace_id: str | None = None,
        agent_registry: AgentRegistry | None = None,
        connector_registry: ConnectorRegistry | None = None,
    ) -> None:
        self._status: PipelineStatus = PipelineStatus.IDLE
        self._current_step: str | None = None
        self._step_results: list[StepResult] = []
        self._in_full_pipeline: bool = False  # suppress IDLE reset during full run

        # Resolve trace_id: explicit > env var > generate.
        # This also sets the contextvars token and os.environ for propagation.
        self._trace_id = resolve_trace_id(trace_id)

        # run_id is the unique identifier for this pipeline execution instance.
        # Derived from trace_id for traceability.
        self._run_id = self._trace_id

        # Install the logging filter so every log line carries trace_id.
        install_trace_logging()

        # Event system — if no manager is provided, create one with the
        # resolved trace_id so every event carries the same ID.
        self.events: EventManager = event_manager or EventManager(
            trace_id=self._trace_id,
            persist_path=str(EVENTS_JSONL_PATH),
        )

        # Agent registry — optional agent-backed execution layer.
        # When an agent is registered for a stage, execute_step delegates
        # to the agent and translates AgentResult → StepResult.
        # Auto-discovers all concrete BaseAgent subclasses in pipeline.agents.
        if agent_registry is not None:
            self._agent_registry: AgentRegistry = agent_registry
        else:
            from pipeline.agents.registry import build_default_registry
            self._agent_registry = build_default_registry()

        # Connector registry — external system connectors (ADO, MCP, etc.).
        # Uses the provided registry or falls back to the global singleton
        # so connectors registered at startup are available to all services.
        self._connector_registry: ConnectorRegistry = (
            connector_registry or _get_default_connector_registry()
        )

        # Decision engine — MCP-assisted pipeline decisions (Phase 4.3).
        # Lazy-initialized when a config enables MCP decisions.
        self._decision_engine: DecisionEngine | None = None

        # Pause/resume support — _pause_event is set (not paused) by default.
        # Calling pause() clears it, blocking the config-driven loop.
        self._pause_event = threading.Event()
        self._pause_event.set()

        # Active pipeline config (set during run_pipeline_from_config)
        self._active_config: PipelineConfig | None = None

        # Lazily initialised shared state (survives across execute_step calls)
        self._config = None
        self._dom_store = None
        self._ai_client = None
        self._embedder = None

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def agent_registry(self) -> AgentRegistry:
        return self._agent_registry

    def register_agent(self, stage_name: str, agent: Any) -> None:
        """Register an agent to back a pipeline stage.

        When an agent is registered for a stage, ``execute_step`` will
        delegate to the agent's ``run()`` method and translate the
        ``AgentResult`` into a ``StepResult``.
        """
        self._agent_registry.register(stage_name, agent)

    @property
    def connector_registry(self) -> ConnectorRegistry:
        """Access the connector registry for external system integrations."""
        return self._connector_registry

    def get_connector(self, name: str):
        """Look up a connector by name from this service's registry.

        Returns None if the connector is not registered.
        """
        return self._connector_registry.get(name)

    @property
    def decision_engine(self) -> DecisionEngine | None:
        """Access the decision engine (None if not initialized)."""
        return self._decision_engine

    def _ensure_decision_engine(self, config: PipelineConfig) -> None:
        """Lazy-initialize the DecisionEngine when MCP decisions are enabled."""
        needs_engine = (
            config.use_mcp_decision
            or config.use_mcp_retry
            or config.use_mcp_condition
        )
        if needs_engine and self._decision_engine is None:
            self._decision_engine = DecisionEngine(
                connector_registry=self._connector_registry,
                events=self.events,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return the current pipeline status, per-step progress, and event-derived progress."""
        return {
            "status": self._status.value,
            "current_step": self._current_step,
            "run_id": self._run_id,
            "config": self._active_config.name if self._active_config else None,
            "steps": [
                {
                    "step": r.step,
                    "ok": r.ok,
                    "error": r.error,
                    "duration_ms": round(r.duration_ms, 1),
                }
                for r in self._step_results
            ],
            "progress": self.events.get_progress(),
            "trace_id": self.events.trace_id,
            "stats": _get_shared_stats(),
        }

    def pause(self) -> None:
        """Pause the pipeline between steps.

        The config-driven execution loop checks ``_pause_event`` between
        steps.  Calling ``pause()`` blocks the loop until ``resume()``.
        """
        if self._status == PipelineStatus.RUNNING:
            self._pause_event.clear()
            self._status = PipelineStatus.PAUSED
            self.events.emit(
                EventType.PIPELINE_PAUSED,
                metadata={"run_id": self._run_id, "step": self._current_step},
            )
            logger.info("[PAUSED] Pipeline paused at step: %s", self._current_step)

    def resume(self) -> None:
        """Resume a paused pipeline."""
        if self._status == PipelineStatus.PAUSED:
            self._status = PipelineStatus.RUNNING
            self._pause_event.set()
            self.events.emit(
                EventType.PIPELINE_RESUMED,
                metadata={"run_id": self._run_id},
            )
            logger.info("[RESUMED] Pipeline resumed")

    # ------------------------------------------------------------------
    # Config-driven execution engine (Phase 3)
    # ------------------------------------------------------------------

    # Maximum step executions to prevent infinite loops in branching configs.
    _MAX_STEP_EXECUTIONS = 500

    def run_pipeline_from_config(
        self,
        config: PipelineConfig,
        input_data: PipelineInput | None = None,
    ) -> PipelineResult:
        """Execute a pipeline defined by a config.

        Phase 3.5 enhancements:
          - **Dynamic branching**: ``on_success_step`` / ``on_failure_step``
            enable non-linear step routing.
          - **Structured conditions**: step conditions can be dicts
            (``{"eq": [...]}``) or legacy strings.
          - **Formalized context**: ``$steps.step_name.data.key`` references.
          - **Loop protection**: max ``_MAX_STEP_EXECUTIONS`` iterations.

        Parameters
        ----------
        config : PipelineConfig
            The pipeline config defining steps, order, and data flow.
        input_data : PipelineInput | None
            Runtime inputs (excel_path, feature_name, flags, etc.).
        """
        inp = input_data or PipelineInput()

        # Resolve trace
        if inp.trace_id and inp.trace_id != self._trace_id:
            self._trace_id = resolve_trace_id(inp.trace_id)
            self.events._trace_id = self._trace_id

        self._active_config = config
        self._status = PipelineStatus.RUNNING
        self._step_results = []
        self._pause_event.set()  # ensure not paused at start

        # Phase 4.3: lazy-init decision engine if MCP decisions enabled
        self._ensure_decision_engine(config)

        result = PipelineResult(trace_id=self._trace_id, run_id=self._run_id)
        pipeline_t0 = time.monotonic()

        # Build the input namespace for $input.* references
        input_ns = {
            "excel_path": inp.excel_path,
            "feature_name": inp.feature_name,
            "force": inp.force,
            "force_scan": inp.force_scan,
            "generate_only": inp.generate_only,
            "config_name": inp.config_name,
        }

        logger.info(
            "[trace_id=%s] Config-driven pipeline '%s' starting (%d steps)",
            self._trace_id, config.name, len(config.steps),
        )

        self.events.emit(
            EventType.PIPELINE_STARTED,
            metadata={
                "run_id": self._run_id,
                "config": config.name,
                "step_count": len(config.steps),
                "steps": config.step_labels,
                "mode": config.name,
            },
        )

        # Build step lookup by name for O(1) branching
        step_index: dict[str, int] = {s.name: i for i, s in enumerate(config.steps)}

        # Results map for $step_name.data.* and $steps.step_name.data.* references
        results_map: dict[str, StepResult] = {}

        self._in_full_pipeline = True
        try:
            os.environ.setdefault(
                "AI_STATS_PATH", str(ARTIFACTS_DIR / "latest_stats.json")
            )
            ai_stats.reset()

            # Step pointer — supports non-linear traversal for branching
            current_idx = 0
            execution_count = 0
            aborted = False

            while current_idx < len(config.steps):
                # Infinite loop guard
                execution_count += 1
                if execution_count > self._MAX_STEP_EXECUTIONS:
                    logger.error(
                        "Pipeline exceeded max step executions (%d). "
                        "Possible infinite loop — aborting.",
                        self._MAX_STEP_EXECUTIONS,
                    )
                    result.exit_code = 1
                    result.steps.append(StepResult(
                        step="loop_guard",
                        ok=False,
                        error=f"Exceeded max step executions ({self._MAX_STEP_EXECUTIONS})",
                    ))
                    aborted = True
                    break

                step_cfg = config.steps[current_idx]

                # Pause check
                self._pause_event.wait()

                # Condition evaluation (supports string AND structured dict)
                if step_cfg.condition is not None:
                    cond_result = _evaluate_condition(step_cfg.condition, results_map, input_ns)

                    # Phase 4.3: optional MCP condition enhancement
                    if (
                        config.use_mcp_condition
                        and self._decision_engine is not None
                    ):
                        # Build a lightweight context from what's available
                        # before full step context resolution (ctx not yet created).
                        _cond_ctx = dict(config.defaults)
                        _cond_ctx.update(input_ns)
                        cond_result = self._decision_engine.enhance_condition(
                            context=_cond_ctx,
                            condition_result=cond_result,
                            condition_expr=step_cfg.condition,
                            step_name=step_cfg.name,
                            results_map=results_map,
                        )

                    if not cond_result:
                        logger.info("[SKIP] Step '%s' — condition not met: %s", step_cfg.name, step_cfg.condition)

                        # Enhanced skipping: record a stub result so later steps
                        # can reference this step's skip status
                        skip_result = StepResult(
                            step=step_cfg.name, ok=False,
                            data={"skipped": True, "reason": "condition_not_met"},
                            error=None,
                        )
                        results_map[step_cfg.name] = skip_result

                        self.events.emit(
                            EventType.STEP_SKIPPED, step_name=step_cfg.name,
                            metadata={
                                "run_id": self._run_id,
                                "condition": str(step_cfg.condition),
                                "reason": "condition_not_met",
                            },
                        )
                        current_idx += 1
                        continue

                # Resolve context
                ctx = _resolve_step_context(
                    step_cfg, results_map, input_ns, config.defaults,
                )

                # Execute
                sr = self.execute_step(step_cfg.name, ctx)
                results_map[step_cfg.name] = sr
                result.steps.append(sr)

                # --- Branching logic (Phase 3.5 + Phase 4.3 MCP decisions) ---
                next_idx = current_idx + 1  # default: linear advance

                if sr.ok:
                    # Check for on_success_step branch
                    if step_cfg.on_success_step:
                        target = step_cfg.on_success_step
                        if target in step_index:
                            next_idx = step_index[target]
                            self.events.emit(
                                EventType.BRANCH_TAKEN,
                                step_name=step_cfg.name,
                                metadata={
                                    "run_id": self._run_id,
                                    "branch": "on_success_step",
                                    "from_step": step_cfg.name,
                                    "to_step": target,
                                    "condition_result": True,
                                },
                            )
                            logger.info(
                                "[BRANCH] %s → %s (on_success_step)",
                                step_cfg.name, target,
                            )
                        else:
                            logger.warning(
                                "on_success_step '%s' not found in config — continuing linearly",
                                target,
                            )
                else:
                    # Step failed — check for on_failure_step branch first
                    if step_cfg.on_failure_step:
                        target = step_cfg.on_failure_step
                        if target in step_index:
                            next_idx = step_index[target]
                            self.events.emit(
                                EventType.BRANCH_TAKEN,
                                step_name=step_cfg.name,
                                metadata={
                                    "run_id": self._run_id,
                                    "branch": "on_failure_step",
                                    "from_step": step_cfg.name,
                                    "to_step": target,
                                    "error": sr.error,
                                },
                            )
                            logger.info(
                                "[BRANCH] %s → %s (on_failure_step, error: %s)",
                                step_cfg.name, target, sr.error,
                            )
                        else:
                            logger.warning(
                                "on_failure_step '%s' not found in config — falling back to on_failure policy",
                                target,
                            )
                            # Fall through to on_failure policy below
                            next_idx = self._apply_failure_policy(
                                step_cfg, result, current_idx, len(config.steps),
                            )
                            if next_idx is None:
                                aborted = True
                                break
                    else:
                        # No branch target — apply on_failure policy
                        next_idx = self._apply_failure_policy(
                            step_cfg, result, current_idx, len(config.steps),
                        )
                        if next_idx is None:
                            aborted = True
                            break

                # Phase 4.3: MCP-assisted decision for multi-path scenarios
                if (
                    config.use_mcp_decision
                    and self._decision_engine is not None
                    and not aborted
                ):
                    # Build candidates: deterministic next + any branch targets
                    candidates = []
                    det_next = config.steps[next_idx].name if next_idx < len(config.steps) else None
                    if det_next:
                        candidates.append(det_next)

                    # Add alternative branch targets as candidates
                    if sr.ok and step_cfg.on_success_step and step_cfg.on_success_step not in candidates:
                        candidates.append(step_cfg.on_success_step)
                    if not sr.ok and step_cfg.on_failure_step and step_cfg.on_failure_step not in candidates:
                        candidates.append(step_cfg.on_failure_step)
                    # Add linear next if not already the default
                    linear_next_idx = current_idx + 1
                    if linear_next_idx < len(config.steps):
                        linear_name = config.steps[linear_next_idx].name
                        if linear_name not in candidates:
                            candidates.append(linear_name)

                    # Only consult MCP when there are multiple candidates
                    if len(candidates) > 1:
                        selected = self._decision_engine.decide_next_step(
                            context=ctx,
                            current_step=step_cfg.name,
                            candidates=candidates,
                            results_map=results_map,
                            valid_steps=set(step_index.keys()),
                        )
                        if selected and selected in step_index:
                            next_idx = step_index[selected]

                current_idx = next_idx

            if not aborted:
                result.exit_code = 0

        except Exception as exc:
            logger.exception("Config-driven pipeline failed with unhandled error")
            result.exit_code = 1
            result.steps.append(StepResult(
                step=self._current_step or "unknown",
                ok=False,
                error=str(exc),
            ))
        finally:
            self._in_full_pipeline = False

        result.duration_ms = (time.monotonic() - pipeline_t0) * 1000

        if result.exit_code == 0:
            self._status = PipelineStatus.COMPLETED
            self.events.emit(
                EventType.PIPELINE_COMPLETED,
                metadata={
                    "run_id": self._run_id,
                    "duration_ms": round(result.duration_ms, 1),
                    "config": config.name,
                },
            )
        else:
            self._status = PipelineStatus.FAILED
            self.events.emit(
                EventType.PIPELINE_FAILED,
                metadata={
                    "run_id": self._run_id,
                    "duration_ms": round(result.duration_ms, 1),
                    "config": config.name,
                },
            )

        result.summary = _get_shared_stats()
        self._active_config = None
        return result

    def _apply_failure_policy(
        self,
        step_cfg: PipelineStepConfig,
        result: PipelineResult,
        current_idx: int,
        total_steps: int,
    ) -> int | None:
        """Apply on_failure policy and return the next step index, or None to abort.

        Phase 4.3: When ``use_mcp_retry`` is enabled and the policy is
        "abort", the DecisionEngine is consulted for a retry recommendation.
        If MCP recommends retry, the step is re-executed (same index).
        """
        # Phase 4.3: MCP retry intelligence for abort scenarios
        if (
            step_cfg.on_failure == "abort"
            and self._decision_engine is not None
            and self._active_config is not None
            and self._active_config.use_mcp_retry
        ):
            # Get the last step result for error info
            last_sr = result.steps[-1] if result.steps else None
            error_msg = last_sr.error if last_sr else "Unknown error"

            should_retry = self._decision_engine.should_retry(
                context={},
                step_name=step_cfg.name,
                error=str(error_msg),
                attempt=1,
                max_retries=1,
            )
            if should_retry:
                logger.info(
                    "Step '%s' failed but MCP recommends retry. Re-executing.",
                    step_cfg.name,
                )
                return current_idx  # retry: same index

        if step_cfg.on_failure == "abort":
            logger.error(
                "Step '%s' failed (on_failure=abort). Aborting pipeline.",
                step_cfg.name,
            )
            result.exit_code = 1
            return None  # signal abort
        elif step_cfg.on_failure == "skip":
            logger.warning(
                "Step '%s' failed (on_failure=skip). Continuing.",
                step_cfg.name,
            )
        else:  # continue
            logger.warning(
                "Step '%s' failed (on_failure=continue). Continuing.",
                step_cfg.name,
            )
        return current_idx + 1

    def run_pipeline(self, input_data: PipelineInput) -> PipelineResult:
        """Execute the full pipeline end-to-end.

        If ``input_data.config_name`` is set, delegates to
        ``run_pipeline_from_config`` with the named config.

        Otherwise, uses the legacy hardcoded orchestration for full
        backward compatibility.
        """
        # If a config name is specified, use the config-driven engine
        if input_data.config_name:
            try:
                config = load_builtin_config(input_data.config_name)
            except FileNotFoundError:
                from pipeline.config import load_config_from_file
                config = load_config_from_file(input_data.config_name)
            return self.run_pipeline_from_config(config, input_data)

        # If generate_only mode, use the generate-only config
        if input_data.generate_only:
            try:
                config = load_builtin_config("generate-only")
                return self.run_pipeline_from_config(config, input_data)
            except FileNotFoundError:
                pass  # fall through to legacy

        # Legacy path (preserved for backward compatibility)
        # If the caller supplied a trace_id on the input, re-resolve so that
        # the service, events, and logging all agree on the same ID.
        if input_data.trace_id and input_data.trace_id != self._trace_id:
            self._trace_id = resolve_trace_id(input_data.trace_id)
            self.events._trace_id = self._trace_id

        self._status = PipelineStatus.RUNNING
        self._step_results = []
        result = PipelineResult(trace_id=self._trace_id, run_id=self._run_id)

        logger.info("[trace_id=%s] [run_id=%s] Pipeline execution starting", self._trace_id, self._run_id)

        pipeline_t0 = time.monotonic()

        self.events.emit(
            EventType.PIPELINE_STARTED,
            metadata={
                "run_id": self._run_id,
                "excel_path": input_data.excel_path,
                "feature_name": input_data.feature_name,
                "mode": "generate-only" if input_data.generate_only else "pipeline",
            },
        )

        try:
            exit_code = self._run_full_pipeline(input_data, result)
            result.exit_code = exit_code
            result.duration_ms = (time.monotonic() - pipeline_t0) * 1000
            if exit_code == 0:
                self._status = PipelineStatus.COMPLETED
                self.events.emit(
                    EventType.PIPELINE_COMPLETED,
                    metadata={
                        "exit_code": 0,
                        "run_id": self._run_id,
                        "duration_ms": round(result.duration_ms, 1),
                    },
                )
            else:
                self._status = PipelineStatus.FAILED
                self.events.emit(
                    EventType.PIPELINE_FAILED,
                    metadata={
                        "exit_code": exit_code,
                        "run_id": self._run_id,
                        "duration_ms": round(result.duration_ms, 1),
                    },
                )
        except Exception as exc:
            result.duration_ms = (time.monotonic() - pipeline_t0) * 1000
            logger.exception("Pipeline failed with unhandled error")
            result.exit_code = 1
            result.steps.append(StepResult(
                step=self._current_step or "unknown",
                ok=False,
                error=str(exc),
            ))
            self._status = PipelineStatus.FAILED
            self.events.emit(
                EventType.PIPELINE_FAILED,
                step_name=self._current_step or "unknown",
                metadata={
                    "error": str(exc),
                    "run_id": self._run_id,
                    "duration_ms": round(result.duration_ms, 1),
                },
            )

        result.summary = _get_shared_stats()
        return result

    def execute_step(self, step: str | StepName, context: dict[str, Any] | None = None) -> StepResult:
        """Execute a *single* named pipeline step.

        This is the entry-point for agent-based flows that need granular
        control (e.g. only run DOM extraction, or only run tests).

        Execution priority:
          1. If an agent is registered for the stage → delegate to agent.run()
          2. Otherwise → use the built-in _step_handlers dispatch table

        During a full pipeline run (``_in_full_pipeline=True``), the service
        status stays RUNNING rather than resetting to IDLE after each step.

        Duration tracking: every step is timed with ``time.monotonic()`` and
        the ``duration_ms`` is included in the StepResult and event metadata.
        """
        ctx = context or {}
        step_name = step.value if isinstance(step, StepName) else step
        self._current_step = step_name
        self._status = PipelineStatus.RUNNING

        # Inject connector registry into context for connector-aware agents.
        # Uses a private key to avoid collisions with user-defined context keys.
        if "_connector_registry" not in ctx:
            ctx["_connector_registry"] = self._connector_registry

        # Check for registered agent first, then built-in handler
        agent = self._agent_registry.get(step_name)
        handler = self._step_handlers.get(step_name)

        if agent is None and handler is None:
            sr = StepResult(step=step_name, ok=False, error=f"Unknown step: {step_name}")
            self._step_results.append(sr)
            self.events.emit(
                EventType.ERROR_OCCURRED, step_name=step_name,
                metadata={"error": sr.error, "run_id": self._run_id},
            )
            if not self._in_full_pipeline:
                self._status = PipelineStatus.IDLE
            return sr

        self.events.emit(
            EventType.STEP_STARTED, step_name=step_name,
            metadata={"run_id": self._run_id},
        )

        t0 = time.monotonic()

        try:
            if agent is not None:
                # Delegate to agent — translate AgentResult → StepResult
                from pipeline.agents.base import AgentResult as _AgentResult

                self.events.emit(
                    EventType.AGENT_STARTED, step_name=step_name,
                    metadata={"agent": agent.name, "run_id": self._run_id},
                )
                agent_result = agent.run(ctx)
                duration_ms = (time.monotonic() - t0) * 1000

                sr = StepResult(
                    step=step_name,
                    ok=agent_result.ok,
                    data=agent_result.data,
                    error=agent_result.error,
                    duration_ms=duration_ms,
                )
                self.events.emit(
                    EventType.AGENT_COMPLETED, step_name=step_name,
                    metadata={
                        "agent": agent.name,
                        "run_id": self._run_id,
                        "duration_ms": round(duration_ms, 1),
                        "metrics": agent_result.metrics,
                    },
                )
                # Surface agent warnings via logging
                for w in agent_result.warnings:
                    logger.warning("[AGENT:%s] %s", agent.name, w)
            else:
                # Built-in handler
                sr = handler(self, ctx)
                duration_ms = (time.monotonic() - t0) * 1000
                sr.duration_ms = duration_ms
        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.exception("Step '%s' failed", step_name)
            sr = StepResult(step=step_name, ok=False, error=str(exc), duration_ms=duration_ms)

        if sr.ok:
            self.events.emit(
                EventType.STEP_COMPLETED, step_name=step_name,
                metadata={
                    "run_id": self._run_id,
                    "duration_ms": round(sr.duration_ms, 1),
                    **{k: v for k, v in sr.data.items() if k not in ("rows", "validated", "accepted", "steps", "feature_content")},
                },
            )
        else:
            self.events.emit(
                EventType.STEP_FAILED, step_name=step_name,
                metadata={
                    "error": sr.error,
                    "run_id": self._run_id,
                    "duration_ms": round(sr.duration_ms, 1),
                },
            )

        self._step_results.append(sr)
        self._current_step = None
        if not self._in_full_pipeline:
            self._status = PipelineStatus.IDLE
        return sr

    # ------------------------------------------------------------------
    # Infrastructure helpers
    # ------------------------------------------------------------------

    def _ensure_ai_stack(self):
        """Lazy-init the AI/vector-store stack (shared across steps)."""
        if self._dom_store is None:
            self._ai_client, self._embedder, self._dom_store, self._config = _init_ai_stack()
        return self._config, self._dom_store

    # Context manager support — guarantees cleanup on all exit paths.
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self) -> None:
        """Release resources (Qdrant connections, AI client, embedder)."""
        if self._dom_store is not None:
            try:
                self._dom_store.close()
            except Exception:
                pass
            self._dom_store = None
        # Also release AI client and embedder to prevent connection leaks
        self._ai_client = None
        self._embedder = None

    # ------------------------------------------------------------------
    # Individual step implementations
    # ------------------------------------------------------------------

    def _step_detect_excel(self, ctx: dict) -> StepResult:
        from pipeline.utils import detect_excel

        excel_path = ctx.get("excel_path")
        raw_path: str | None = None

        # If path is already set (e.g., from ADO data source), validate it exists
        if excel_path is not None:
            p = Path(excel_path).expanduser().resolve()
            if p.exists():
                logger.info("Using pre-set input file: %s", p)
                return StepResult(
                    step=StepName.DETECT_EXCEL.value,
                    ok=True,
                    data={"excel_path": str(p), "raw_path": None},
                )
            else:
                logger.warning("Pre-set input file not found: %s — auto-detecting", p)
                excel_path = None

        if excel_path is None:
            excel_path, raw_path = detect_excel()

        return StepResult(
            step=StepName.DETECT_EXCEL.value,
            ok=True,
            data={"excel_path": excel_path, "raw_path": raw_path},
        )

    def _step_read_excel(self, ctx: dict) -> StepResult:
        excel_path = ctx.get("excel_path")
        if not excel_path:
            return StepResult(step=StepName.READ_EXCEL.value, ok=False, error="excel_path required")

        path = Path(excel_path).expanduser().resolve()
        ext = path.suffix.lower()

        # Use PipelineInputAdapter for JSON/CSV, Excel reader for xlsx
        if ext in (".json", ".csv"):
            from pipeline.io import PipelineInputAdapter
            rows = PipelineInputAdapter.detect_and_load(path)
            logger.info("Loaded %d rows from %s file: %s", len(rows), ext, path.name)
        else:
            from excel.excel_reader import read_excel
            rows = read_excel(path)

        return StepResult(
            step=StepName.READ_EXCEL.value,
            ok=True,
            data={"excel_path": str(path), "rows": rows, "row_count": len(rows)},
        )

    def _step_init_dom(self, ctx: dict) -> StepResult:
        """Initialise AI stack and populate DOM KB if needed.

        This consolidates the duplicated logic that existed in:
          - main.py lines 263-336
          - dom_tools.py lines 73-126
        """
        force_scan = ctx.get("force_scan", False)
        config, dom_store = self._ensure_ai_stack()

        base_url, username, password = _resolve_dom_env()

        if force_scan or not dom_store.is_populated():
            if force_scan:
                try:
                    dom_store.clear()
                except Exception as exc:
                    logger.warning("[DOM] Could not clear DOM KB: %s", exc)

            logger.info("[DOM] DOM KB not populated — extracting from %s", base_url)
            from framework.dom_extractor import extract_all_pages

            elements = extract_all_pages(
                base_url=base_url, username=username, password=password,
            )
            dom_store.store_elements(elements)

            pages_scanned = len({e.page_name for e in elements})
            ai_stats.increment("dom_elements", len(elements))
            ai_stats.increment("pages_scanned", pages_scanned)

            return StepResult(
                step=StepName.INIT_DOM.value,
                ok=True,
                data={
                    "source": "extracted",
                    "element_count": len(elements),
                    "pages_scanned": pages_scanned,
                },
            )
        else:
            cached_count = dom_store.count()
            ai_stats.increment("dom_elements", cached_count)
            return StepResult(
                step=StepName.INIT_DOM.value,
                ok=True,
                data={"source": "cached", "element_count": cached_count},
            )

    def _step_extract_dom(self, ctx: dict) -> StepResult:
        """Enrich rows with DOM/RAG locator information.

        This consolidates the per-row enrichment logic from dom_tools.py.
        """
        rows = ctx.get("rows", [])
        config, dom_store = self._ensure_ai_stack()

        from framework.rag.element_resolver import RAGElementResolver
        from framework.locator_engine import get_best_selector

        resolver = RAGElementResolver(dom_store)
        enriched: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []

        for row in rows:
            page = str(row.get("Page") or "").strip() or None
            target = str(row.get("Target") or "").strip()

            dom_info: dict[str, Any] | None = None
            if target and target != "-":
                resolved = resolver.resolve(target, page_filter=page)
                if resolved is None:
                    unresolved.append({"page": page, "target": target})
                else:
                    selector = get_best_selector(resolved)
                    dom_info = {
                        "original_query": resolved.original_query,
                        "matched_element": resolved.matched_element,
                        "page": resolved.page,
                        "tag": resolved.tag,
                        "score": resolved.score,
                        "selector": selector,
                        "locator_candidates": list(resolved.locator_candidates),
                        "attributes": dict(resolved.attributes),
                    }

            enriched.append({
                "TC_ID": row.get("TC_ID"),
                "Page": row.get("Page"),
                "Action": row.get("Action"),
                "Target": row.get("Target"),
                "Value": row.get("Value"),
                "Expected": row.get("Expected"),
                "dom": dom_info,
            })

        return StepResult(
            step=StepName.EXTRACT_DOM.value,
            ok=True,
            data={
                "steps": enriched,
                "step_count": len(enriched),
                "unresolved": unresolved,
                "unresolved_count": len(unresolved),
            },
        )

    def _step_register_pages(self, ctx: dict) -> StepResult:
        config, dom_store = self._ensure_ai_stack()
        from pipeline.utils import discover_dom_pages
        from core.pages.page_registry import register_dynamic_pages

        dom_pages = discover_dom_pages(dom_store)
        register_dynamic_pages(dom_pages)

        return StepResult(
            step=StepName.REGISTER_PAGES.value,
            ok=True,
            data={"pages": sorted(dom_pages)},
        )

    def _step_convert_raw(self, ctx: dict) -> StepResult:
        import pandas as pd
        from ai.raw_step_converter import RawStepConverter

        raw_path = ctx.get("raw_path")
        excel_path = ctx.get("excel_path")
        if not raw_path:
            return StepResult(step=StepName.CONVERT_RAW.value, ok=True, data={"skipped": True})

        config, dom_store = self._ensure_ai_stack()
        converter = RawStepConverter(config, dom_store=dom_store)
        converter.convert_file(raw_path, excel_path)

        raw_count = len(pd.read_excel(raw_path, dtype=str))
        ai_stats.increment("raw_steps_converted", raw_count)

        return StepResult(
            step=StepName.CONVERT_RAW.value,
            ok=True,
            data={"raw_path": raw_path, "excel_path": excel_path, "rows_converted": raw_count},
        )

    def _step_version_check(self, ctx: dict) -> StepResult:
        from generator.version_manager import has_changed

        excel_path = ctx.get("excel_path")
        force = ctx.get("force", False)

        changed = force or has_changed(excel_path)
        if force:
            if LATEST_MANIFEST_PATH.exists():
                LATEST_MANIFEST_PATH.unlink()

        return StepResult(
            step=StepName.VERSION_CHECK.value,
            ok=True,
            data={"changed": changed, "forced": force},
        )

    def _step_validate(self, ctx: dict) -> StepResult:
        from validator.schema_validator import validate_schema
        from validator.action_validator import validate_action
        from validator.workflow_validator import validate_workflow

        rows = ctx.get("rows", [])
        if not rows:
            return StepResult(
                step=StepName.VALIDATE.value, ok=False,
                error="No rows to validate (empty input)",
            )
        validate_schema(rows[0].keys())

        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row["TC_ID"]].append(row)

        validated: dict[str, list[dict]] = {}
        rejected: list[str] = []

        for tc_id, tc_rows in grouped.items():
            try:
                validate_workflow(tc_id, tc_rows)
                for row in tc_rows:
                    validate_action(row)
                validated[tc_id] = tc_rows
            except (ValueError, TypeError, KeyError) as e:
                rejected.append(tc_id)
                logger.warning("[SKIP] %s validation failed: %s", tc_id, e)

        if not validated:
            return StepResult(
                step=StepName.VALIDATE.value,
                ok=False,
                error="No test cases passed validation",
                data={"rejected": rejected},
            )

        return StepResult(
            step=StepName.VALIDATE.value,
            ok=True,
            data={
                "validated": validated,
                "validated_count": len(validated),
                "rejected": rejected,
                "rejected_count": len(rejected),
            },
        )

    def _step_normalize(self, ctx: dict) -> StepResult:
        from ai.normalizer import AINormaliser, GenerationError, NormalisedStep

        validated = ctx.get("validated", {})
        config, dom_store = self._ensure_ai_stack()

        normaliser = AINormaliser(config, dom_store=dom_store)
        accepted: dict[str, list[NormalisedStep]] = {}
        rejected: list[str] = []

        for tc_id, tc_rows in validated.items():
            logger.info("Normalising TC '%s' (%d steps)", tc_id, len(tc_rows))
            try:
                steps = normaliser.normalise_tc(tc_id, tc_rows)
                accepted[tc_id] = steps
            except GenerationError as e:
                rejected.append(tc_id)
                logger.error("[FAIL] %s REJECTED: %s", tc_id, e)

        normaliser.close()

        if not accepted:
            return StepResult(
                step=StepName.NORMALIZE.value,
                ok=False,
                error="No test cases passed normalisation",
                data={"rejected": rejected},
            )

        return StepResult(
            step=StepName.NORMALIZE.value,
            ok=True,
            data={
                "accepted": accepted,
                "accepted_count": len(accepted),
                "rejected": rejected,
            },
        )

    def _step_generate(self, ctx: dict) -> StepResult:
        from generator.feature_generator import generate_feature, write_feature_file
        from generator.version_manager import create_version_folder, save_artifact

        accepted = ctx.get("accepted", {})
        feature_name = ctx.get("feature_name", "Login")
        excel_path = ctx.get("excel_path", "")

        content = generate_feature(feature_name, accepted)
        feature_path = write_feature_file(feature_name, content)

        version_folder = create_version_folder(excel_path)
        save_artifact(
            version_folder,
            f"{feature_name.lower().replace(' ', '_')}.feature",
            content,
        )

        # Build a snapshot for the versioned run_summary (in-memory, no
        # redundant disk write — _step_persist writes latest_run.json).
        run_stats = _get_shared_stats()
        snapshot = {
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "trace_id": self._trace_id,
            "mode": ctx.get("mode", "pipeline"),
            "regenerated": True,
            "excel": excel_path,
            "feature": feature_path,
            "version_folder": version_folder,
            "stats": run_stats,
            "cumulative": _read_json(CUMULATIVE_STATS_PATH).get("cumulative", {}),
        }
        save_artifact(
            version_folder,
            "run_summary.json",
            json.dumps(snapshot, indent=2),
        )

        return StepResult(
            step=StepName.GENERATE.value,
            ok=True,
            data={
                "feature_path": feature_path,
                "feature_content": content,
                "version_folder": version_folder,
            },
        )

    def _step_execute(self, ctx: dict) -> StepResult:
        from execution.runner import run_tests

        # Release Qdrant connection so the pytest subprocess can access
        # the local vector store without file-lock contention.
        self.close()

        result = run_tests()

        # ── TRUTH VALIDATION ──────────────────────────────────────────
        # Never infer success from exit code alone.  A pytest run that
        # discovers 0 tests (or skips all) may still exit with code 0,
        # which would be a *false positive*.  We require at least one
        # test to have actually passed before marking the step ok.
        truly_ok = result.success and result.total > 0 and result.passed > 0

        if result.success and not truly_ok:
            logger.warning(
                "[TRUTH] _step_execute: exit_code=0 but total=%d passed=%d "
                "skipped=%d — marking step as FAIL (false-positive prevention)",
                result.total, result.passed, result.skipped,
            )

        return StepResult(
            step=StepName.EXECUTE.value,
            ok=truly_ok,
            data={
                "exit_code": result.exit_code,
                "passed": result.passed,
                "failed": result.failed,
                "errors": result.errors,
                "skipped": result.skipped,
                "total": result.total,
                "success": result.success,
                "validated_ok": truly_ok,
            },
        )

    def _step_persist(self, ctx: dict) -> StepResult:
        """Persist final run summary and cumulative stats."""
        from generator.version_manager import save_artifact, get_latest_version_folder

        run_stats = _get_shared_stats()
        cumulative = _update_cumulative_stats(run_stats).get("cumulative", {})

        payload = {
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "trace_id": self._trace_id,
            "mode": ctx.get("mode", "pipeline"),
            "regenerated": ctx.get("regenerated", True),
            "excel": ctx.get("excel_path", ""),
            "feature": ctx.get("feature_path", ""),
            "version_folder": ctx.get("version_folder", ""),
            "tests": ctx.get("tests", {}),
            "stats": run_stats,
            "cumulative": cumulative,
        }
        _write_json(str(LATEST_RUN_PATH), payload)

        version_folder = ctx.get("version_folder") or get_latest_version_folder()
        if version_folder:
            save_artifact(
                version_folder,
                "run_summary.json",
                json.dumps(payload, indent=2),
            )

        return StepResult(
            step=StepName.PERSIST.value,
            ok=True,
            data=payload,
        )

    # Step dispatch table
    _step_handlers: dict[str, Any] = {
        StepName.DETECT_EXCEL.value: _step_detect_excel,
        StepName.READ_EXCEL.value: _step_read_excel,
        StepName.INIT_DOM.value: _step_init_dom,
        StepName.EXTRACT_DOM.value: _step_extract_dom,
        StepName.REGISTER_PAGES.value: _step_register_pages,
        StepName.CONVERT_RAW.value: _step_convert_raw,
        StepName.VERSION_CHECK.value: _step_version_check,
        StepName.VALIDATE.value: _step_validate,
        StepName.NORMALIZE.value: _step_normalize,
        StepName.GENERATE.value: _step_generate,
        StepName.EXECUTE.value: _step_execute,
        StepName.PERSIST.value: _step_persist,
    }

    # ------------------------------------------------------------------
    # Full pipeline orchestration (extracted from main.py:run_pipeline)
    # ------------------------------------------------------------------

    def _run_full_pipeline(self, inp: PipelineInput, result: PipelineResult) -> int:
        """Internal: run every stage in sequence.

        All steps are routed through :meth:`execute_step` so that
        STEP_STARTED / STEP_COMPLETED / STEP_FAILED events are emitted
        consistently — the dashboard event stream gets real-time updates.
        """
        self._in_full_pipeline = True
        try:
            return self._run_full_pipeline_inner(inp, result)
        finally:
            self._in_full_pipeline = False

    def _run_full_pipeline_inner(self, inp: PipelineInput, result: PipelineResult) -> int:
        """Actual sequential orchestration (always called with _in_full_pipeline=True)."""

        os.environ.setdefault("AI_STATS_PATH", str(ARTIFACTS_DIR / "latest_stats.json"))
        ai_stats.reset()

        # ── 1. Detect Excel ────────────────────────────────────────────
        detect_sr = self.execute_step(StepName.DETECT_EXCEL, {"excel_path": inp.excel_path})
        result.steps.append(detect_sr)
        if not detect_sr.ok:
            return 1

        excel_path = detect_sr.data["excel_path"]
        raw_path = detect_sr.data.get("raw_path")

        logger.info("=" * 55)
        logger.info("  AI-Driven Automation Framework - Pipeline Start")
        logger.info("=" * 55)
        if raw_path:
            logger.info("[INFO] Raw Excel detected: %s", raw_path)
            logger.info("[INFO] Template target:    %s", excel_path)
        else:
            logger.info("[INFO] Excel detected: %s", excel_path)

        # ── 2. DOM Knowledge Extraction ────────────────────────────────
        dom_sr = self.execute_step(StepName.INIT_DOM, {"force_scan": inp.force_scan})
        result.steps.append(dom_sr)
        if not dom_sr.ok:
            return 1

        # Log DOM status banner (via logger, not print — service-layer hygiene)
        src = dom_sr.data.get("source", "unknown")
        elem_count = dom_sr.data.get("element_count", 0)
        pages_count = dom_sr.data.get("pages_scanned", "?")
        logger.info("=" * 60)
        if src == "extracted":
            logger.info("  AI DOM Knowledge Base Ready")
            logger.info("-" * 60)
            logger.info("  Total elements indexed: %d", elem_count)
            logger.info("  Pages scanned:          %s", pages_count)
        else:
            logger.info("  AI DOM Knowledge Base Loaded From Cache")
            logger.info("-" * 60)
            logger.info("  Total elements indexed: %d", elem_count)
        logger.info("  Vector DB:              Qdrant (local)")
        logger.info("=" * 60)

        # ── 2a. Register Dynamic Pages ─────────────────────────────────
        pages_sr = self.execute_step(StepName.REGISTER_PAGES, {})
        result.steps.append(pages_sr)

        # ── 2b. Raw Step Conversion ────────────────────────────────────
        force = inp.force
        if raw_path is not None:
            logger.info("=" * 60)
            logger.info("  Converting Raw Steps -> Structured Template")
            logger.info("-" * 60)

            raw_sr = self.execute_step(StepName.CONVERT_RAW, {
                "raw_path": raw_path,
                "excel_path": excel_path,
            })
            result.steps.append(raw_sr)

            if raw_sr.ok and not raw_sr.data.get("skipped"):
                logger.info("  Raw steps converted:    %d", raw_sr.data.get("rows_converted", 0))
                logger.info("  Output:                 %s", excel_path)
                logger.info("=" * 60)
                force = True  # regenerate after raw conversion

        # ── 3. Version check ───────────────────────────────────────────
        vc_sr = self.execute_step(StepName.VERSION_CHECK, {"excel_path": excel_path, "force": force})
        result.steps.append(vc_sr)

        if not vc_sr.data["changed"]:
            logger.info("Excel unchanged (same mtime). Skipping regeneration.")
            if inp.generate_only:
                logger.info("Generation-only mode - nothing to regenerate.")
                self.execute_step(StepName.PERSIST, {
                    "mode": "generate-only",
                    "regenerated": False,
                    "excel_path": excel_path,
                    "version_folder": self._get_latest_version_folder(),
                })
                return 0

            logger.info("Executing tests from existing generated feature...")
            exec_sr = self.execute_step(StepName.EXECUTE, {})
            result.steps.append(exec_sr)
            self.execute_step(StepName.PERSIST, {
                "mode": "run-only",
                "regenerated": False,
                "excel_path": excel_path,
                "version_folder": self._get_latest_version_folder(),
                "tests": exec_sr.data,
            })
            return exec_sr.data.get("exit_code", 1)

        # ── 4. Read Excel ──────────────────────────────────────────────
        read_sr = self.execute_step(StepName.READ_EXCEL, {"excel_path": excel_path})
        result.steps.append(read_sr)
        if not read_sr.ok:
            return 1
        rows = read_sr.data["rows"]

        # ── 5-6. Validate ──────────────────────────────────────────────
        logger.info("[INFO] Validating schema...")
        val_sr = self.execute_step(StepName.VALIDATE, {"rows": rows})
        result.steps.append(val_sr)
        if not val_sr.ok:
            logger.error("No test cases passed validation. Aborting.")
            return 1

        validated = val_sr.data["validated"]
        logger.info(
            "Validation passed: %d TC(s) - %s",
            len(validated), sorted(validated.keys()),
        )

        # ── 7. AI Normalisation ────────────────────────────────────────
        logger.info("Initialising AI Normaliser (Azure OpenAI + Qdrant RAG + DOM Knowledge)...")
        norm_sr = self.execute_step(StepName.NORMALIZE, {"validated": validated})
        result.steps.append(norm_sr)
        if not norm_sr.ok:
            logger.error("No test cases passed normalisation. Aborting.")
            return 1

        accepted = norm_sr.data["accepted"]
        logger.info("--- Normalisation Summary ---")
        logger.info("  Accepted: %d - %s", len(accepted), sorted(accepted.keys()))

        # ── 8. Generate feature file ───────────────────────────────────
        logger.info("[INFO] Generating feature file: %s", inp.feature_name)
        gen_sr = self.execute_step(StepName.GENERATE, {
            "accepted": accepted,
            "feature_name": inp.feature_name,
            "excel_path": excel_path,
            "mode": "generate" if inp.generate_only else "pipeline",
        })
        result.steps.append(gen_sr)

        feature_path = gen_sr.data["feature_path"]
        version_folder = gen_sr.data["version_folder"]
        content = gen_sr.data["feature_content"]

        # Log generated feature for visibility
        logger.info("=" * 60)
        logger.info("GENERATED FEATURE FILE:")
        logger.info("=" * 60)
        for line in content.splitlines():
            logger.info("  %s", line)
        logger.info("=" * 60)

        # ── 9. Generate-only exit ──────────────────────────────────────
        if inp.generate_only:
            logger.info("=" * 55)
            logger.info("  Generation Complete (--generate-only)")
            logger.info("  Excel:    %s", excel_path)
            logger.info("  Feature:  %s", feature_path)
            logger.info("  Version:  %s", version_folder)
            logger.info("  Tests:    skipped")
            logger.info("=" * 55)
            self.execute_step(StepName.PERSIST, {
                "mode": "generate-only",
                "regenerated": True,
                "excel_path": excel_path,
                "feature_path": feature_path,
                "version_folder": version_folder,
                "tests": {"skipped": True},
            })
            return 0

        # ── 10. Execute tests ──────────────────────────────────────────
        self.close()  # Release Qdrant so pytest subprocess can access it
        logger.info("[INFO] DOM store released - Qdrant available for test subprocess")

        logger.info("[INFO] Executing tests...")
        exec_sr = self.execute_step(StepName.EXECUTE, {})
        result.steps.append(exec_sr)

        # ── 11. Persist final summary ──────────────────────────────────
        self.execute_step(StepName.PERSIST, {
            "mode": "pipeline",
            "regenerated": True,
            "excel_path": excel_path,
            "feature_path": feature_path,
            "version_folder": version_folder,
            "tests": exec_sr.data,
        })

        # ── 12. Log summary ───────────────────────────────────────────
        logger.info("=" * 55)
        logger.info("  Pipeline Complete")
        logger.info("  Excel:    %s", excel_path)
        logger.info("  Feature:  %s", feature_path)
        logger.info("  Version:  %s", version_folder)
        logger.info(
            "  Tests:    %d passed, %d failed",
            exec_sr.data.get("passed", 0), exec_sr.data.get("failed", 0),
        )
        logger.info("=" * 55)

        return exec_sr.data.get("exit_code", 1)

    @staticmethod
    def _get_latest_version_folder() -> str | None:
        from generator.version_manager import get_latest_version_folder
        return get_latest_version_folder()
