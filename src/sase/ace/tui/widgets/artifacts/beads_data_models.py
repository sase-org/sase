"""Immutable worker data for the Artifacts Beads pane."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sase.ace.patch.models import Patch
from sase.bead_flag_presentation import FlagDuePresentation
from sase.bead.model import Issue
from sase.vcs_provider import IssueWire

ExternalIssueRelation = Literal["mirrored", "referenced"]


@dataclass(frozen=True)
class ExternalIssueCapabilities:
    """Warm issue-tracker capability flags for one project."""

    listing: bool = False
    reads: bool = False
    mutations: bool = False
    urls: bool = False

    @property
    def any(self) -> bool:
        """Return whether the provider exposes any issue capability."""

        return self.listing or self.reads or self.mutations or self.urls


@dataclass(frozen=True)
class ExternalIssueProjectCache:
    """Bounded cached issue-list result for one project."""

    project: str
    display_name: str
    project_file: str = ""
    cwd: str = ""
    capabilities: ExternalIssueCapabilities = field(
        default_factory=ExternalIssueCapabilities
    )
    issues: tuple[IssueWire, ...] = ()
    refreshed_at: float = 0.0
    complete: bool = False
    truncated: bool = False
    error: str = ""

    def issue_for_number(self, number: int) -> IssueWire | None:
        """Return the cached issue with *number*, when the list contained it."""

        return next((issue for issue in self.issues if issue.number == number), None)


@dataclass(frozen=True)
class ExternalIssueLink:
    """A normalized local bead to external issue relationship."""

    external_ref: str
    project: str
    display_project: str
    issue_id: str
    relation: ExternalIssueRelation
    issue: IssueWire | None = None
    stale: bool = False
    drift: bool = False
    reverse_beads: tuple[Issue, ...] = ()
    reverse_patches: tuple[Patch, ...] = ()

    @property
    def state(self) -> str:
        """Return the tracker state, or the degraded link state."""

        if self.stale:
            return "stale"
        if self.issue is None:
            return "unknown"
        return self.issue.state


@dataclass(frozen=True)
class ProjectBead:
    """A bead together with the project that owns its store."""

    project: str
    issue: Issue


@dataclass(frozen=True)
class PendingTriage:
    """The pending TaskTriage gate associated with a task bead."""

    notification_id: str
    request_id: str
    created_at: str


@dataclass(frozen=True)
class BeadsSnapshot:
    """Immutable result applied to the Beads pane on the UI thread."""

    project: str | None
    projects: tuple[str, ...]
    display_names: dict[str, str]
    beads_dirs: dict[str, str | None]
    workspace_dirs: dict[str, str | None]
    tasks: tuple[ProjectBead, ...]
    epics: tuple[ProjectBead, ...]
    phases_by_epic: dict[tuple[str, str], tuple[ProjectBead, ...]]
    ready_ids: frozenset[tuple[str, str]]
    blocked_ids: frozenset[tuple[str, str]]
    plan_links: dict[tuple[str, str], str]
    triage_gates: dict[tuple[str, str], PendingTriage]
    source_key: tuple[object, ...]
    errors: dict[str, str]
    external_projects: dict[str, ExternalIssueProjectCache] = field(
        default_factory=dict
    )
    external_links: dict[tuple[str, str], tuple[ExternalIssueLink, ...]] = field(
        default_factory=dict
    )
    external_unmirrored_counts: dict[str, int] = field(default_factory=dict)
    external_source_key: tuple[object, ...] = ()
    flags: tuple[ProjectBead, ...] = ()
    flag_due: dict[tuple[str, str], FlagDuePresentation] = field(default_factory=dict)


__all__ = [
    "BeadsSnapshot",
    "ExternalIssueCapabilities",
    "ExternalIssueLink",
    "ExternalIssueProjectCache",
    "ExternalIssueRelation",
    "PendingTriage",
    "ProjectBead",
]
