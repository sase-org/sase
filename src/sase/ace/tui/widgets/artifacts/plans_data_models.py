"""Immutable worker data for the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import dataclass

from sase.bead.model import Issue
from sase.notifications.models import Notification
from sase.plan_search.model import PlanSearchMatch


@dataclass(frozen=True)
class PlanProposal:
    """One pending plan approval with its existing notification context."""

    project: str
    notification: Notification
    title: str
    tier: str
    age: str
    timestamp: str
    plan_path: str
    content: str
    frontmatter: dict[str, str]
    body: str
    agent: str
    provider_model: str


@dataclass(frozen=True)
class ProjectIssue:
    """A bead issue together with the project that owns its store."""

    project: str
    issue: Issue


@dataclass(frozen=True)
class ProjectArchive:
    """An archived plan together with the project that owns its SDD root."""

    project: str
    match: PlanSearchMatch
    role: str = "plans"


@dataclass(frozen=True)
class LinkedPlanDocument:
    """Worker-loaded committed plan linked from an epic or phase bead."""

    reference: str
    path: str
    content: str
    frontmatter: dict[str, str]
    body: str
    error: str | None
    signature: tuple[int, int, int, int] | None

    @property
    def available(self) -> bool:
        """Return whether the linked document was read and parsed."""
        return self.error is None


@dataclass(frozen=True)
class PlansSnapshot:
    """Immutable result applied to the Plans pane on the UI thread."""

    project: str | None
    projects: tuple[str, ...]
    display_names: dict[str, str]
    beads_dirs: dict[str, str | None]
    plans_roots: dict[str, dict[str, str]]
    workspace_dirs: dict[str, str | None]
    proposals: tuple[PlanProposal, ...]
    epics: tuple[ProjectIssue, ...]
    phases_by_epic: dict[tuple[str, str], tuple[ProjectIssue, ...]]
    ready_ids: frozenset[tuple[str, str]]
    blocked_ids: frozenset[tuple[str, str]]
    archive: tuple[ProjectArchive, ...]
    linked_plan_documents: dict[tuple[str, str], LinkedPlanDocument]
    source_key: tuple[object, ...]
    errors: dict[str, str]
    archive_truncated: bool = False


@dataclass(frozen=True)
class DeepArchiveFetch:
    """One bounded, cross-project archive browse completed off-thread."""

    archive: tuple[ProjectArchive, ...]
    scanned_count: int
    capped: bool
    errors: dict[str, str]


@dataclass(frozen=True)
class PlansProject:
    """Resolved metadata for one project included in a snapshot."""

    project: str
    display_name: str
    workspace_dir: str | None


__all__ = [
    "LinkedPlanDocument",
    "PlanProposal",
    "PlansSnapshot",
    "ProjectArchive",
    "ProjectIssue",
]
