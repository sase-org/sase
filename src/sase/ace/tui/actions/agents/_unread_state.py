"""Unread agent state and notification acknowledgment helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from ...models.agent_nodes import (
    AgentCompletionKey,
    agent_node_completion_keys,
    agent_node_projection_index,
    is_agents_tab_agent_node,
)
from ...models.agent_status import is_unread_completed_status

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


class BulkUnreadToggleOutcome(Enum):
    """Outcomes for the Agents-tab bulk unread/read toggle."""

    MARKED_READ = "marked_read"
    RESTORED_UNREAD = "restored_unread"
    NOOP = "noop"


@dataclass(frozen=True)
class _BulkUnreadToggleResult:
    """Result of the session-local bulk unread/read toggle."""

    outcome: BulkUnreadToggleOutcome
    count: int = 0


class AgentUnreadStateMixin:
    """Mixin providing unread state mutation and notification cleanup."""

    _agents: list[Agent]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]
    _pending_bulk_read_agent_ids: set[tuple[AgentType, str, str | None]] | None
    _agent_info_metrics_cache: tuple[Any, ...] | None

    def _notification_keys_for_agents(
        self,
        agents: Iterable[Agent],
    ) -> list[AgentCompletionKey]:
        """Return unique completion-notification keys for agent nodes."""
        requested_agents = tuple(agents)
        loaded_source = cast(
            "Iterable[Agent]",
            getattr(self, "_agents_with_children", None)
            or getattr(self, "_agents", ()),
        )
        loaded_agents = tuple(loaded_source)
        roster = [*requested_agents, *loaded_agents]
        node_index = agent_node_projection_index(roster)
        keys: list[AgentCompletionKey] = []
        seen: set[AgentCompletionKey] = set()
        for agent in requested_agents:
            projection = node_index.owner_for_identity(agent.identity)
            if projection is not None and projection.identity == agent.identity:
                node_keys = projection.completion_keys
            elif is_agents_tab_agent_node(agent):
                node_keys = agent_node_completion_keys(agent)
            else:
                node_keys = ((agent.cl_name, agent.raw_suffix),)
            for key in node_keys:
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
        return keys

    def _notification_key_dicts_for_agents(
        self,
        agents: Iterable[Agent],
    ) -> list[dict[str, str | None]]:
        """Return notification API key dicts for agent nodes."""
        return [
            {"cl_name": cl_name, "raw_suffix": raw_suffix}
            for cl_name, raw_suffix in self._notification_keys_for_agents(agents)
        ]

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

    def _has_bulk_read_undo_available(self) -> bool:
        """Return True when a session-local bulk-read undo is armed."""
        return bool(getattr(self, "_pending_bulk_read_agent_ids", None))

    def _invalidate_bulk_read_undo(self) -> None:
        """Clear any pending bulk-read undo snapshot."""
        if getattr(self, "_pending_bulk_read_agent_ids", None) is not None:
            self._pending_bulk_read_agent_ids = None

    def _toggle_all_unread_done_agents_read(self) -> _BulkUnreadToggleResult:
        """Mark the current terminal unread batch read, or restore the last batch."""
        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        roster = getattr(self, "_agents_with_children", None) or self._agents
        if unread_ids:
            target_agents = [
                agent
                for agent in roster
                if is_agents_tab_agent_node(agent)
                and agent.identity in unread_ids
                and is_unread_completed_status(agent.status)
            ]
            if target_agents:
                return self._mark_current_unread_done_agents_read(target_agents)

        pending_ids = getattr(self, "_pending_bulk_read_agent_ids", None)
        if pending_ids is not None:
            return self._restore_bulk_read_undo(pending_ids)

        return _BulkUnreadToggleResult(BulkUnreadToggleOutcome.NOOP)

    def _mark_all_unread_done_agents_read(self) -> _BulkUnreadToggleResult:
        """Compatibility wrapper for the configured bulk-read action."""
        return self._toggle_all_unread_done_agents_read()

    def _mark_current_unread_done_agents_read(
        self,
        target_agents: list[Agent],
    ) -> _BulkUnreadToggleResult:
        """Acknowledge a selected batch of currently loaded terminal rows."""
        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None:
            return _BulkUnreadToggleResult(BulkUnreadToggleOutcome.NOOP)

        before_unread = set(unread_ids)
        target_identities = {agent.identity for agent in target_agents}
        self._pending_bulk_read_agent_ids = set(target_identities)
        unread_ids.difference_update(target_identities)
        self._manual_unread_ids().difference_update(target_identities)
        if hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        agent_keys = self._notification_key_dicts_for_agents(target_agents)

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
        return _BulkUnreadToggleResult(
            BulkUnreadToggleOutcome.MARKED_READ,
            len(target_agents),
        )

    def _restore_bulk_read_undo(
        self,
        pending_ids: set[tuple[AgentType, str, str | None]],
    ) -> _BulkUnreadToggleResult:
        """Restore still-loaded terminal identities from a bulk-read snapshot."""
        restore_ids = set(pending_ids)
        self._pending_bulk_read_agent_ids = None
        if not restore_ids:
            return _BulkUnreadToggleResult(BulkUnreadToggleOutcome.NOOP)

        roster = getattr(self, "_agents_with_children", None) or self._agents
        target_agents = [
            agent
            for agent in roster
            if is_agents_tab_agent_node(agent)
            and agent.identity in restore_ids
            and is_unread_completed_status(agent.status)
        ]
        if not target_agents:
            return _BulkUnreadToggleResult(BulkUnreadToggleOutcome.NOOP)

        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None:
            unread_ids = set()
            self._unread_completed_agent_ids = unread_ids  # type: ignore[attr-defined]
        before_unread = set(unread_ids)
        restored_identities = {agent.identity for agent in target_agents}
        unread_ids.update(restored_identities)
        self._manual_unread_ids().update(restored_identities)
        if hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        self._repaint_changed_unread_rows(before_unread)
        return _BulkUnreadToggleResult(
            BulkUnreadToggleOutcome.RESTORED_UNREAD,
            len(target_agents),
        )

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

        agent_keys = self._notification_keys_for_agents(agents)
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

        roster = [
            *dismissed_agents,
            *(getattr(self, "_agents_with_children", None) or self._agents),
        ]
        node_index = agent_node_projection_index(roster)
        identities = {agent.identity for agent in dismissed_agents}
        identities.update(
            projection.identity
            for agent in dismissed_agents
            if (projection := node_index.owner_for_identity(agent.identity)) is not None
        )
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
            self._notification_key_dicts_for_agents(dismissed_agents)
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
        if (
            not is_agents_tab_agent_node(agent)
            or agent.identity in self._manual_unread_ids()
        ):
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
            self._notification_key_dicts_for_agents([agent])
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
        if not is_agents_tab_agent_node(agent):
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
        if agent is None or not is_agents_tab_agent_node(agent):
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
            self._invalidate_bulk_read_undo()
            manual_ids.add(identity)
            unread_ids.add(identity)
            if hasattr(self, "_agent_info_metrics_cache"):
                self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        self._repaint_changed_unread_rows(before_unread)
