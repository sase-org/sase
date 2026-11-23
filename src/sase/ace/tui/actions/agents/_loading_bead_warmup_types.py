"""Shared bead-warmup candidate and result types.

These dataclasses are imported by the narrow bead-warmup mixins
(:mod:`._loading_bead_warmup_scan`, :mod:`._loading_bead_warmup_candidates`,
and :mod:`._loading_bead_warmup_apply`). They live here under public names
so no new module imports a ``_``-prefixed name across the split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

__all__ = [
    "AgentBeadWarmupCandidates",
    "AgentBeadWarmupResults",
]


@dataclass(frozen=True, slots=True)
class AgentBeadWarmupCandidates:
    """Surfaced-row and relevant waiter cache work for one coalesced pass."""

    bead_display_agents: tuple[Agent, ...] = ()
    wait_bead_status_agents: tuple[Agent, ...] = ()
    follow_progress_agents: tuple[Agent, ...] = field(default_factory=tuple)
    stranded_projects: tuple[str, ...] = ()
    force_stranded_projects: tuple[str, ...] = ()
    force_stranded_immediate: bool = False
    stranded_scan_more: bool = False
    roster_generation: int = 0
    candidates_examined: int = 0
    cause_counts: tuple[tuple[str, int], ...] = ()

    def __bool__(self) -> bool:
        return bool(
            self.bead_display_agents
            or self.wait_bead_status_agents
            or self.follow_progress_agents
            or self.stranded_projects
            or self.force_stranded_projects
            or self.stranded_scan_more
        )

    @property
    def total_count(self) -> int:
        """Return total candidate rows across all bead warmup lanes."""
        return (
            len(self.bead_display_agents)
            + len(self.wait_bead_status_agents)
            + len(self.follow_progress_agents)
            + len(self.stranded_projects)
            + len(self.force_stranded_projects)
        )


@dataclass(frozen=True, slots=True)
class AgentBeadWarmupResults:
    """Cache-visible row changes produced by one bead warmup pass."""

    bead_display_results: dict[tuple[AgentType, str, str | None], bool]
    wait_bead_status_identities: set[tuple[AgentType, str, str | None]]
    follow_progress_identities: set[tuple[AgentType, str, str | None]] = field(
        default_factory=set
    )
    stranded_changed_projects: frozenset[str] = frozenset()
    stranded_warmed_projects: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        return bool(
            self.bead_display_results
            or self.wait_bead_status_identities
            or self.follow_progress_identities
            or self.stranded_changed_projects
            or self.stranded_warmed_projects
        )
