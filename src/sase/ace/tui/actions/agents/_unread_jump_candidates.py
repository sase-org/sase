"""Candidate discovery for time-ordered agent jumps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ...models.agent_status import is_unread_completed_status

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


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
                agent.identity in unread_ids
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
        """Return direct members hidden only by a collapsed outer clan fold."""
        complete = list(getattr(self, "_agents_with_children", ()) or ())
        fold_manager = getattr(self, "_fold_manager", None)
        if not complete or fold_manager is None:
            return []

        from ...models._agent_tree import agent_fold_key
        from ...models.fold_state import FoldLevel

        members_by_fold: dict[str, list[Agent]] = {}
        for container in complete:
            if not container.is_clan_container:
                continue
            fold_key = agent_fold_key(container)
            if fold_key is None or fold_manager.get(fold_key) != FoldLevel.COLLAPSED:
                continue
            direct_members = [
                member
                for member in container.runtime_children
                if not member.is_clan_container
                and member.tree_parent_key == fold_key
                and member.identity not in seen
            ]
            if direct_members:
                members_by_fold[fold_key] = direct_members

        candidates: list[TimedAgentJumpCandidate] = []
        for fold_key, direct_members in members_by_fold.items():
            visible_by_identity = self._prospective_clan_member_panels(
                complete,
                fold_key,
            )
            for member in direct_members:
                panel_key = visible_by_identity.get(member.identity)
                if member.identity not in visible_by_identity or not predicate(member):
                    continue
                candidates.append(
                    TimedAgentJumpCandidate(
                        identity=member.identity,
                        panel_key=panel_key,
                        jump_time=(
                            time_for_agent(member)
                            if time_for_agent is not None
                            else member.stop_time or member.start_time
                        ),
                        visible_idx=None,
                        clan_fold_key=fold_key,
                    )
                )
                seen.add(member.identity)
        return candidates

    def _prospective_clan_member_panels(
        self,
        complete: list[Agent],
        fold_key: str,
    ) -> dict[tuple[AgentType, str, str | None], str | None]:
        """Project rows that would render after expanding exactly one clan."""
        from sase.core.time import local_now

        from ...models import filter_agents_by_fold_state
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.agent_panels import AgentPanelGroup, agents_for_panel
        from ...models.fold_state import FoldLevel, FoldStateManager
        from ._fold_scope import panel_fold_registry

        source_manager = self._fold_manager  # type: ignore[attr-defined]
        projected_manager = FoldStateManager()
        for key, level in source_manager.snapshot().items():
            if level in {FoldLevel.EXPANDED, FoldLevel.FULLY_EXPANDED}:
                projected_manager.expand(key)
            if level == FoldLevel.FULLY_EXPANDED:
                projected_manager.expand(key)
        projected_manager.expand(fold_key)
        projected, _counts = filter_agents_by_fold_state(
            complete,
            projected_manager,
        )

        raw_query = getattr(self, "_agent_search_query", "") or ""
        if raw_query:
            parse_query = getattr(self, "_get_or_parse_agent_query", None)
            parsed = parse_query() if callable(parse_query) else None
            if parsed is None:
                from ....agent_query import parse_agent_query

                try:
                    parsed = parse_agent_query(raw_query)
                except Exception:
                    return {}
            from ....agent_query import evaluate_agent_query
            from ...models._agent_tree import filter_tree_rows

            content_index = getattr(self, "_agent_content_search_index", None)
            now = local_now()
            projected = filter_tree_rows(
                projected,
                lambda agent: evaluate_agent_query(
                    parsed,
                    agent,
                    now=now,
                    content_cache=content_index,
                ),
            )

        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        merge_tag_panels = bool(getattr(self, "_agent_panels_grouped", False))
        panel_group = AgentPanelGroup.from_agents(
            projected,
            merge_tag_panels=merge_tag_panels,
        )
        rendered: dict[tuple[AgentType, str, str | None], str | None] = {}
        for panel_key in panel_group.panel_keys:
            panel_agents = agents_for_panel(
                projected,
                panel_key,
                merge_tag_panels=merge_tag_panels,
            )
            tree = build_agent_tree(
                panel_agents,
                fold_registry=panel_fold_registry(self, panel_key),
                mode=mode,
            )
            for entry in tree:
                if entry.kind != "agent" or entry.agent_idx is None:
                    continue
                if 0 <= entry.agent_idx < len(panel_agents):
                    rendered[panel_agents[entry.agent_idx].identity] = panel_key
        return rendered
