"""Unread completed-agent helpers for the ace TUI app."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from ...models.agent_status import (
    is_stopped_agent_status,
    is_unread_completed_status,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


def _stopped_agent_jump_time(agent: Agent) -> datetime | None:
    """Return the best timestamp for ordering stopped-agent jumps."""
    if agent.status == "PLAN" and agent.plan_times:
        return max(agent.plan_times)
    if agent.status == "QUESTION" and agent.questions_times:
        return max(agent.questions_times)
    return agent.stop_time or agent.start_time


@dataclass(frozen=True, slots=True)
class _TimedAgentJumpCandidate:
    """Stable jump target, optionally hidden by one collapsed clan fold."""

    identity: tuple[AgentType, str, str | None]
    panel_key: str | None
    jump_time: datetime | None
    visible_idx: int | None
    clan_fold_key: str | None = None


class AgentUnreadMixin:
    """Mixin providing unread completed-agent state and navigation."""

    _agents: list[Agent]
    current_idx: int
    current_attempt_number: int | None
    _current_group_key: tuple[str, ...] | None
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]
    _agent_info_metrics_cache: tuple[Any, ...] | None
    _unread_jump_candidates_cache: tuple[Any, Any] | None

    def _repaint_changed_unread_rows(
        self,
        before: set[tuple[AgentType, str, str | None]],
    ) -> bool:
        """Use ancestor-aware repainting with a narrow compatibility fallback."""
        patch_changes = getattr(self, "_patch_unread_completed_agent_changes", None)
        if callable(patch_changes):
            return bool(patch_changes(before))

        after: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        changed = before ^ after
        for agent in self._agents:
            if agent.identity not in changed:
                continue
            if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
                self._refresh_agents_display(  # type: ignore[attr-defined]
                    list_changed=True,
                    defer_detail=True,
                )
                return False
        return True

    def _has_unread_completed_agent(self) -> bool:
        """Return True when an unread terminal row is currently jumpable."""
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        if not unread_ids:
            return False
        return bool(self._unread_timed_jump_candidates())

    def _has_stopped_agent(self) -> bool:
        """Return True when a stopped agent row is currently loaded."""
        return any(is_stopped_agent_status(agent.status) for agent in self._agents)

    def _mark_all_unread_done_agents_read(self) -> int:
        """Acknowledge all currently loaded unread terminal agent rows."""
        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if not unread_ids:
            return 0

        before_unread = set(unread_ids)
        roster = getattr(self, "_agents_with_children", None) or self._agents
        target_agents = [
            agent
            for agent in roster
            if not agent.is_clan_container
            and agent.identity in unread_ids
            and is_unread_completed_status(agent.status)
        ]
        if not target_agents:
            return 0

        target_identities = {agent.identity for agent in target_agents}
        unread_ids.difference_update(target_identities)
        self._manual_unread_ids().difference_update(target_identities)
        if hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        agent_keys = [
            {"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}
            for agent in target_agents
        ]

        from sase.notifications import (
            dismiss_agent_completion_notifications_matching_agents,
        )

        dismissed_count = dismiss_agent_completion_notifications_matching_agents(
            agent_keys
        )
        self._remove_agent_completion_notifications_from_cache(target_agents)
        if dismissed_count:
            refresh_count = getattr(self, "_refresh_notification_count", None)
            if callable(refresh_count):
                refresh_count()

        self._repaint_changed_unread_rows(before_unread)
        return len(target_agents)

    def _jump_to_next_unread_done_agent(self) -> bool:
        """Reveal and select the next unread completed agent, then acknowledge it."""
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        if not unread_ids:
            return False

        def acknowledge_target(
            agent: Agent,
            needs_full_refresh: bool,
            panel_expanded: bool,
        ) -> None:
            if panel_expanded:
                self._clear_agent_unread_and_dismiss_notification(agent)
                self._refresh_agents_display(  # type: ignore[attr-defined]
                    list_changed=True, defer_detail=True
                )
            elif needs_full_refresh:
                before_unread = set(getattr(self, "_unread_completed_agent_ids", set()))
                changed = self._clear_agent_unread_and_dismiss_notification(agent)
                if changed and not self._repaint_changed_unread_rows(before_unread):
                    return
                self._refresh_agents_display(  # type: ignore[attr-defined]
                    list_changed=False, defer_detail=True
                )
            else:
                self._acknowledge_agent_unread(agent)

        def predicate(agent: Agent) -> bool:
            return agent.identity in unread_ids and is_unread_completed_status(
                agent.status
            )

        return self._jump_to_next_matching_agent_by_time(
            predicate=predicate,
            after_select=acknowledge_target,
            include_collapsed_clan_members=True,
            candidates=self._unread_timed_jump_candidates(),
        )

    def _jump_to_next_stopped_agent(self) -> bool:
        """Move focus to the next visible stopped agent without acknowledging it."""
        return self._jump_to_next_matching_agent_by_time(
            predicate=lambda agent: is_stopped_agent_status(agent.status),
            after_select=None,
            time_for_agent=_stopped_agent_jump_time,
        )

    def _jump_to_next_matching_agent_by_time(
        self,
        *,
        predicate: Callable[[Agent], bool],
        after_select: Callable[[Agent, bool, bool], None] | None,
        time_for_agent: Callable[[Agent], datetime | None] | None = None,
        include_collapsed_clan_members: bool = False,
        candidates: list[_TimedAgentJumpCandidate] | None = None,
    ) -> bool:
        """Move focus to the next jumpable agent matching *predicate* by recency."""
        if candidates is None:
            candidates = self._timed_agent_jump_candidates(
                predicate=predicate,
                time_for_agent=time_for_agent,
                include_collapsed_clan_members=include_collapsed_clan_members,
            )
        if not candidates:
            return False

        target_pos = 0
        panel_group = getattr(self, "_panel_group", None)
        visible_panel_indices = self._visible_agent_panel_indices(  # type: ignore[attr-defined]
            include_collapsed_panels=True
        )
        focused_panel_is_collapsed = (
            panel_group is not None
            and panel_group.focused_key in getattr(self, "_collapsed_panel_keys", set())
        )
        current_panel_idx = visible_panel_indices.get(self.current_idx)
        current_is_visible_agent = (
            getattr(self, "_current_group_key", None) is None
            and self.current_idx in visible_panel_indices
            and not focused_panel_is_collapsed
            and (
                panel_group is None
                or current_panel_idx == getattr(panel_group, "focused_idx", None)
            )
        )
        if current_is_visible_agent:
            current_identity = self._agents[self.current_idx].identity
            for candidate_pos, candidate in enumerate(candidates):
                if candidate.identity == current_identity:
                    target_pos = (candidate_pos + 1) % len(candidates)
                    break

        target = candidates[target_pos]
        if target.clan_fold_key is not None:
            return self._reveal_and_select_timed_jump_candidate(
                target,
                predicate=predicate,
                after_select=after_select,
            )

        target_idx = target.visible_idx
        if target_idx is None or not (0 <= target_idx < len(self._agents)):
            return False
        target_panel_key = target.panel_key
        old_idx = self.current_idx
        old_panel_key = panel_group.focused_key if panel_group is not None else None
        old_group_key = self._current_group_key
        panel_was_collapsed = panel_group is not None and target_panel_key in getattr(
            self, "_collapsed_panel_keys", set()
        )
        focus_will_change = (
            old_idx != target_idx
            or old_group_key is not None
            or target_panel_key != old_panel_key
            or panel_was_collapsed
        )
        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if focus_will_change and callable(save_jump_anchor):
            save_jump_anchor()

        panel_expanded = False
        if panel_was_collapsed:
            expand_panel = getattr(self, "_expand_agent_panel", None)
            if callable(expand_panel):
                panel_expanded = bool(expand_panel(target_panel_key))

        target_agent = self._agents[target_idx]
        panel_changed = target_panel_key != old_panel_key
        if panel_group is not None:
            try:
                target_panel_idx = panel_group.panel_keys.index(target_panel_key)
            except ValueError:
                return False
            if target_panel_idx != panel_group.focused_idx:
                panel_group.focused_idx = target_panel_idx
        self._current_group_key = None
        self.current_idx = target_idx
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]

        needs_full_refresh = panel_changed or (
            old_idx == target_idx and old_group_key is not None
        )
        if after_select is not None:
            after_select(target_agent, needs_full_refresh, panel_expanded)
        elif panel_expanded:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )
        elif needs_full_refresh:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=False, defer_detail=True
            )
        return True

    def _unread_timed_jump_candidates(self) -> list[_TimedAgentJumpCandidate]:
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
    ) -> list[_TimedAgentJumpCandidate]:
        """Discover rendered targets plus revealable direct clan members."""
        if not self._agents and not getattr(self, "_agents_with_children", None):
            return []

        visible_panel_indices = self._visible_agent_panel_indices(  # type: ignore[attr-defined]
            include_collapsed_panels=True
        )
        panel_group = getattr(self, "_panel_group", None)
        candidates: list[_TimedAgentJumpCandidate] = []
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
                _TimedAgentJumpCandidate(
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
    ) -> list[_TimedAgentJumpCandidate]:
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

        candidates: list[_TimedAgentJumpCandidate] = []
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
                    _TimedAgentJumpCandidate(
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

    def _reveal_and_select_timed_jump_candidate(
        self,
        target: _TimedAgentJumpCandidate,
        *,
        predicate: Callable[[Agent], bool],
        after_select: Callable[[Agent, bool, bool], None] | None,
    ) -> bool:
        """Expand one target clan, refilter, resolve by identity, and select."""
        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if callable(save_jump_anchor):
            save_jump_anchor()

        fold_manager = getattr(self, "_fold_manager", None)
        if fold_manager is None or target.clan_fold_key is None:
            return False
        if not fold_manager.expand(target.clan_fold_key):
            return False

        # Expand an already-known collapsed tag panel before the structural
        # refilter so both fold changes land in one rebuilt projection.
        expand_panel = getattr(self, "_expand_agent_panel", None)
        if callable(expand_panel):
            expand_panel(target.panel_key)

        invalidate = getattr(self, "_invalidate_agent_panel_cache", None)
        if callable(invalidate):
            invalidate()
        refilter = getattr(self, "_refilter_agents", None)
        if not callable(refilter):
            return False
        try:
            refilter(refresh_content_index=False)
        except TypeError:
            refilter()

        target_idx = next(
            (
                idx
                for idx, agent in enumerate(self._agents)
                if agent.identity == target.identity
            ),
            None,
        )
        if target_idx is None:
            return False
        target_agent = self._agents[target_idx]
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        if target_agent.identity not in unread_ids or not predicate(target_agent):
            return False

        visible = self._visible_agent_panel_indices(  # type: ignore[attr-defined]
            include_collapsed_panels=True
        )
        if target_idx not in visible:
            return False

        panel_group = getattr(self, "_panel_group", None)
        target_panel_idx = visible[target_idx]
        target_panel_key = None
        if panel_group is not None:
            if target_panel_idx is None or not (
                0 <= target_panel_idx < len(panel_group.panel_keys)
            ):
                return False
            target_panel_key = panel_group.panel_keys[target_panel_idx]

        panel_expanded_after_refilter = False
        if (
            panel_group is not None
            and target_panel_key in getattr(self, "_collapsed_panel_keys", set())
            and callable(expand_panel)
        ):
            panel_expanded_after_refilter = bool(expand_panel(target_panel_key))

        if panel_group is not None and target_panel_idx != panel_group.focused_idx:
            panel_group.focused_idx = target_panel_idx
        self._current_group_key = None
        self.current_idx = target_idx
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]

        if after_select is not None:
            after_select(target_agent, True, panel_expanded_after_refilter)
        elif panel_expanded_after_refilter:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True,
                defer_detail=True,
            )
        else:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=False,
                defer_detail=True,
            )
        return True

    def _manual_unread_ids(self) -> set[tuple[AgentType, str, str | None]]:
        """Return the session-local manual unread guard set."""
        manual_ids = getattr(self, "_manual_unread_agent_ids", None)
        if manual_ids is None:
            manual_ids = set()
            self._manual_unread_agent_ids = manual_ids
        return manual_ids

    def _arm_manual_unread_after_departure(self, agent: Agent | None) -> None:
        """Let a manually unread row clear normally the next time it is selected."""
        if agent is None:
            return
        self._manual_unread_ids().discard(agent.identity)

    def _remove_agent_completion_notifications_from_cache(
        self,
        agents: list[Agent],
    ) -> int:
        """Drop acknowledged completion notifications from the cached snapshot."""
        snapshot = getattr(self, "_notification_snapshot_cache", None)
        notifications = getattr(snapshot, "notifications", None)
        if snapshot is None or notifications is None or not agents:
            return 0

        from dataclasses import is_dataclass, replace

        from ._notification_utils import agent_completion_notification_matches_agent

        agent_keys = [(agent.cl_name, agent.raw_suffix) for agent in agents]
        filtered = []
        removed_ids: set[str] = set()
        for notification in notifications:
            if any(
                agent_completion_notification_matches_agent(
                    notification,
                    cl_name=cl_name,
                    raw_suffix=raw_suffix,
                )
                for cl_name, raw_suffix in agent_keys
            ):
                notification_id = getattr(notification, "id", None)
                if isinstance(notification_id, str):
                    removed_ids.add(notification_id)
                continue
            filtered.append(notification)
        if len(filtered) == len(notifications):
            return 0

        if isinstance(notifications, list):
            removed_count = len(notifications) - len(filtered)
            notifications[:] = filtered
            updated_snapshot = snapshot
        elif is_dataclass(snapshot):
            removed_count = len(notifications) - len(filtered)
            updated_snapshot = replace(cast(Any, snapshot), notifications=filtered)
        else:
            try:
                removed_count = len(notifications) - len(filtered)
                snapshot.notifications = filtered
            except Exception:
                return 0
            updated_snapshot = snapshot

        set_cache = getattr(self, "_set_notification_snapshot_cache", None)
        if callable(set_cache):
            set_cache(updated_snapshot)
        else:
            self._notification_snapshot_cache = updated_snapshot  # type: ignore[attr-defined]

        last_unread_ids = getattr(self, "_last_unread_ids", None)
        if isinstance(last_unread_ids, set):
            last_unread_ids.difference_update(removed_ids)
        return removed_count

    def _dismiss_agent_completion_notifications_for_dismissed_agents(
        self,
        agents: Iterable[Agent],
    ) -> int:
        """Clear unread state and active completion notifications for dismisses.

        Unlike read-side acknowledgment, explicit dismissal removes any manual
        unread guard because the row is leaving the Agents tab.
        """
        dismissed_agents = list(agents)
        if not dismissed_agents:
            return 0

        identities = {agent.identity for agent in dismissed_agents}
        before_unread = set(getattr(self, "_unread_completed_agent_ids", set()))
        changed_unread_state = False

        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if isinstance(unread_ids, set):
            before = set(unread_ids)
            unread_ids.difference_update(identities)
            changed_unread_state = changed_unread_state or unread_ids != before

        manual_ids = getattr(self, "_manual_unread_agent_ids", None)
        if isinstance(manual_ids, set):
            before = set(manual_ids)
            manual_ids.difference_update(identities)
            changed_unread_state = changed_unread_state or manual_ids != before

        if changed_unread_state and hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        from sase.notifications import (
            dismiss_agent_completion_notifications_matching_agents,
        )

        dismissed_count = dismiss_agent_completion_notifications_matching_agents(
            [
                {"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}
                for agent in dismissed_agents
            ]
        )
        removed_count = self._remove_agent_completion_notifications_from_cache(
            dismissed_agents
        )
        if dismissed_count or removed_count or changed_unread_state:
            refresh_count = getattr(self, "_refresh_notification_count", None)
            if callable(refresh_count):
                refresh_count()
        if changed_unread_state:
            self._repaint_changed_unread_rows(before_unread)
        return dismissed_count

    def _clear_agent_unread_and_dismiss_notification(self, agent: Agent) -> bool:
        """Clear unread state for *agent* and dismiss its matching notification.

        Returns True only when the agent moved from unread to read. When the
        agent is in a terminal status, any active completion notification
        targeting the same ``(cl_name, raw_suffix)`` is dismissed and the
        notification indicator is refreshed so the one-to-one row/notification
        contract holds.
        """
        if agent.is_clan_container or agent.identity in self._manual_unread_ids():
            return False

        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None or agent.identity not in unread_ids:
            return False

        unread_ids.discard(agent.identity)
        if hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        if not is_unread_completed_status(agent.status):
            return True

        from sase.notifications import (
            dismiss_agent_completion_notifications_matching_agents,
        )

        dismissed_count = dismiss_agent_completion_notifications_matching_agents(
            [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}]
        )
        self._remove_agent_completion_notifications_from_cache([agent])
        if dismissed_count:
            refresh_count = getattr(self, "_refresh_notification_count", None)
            if callable(refresh_count):
                refresh_count()
        return True

    def _acknowledge_agent_unread(self, agent: Agent) -> bool:
        """Clear unread for *agent* unless it is manually guarded.

        Returns True when the visible row was patched or refreshed.
        """
        if agent.is_clan_container:
            return False
        before_unread = set(getattr(self, "_unread_completed_agent_ids", set()))
        if not self._clear_agent_unread_and_dismiss_notification(agent):
            return False

        self._repaint_changed_unread_rows(before_unread)
        return True

    def _toggle_agent_unread(self) -> None:
        """Toggle the selected Agents-tab row's manual unread marker."""
        if getattr(self, "_current_group_key", None) is not None:
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None or agent.is_clan_container:
            return

        before_unread = set(getattr(self, "_unread_completed_agent_ids", set()))
        identity = agent.identity
        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None:
            unread_ids = set()
            self._unread_completed_agent_ids = unread_ids  # type: ignore[attr-defined]
        manual_ids = self._manual_unread_ids()

        if identity in manual_ids:
            manual_ids.discard(identity)
            self._clear_agent_unread_and_dismiss_notification(agent)
        else:
            manual_ids.add(identity)
            unread_ids.add(identity)
            if hasattr(self, "_agent_info_metrics_cache"):
                self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        self._repaint_changed_unread_rows(before_unread)
