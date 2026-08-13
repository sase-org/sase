"""Immutable worker data for the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import dataclass

from sase.notifications.models import Notification
from sase.plan_search.model import PlanSearchMatch

from .bead_plan_links import BeadPlanLink


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
class ProjectArchive:
    """An archived plan together with the project that owns its SDD root."""

    project: str
    match: PlanSearchMatch
    role: str = "plans"


@dataclass(frozen=True)
class LinkedPlanDocument:
    """Worker-loaded committed plan linked from a live bead."""

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
class ActivePlanDocument:
    """A committed plan document linked from a live bead."""

    project: str
    document: LinkedPlanDocument
    owner: BeadPlanLink
    role: str = "plans"


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
    active: tuple[ActivePlanDocument, ...]
    archive: tuple[ProjectArchive, ...]
    bead_plan_links: dict[tuple[str, str], BeadPlanLink]
    linked_plan_documents: dict[tuple[str, str], LinkedPlanDocument]
    source_key: tuple[object, ...]
    errors: dict[str, str]
    archive_truncated: bool = False
    provider_kind: str = "plan"
    provider_label: str = "Plan"


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
    "ActivePlanDocument",
    "LinkedPlanDocument",
    "PlanProposal",
    "PlansSnapshot",
    "ProjectArchive",
]
