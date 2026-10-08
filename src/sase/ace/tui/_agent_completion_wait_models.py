"""Wait-dependency count models and shared tribe parsing."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sase.agent.status_buckets import AGENT_STATUS_BUCKETS
from sase.bead_status_presentation import BEAD_STATUS_VALUES
from sase.core.agent_tribe import InvalidTribeError, parse_tribe_reference

if TYPE_CHECKING:
    from sase.core.wait_dependency_resolution import TribeWaitBinding


@dataclass(frozen=True, slots=True)
class AgentWaitStatusMaps:
    """Wait-display state derived from one already-loaded agent snapshot."""

    buckets: dict[str, str]
    clan_member_statuses: dict[str, tuple[tuple[str, str], ...]]
    tribe_bindings: dict[tuple[object, str], TribeWaitBinding]


@dataclass(frozen=True, slots=True)
class WaitAgentStatusCounts:
    """Compact status counts for one WAITING row's ordinary agent dependencies."""

    stopped: int = 0
    failed: int = 0
    starting: int = 0
    running: int = 0
    queued: int = 0
    waiting: int = 0
    done: int = 0
    unknown: int = 0

    @property
    def has_any(self) -> bool:
        """Return whether any agent dependency has a countable visible status."""
        return any(
            (
                self.stopped,
                self.failed,
                self.starting,
                self.running,
                self.queued,
                self.waiting,
                self.done,
                self.unknown,
            )
        )

    def count_for_bucket(self, bucket: str) -> int:
        """Return this row's count for a normalized agent status bucket."""
        field_name = WAIT_COUNT_FIELDS.get(bucket)
        if field_name is None:
            return 0
        return getattr(self, field_name)

    def nonzero_buckets(self) -> Iterator[tuple[str, int]]:
        """Yield canonical agent buckets with a positive count, unknown last."""
        for bucket in AGENT_STATUS_BUCKETS:
            count = self.count_for_bucket(bucket)
            if count > 0:
                yield bucket, count
        if self.unknown > 0:
            yield "unknown", self.unknown


@dataclass(frozen=True, slots=True)
class WaitBeadStatusCounts:
    """Compact status counts for one WAITING row's waited-on beads."""

    open: int = 0
    claimed: int = 0
    ready: int = 0
    snoozed: int = 0
    in_progress: int = 0
    closed: int = 0
    unknown: int = 0

    @property
    def has_any(self) -> bool:
        """Return whether any bead dependency has a countable visible status."""
        return any(
            (
                self.open,
                self.claimed,
                self.ready,
                self.snoozed,
                self.in_progress,
                self.closed,
                self.unknown,
            )
        )

    def count_for_status(self, status: str) -> int:
        """Return this row's count for an exact bead status or ``unknown``."""
        if status == "unknown":
            return self.unknown
        if status not in BEAD_COUNT_FIELDS:
            return 0
        return getattr(self, status)

    def nonzero_statuses(self) -> Iterator[tuple[str, int]]:
        """Yield canonical bead statuses with a positive count, unknown last."""
        for status in BEAD_STATUS_VALUES:
            count = getattr(self, status)
            if count > 0:
                yield status, count
        if self.unknown > 0:
            yield "unknown", self.unknown


@dataclass(frozen=True, slots=True)
class WaitDependencyStatusCounts:
    """Compact counts for one WAITING row's visible dependencies.

    ``follows`` is the epic-follow segment: cached statuses of the epics a
    FOLLOWING target was promoted to. It stays separate from ``beads`` so
    derived beads never inflate the authored-bead counts.
    """

    agents: WaitAgentStatusCounts = field(default_factory=WaitAgentStatusCounts)
    beads: WaitBeadStatusCounts = field(default_factory=WaitBeadStatusCounts)
    follows: WaitBeadStatusCounts = field(default_factory=WaitBeadStatusCounts)

    @property
    def has_any(self) -> bool:
        """Return whether any dependency domain has a countable status."""
        return self.agents.has_any or self.beads.has_any or self.follows.has_any


ZERO_WAIT_DEPENDENCY_STATUS_COUNTS = WaitDependencyStatusCounts()
WAIT_COUNT_FIELDS: dict[str, str] = {
    bucket: bucket.lower() for bucket in AGENT_STATUS_BUCKETS
}
BEAD_COUNT_FIELDS: frozenset[str] = frozenset(BEAD_STATUS_VALUES)


def parse_tribe_target(
    reference: str, *, stored_tribes: tuple[str, ...] = ()
) -> str | None:
    """Resolve a wait target reference using the same rows the binding uses.

    *stored_tribes* comes from the already-loaded ``tribe_rows`` snapshot, so
    a public ``@job`` reference resolves to an independent historical ``job``
    identity when one is present, matching the binding computed just below
    from the same rows — no extra I/O beyond what this render already loaded.
    """
    try:
        return parse_tribe_reference(reference, stored_tribes=stored_tribes)
    except InvalidTribeError:
        return None


__all__ = [
    "BEAD_COUNT_FIELDS",
    "WAIT_COUNT_FIELDS",
    "AgentWaitStatusMaps",
    "WaitAgentStatusCounts",
    "WaitBeadStatusCounts",
    "WaitDependencyStatusCounts",
    "ZERO_WAIT_DEPENDENCY_STATUS_COUNTS",
    "parse_tribe_target",
]
