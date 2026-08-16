"""Internal data models for external issue reconciliation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sase.bead.model import Issue

from .budget import LANE_CHOP_TIMEOUT_SECONDS


@dataclass(frozen=True)
class MirrorReport:
    """Outcome of one issue-mirror reconciliation pass for one project."""

    project: str
    display_name: str
    issues_seen: int = 0
    beads_created: int = 0
    beads_closed: int = 0
    beads_reopened: int = 0
    notes_appended: int = 0
    #: Already covered under the lock; a real duplicate was avoided.
    conflicts: int = 0
    #: Skipped by ``external_mirror.issues.filters`` (or its deprecated
    #: ``exclude_labels`` alias).
    unmirrored: int = 0
    #: Planned creations or notes the pass budget could not apply this pass.
    deferred: int = 0
    provider_calls: int = 0
    checkpoint_advanced: bool = False
    #: Dry-run detail: the refs that would be (or were) created, in apply order.
    created_refs: tuple[str, ...] = ()
    #: Dry-run/apply detail: mirrored refs whose beads would be (or were) closed.
    closed_refs: tuple[str, ...] = ()
    #: Dry-run/apply detail: mirrored refs whose beads would be (or were) reopened.
    reopened_refs: tuple[str, ...] = ()
    #: Non-empty reason when the pass was degraded (backoff, auth failure, ...).
    degraded: str = ""


@dataclass(frozen=True)
class MirrorBudget:
    """Per-pass bounds shared by the chop and CLI so both converge alike.

    Unlike ``bead_claim_checks``, this reconciler handles exactly one project
    per invocation (the ``for_each`` fan-out already isolates projects into
    separate script runs), so there is no shared lock-wait budget to slice
    across competing projects in one pass.
    """

    #: Derived from ``LANE_CHOP_TIMEOUT_SECONDS``, the ``external_mirror``
    #: lane's configured ``chop_timeout``.
    work_seconds: float = 0.75 * LANE_CHOP_TIMEOUT_SECONDS
    max_creations: int = 25
    max_notes: int = 50


@dataclass(frozen=True)
class CreateCandidate:
    ref: str
    display_ref: str
    title: str
    description: str
    sort_key: tuple[str, str]


@dataclass(frozen=True)
class CoveredBead:
    bead: Issue
    mirrored: bool


@dataclass(frozen=True)
class TransitionCandidate:
    bead_id: str
    ref: str
    new_upstream_state: str
    action: Literal["close", "reopen", "none"]
    observation: str


@dataclass(frozen=True)
class ApplyOutcome:
    beads_created: int = 0
    beads_closed: int = 0
    beads_reopened: int = 0
    notes_appended: int = 0
    conflicts: int = 0
    deferred: int = 0
    created_refs: tuple[str, ...] = ()
    closed_refs: tuple[str, ...] = ()
    reopened_refs: tuple[str, ...] = ()
    applied_note_refs: dict[str, str] = field(default_factory=dict)
