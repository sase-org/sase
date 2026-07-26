"""Shared value types for the Agents tab model."""

from dataclasses import dataclass
from enum import Enum

from sase.core.agent_types import AgentType


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


__all__ = ["AgentChildLinkage", "AgentType", "LinkedRepoMetadata"]
