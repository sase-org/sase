"""Plan notification mute-state synchronization to agent tags."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.notifications import Notification


class AgentNotificationMuteTagMixin:
    """Mirror muted plan-approval notifications into the matching agent row."""

    def _sync_plan_notification_mute_tag(
        self: Any,
        notification: Notification,
        *,
        muted: bool,
    ) -> bool:
        """Sync a PlanApproval notification's muted state to the agent tag.

        The ``mute`` tag is only added when the loaded agent is currently
        untagged and the persistent tag store is still untagged. It is only
        cleared when the persisted or in-memory tag is still ``mute``.

        Returns True when an in-memory loaded row changed.
        """
        if notification.action != "PlanApproval":
            return False

        from ._notification_navigation import find_agent_for_notification

        agent = find_agent_for_notification(self, notification)
        if agent is None:
            return False

        from sase.ace.agent_tags import (
            MUTE_AGENT_TAG,
            clear_agent_tag_if_matches,
            set_agent_tag_if_unset,
        )

        memory_changed = False
        if muted:
            if agent.tag:
                return False
            if set_agent_tag_if_unset(agent.identity, MUTE_AGENT_TAG):
                agent.tag = MUTE_AGENT_TAG
                memory_changed = True
        else:
            clear_agent_tag_if_matches(agent.identity, MUTE_AGENT_TAG)
            if agent.tag == MUTE_AGENT_TAG:
                agent.tag = None
                memory_changed = True

        if memory_changed:
            self._refresh_agents_display_after_notification_tag_change()
        return memory_changed

    def _sync_expired_plan_notification_mute_tags(
        self: Any,
        notifications: list[Notification],
        expired_ids: list[str],
    ) -> None:
        """Clear mute tags for expired snoozed PlanApproval notifications."""
        if not expired_ids:
            return
        expired_id_set = set(expired_ids)
        for notification in notifications:
            if notification.id not in expired_id_set:
                continue
            self._sync_plan_notification_mute_tag(notification, muted=False)

    def _refresh_agents_display_after_notification_tag_change(self: Any) -> None:
        """Refresh tag-derived agent panels from current in-memory rows."""
        invalidate = getattr(self, "_invalidate_agent_panel_cache", None)
        if callable(invalidate):
            invalidate()

        refresh = getattr(self, "_refresh_agents_display", None)
        if callable(refresh):
            refresh(list_changed=True)
