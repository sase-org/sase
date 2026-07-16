"""Unread completed-agent helpers for the ace TUI app."""

from __future__ import annotations

from collections.abc import Callable, Iterable
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


class AgentUnreadMixin:
    """Mixin providing unread completed-agent state and navigation."""

    _agents: list[Agent]
    current_idx: int
    current_attempt_number: int | None
    _current_group_key: tuple[str, ...] | None
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]
    _agent_info_metrics_cache: tuple[Any, ...] | None

    def _has_unread_completed_agent(self) -> bool:
        """Return True when a visible terminal row is still unread."""
        unread_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        if not unread_ids:
            return False
        return any(
            is_unread_completed_status(agent.status) and agent.identity in unread_ids
            for agent in self._agents
        )

    def _has_stopped_agent(self) -> bool:
        """Return True when a stopped agent row is currently loaded."""
        return any(is_stopped_agent_status(agent.status) for agent in self._agents)

    def _mark_all_unread_done_agents_read(self) -> int:
        """Acknowledge all currently loaded unread terminal agent rows."""
        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if not unread_ids:
            return 0

        target_agents = [
            agent
            for agent in self._agents
            if agent.identity in unread_ids and is_unread_completed_status(agent.status)
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

        patched_all = True
        for agent in target_agents:
            if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
                patched_all = False
                break
        if not patched_all:
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True,
            )
        return len(target_agents)

    def _jump_to_next_unread_done_agent(self) -> bool:
        """Move focus to the next visible unread completed agent and acknowledge it."""
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
                changed = self._clear_agent_unread_and_dismiss_notification(agent)
                if changed and not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
                    self._refresh_agents_display(  # type: ignore[attr-defined]
                        list_changed=True, defer_detail=True
                    )
                    return
                self._refresh_agents_display(  # type: ignore[attr-defined]
                    list_changed=False, defer_detail=True
                )
            else:
                self._acknowledge_agent_unread(agent)

        return self._jump_to_next_matching_agent_by_time(
            predicate=lambda agent: (
                agent.identity in unread_ids
                and is_unread_completed_status(agent.status)
            ),
            after_select=acknowledge_target,
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
    ) -> bool:
        """Move focus to the next jumpable agent matching *predicate* by recency."""
        if not self._agents:
            return False

        visible_panel_indices = self._visible_agent_panel_indices(  # type: ignore[attr-defined]
            include_collapsed_panels=True
        )
        if not visible_panel_indices:
            return False

        panel_group = getattr(self, "_panel_group", None)
        candidates: list[tuple[int, str | None, datetime | None]] = []
        for idx, panel_idx in visible_panel_indices.items():
            agent = self._agents[idx]
            if predicate(agent):
                if panel_group is None:
                    panel_key = None
                elif panel_idx is not None and 0 <= panel_idx < len(
                    panel_group.panel_keys
                ):
                    panel_key = panel_group.panel_keys[panel_idx]
                else:
                    continue
                jump_time = (
                    time_for_agent(agent)
                    if time_for_agent is not None
                    else agent.stop_time or agent.start_time
                )
                candidates.append((idx, panel_key, jump_time))

        if not candidates:
            return False

        candidates.sort(
            key=lambda candidate: candidate[2] or datetime.min, reverse=True
        )

        target_pos = 0
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
            for candidate_pos, (idx, _panel_key, _jump_time) in enumerate(candidates):
                if idx == self.current_idx:
                    target_pos = (candidate_pos + 1) % len(candidates)
                    break

        target_idx, target_panel_key, _jump_time = candidates[target_pos]
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
        return dismissed_count

    def _clear_agent_unread_and_dismiss_notification(self, agent: Agent) -> bool:
        """Clear unread state for *agent* and dismiss its matching notification.

        Returns True only when the agent moved from unread to read. When the
        agent is in a terminal status, any active completion notification
        targeting the same ``(cl_name, raw_suffix)`` is dismissed and the
        notification indicator is refreshed so the one-to-one row/notification
        contract holds.
        """
        if agent.identity in self._manual_unread_ids():
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
        if not self._clear_agent_unread_and_dismiss_notification(agent):
            return False

        if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )
        return True

    def _toggle_agent_unread(self) -> None:
        """Toggle the selected Agents-tab row's manual unread marker."""
        if getattr(self, "_current_group_key", None) is not None:
            return

        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            return

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

        if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )
