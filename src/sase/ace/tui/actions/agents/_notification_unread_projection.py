"""Agent-row unread projection for notification state."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from ._notification_utils import active_completion_agent_keys

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent
    from ...models.agent import AgentType


def loaded_real_agent_roster(owner: Any) -> tuple[Agent, ...]:
    """Return the complete loaded display-eligible roster without clan rows."""
    roster: Iterable[Agent] = (
        getattr(owner, "_agents_with_children", None)
        or getattr(owner, "_agents", ())
        or ()
    )
    return tuple(agent for agent in roster if not agent.is_clan_container)


def _member_clan_key(agent: Agent) -> tuple[str, str | None] | None:
    if not agent.agent_clan:
        return None
    return (agent.agent_clan, agent.agent_clan_generation)


class AgentNotificationUnreadMixin:
    """Project active completion notifications onto agent rows."""

    _agent_info_metrics_cache: tuple[Any, ...] | None

    def _patch_unread_completed_agent_changes(
        self: Any,
        before: set[tuple[AgentType, str, str | None]],
    ) -> bool:
        """Repaint changed real rows and any visible clan ancestors.

        Returns ``True`` when selective patches were sufficient (or no Agents
        rows were active), and ``False`` after falling back to a list rebuild.
        """
        after: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        changed = before ^ after
        if not changed:
            return True
        if getattr(self, "current_tab", None) != "agents":
            return True

        roster_by_identity = {
            agent.identity: agent for agent in loaded_real_agent_roster(self)
        }
        changed_members = [
            roster_by_identity[identity]
            for identity in changed
            if identity in roster_by_identity
        ]
        affected_clans = {
            clan_key
            for member in changed_members
            if (clan_key := _member_clan_key(member)) is not None
        }

        patch_agents: list[Agent] = []
        patch_keys: set[object] = set()
        for agent in getattr(self, "_agents", ()):
            should_patch = agent.identity in changed
            if agent.is_clan_container:
                should_patch = (
                    agent.agent_clan,
                    agent.agent_clan_generation,
                ) in affected_clans
                patch_key: object = (
                    "clan",
                    agent.agent_clan,
                    agent.agent_clan_generation,
                )
            else:
                patch_key = ("agent", agent.identity)
            if not should_patch or patch_key in patch_keys:
                continue
            patch_keys.add(patch_key)
            patch_agents.append(agent)

        needs_rebuild = False
        try_patch = getattr(self, "_try_patch_agent_row", None)
        for agent in patch_agents:
            if not callable(try_patch) or not try_patch(agent):
                needs_rebuild = True
                break
        if needs_rebuild:
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                refresh(list_changed=True, defer_detail=True)
                return False

        refresh_titles = getattr(self, "_refresh_agent_panel_titles", None)
        if callable(getattr(self, "query_one", None)) and callable(refresh_titles):
            refresh_titles()
        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(getattr(self, "query_one", None)) and callable(update_info):
            update_info()
        refresh_summary = getattr(self, "_refresh_tribe_summary_only", None)
        if callable(refresh_summary):
            refresh_summary()

        get_selected = getattr(self, "_get_selected_agent", None)
        selected = get_selected() if callable(get_selected) else None
        if (
            selected is not None
            and selected.is_clan_container
            and (
                selected.agent_clan,
                selected.agent_clan_generation,
            )
            in affected_clans
        ):
            refresh_detail = getattr(self, "_apply_agent_detail_immediate", None)
            if callable(getattr(self, "query_one", None)) and callable(refresh_detail):
                refresh_detail()
        return True

    def _reconcile_unread_from_cached_notifications(self: Any) -> None:
        """Apply cached completion notifications to loaded real-agent unread state."""
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

        For each loaded display-eligible terminal agent:

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
        roster = loaded_real_agent_roster(self)
        loaded_ids = {agent.identity for agent in roster}
        unread_ids.intersection_update(loaded_ids)
        manual_ids.intersection_update(loaded_ids)

        for agent in roster:
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
