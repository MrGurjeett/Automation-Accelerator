"""Pipeline configuration schema — defines the structure of config-driven pipelines.

A pipeline config is a declarative description of which steps to execute,
in what order, with what inputs, and under what conditions.  The config
engine in :mod:`pipeline.service` reads these configs and drives
``execute_step`` calls dynamically — replacing hardcoded orchestration.

Example JSON config::

    {
        "name": "full-pipeline",
        "version": "1",
        "description": "Full pipeline: ingest, validate, normalize, generate, execute",
        "defaults": {"feature_name": "Login"},
        "steps": [
            {"name": "detect_excel"},
            {"name": "init_dom", "inputs": {"force_scan": "$input.force_scan"}},
            {"name": "read_excel", "inputs": {"excel_path": "$detect_excel.data.excel_path"}},
            {"name": "validate", "inputs": {"rows": "$read_excel.data.rows"}}
        ]
    }
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass
class PipelineStepConfig:
    """Configuration for a single pipeline step.

    Attributes
    ----------
    name : str
        Step identifier (must match a StepName value or registered agent stage).
    agent : str | None
        Optional agent name to override the default handler for this step.
    inputs : dict
        Mapping of context keys to data sources.  Values can be:
        - Literal values (str, int, bool)
        - ``$steps.step_name.data.key`` references (Phase 3.5 formal)
        - ``$step_name.data.key`` references (Phase 3 legacy)
        - ``$input.field`` references to PipelineInput fields
    condition : str | dict | None
        Optional condition expression.  Step is skipped when False.
        - **String** (Phase 3): ``"$step.ok == true"``, ``"$step.data.key == value"``
        - **Dict** (Phase 3.5): ``{"eq": ["$steps.validate.ok", true]}``
        - Supports logical combinators: ``{"and": [...]}``, ``{"or": [...]}``, ``{"not": {...}}``
    on_failure : str
        Behavior when the step fails: ``"abort"`` (default), ``"skip"``, ``"continue"``
    on_success_step : str | None
        Step name to jump to after successful execution (non-linear routing).
        When ``None``, execution proceeds to the next step in the list.
    on_failure_step : str | None
        Step name to jump to after failed execution (non-linear routing).
        Takes precedence over ``on_failure`` policy when set.
    label : str
        Human-readable label for the stepper UI.
    timeout_s : int | None
        Optional timeout in seconds (reserved for future use).
    """

    name: str
    agent: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    condition: Any = None  # str | dict | None
    on_failure: str = "abort"
    on_success_step: str | None = None
    on_failure_step: str | None = None
    label: str = ""
    timeout_s: int | None = None

    def __post_init__(self):
        if self.on_failure not in ("abort", "skip", "continue"):
            raise ValueError(f"Invalid on_failure policy: {self.on_failure!r}")


@dataclass
class PipelineConfig:
    """Full pipeline configuration.

    Attributes
    ----------
    name : str
        Unique name for the config (e.g. ``"full-pipeline"``).
    version : str
        Schema version for forward compatibility.
    description : str
        Human-readable description.
    steps : list[PipelineStepConfig]
        Ordered list of steps to execute.
    defaults : dict
        Default context values available to all steps.
    """

    name: str
    version: str = "1"
    description: str = ""
    steps: list[PipelineStepConfig] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)

    # Phase 4.3 — MCP decision flags (all default False for backward compatibility)
    use_mcp_decision: bool = False
    use_mcp_retry: bool = False
    use_mcp_condition: bool = False

    @property
    def step_names(self) -> list[str]:
        return [s.name for s in self.steps]

    @property
    def step_labels(self) -> list[dict[str, str]]:
        """Return step key/label pairs for stepper UI."""
        return [
            {"key": s.name, "label": s.label or s.name.replace("_", " ").title()}
            for s in self.steps
        ]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_step_config(raw: dict[str, Any]) -> PipelineStepConfig:
    """Parse a raw dict into a PipelineStepConfig."""
    return PipelineStepConfig(
        name=raw["name"],
        agent=raw.get("agent"),
        inputs=raw.get("inputs", {}),
        condition=raw.get("condition"),
        on_failure=raw.get("on_failure", "abort"),
        on_success_step=raw.get("on_success_step"),
        on_failure_step=raw.get("on_failure_step"),
        label=raw.get("label", ""),
        timeout_s=raw.get("timeout_s"),
    )


def parse_pipeline_config(raw: dict[str, Any]) -> PipelineConfig:
    """Parse a raw dict (from JSON/YAML) into a PipelineConfig.

    Raises
    ------
    ValueError
        If the config is invalid (missing required fields, etc.).
    """
    if "name" not in raw:
        raise ValueError("Pipeline config must have a 'name' field")
    if "steps" not in raw or not raw["steps"]:
        raise ValueError("Pipeline config must have at least one step")

    steps = [parse_step_config(s) for s in raw["steps"]]

    return PipelineConfig(
        name=raw["name"],
        version=raw.get("version", "1"),
        description=raw.get("description", ""),
        steps=steps,
        defaults=raw.get("defaults", {}),
        use_mcp_decision=bool(raw.get("use_mcp_decision", False)),
        use_mcp_retry=bool(raw.get("use_mcp_retry", False)),
        use_mcp_condition=bool(raw.get("use_mcp_condition", False)),
    )


def load_config_from_file(path: str | Path) -> PipelineConfig:
    """Load a pipeline config from a JSON or YAML file.

    YAML requires ``pyyaml`` to be installed; JSON works out of the box.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")

    text = p.read_text(encoding="utf-8")

    if p.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError("pyyaml is required for YAML configs: pip install pyyaml")
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)

    return parse_pipeline_config(raw)


def load_builtin_config(name: str) -> PipelineConfig:
    """Load a built-in config by name.

    Searches ``pipeline/configs/`` for a file whose parsed ``name`` field
    matches, or whose filename (stem) matches.  Supports both dash and
    underscore variants (e.g. ``"full-pipeline"`` matches ``full_pipeline.json``).
    """
    configs_dir = Path(__file__).parent / "configs"

    # Normalize: try exact filename first, then with dash/underscore variants
    variants = [name, name.replace("-", "_"), name.replace("_", "-")]

    for variant in variants:
        for ext in (".json", ".yaml", ".yml"):
            p = configs_dir / f"{variant}{ext}"
            if p.exists():
                return load_config_from_file(p)

    # Fallback: scan all files and match by parsed name
    if configs_dir.exists():
        for p in configs_dir.iterdir():
            if p.suffix in (".json", ".yaml", ".yml"):
                try:
                    cfg = load_config_from_file(p)
                    if cfg.name == name:
                        return cfg
                except Exception:
                    continue

    available = list_available_configs()
    raise FileNotFoundError(
        f"Built-in config '{name}' not found. Available: {[c['name'] for c in available]}"
    )


def list_available_configs() -> list[dict[str, Any]]:
    """List all available pipeline configs (built-in + user).

    Returns a list of config summaries with name, description, step_count,
    and is_builtin.
    """
    configs = []
    configs_dir = Path(__file__).parent / "configs"

    if configs_dir.exists():
        for p in sorted(configs_dir.iterdir()):
            if p.suffix in (".json", ".yaml", ".yml"):
                try:
                    cfg = load_config_from_file(p)
                    configs.append({
                        "name": cfg.name,
                        "description": cfg.description,
                        "step_count": len(cfg.steps),
                        "steps": cfg.step_labels,
                        "is_builtin": True,
                        "path": str(p),
                    })
                except Exception as e:
                    logger.warning("Failed to load config %s: %s", p, e)

    return configs
