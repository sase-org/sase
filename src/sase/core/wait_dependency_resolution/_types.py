"""Internal wait-dependency resolution records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.core.dismissed_agent_completion import (
    FAILURE_OUTCOMES,
    IDENTITY_SUCCESS_OUTCOMES,
    KNOWN_DONE_OUTCOMES,
    SUCCESS_OUTCOME,
    WAIT_SUCCESS_OUTCOMES,
    ArchivedAgentCompletion,
)

HANDOFF_TERMINAL_STEP_STATUSES = frozenset({"completed", "skipped"})


@dataclass(frozen=True)
class WaitCandidate:
    timestamp: str
    is_resolved: bool
    is_done: bool
    is_failed: bool = False
    name: str = ""
    project_name: str = ""
    artifact_dir: str = ""
    outcome: str | None = None
    has_done_marker: bool = False


@dataclass(frozen=True)
class ArtifactCandidate:
    name: str
    timestamp: str
    project_name: str
    artifact_dir: str
    parent_timestamp: str | None
    family_name: str | None
    is_resolved: bool
    is_done: bool
    is_identity_success: bool
    is_failed: bool = False
    is_queued: bool = False
    clan_name: str | None = None
    clan_generation: str | None = None
    clan_tribe: str | None = None
    archived_completion: ArchivedAgentCompletion | None = None
    outcome: str | None = None
    has_done_marker: bool = False


@dataclass(frozen=True)
class TribeCandidate:
    """The canonical next complete entity for one tribe wait target."""

    tribe: str
    kind: Literal["agent", "clan"]
    name: str
    timestamp: str
    members: tuple[ArtifactCandidate, ...]
    generation: str | None = None


@dataclass(frozen=True)
class FamilyCandidate:
    timestamp: str
    is_resolved: bool
    is_done: bool
    is_identity_success: bool = False
    is_failed: bool = False


@dataclass(frozen=True)
class WaitDependencyStatus:
    state: str
    blocked_on: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.state == "resolved"


@dataclass(frozen=True)
class SubmittedPlanArtifact:
    """A planner-phase artifact whose plan is submitted and awaiting review.

    ``plan_path`` is the proposed plan file. ``planner_row_name`` is the
    canonical ``<base>--plan`` row name the TUI shows for this artifact, used
    both as the ``%wait`` alias and the cross-agent ``agents[...]`` Jinja key.
    """

    plan_path: str
    planner_row_name: str
    base_name: str
