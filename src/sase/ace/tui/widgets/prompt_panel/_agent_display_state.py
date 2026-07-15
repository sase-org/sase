"""Shared state types for agent prompt-panel rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.ace.changespec.models import DeltaEntry
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.tools import SlowToolSource
from sase.ace.tui.tools.report import SlowToolCallReportSpec
from sase.repo_inventory import RepoKind

from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._agent_artifacts import AgentArtifactPath


@dataclass
class CommitViewSpec:
    """Commit metadata needed by the in-TUI commit viewer."""

    short_sha: str
    sha: str
    repo_name: str
    cwd: str | None
    subject: str
    message: str
    diff_path: str | None
    is_primary: bool
    repo_kind: RepoKind = "linked"


@dataclass
class HeaderHintState:
    """Mutable file-hint state shared with hint-mode header rendering."""

    hint_counter: int
    hint_mappings: dict[int, str]
    workspace_dir: str | None
    tool_call_reports: dict[str, SlowToolCallReportSpec]
    commit_views: dict[int, CommitViewSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentHintRender:
    """Prompt-panel hint render result."""

    file_hints: dict[int, str]
    tool_call_reports: dict[str, SlowToolCallReportSpec]
    commit_views: dict[int, CommitViewSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class DetailHeaderSummary:
    """Precomputed data that is too expensive for hot header rendering."""

    xprompts_used: list[dict[str, Any]] | None = None
    bead_display: str | None = None
    plan_goal: str | None = None
    delta_entries: list[DeltaEntry] | None = None
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = ()
    artifact_paths: list[AgentArtifactPath] | None = None
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = ()
    skill_uses: tuple[SkillUseDisplayEvent, ...] = ()
    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = ()
    slow_tool_sources: tuple[SlowToolSource, ...] | None = None
