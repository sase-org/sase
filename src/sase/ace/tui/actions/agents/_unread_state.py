"""Unread agent state and notification acknowledgment helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
import logging
import time
from typing import TYPE_CHECKING, Any, cast

from ...models.agent_nodes import (
    AgentCompletionKey,
    agent_node_completion_keys,
    is_agents_tab_agent_node,
)
from ...models.agent_status import is_unread_completed_status
from ._unread_set_generation import bump_unread_set_generation

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class _UnreadNotificationDismissal:
    """Notification-store dismissal that follows an optimistic unread ack."""

    agents: tuple[Agent, ...]
    keys: tuple[AgentCompletionKey, ...]
    identities: frozenset[tuple[AgentType, str, str | None]]
    restore_manual_ids: frozenset[tuple[AgentType, str, str | None]]
    prior_pending_bulk_read_ids: frozenset[tuple[AgentType, str, str | None]] | None
    prior_pending_bulk_read_armed_at: float | None = None
    op_id: int = 0


class AgentUnreadStateMixin:
    """Mixin providing unread state mutation and notification cleanup."""

    _agents: list[Agent]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]
    _pending_bulk_read_agent_ids: set[tuple[AgentType, str, str | None]] | None
    _pending_bulk_read_armed_at: float | None
    _agent_info_metrics_cache: tuple[Any, ...] | None

    def _notification_key_dicts_from_keys(
        self,
        keys: Iterable[AgentCompletionKey],
    ) -> list[dict[str, str | None]]:
        """Return notification API key dicts for precomputed completion keys."""
        return [
            {"cl_name": cl_name, "raw_suffix": raw_suffix}
            for cl_name, raw_suffix in keys
        ]

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
        loaded_identities = {agent.identity for agent in loaded_agents}
        if all(agent.identity in loaded_identities for agent in requested_agents):
            # Targets already loaded: index the loaded roster alone so this
            # shares the cached build with the reconcile/finalize passes.
            roster = list(loaded_agents)
        else:
            roster = [*requested_agents, *loaded_agents]
        from ._roster_generation import cached_agent_node_projection_index

        node_index = cached_agent_node_projection_index(self, roster)
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
        return self._notification_key_dicts_from_keys(
            self._notification_keys_for_agents(agents)
        )

    def _repaint_changed_unread_rows(
        self,
        before: set[tuple[AgentType, str, str | None]],
    ) -> bool:
        """Paint an unread diff through the one batched chrome helper.

        Always ``True``: the helper skips collapsed panels, rebuilds at
        most the failing visible row's panel, and never falls back to a
        full display rebuild. This calls the helper directly (rather than
        via ``_patch_unread_completed_agent_changes``) so every mixin
        composition paints through the same path.
        """
        from ._unread_chrome import apply_unread_chrome

        return apply_unread_chrome(self, before)

    def _has_bulk_read_undo_available(self) -> bool:
        """Return True when a session-local bulk-read undo is armed.

        The undo is explicit and time-bound: outside the
        ``BULK_READ_UNDO_WINDOW_SECONDS`` window after the mark it reads
        as unavailable (the stale snapshot expires on the next toggle).
        """
        if not getattr(self, "_pending_bulk_read_agent_ids", None):
            return False
        from ._unread_bulk_scope import bulk_read_undo_window_open

        return bulk_read_undo_window_open(
            getattr(self, "_pending_bulk_read_armed_at", None)
        )

    def _invalidate_bulk_read_undo(self) -> None:
        """Clear any pending bulk-read undo snapshot."""
        if getattr(self, "_pending_bulk_read_agent_ids", None) is not None:
            self._pending_bulk_read_agent_ids = None
        if getattr(self, "_pending_bulk_read_armed_at", None) is not None:
            self._pending_bulk_read_armed_at = None

    def _bulk_read_undo_window_open(self) -> bool:
        """Return True when the armed bulk-read undo is still in its window."""
        if not getattr(self, "_pending_bulk_read_agent_ids", None):
            return False
        from ._unread_bulk_scope import bulk_read_undo_window_open

        return bulk_read_undo_window_open(
            getattr(self, "_pending_bulk_read_armed_at", None)
        )

    def _expire_bulk_read_undo(self) -> None:
        """Drop a bulk-read undo snapshot whose window has closed."""
        if not self._bulk_read_undo_window_open():
            self._invalidate_bulk_read_undo()

    def _toggle_all_unread_done_agents_read(self) -> _BulkUnreadToggleResult:
        """Mark every loaded unread batch read, or undo the last mark in-window.

        "All" is every loaded unread terminal agent node across all Agents
        tabs, including collapsed clans and tribes and off-tab query rows
        (see :mod:`._unread_bulk_scope`); collecting targets never expands
        a panel. With nothing unread, ``,u`` restores the same identities
        only inside the undo window; afterwards it is a plain NOOP.
        """
        from ._unread_bulk_scope import bulk_unread_ack_targets

        target_agents = bulk_unread_ack_targets(self)
        if target_agents:
            return self._mark_current_unread_done_agents_read(target_agents)

        if self._bulk_read_undo_window_open():
            pending_ids = getattr(self, "_pending_bulk_read_agent_ids", None)
            if pending_ids is not None:
                return self._restore_bulk_read_undo(pending_ids)

        # A stale undo snapshot expires the instant the window closes so a
        # later mark can never resurrect it.
        self._expire_bulk_read_undo()
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
        before_manual = set(self._manual_unread_ids())
        before_pending = getattr(self, "_pending_bulk_read_agent_ids", None)
        before_pending_armed_at = getattr(self, "_pending_bulk_read_armed_at", None)
        target_identities = {agent.identity for agent in target_agents}
        self._pending_bulk_read_agent_ids = set(target_identities)
        self._pending_bulk_read_armed_at = time.monotonic()
        unread_ids.difference_update(target_identities)
        self._manual_unread_ids().difference_update(target_identities)
        bump_unread_set_generation(self, removed=target_identities)
        if hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        self._schedule_unread_notification_dismissal(
            _UnreadNotificationDismissal(
                agents=tuple(target_agents),
                keys=tuple(self._notification_keys_for_agents(target_agents)),
                identities=frozenset(target_identities),
                restore_manual_ids=frozenset(before_manual & target_identities),
                prior_pending_bulk_read_ids=(
                    frozenset(before_pending) if before_pending is not None else None
                ),
                prior_pending_bulk_read_armed_at=before_pending_armed_at,
            )
        )
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
        self._pending_bulk_read_armed_at = None
        if not restore_ids:
            return _BulkUnreadToggleResult(BulkUnreadToggleOutcome.NOOP)

        from ._pending_ack_fence import release_pending_ack_entries

        # The user overrode the in-flight acks: release their fence entries
        # so the next reconcile projects the restored rows from the store
        # instead of holding them read.
        release_pending_ack_entries(self, restore_ids)

        from ._unread_bulk_scope import (
            bulk_ack_roster_universe,
            is_bulk_ack_unread_target,
        )

        # The mark just removed these identities from the unread set, so
        # probe the shared predicate with them present: restore covers
        # still-loaded terminal rows across all tabs, never expanding panels.
        probe_ids = (
            getattr(self, "_unread_completed_agent_ids", set()) or set()
        ) | restore_ids
        target_agents = [
            agent
            for agent in bulk_ack_roster_universe(self)
            if agent.identity in restore_ids
            and is_bulk_ack_unread_target(agent, probe_ids)
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
        bump_unread_set_generation(self)
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

        from ._notification_utils import agent_row_notification_matches_agent

        agent_keys = self._notification_keys_for_agents(agents)
        filtered = []
        removed_ids: set[str] = set()
        for notification in notifications:
            if any(
                agent_row_notification_matches_agent(
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
        from ._roster_generation import cached_agent_node_projection_index

        node_index = cached_agent_node_projection_index(self, roster)
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
            if unread_ids != before:
                changed_unread_state = True
                bump_unread_set_generation(self, removed=identities)

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

    def _schedule_unread_notification_dismissal(
        self,
        request: _UnreadNotificationDismissal,
    ) -> None:
        """Persist an optimistic read-side notification dismissal off-thread.

        The request joins the coalescing ack queue: one worker drains the
        queue and issues one Rust call per batch. The worker computes the
        cached snapshot's matching ids off-thread so completion never
        reads the store on the UI thread.
        """
        from dataclasses import replace

        from ._pending_ack_fence import register_pending_ack
        from ._unread_ack_writer import enqueue_unread_ack

        # Register before scheduling: every reconcile path treats these
        # identities as read until a post-write snapshot retires them.
        request = replace(
            request,
            op_id=register_pending_ack(self, request.identities),
        )
        try:
            enqueue_unread_ack(self, request)
        except Exception:
            log.exception("Failed to schedule acknowledged-agent notification write")
            self._restore_unread_notification_dismissal(request)

    def _remove_agent_completion_notifications_from_cache_by_ids(
        self,
        ids: set[str],
    ) -> int:
        """Drop cached snapshot notifications by id set (no store I/O)."""
        from ._unread_ack_writer import remove_cached_notifications_by_ids

        return remove_cached_notifications_by_ids(self, ids)

    def _complete_unread_notification_dismissal(
        self,
        request: _UnreadNotificationDismissal,
        *,
        dismissed_count: int,
        error: Exception | None,
        store_bytes: int | None = None,
        matched_ids: set[str] | None = None,
    ) -> None:
        """Reconcile the off-thread notification write outcome on the UI thread.

        Never reads the store: the worker computed *matched_ids* off-thread
        and the completion applies them to the cached snapshot by id set.
        """
        from sase.ace.tui.util.trace import tui_trace

        with tui_trace(
            "unread.ack_complete",
            targets=len(request.identities),
            store_bytes=store_bytes if store_bytes is not None else -1,
        ):
            self._apply_unread_notification_dismissal_outcome(
                request,
                dismissed_count=dismissed_count,
                error=error,
                matched_ids=matched_ids,
            )

    def _apply_unread_notification_dismissal_outcome(
        self,
        request: _UnreadNotificationDismissal,
        *,
        dismissed_count: int,
        error: Exception | None,
        matched_ids: set[str] | None = None,
    ) -> None:
        """Apply the off-thread notification write outcome on the UI thread.

        Read-free: removes the worker-computed *matched_ids* from the cached
        snapshot by id set and schedules only the guarded async resync. The
        optimistic paint already went through the chrome helper; the resync's
        reconcile repaints through it as well.
        """
        from ._pending_ack_fence import mark_pending_ack_write_complete

        if error is not None:
            self._restore_unread_notification_dismissal(request)
            notify = getattr(self, "notify", None)
            if callable(notify):
                notify(
                    "Could not mark agent notification read; restored unread marker",
                    severity="error",
                )
            return

        # The write landed: stamp done_seq so only a read that began
        # after this point retires the pending entries. Recorded per op
        # when its batch lands, so each op in a failed batch still
        # restores only its own still-owned identities.
        mark_pending_ack_write_complete(self, request.op_id, request.identities)
        removed_count = self._remove_agent_completion_notifications_from_cache_by_ids(
            set(matched_ids) if matched_ids else set()
        )
        if dismissed_count or removed_count:
            schedule = getattr(self, "_schedule_notification_snapshot_refresh", None)
            if callable(schedule):
                try:
                    schedule()
                except Exception:
                    log.exception("Failed to schedule post-ack notification resync")

    def _restore_unread_notification_dismissal(
        self,
        request: _UnreadNotificationDismissal,
    ) -> None:
        """Restore optimistic unread state after a store-write failure.

        Only identities this op still owns are restored: a later op on the
        same identity overwrote the pending entry and takes ownership, so an
        earlier failure must not clobber its optimistic state.
        """
        from dataclasses import replace

        from ._pending_ack_fence import (
            owned_pending_ack_identities,
            release_pending_ack_entries,
        )

        owned = owned_pending_ack_identities(self, request.op_id, request.identities)
        release_pending_ack_entries(self, owned)
        if not owned:
            return
        fully_owned = owned == set(request.identities)
        request = replace(
            request,
            identities=frozenset(owned),
            restore_manual_ids=request.restore_manual_ids & owned,
        )
        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None:
            unread_ids = set()
            self._unread_completed_agent_ids = unread_ids  # type: ignore[attr-defined]
        before_unread = set(unread_ids)
        unread_ids.update(request.identities)
        bump_unread_set_generation(self)

        manual_ids = self._manual_unread_ids()
        manual_ids.update(request.restore_manual_ids)

        current_pending = getattr(self, "_pending_bulk_read_agent_ids", None)
        if fully_owned and current_pending == set(request.identities):
            self._pending_bulk_read_agent_ids = (
                set(request.prior_pending_bulk_read_ids)
                if request.prior_pending_bulk_read_ids is not None
                else None
            )  # type: ignore[attr-defined]
            self._pending_bulk_read_armed_at = (
                request.prior_pending_bulk_read_armed_at
                if request.prior_pending_bulk_read_ids is not None
                else None
            )

        if hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]
        self._repaint_changed_unread_rows(before_unread)

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
        bump_unread_set_generation(self, removed={agent.identity})
        if hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        if not is_unread_completed_status(agent.status):
            return True

        self._schedule_unread_notification_dismissal(
            _UnreadNotificationDismissal(
                agents=(agent,),
                keys=tuple(self._notification_keys_for_agents([agent])),
                identities=frozenset({agent.identity}),
                restore_manual_ids=frozenset(),
                prior_pending_bulk_read_ids=None,
            )
        )
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
            bump_unread_set_generation(self)
            from ._pending_ack_fence import release_pending_ack_entries

            # An explicit manual mark overrides any in-flight ack for this
            # row so a pre-write snapshot cannot clear it again.
            release_pending_ack_entries(self, {identity})
            if hasattr(self, "_agent_info_metrics_cache"):
                self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

        self._repaint_changed_unread_rows(before_unread)
