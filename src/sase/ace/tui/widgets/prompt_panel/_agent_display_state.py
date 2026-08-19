"""Shared state types for agent prompt-panel rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sase.ace.patch.models import DeltaEntry
from sase.ace.tui.glossary_reads import GlossaryReadDisplayEvent
from sase.ace.tui.memory_reads import MemoryReadDisplayEvent
from sase.ace.tui.opened_workspaces import OpenedWorkspaceDisplayEvent
from sase.ace.tui.skill_uses import SkillUseDisplayEvent
from sase.ace.tui.tools import SlowToolSource
from sase.ace.tui.tools.report import SlowToolCallReportSpec
from sase.glossary.read_report import GlossaryReadReportSpec
from sase.plan_documents import PlanWorkspace
from sase.repo_inventory import RepoKind

from ...models.agent_associated_plan import (
    AssociatedPlanSummary,
    BeadSummary,
    PhaseBeadSummary,
)
from ..file_panel._linked_deltas import LinkedDeltaGroup
from ._artifact_files import ArtifactFilePath


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
    plan_workspaces: tuple[PlanWorkspace, ...] = ()
    # Epoch seconds when the commit was created; author time where available.
    created_at: int | None = None
    parent_ids: tuple[str, ...] = ()

    @property
    def is_merge(self) -> bool:
        """Whether this commit has more than one parent."""
        return len(self.parent_ids) > 1


@dataclass
class HeaderHintState:
    """Mutable file-hint state shared with hint-mode header rendering."""

    hint_counter: int
    hint_mappings: dict[int, str]
    workspace_dir: str | None
    tool_call_reports: dict[str, SlowToolCallReportSpec]
    commit_views: dict[int, CommitViewSpec] = field(default_factory=dict)
    glossary_reports: dict[str, GlossaryReadReportSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentHintRender:
    """Prompt-panel hint render result."""

    file_hints: dict[int, str]
    tool_call_reports: dict[str, SlowToolCallReportSpec]
    commit_views: dict[int, CommitViewSpec] = field(default_factory=dict)
    glossary_reports: dict[str, GlossaryReadReportSpec] = field(default_factory=dict)
    header_enrichment_pending: bool = False


type DetailContextLane = Literal[
    "plan-bead",
    "artifacts",
    "memory",
    "glossary",
    "skills",
    "workspaces",
    "slow-tools",
    "xprompts",
    "page-url",
    "wait-beads",
]
# The independently resolved/cached lanes inside `DetailHeaderSummary` (bead
# sase-l6.3). `plan-bead`, `artifacts`, `memory`, `glossary`, `skills`, and
# `workspaces` back the SASE CONTEXT lanes in `CONTEXT_LANE_ORDER`
# (`_agent_context.py:30`; `plan-bead` covers both PLAN and BEAD, which share
# one resolver). The remaining four back non-context summary fields resolved
# by the same worker. `bead_display` is deliberately not a lane: it is a
# cheap cache read (`cached_bead_display`), not a store parse, and its own
# dedicated worker (`start_agent_bead_display_resolve`) keeps it fresh
# independently of lane selection.
ALL_DETAIL_CONTEXT_LANES: frozenset[DetailContextLane] = frozenset(
    {
        "plan-bead",
        "artifacts",
        "memory",
        "glossary",
        "skills",
        "workspaces",
        "slow-tools",
        "xprompts",
        "page-url",
        "wait-beads",
    }
)


@dataclass(frozen=True)
class DetailHeaderSummary:
    """Precomputed data that is too expensive for hot header rendering."""

    xprompts_used: list[dict[str, Any]] | None = None
    bead_display: str | None = None
    wait_bead_statuses: tuple[tuple[str, str | None], ...] | None = None
    phase_bead: PhaseBeadSummary | None = None
    associated_plan: AssociatedPlanSummary | None = None
    delta_entries: list[DeltaEntry] | None = None
    linked_delta_groups: tuple[LinkedDeltaGroup, ...] = ()
    artifact_file_paths: list[ArtifactFilePath] | None = None
    memory_reads: tuple[MemoryReadDisplayEvent, ...] = ()
    glossary_reads: tuple[GlossaryReadDisplayEvent, ...] = ()
    skill_uses: tuple[SkillUseDisplayEvent, ...] = ()
    opened_workspaces: tuple[OpenedWorkspaceDisplayEvent, ...] = ()
    slow_tool_sources: tuple[SlowToolSource, ...] | None = None
    agent_page_url: str | None = None
    # Lanes this instance actually resolved (attempted), as opposed to lanes
    # that were never requested. A lane in `ready_lanes` whose field is still
    # falsy resolved to "nothing" rather than "not yet resolved". Defaults to
    # every lane so a summary built without lane selection (the common case)
    # is treated as a complete, mergeable snapshot.
    ready_lanes: frozenset[DetailContextLane] = ALL_DETAIL_CONTEXT_LANES

    @property
    def bead_summary(self) -> BeadSummary | None:
        """Return the generalized bead summary behind the compatibility field."""
        return self.phase_bead
