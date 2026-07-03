"""Shared state types for agent prompt-panel rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sase.ace.changespec.models import DeltaEntry
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.tools import ToolCallEntry

from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._agent_artifacts import AgentArtifactPath


@dataclass
class HeaderHintState:
    """Mutable file-hint state shared with hint-mode header rendering."""

    hint_counter: int
    hint_mappings: dict[int, str]
    workspace_dir: str | None


@dataclass(frozen=True)
class DetailHeaderSummary:
    """Precomputed data that is too expensive for hot header rendering."""

    xprompts_used: list[dict[str, Any]] | None = None
    bead_display: str | None = None
    delta_entries: list[DeltaEntry] | None = None
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = ()
    artifact_paths: list[AgentArtifactPath] | None = None
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = ()
    skill_uses: tuple[SkillUseDisplayEvent, ...] = ()
    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = ()
    slow_tool_candidates: tuple[ToolCallEntry, ...] | None = None
    slow_tool_end_reference: datetime | None = None
