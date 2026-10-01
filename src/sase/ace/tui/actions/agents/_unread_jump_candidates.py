"""Candidate discovery for time-ordered agent jumps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.core.agent_tab import AgentTabKey

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
    tab_key: AgentTabKey | None = None


class AgentUnreadJumpCandidatesMixin:
    """Mixin that discovers visible and revealable timed jump targets."""

    _agents: list[Agent]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _unread_jump_candidates_cache: tuple[Any, Any] | None

    def _unread_timed_jump_candidates(self) -> list[TimedAgentJumpCandidate]:
        """Return a cached unread candidate projection for jump reuse.

        Keyed by cheap generations (roster, unread-set, fold, tab,
        committed query) so consecutive ``,j`` presses reuse the list
        without the old O(N) status-tuple plus ``frozenset`` build.
        """
        from ._unread_bulk_scope import is_bulk_ack_unread_target
        from ._unread_set_generation import unread_jump_cache_key

        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        cache_key = unread_jump_cache_key(self)
        cached = getattr(self, "_unread_jump_candidates_cache", None)
        if cached is not None and cached[0] == cache_key:
            return cached[1]

        candidates = self._timed_agent_jump_candidates(
            predicate=lambda agent: is_bulk_ack_unread_target(agent, unread_ids),
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

        candidates.extend(
            self._off_tab_jump_candidates(
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

    def _off_tab_jump_candidates(
        self,
        *,
        predicate: Callable[[Agent], bool],
        time_for_agent: Callable[[Agent], datetime | None] | None,
        seen: set[tuple[AgentType, str, str | None]],
    ) -> list[TimedAgentJumpCandidate]:
        """Return matching rows on agent tabs other than the active one.

        ``,j``/``,J`` jump across tabs, so candidates come from the
        tab-independent ``_agents_query_result`` instead of only the
        active tab's ``_agents``. Without an index there are no off-tab
        rows and this stays empty. Rows already seen as visible or
        collapsed-clan candidates keep their existing entry.
        """
        index = getattr(self, "_agent_tab_index", None)
        if index is None:
            return []
        active = getattr(self, "_active_agent_tab", None)
        query_result = list(getattr(self, "_agents_query_result", None) or ())
        if not query_result:
            return []
        candidates: list[TimedAgentJumpCandidate] = []
        for agent in query_result:
            if agent.identity in seen:
                continue
            if agent.is_clan_container or not predicate(agent):
                continue
            try:
                tab_key = index.key_for(agent)
            except Exception:
                continue
            if tab_key == active:
                continue
            candidates.append(
                TimedAgentJumpCandidate(
                    identity=agent.identity,
                    panel_key=None,
                    jump_time=(
                        time_for_agent(agent)
                        if time_for_agent is not None
                        else agent.stop_time or agent.start_time
                    ),
                    visible_idx=None,
                    tab_key=tab_key,
                )
            )
            seen.add(agent.identity)
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
