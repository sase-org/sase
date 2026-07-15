"""Shared value types for the Agents tab model."""

from dataclasses import dataclass
from enum import Enum


class AgentType(Enum):
    """Types of agents that can be tracked."""

    RUNNING = "run"  # Manual sase run commands (RUNNING field)
    WORKFLOW = "workflow"  # Multi-step YAML workflows


class AgentChildLinkage(Enum):
    """How an agent row links to a parent row in the Agents tab."""

    ROOT = "root"
    WORKFLOW_STEP = "workflow_step"
    FAMILY_MEMBER = "family_member"


@dataclass(frozen=True)
class LinkedRepoMetadata:
    """Resolved linked repository metadata recorded for an agent run."""

    name: str
    workspace_dir: str
