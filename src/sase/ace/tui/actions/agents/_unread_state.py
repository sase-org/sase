"""Unread agent state and notification acknowledgment helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, cast

from ...models.agent_status import is_unread_completed_status

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class AgentUnreadStateMixin:
    """Mixin providing unread state mutation and notification cleanup."""

    _agents: list[Agent]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]
    _agent_info_metrics_cache: tuple[Any, ...] | None

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
