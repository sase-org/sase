"""Immutable worker data for the Artifacts Beads pane."""

from __future__ import annotations

from dataclasses import dataclass

from sase.bead.model import Issue


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


__all__ = ["BeadsSnapshot", "PendingTriage", "ProjectBead"]
