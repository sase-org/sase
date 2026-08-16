"""Candidate discovery for time-ordered agent jumps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ...models.agent_nodes import is_agents_tab_agent_node
from ...models.agent_status import is_unread_completed_status

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ._prospective_clan import ProspectiveClanMember


@dataclass(frozen=True, slots=True)
class TimedAgentJumpCandidate:
    """Stable jump target, optionally hidden by one collapsed clan fold."""

    identity: tuple[AgentType, str, str | None]
    panel_key: str | None
    jump_time: datetime | None
    visible_idx: int | None
    clan_fold_key: str | None = None


class AgentUnreadJumpCandidatesMixin:
    """Mixin that discovers visible and revealable timed jump targets."""

    _agents: list[Agent]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _unread_jump_candidates_cache: tuple[Any, Any] | None

    def _unread_timed_jump_candidates(self) -> list[TimedAgentJumpCandidate]:
        """Return a cached unread candidate projection for footer/jump reuse."""
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        complete = getattr(self, "_agents_with_children", None) or self._agents
        fold_manager = getattr(self, "_fold_manager", None)
        fold_signature = (
            tuple(
                sorted(
                    (key, level.value) for key, level in fold_manager.snapshot().items()
                )
            )
            if fold_manager is not None
            else ()
        )
        group_registry = getattr(self, "_group_fold_registry", None)
        status_signature = tuple(
            (
                agent.identity,
                agent.status,
                agent.start_time,
                agent.stop_time,
                agent.tree_parent_key,
            )
            for agent in complete
            if not agent.is_clan_container
        )
        cache_key = (
            id(self._agents),
            id(complete),
            frozenset(unread_ids),
            fold_signature,
            id(group_registry),
            getattr(group_registry, "version", 0),
            getattr(self, "_grouping_mode", None),
            bool(getattr(self, "_agent_panels_grouped", False)),
            getattr(self, "_agent_search_query", "") or "",
            id(getattr(self, "_agent_content_search_index", None)),
            status_signature,
        )
        cached = getattr(self, "_unread_jump_candidates_cache", None)
        if cached is not None and cached[0] == cache_key:
            return cached[1]

        candidates = self._timed_agent_jump_candidates(
            predicate=lambda agent: (
                is_agents_tab_agent_node(agent)
                and agent.identity in unread_ids
                and is_unread_completed_status(agent.status)
            ),
            time_for_agent=None,
            include_collapsed_clan_members=True,
        )
        self._unread_jump_candidates_cache = (cache_key, candidates)
        return candidates

    def _timed_agent_jump_candidates(
        self,
        *,
        predicate: Callable[[Agent], bool],
        time_for_agent: Callable[[Agent], datetime | None] | None,
        include_collapsed_clan_members: bool,
    ) -> list[TimedAgentJumpCandidate]:
        """Discover rendered targets plus revealable direct clan members."""
        if not self._agents and not getattr(self, "_agents_with_children", None):
            return []

        visible_panel_indices = self._visible_agent_panel_indices(  # type: ignore[attr-defined]
            include_collapsed_panels=True
        )
        panel_group = getattr(self, "_panel_group", None)
        candidates: list[TimedAgentJumpCandidate] = []
        seen: set[tuple[AgentType, str, str | None]] = set()
        for idx, panel_idx in visible_panel_indices.items():
            agent = self._agents[idx]
            if agent.is_clan_container or not predicate(agent):
                continue
            if panel_group is None:
                panel_key = None
            elif panel_idx is not None and 0 <= panel_idx < len(panel_group.panel_keys):
                panel_key = panel_group.panel_keys[panel_idx]
            else:
                continue
            candidates.append(
                TimedAgentJumpCandidate(
                    identity=agent.identity,
                    panel_key=panel_key,
                    jump_time=(
                        time_for_agent(agent)
                        if time_for_agent is not None
                        else agent.stop_time or agent.start_time
                    ),
                    visible_idx=idx,
                )
            )
            seen.add(agent.identity)

        if include_collapsed_clan_members:
            candidates.extend(
                self._collapsed_clan_jump_candidates(
                    predicate=predicate,
                    time_for_agent=time_for_agent,
                    seen=seen,
                )
            )

        candidates.sort(
            key=lambda candidate: candidate.jump_time or datetime.min,
            reverse=True,
        )
        return candidates

    def _collapsed_clan_jump_candidates(
        self,
        *,
        predicate: Callable[[Agent], bool],
        time_for_agent: Callable[[Agent], datetime | None] | None,
        seen: set[tuple[AgentType, str, str | None]],
    ) -> list[TimedAgentJumpCandidate]:
        """Return direct members hidden only by collapsed outer clan folds."""
        complete = list(getattr(self, "_agents_with_children", ()) or ())
        fold_manager = getattr(self, "_fold_manager", None)
        if not complete or fold_manager is None:
            return []

        candidates: list[TimedAgentJumpCandidate] = []
        projected = self._prospective_clan_member_panels(complete)
        for target in projected.values():
            member = target.agent
            if member.identity in seen or not predicate(member):
                continue
            candidates.append(
                TimedAgentJumpCandidate(
                    identity=member.identity,
                    panel_key=target.panel_key,
                    jump_time=(
                        time_for_agent(member)
                        if time_for_agent is not None
                        else member.stop_time or member.start_time
                    ),
                    visible_idx=None,
                    clan_fold_key=target.clan_fold_key,
                )
            )
            seen.add(member.identity)
        return candidates

    def _prospective_clan_member_panels(
        self,
        complete: list[Agent],
    ) -> dict[
        tuple[AgentType, str, str | None],
        ProspectiveClanMember,
    ]:
        """Project all direct rows hidden only by collapsed clan ancestry."""
        from ._prospective_clan import prospective_clan_members

        return prospective_clan_members(self, complete)
