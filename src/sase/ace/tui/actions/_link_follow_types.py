"""Types and debug counters for host-owned ``$`` link-follow."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from sase.ace.query_record import QueryRecord
from sase.core.artifact_entry_target import ArtifactEntryTarget

if TYPE_CHECKING:
    from .axe_display._loader_state import AxeItemKey

log = logging.getLogger(__name__)

_LINK_TRAIL_MAX = 32
_link_follow_outcomes: Counter[str] = Counter()


def record_link_follow_outcome(outcome: str) -> None:
    """Count one follow resolution or failure class for debug logging."""
    _link_follow_outcomes[outcome] += 1
    log.debug(
        "link-follow outcome=%s count=%d totals=%s",
        outcome,
        _link_follow_outcomes[outcome],
        dict(_link_follow_outcomes),
    )


@dataclass(frozen=True, slots=True)
class LinkTrailHop:
    """One successful link-follow origin, retained for future backtracking."""

    tab: str
    pane_key: str | None
    origin: ArtifactEntryTarget | None
    query_source: str | None
    project_scope: str | None = None
    axe_key: AxeItemKey | None = None
    #: Lumberjack this hop's forward jump had to expand to reveal its chop,
    #: recorded so walking back can put the AXE tree back the way it was.
    axe_fold_expanded: str | None = None


@dataclass(frozen=True, slots=True)
class LinkFollowTransaction:
    """One open ``$`` link-follow awaiting an authoritative pane outcome.

    Registered before any pane is asked to resolve *target*, so a
    synchronous completion (reported through the shared
    :meth:`~.entry_navigation.ArtifactEntryNavigator._complete_entry_request`
    seam) can be finalized safely. ``rung`` is the next ladder step to
    try and only ever increases, so an authoritative ``MISSING`` cannot
    retry a rung that already fired. ``hydrated`` marks that this
    transaction (or the one it restarted from) already spent its one
    targeted-hydration attempt, so a fetched row that still misses every
    rung on re-entry reports absence instead of hydrating in a loop.
    """

    generation: int
    ref: str
    target: ArtifactEntryTarget
    origin: LinkTrailHop
    rung: int
    origin_query: QueryRecord | None = None
    origin_target: ArtifactEntryTarget | None = None
    hydrated: bool = False


__all__ = [
    "LinkTrailHop",
    "_LINK_TRAIL_MAX",
    "_link_follow_outcomes",
    "LinkFollowTransaction",
    "record_link_follow_outcome",
]
