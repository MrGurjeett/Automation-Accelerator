"""Unified pipeline package — single source of truth for execution orchestration."""

from pipeline.service import PipelineService, PipelineInput, PipelineResult, StepResult
from pipeline.events import EventManager, EventType, PipelineEvent
from pipeline.utils import detect_excel, discover_dom_pages
from pipeline.agents import AgentRegistry, BaseAgent, AgentResult
from pipeline.config import PipelineConfig, PipelineStepConfig, load_builtin_config, list_available_configs
from pipeline.conditions import ConditionEvaluator, evaluate_condition, resolve_ref
from pipeline.io import PipelineInputAdapter, PipelineOutputExporter
from pipeline.connectors import (
    BaseConnector,
    ConnectorResult,
    ConnectorRegistry,
    get_connector,
    initialize_connectors,
)

__all__ = [
    "PipelineService",
    "PipelineInput",
    "PipelineResult",
    "StepResult",
    "EventManager",
    "EventType",
    "PipelineEvent",
    "detect_excel",
    "discover_dom_pages",
    "AgentRegistry",
    "BaseAgent",
    "AgentResult",
    "PipelineConfig",
    "PipelineStepConfig",
    "load_builtin_config",
    "list_available_configs",
    "ConditionEvaluator",
    "evaluate_condition",
    "resolve_ref",
    "PipelineInputAdapter",
    "PipelineOutputExporter",
    "BaseConnector",
    "ConnectorResult",
    "ConnectorRegistry",
    "get_connector",
    "initialize_connectors",
]
