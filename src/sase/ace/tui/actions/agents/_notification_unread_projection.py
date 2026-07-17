"""Agent-row unread projection for notification state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._notification_utils import active_completion_agent_keys

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models.agent import AgentType


class AgentNotificationUnreadMixin:
    """Project active completion notifications onto agent rows."""

    _agent_info_metrics_cache: tuple[Any, ...] | None

    def _patch_unread_completed_agent_changes(
        self: Any,
        before: set[tuple[AgentType, str, str | None]],
    ) -> None:
        """Patch row styling after notification-cache reconciliation."""
        after: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        changed = before ^ after
        if not changed or getattr(self, "current_tab", None) != "agents":
            return
        needs_rebuild = False
        try_patch = getattr(self, "_try_patch_agent_row", None)
        for agent in self._agents:  # type: ignore[attr-defined]
            if agent.identity not in changed:
                continue
            if not callable(try_patch) or not try_patch(agent):
                needs_rebuild = True
        if needs_rebuild:
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                refresh(list_changed=True, defer_detail=True)
                return
        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(getattr(self, "query_one", None)) and callable(update_info):
            update_info()
        refresh_summary = getattr(self, "_refresh_collapsed_panel_summary_only", None)
        if callable(refresh_summary):
            refresh_summary()

    def _reconcile_unread_from_cached_notifications(self: Any) -> None:
        """Apply cached completion notifications to visible agent unread state."""
        snapshot = getattr(self, "_notification_snapshot_cache", None)
        if snapshot is None:
            return
        before = set(getattr(self, "_unread_completed_agent_ids", set()))
        self._reconcile_unread_from_completion_notifications(snapshot.notifications)
        self._patch_unread_completed_agent_changes(before)

    def _reconcile_unread_from_completion_notifications(
        self: Any,
        notifications: list[Notification],
    ) -> None:
        """Project active completion notifications onto agent-row unread state.

        For each visible terminal agent:

        - If a matching active (not-dismissed) completion notification exists,
          mark the row unread.
        - If no matching notification exists, clear the row's unread marker
          unless it was manually marked unread via ``U``.
        """
        from ._core import is_unread_completed_status

        active_keys = active_completion_agent_keys(notifications)

        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None:
            unread_ids = set()
            self._unread_completed_agent_ids = unread_ids  # type: ignore[attr-defined]
        manual_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_manual_unread_agent_ids", set()
        )
        before = set(unread_ids)

        for agent in self._agents:  # type: ignore[attr-defined]
            if not is_unread_completed_status(agent.status):
                continue
            has_notification = (agent.cl_name, agent.raw_suffix) in active_keys or (
                agent.cl_name,
                None,
            ) in active_keys
            if has_notification:
                if agent.identity not in manual_ids:
                    unread_ids.add(agent.identity)
            else:
                # Manual unread guards a row even without a notification.
                if agent.identity not in manual_ids:
                    unread_ids.discard(agent.identity)
        if unread_ids != before and hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]
