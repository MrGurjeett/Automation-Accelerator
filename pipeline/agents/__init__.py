"""Pipeline agent layer — modular, reusable units of pipeline work.

Agents encapsulate domain-specific logic (parsing, validation, DOM
extraction, etc.) behind a uniform interface.  They do NOT emit events
directly — they return structured :class:`AgentResult` objects to the
pipeline orchestrator, which handles all event emission centrally via
:meth:`PipelineService.execute_step`.

Architecture::

    PipelineService  (orchestrator — owns events)
        └─ execute_step(stage, context)
               └─ StageAgent.run(context)  → AgentResult
                      ↑ no event emission here

This separation keeps agents testable in isolation and prevents
duplicate or inconsistent event streams.
"""

from pipeline.agents.base import BaseAgent, AgentResult, ConnectorAwareMixin
from pipeline.agents.registry import AgentRegistry

# MCP agent base
from pipeline.agents.mcp_base import MCPAgentBase

# Ingestion agents
from pipeline.agents.ingestion import (
    ExcelDetectionAgent,
    ExcelReaderAgent,
    RawStepConversionAgent,
)

# DOM agents
from pipeline.agents.dom import (
    DOMInitAgent,
    DOMExtractionAgent,
    PageRegistrationAgent,
)

# Processing agents
from pipeline.agents.processing import (
    ValidationAgent,
    NormalizationAgent,
    FeatureGenerationAgent,
)

# Output agents
from pipeline.agents.output import (
    VersionCheckAgent,
    ExecutionAgent,
    PersistenceAgent,
)

# MCP-powered agents (Phase 4.2)
from pipeline.agents.mcp_agents import (
    MCPGenerationAgent,
    MCPValidationAgent,
    MCPEnrichmentAgent,
    MCPRecoveryAgent,
)

__all__ = [
    # Base
    "BaseAgent",
    "AgentResult",
    "AgentRegistry",
    "ConnectorAwareMixin",
    "MCPAgentBase",
    # Ingestion
    "ExcelDetectionAgent",
    "ExcelReaderAgent",
    "RawStepConversionAgent",
    # DOM
    "DOMInitAgent",
    "DOMExtractionAgent",
    "PageRegistrationAgent",
    # Processing
    "ValidationAgent",
    "NormalizationAgent",
    "FeatureGenerationAgent",
    # Output
    "VersionCheckAgent",
    "ExecutionAgent",
    "PersistenceAgent",
    # MCP agents (Phase 4.2)
    "MCPGenerationAgent",
    "MCPValidationAgent",
    "MCPEnrichmentAgent",
    "MCPRecoveryAgent",
]
