"""Agent-row unread projection for notification state."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._notification_utils import (
    active_row_owned_notification_keys,
    loaded_real_agent_roster as loaded_real_agent_roster,
)
from ...models.agent_nodes import (
    normalize_agent_node_identities,
    projection_has_active_completion,
)

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent
    from ...models.agent import AgentType


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
        *,
        status_changed: set[tuple[AgentType, str, str | None]]
        | tuple[tuple[AgentType, str, str | None], ...] = (),
    ) -> bool:
        """Repaint changed real rows and any visible clan ancestors.

        Returns ``True`` when selective patches were sufficient (or no Agents
        rows were active), and ``False`` after falling back to a list rebuild.
        """
        after: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_unread_completed_agent_ids", set()
        )
        changed = before ^ after
        status_changed_set = set(status_changed or ())
        if not changed and not status_changed_set:
            return True
        if getattr(self, "current_tab", None) != "agents":
            return True

        combined = set(changed) | status_changed_set
        roster = loaded_real_agent_roster(self)
        from ._roster_generation import cached_agent_node_projection_index

        node_index = cached_agent_node_projection_index(self, roster)
        roster_by_identity = {agent.identity: agent for agent in roster}
        changed_members = [
            roster_by_identity[identity]
            for identity in combined
            if identity in roster_by_identity
        ]
        changed_node_identities = {
            projection.identity
            for identity in combined
            if (projection := node_index.owner_for_identity(identity)) is not None
        }
        affected_clans = {
            clan_key
            for member in changed_members
            if (clan_key := _member_clan_key(member)) is not None
        }

        patch_agents: list[Agent] = []
        patch_keys: set[object] = set()
        for agent in getattr(self, "_agents", ()):
            should_patch = (
                agent.identity in combined or agent.identity in changed_node_identities
            )
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
        from ._pending_ack_fence import snapshot_read_seq

        snapshot = getattr(self, "_notification_snapshot_cache", None)
        if snapshot is None:
            return
        before = set(getattr(self, "_unread_completed_agent_ids", set()))
        self._reconcile_unread_from_completion_notifications(
            snapshot.notifications,
            snapshot_seq=snapshot_read_seq(snapshot),
        )
        self._patch_unread_completed_agent_changes(before)

    def _reconcile_unread_from_completion_notifications(
        self: Any,
        notifications: list[Notification],
        *,
        snapshot_seq: int | None = None,
    ) -> None:
        """Project active completion notifications onto agent-row unread state.

        For each loaded display-eligible terminal agent:

        - If a matching active (not-dismissed) completion notification exists,
          mark the row unread.
        - If no matching notification exists, clear the row's unread marker
          unless it was manually marked unread via ``U``.

        Identities held in the pending-ack overlay stay read until a
        post-write snapshot retires them; *snapshot_seq* is the applying
        snapshot's read-start sequence (``None`` when unknown).
        """
        from sase.ace.tui.util.trace import tui_trace

        with tui_trace(
            "unread.reconcile",
            notifications=len(notifications),
        ) as _trace_extra:
            result = self._apply_reconciled_unread_from_completion_notifications(
                notifications,
                snapshot_seq=snapshot_seq,
            )
            _trace_extra.update(result)

    def _apply_reconciled_unread_from_completion_notifications(
        self: Any,
        notifications: list[Notification],
        *,
        snapshot_seq: int | None = None,
    ) -> dict[str, object]:
        """Apply the unread projection; return trace counters for the span."""
        from ._core import is_unread_completed_status
        from ._pending_ack_fence import (
            pending_ack_identities,
            retire_pending_ack_entries,
        )

        # Retire first: an entry survives only while no applied read began
        # after its write landed, so a genuinely new completion for a
        # retired identity resurfaces here (at most one poll later).
        if snapshot_seq is not None:
            retire_pending_ack_entries(self, snapshot_seq)
        pending_ids = pending_ack_identities(self)

        active_keys = active_row_owned_notification_keys(notifications)

        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None:
            unread_ids = set()
            self._unread_completed_agent_ids = unread_ids  # type: ignore[attr-defined]
        manual_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_manual_unread_agent_ids", set()
        )
        before = set(unread_ids)
        roster = loaded_real_agent_roster(self)
        from ._roster_generation import cached_agent_node_projection_index

        node_index = cached_agent_node_projection_index(self, roster)
        prior_unread_ids = set(unread_ids)
        prior_manual_ids = set(manual_ids)
        unread_node_ids = normalize_agent_node_identities(
            prior_unread_ids,
            node_index,
        )
        manual_ids.clear()
        manual_ids.update(
            normalize_agent_node_identities(
                prior_manual_ids,
                node_index,
            )
        )
        next_unread: set[tuple[AgentType, str, str | None]] = set()

        for projection in node_index.projections:
            agent = projection.node
            if not is_unread_completed_status(agent.status):
                continue
            if agent.identity in manual_ids:
                if agent.identity in unread_node_ids:
                    next_unread.add(agent.identity)
                continue
            has_notification = projection_has_active_completion(
                projection,
                active_keys,
            )
            if has_notification:
                next_unread.add(agent.identity)
        # In-flight acks stay read: the applying snapshot predates their
        # write (or its sequence is unknown), so re-confirming it must not
        # resurrect the row.
        next_unread.difference_update(pending_ids)
        unread_ids.clear()
        unread_ids.update(next_unread)
        # Only genuinely new unread invalidates the bulk-read undo: pending
        # identities can never appear above (they were just filtered), so a
        # reconcile that only re-confirms them keeps undo armed while a
        # genuinely new identity still invalidates it.
        genuinely_new = (unread_ids - before) - pending_ids
        if genuinely_new:
            invalidate_bulk_undo = getattr(self, "_invalidate_bulk_read_undo", None)
            if callable(invalidate_bulk_undo):
                invalidate_bulk_undo()
        if unread_ids != before and hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]
        return {
            "loaded_agents": len(roster),
            "unread": len(next_unread),
            "changed": len(unread_ids ^ before),
            "pending": len(pending_ids),
        }
