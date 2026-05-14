"""Notification polling and display methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent
    from ...models.agent import AgentType
    from ._types import PlanFeedbackContext

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


def _active_completion_agent_keys(
    notifications: list[Notification],
) -> set[tuple[str, str | None]]:
    """Return ``(cl_name, raw_suffix)`` keys for active completion notifications.

    A completion notification is identified by ``sender == "user-agent"`` and
    ``action`` in ``{"JumpToAgent", "ViewErrorReport"}`` with ``cl_name``
    present in ``action_data``. ``raw_suffix`` may be absent when the writer
    did not record one — those rows match agents by ``cl_name`` only.

    "Active" means not yet dismissed. Default snapshots already omit
    dismissed rows, but the predicate is enforced here as well so callers
    that pass ``include_dismissed=True`` get the right projection. Silent
    rows still count: per the one-to-one contract, dismissed status is
    what gates the row, not indicator visibility.
    """
    keys: set[tuple[str, str | None]] = set()
    for n in notifications:
        if n.sender != "user-agent":
            continue
        if n.action not in ("JumpToAgent", "ViewErrorReport"):
            continue
        if n.dismissed:
            continue
        cl_name = n.action_data.get("cl_name")
        if not cl_name:
            continue
        raw_suffix = n.action_data.get("raw_suffix") or None
        keys.add((cl_name, raw_suffix))
    return keys


def _unread_notification_buckets(
    notifications: list[Notification],
) -> tuple[
    list[Notification], list[Notification], list[Notification], list[Notification]
]:
    from sase.notifications import is_error, is_priority

    unread_priority: list[Notification] = []
    unread_errors: list[Notification] = []
    unread_rest: list[Notification] = []
    unread_muted: list[Notification] = []
    for n in notifications:
        if n.read or n.silent:
            continue
        if n.muted:
            unread_muted.append(n)
        elif is_error(n):
            unread_errors.append(n)
        elif is_priority(n):
            unread_priority.append(n)
        else:
            unread_rest.append(n)
    return unread_priority, unread_errors, unread_rest, unread_muted


class AgentNotificationMixin:
    """Mixin providing notification polling and display methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    _last_unread_ids: set[str]
    current_idx: int
    current_tab: TabName
    hide_non_run_agents: bool
    _agents: list[Agent]
    _hidden_count: int
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _plan_feedback_context: PlanFeedbackContext | None
    _agent_info_metrics_cache: tuple[Any, ...] | None

    def _set_notification_snapshot_cache(self, snapshot: object) -> None:
        """Store the latest notification snapshot for hot-path readers."""
        self._notification_snapshot_cache = snapshot  # type: ignore[attr-defined]
        self._notification_snapshot_version = (  # type: ignore[attr-defined]
            getattr(self, "_notification_snapshot_version", 0) + 1
        )

    def _read_notification_snapshot_from_provider(
        self,
        *,
        include_dismissed: bool = False,
        expire_due_snoozes: bool = False,
    ) -> Any:
        """Return the notification snapshot via the configured ACE provider."""
        from ._notification_provider import read_notification_snapshot_for_tui

        result = read_notification_snapshot_for_tui(
            include_dismissed=include_dismissed,
            expire_due_snoozes=expire_due_snoozes,
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_provider_fallback_reason = result.fallback_reason  # type: ignore[attr-defined]
        self._notification_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _read_notification_counts_from_provider(self) -> Any:
        """Return count-only notification data via the configured ACE provider."""
        from ...provider_contract import AceCountPatch, AceDeltaBatch
        from ._notification_provider import (
            apply_notification_count_delta,
            read_notification_counts_for_tui,
        )

        result = read_notification_counts_for_tui(
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_provider_fallback_reason = result.fallback_reason  # type: ignore[attr-defined]
        self._notification_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        previous_counts = getattr(self, "_notification_counts_cache", None)
        if previous_counts is not None:
            from dataclasses import replace

            patched_counts = apply_notification_count_delta(
                previous_counts,
                AceDeltaBatch(
                    surface="notification_counts",
                    snapshot_id=None,
                    sequence=None,
                    count_patches=[
                        AceCountPatch("priority", result.value.counts.priority),
                        AceCountPatch("errors", result.value.counts.errors),
                        AceCountPatch("rest", result.value.counts.rest),
                        AceCountPatch("muted", result.value.counts.muted),
                    ],
                ),
            )
            result = replace(result, value=replace(result.value, counts=patched_counts))
        self._notification_counts_cache = result.value.counts  # type: ignore[attr-defined]
        return result.value

    def _read_unread_notification_page_from_provider(
        self,
        *,
        include_dismissed: bool = False,
        limit: int | None = None,
    ) -> Any:
        """Return one unread modal page via the configured ACE provider."""
        from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT

        from ._notification_provider import read_unread_notification_page_for_tui

        result = read_unread_notification_page_for_tui(
            include_dismissed=include_dismissed,
            limit=limit or LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_provider_fallback_reason = result.fallback_reason  # type: ignore[attr-defined]
        self._notification_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _read_notification_detail_from_provider(
        self,
        notification_id: str,
    ) -> Any:
        """Return selected notification detail via the configured provider."""
        from ._notification_provider import read_notification_detail_for_tui

        result = read_notification_detail_for_tui(
            notification_id,
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_detail_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_detail_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _read_notification_pending_actions_from_provider(self) -> Any:
        """Return pending notification actions via the configured provider."""
        from ._notification_provider import read_notification_pending_actions_for_tui

        result = read_notification_pending_actions_for_tui(
            client=getattr(self, "_daemon_read_client", None),
            args=getattr(self, "_daemon_read_args", None),
        )
        self._notification_pending_actions_provider_used_daemon = result.used_daemon  # type: ignore[attr-defined]
        self._notification_pending_actions_provider_snapshot = getattr(  # type: ignore[attr-defined]
            result.value, "shared_snapshot", None
        )
        return result.value

    def _schedule_notification_snapshot_refresh(self) -> None:
        """Refresh the notification cache off the current finalization frame."""
        if getattr(self, "_notification_snapshot_refresh_pending", False):
            return
        self._notification_snapshot_refresh_pending = True  # type: ignore[attr-defined]
        call_later = getattr(self, "call_later", None)
        if callable(call_later):
            call_later(self._refresh_notification_count_async)
            return
        self._notification_snapshot_refresh_pending = False  # type: ignore[attr-defined]

    def _selected_agent_identity_for_notification_reconcile(
        self,
    ) -> tuple[AgentType, str, str | None] | None:
        agents = getattr(self, "_agents", None) or []
        if (
            getattr(self, "current_tab", None) == "agents"
            and getattr(self, "_current_group_key", None) is None
            and 0 <= getattr(self, "current_idx", -1) < len(agents)
        ):
            return agents[self.current_idx].identity
        return None

    def _patch_unread_completed_agent_changes(
        self,
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
        for agent in self._agents:
            if agent.identity not in changed:
                continue
            if not callable(try_patch) or not try_patch(agent):
                needs_rebuild = True
        if needs_rebuild:
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                refresh(list_changed=True, defer_detail=True)

    def _reconcile_unread_from_cached_notifications(self) -> None:
        """Apply cached completion notifications to visible agent unread state."""
        snapshot = getattr(self, "_notification_snapshot_cache", None)
        if snapshot is None:
            return
        before = set(getattr(self, "_unread_completed_agent_ids", set()))
        self._reconcile_unread_from_completion_notifications(
            snapshot.notifications,
            exclude_identity=self._selected_agent_identity_for_notification_reconcile(),
        )
        self._patch_unread_completed_agent_changes(before)

    async def _poll_agent_completions(self) -> None:
        """Poll notification store for new unread notifications.

        Detects when unread count increases and triggers bell/toast.
        Called on every auto-refresh regardless of current tab. The disk
        parse happens off the main thread so the polling tick doesn't
        block the event loop while the user is settling into the TUI.
        """
        import asyncio

        from ._toasts import format_batch_toasts

        snapshot = await asyncio.to_thread(
            self._read_notification_snapshot_from_provider,
            expire_due_snoozes=True,
        )
        self._set_notification_snapshot_cache(snapshot)
        notifications = snapshot.notifications
        expired_snoozes = snapshot.expired_ids
        unread_priority, unread_errors, unread_rest, unread_muted = (
            _unread_notification_buckets(notifications)
        )

        unread_active = unread_priority + unread_errors + unread_rest
        current_ids = {n.id for n in unread_active}
        new_ids = current_ids - self._last_unread_ids
        new_notifications = [n for n in unread_active if n.id in new_ids]

        # Detect newly arrived notifications (muted arrivals don't toast/bell).
        # Snooze expirations also ring once per batch — read-and-snoozed rows
        # don't re-enter unread, so the bell is the only reminder for them.
        if new_notifications:
            self._ring_tmux_bell()
            for message, severity in format_batch_toasts(new_notifications):
                self.notify(  # type: ignore[attr-defined]
                    message,
                    severity=severity,
                    timeout=8,
                )
        elif expired_snoozes:
            self._ring_tmux_bell()

        self._last_unread_ids = current_ids

        # Update persistent notification indicator
        from ...widgets import NotificationIndicator

        counts = snapshot.counts
        indicator = self.query_one(  # type: ignore[attr-defined]
            "#notification-indicator", NotificationIndicator
        )
        indicator.set_counts(counts.priority + counts.errors, counts.rest, counts.muted)

        # Status overrides apply regardless of mute — muting quiets the
        # indicator, it shouldn't break the agent's lifecycle.
        self._apply_notification_status_overrides(unread_active + unread_muted)

        # Project active completion notifications onto Agents-tab unread rows
        # so dismissed status drives the row marker (one-to-one contract).
        selected_identity = self._selected_agent_identity_for_notification_reconcile()
        self._reconcile_unread_from_completion_notifications(
            notifications, exclude_identity=selected_identity
        )

    def _apply_notification_status_overrides(self, unread: list[Notification]) -> None:
        """Scan unread notifications and set PLAN/QUESTION status overrides.

        For PlanApproval notifications, sets the matching agent's override to
        PLAN. For UserQuestion notifications, sets the override to QUESTION
        and conditionally saves the pre-question status (only if not already
        saved, to preserve the original status across multiple questions).

        Also auto-dismisses PlanApproval notifications that were responded to
        externally (e.g. user approved via Telegram), updating agent status
        accordingly.
        """
        dismissed_any = False
        for notification in unread:
            if notification.action not in ("PlanApproval", "UserQuestion"):
                continue

            # Check if PlanApproval was already responded to externally
            # (e.g. via Telegram). If so, auto-dismiss and update status.
            if notification.action == "PlanApproval":
                if self._auto_dismiss_external_plan_response(notification):
                    dismissed_any = True
                    continue

            # Extract agent identity fields from notification
            cl_name = notification.action_data.get("agent_cl_name")
            if not cl_name:
                continue

            from ._notification_navigation import agent_matches_notification_identity

            # Find matching agent
            for agent in self._agents:
                if not agent_matches_notification_identity(
                    agent, notification, cl_name
                ):
                    continue

                # Skip finished agents — overrides don't apply
                if agent.status in ("DONE", "FAILED"):
                    break

                if notification.action == "PlanApproval":
                    self._agent_status_overrides[agent.identity] = "PLAN"
                elif notification.action == "UserQuestion":
                    # Save pre-question status only if not already saved
                    if agent.identity not in self._agent_pre_question_status:
                        self._agent_pre_question_status[agent.identity] = agent.status
                    self._agent_status_overrides[agent.identity] = "QUESTION"

                break

        if dismissed_any:
            self._refresh_notification_count()

    def _reconcile_unread_from_completion_notifications(
        self,
        notifications: list[Notification],
        *,
        exclude_identity: tuple[AgentType, str, str | None] | None = None,
    ) -> None:
        """Project active completion notifications onto agent-row unread state.

        For each visible terminal agent:

        - If a matching active (not-dismissed) completion notification exists,
          mark the row unread.
        - If no matching notification exists, clear the row's unread marker
          unless it was manually marked unread via ``U``.

        ``exclude_identity`` opts a single visible row out of being marked
        unread — used by the agents-tab finalize step to keep the currently
        focused row from re-appearing as unread after its notification has
        just been dismissed.
        """
        from ._core import is_unread_completed_status

        active_keys = _active_completion_agent_keys(notifications)

        unread_ids = getattr(self, "_unread_completed_agent_ids", None)
        if unread_ids is None:
            unread_ids = set()
            self._unread_completed_agent_ids = unread_ids  # type: ignore[attr-defined]
        manual_ids: set[tuple[AgentType, str, str | None]] = getattr(
            self, "_manual_unread_agent_ids", set()
        )
        before = set(unread_ids)

        for agent in self._agents:
            if not is_unread_completed_status(agent.status):
                continue
            has_notification = (agent.cl_name, agent.raw_suffix) in active_keys or (
                agent.cl_name,
                None,
            ) in active_keys
            if has_notification:
                if (
                    agent.identity != exclude_identity
                    and agent.identity not in manual_ids
                ):
                    unread_ids.add(agent.identity)
            else:
                # Manual unread guards a row even without a notification.
                if agent.identity not in manual_ids:
                    unread_ids.discard(agent.identity)
        if unread_ids != before and hasattr(self, "_agent_info_metrics_cache"):
            self._agent_info_metrics_cache = None  # type: ignore[attr-defined]

    def _auto_dismiss_external_plan_response(self, notification: Notification) -> bool:
        """Auto-dismiss a PlanApproval notification responded to externally.

        When a plan is approved/rejected via Telegram (or another external
        source), the response file (plan_response.json) exists but the TUI
        notification isn't dismissed. This detects that and handles it.

        Detection uses three signals (checked in order):
        1. plan_response.json exists — response written, handler may not have
           consumed it yet.
        2. plan_approved.marker exists — handler already processed approval.
        3. plan_request.json is gone — handler already consumed the response
           (rejection, since approval would leave a marker).

        Returns True if the notification was auto-dismissed.
        """
        import json
        from pathlib import Path

        from sase.notifications import mark_dismissed

        from ._notification_actions import (
            find_agent_for_notification,
            persist_plan_approved,
        )

        response_dir = notification.action_data.get("response_dir")
        if not response_dir:
            return False

        response_dir_path = Path(response_dir)
        response_file = response_dir_path / "plan_response.json"
        request_file = response_dir_path / "plan_request.json"
        marker_file = response_dir_path / "plan_approved.marker"

        # Case 1: Response file exists — read action from it.
        if response_file.exists():
            mark_dismissed(notification.id)

            # Read response to update agent status accordingly
            try:
                with open(response_file, encoding="utf-8") as f:
                    response = json.load(f)
            except (json.JSONDecodeError, OSError):
                return True

            agent = find_agent_for_notification(self, notification)
            if agent is not None:
                action = response.get("action")
                if action == "approve":
                    is_tale = (
                        response.get("commit_plan") is True
                        and response.get("run_coder", True) is True
                    )
                    status = "TALE APPROVED" if is_tale else "PLAN APPROVED"
                    self._agent_status_overrides[agent.identity] = status
                    persist_plan_approved(
                        agent, action="tale" if is_tale else "approve"
                    )
                elif action == "epic":
                    self._agent_status_overrides[agent.identity] = "EPIC APPROVED"
                    persist_plan_approved(agent, action="epic")
                elif action == "legend":
                    self._agent_status_overrides[agent.identity] = "LEGEND APPROVED"
                    persist_plan_approved(agent, action="legend")
                else:
                    # Reject with feedback: agent is resuming, mark as RUNNING
                    self._agent_status_overrides[agent.identity] = "RUNNING"
                self._load_agents()  # type: ignore[attr-defined]

            return True

        # Case 2: Approval marker exists — handler already processed approval.
        if marker_file.exists():
            mark_dismissed(notification.id)

            agent = find_agent_for_notification(self, notification)
            if agent is not None:
                self._agent_status_overrides[agent.identity] = "PLAN APPROVED"
                persist_plan_approved(agent)
                self._load_agents()  # type: ignore[attr-defined]

            return True

        # Case 3: Request file gone but directory exists — handler consumed
        # the response (rejection, since approval leaves a marker).
        if not request_file.exists() and response_dir_path.is_dir():
            mark_dismissed(notification.id)

            agent = find_agent_for_notification(self, notification)
            if agent is not None:
                self._agent_status_overrides.pop(agent.identity, None)
                self._load_agents()  # type: ignore[attr-defined]

            return True

        return False

    def _refresh_notification_count(self) -> None:
        """Reload unread notification count from disk and update the indicator.

        Called after notifications are dismissed outside the notification modal
        (e.g. when an agent is killed or dismissed-done).
        """
        from ...widgets import NotificationIndicator

        count_snapshot = self._read_notification_counts_from_provider()
        counts = count_snapshot.counts

        if not getattr(self, "_notification_provider_used_daemon", False):
            snapshot = self._read_notification_snapshot_from_provider()
            self._set_notification_snapshot_cache(snapshot)
            unread_priority, unread_errors, unread_rest, _ = (
                _unread_notification_buckets(snapshot.notifications)
            )
            counts = snapshot.counts
            self._last_unread_ids = {
                n.id for n in unread_priority + unread_errors + unread_rest
            }
        elif (
            cached := getattr(self, "_notification_snapshot_cache", None)
        ) is not None:
            unread_priority, unread_errors, unread_rest, _ = (
                _unread_notification_buckets(cached.notifications)
            )
            self._last_unread_ids = {
                n.id for n in unread_priority + unread_errors + unread_rest
            }

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#notification-indicator", NotificationIndicator
            )
        except Exception:
            return
        indicator.set_counts(counts.priority + counts.errors, counts.rest, counts.muted)
        self._reconcile_unread_from_cached_notifications()

    async def _refresh_notification_count_async(self) -> None:
        """Async variant that reads the notifications file off the main thread.

        The widget update still runs on the asyncio event loop (main thread).
        """
        import asyncio

        from ...widgets import NotificationIndicator

        try:
            count_snapshot = await asyncio.to_thread(
                self._read_notification_counts_from_provider
            )
        except Exception:
            self._notification_snapshot_refresh_pending = False  # type: ignore[attr-defined]
            raise
        self._notification_snapshot_refresh_pending = False  # type: ignore[attr-defined]
        counts = count_snapshot.counts

        if not getattr(self, "_notification_provider_used_daemon", False):
            snapshot = await asyncio.to_thread(
                self._read_notification_snapshot_from_provider
            )
            self._set_notification_snapshot_cache(snapshot)
            unread_priority, unread_errors, unread_rest, _ = (
                _unread_notification_buckets(snapshot.notifications)
            )
            counts = snapshot.counts
            self._last_unread_ids = {
                n.id for n in unread_priority + unread_errors + unread_rest
            }
        elif (
            cached := getattr(self, "_notification_snapshot_cache", None)
        ) is not None:
            unread_priority, unread_errors, unread_rest, _ = (
                _unread_notification_buckets(cached.notifications)
            )
            self._last_unread_ids = {
                n.id for n in unread_priority + unread_errors + unread_rest
            }

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#notification-indicator", NotificationIndicator
            )
        except Exception:
            return
        indicator.set_counts(counts.priority + counts.errors, counts.rest, counts.muted)
        self._reconcile_unread_from_cached_notifications()

    def _ring_tmux_bell(self) -> None:
        """Ring tmux bell to notify user of agent completion."""
        import os
        import subprocess

        from sase.core.shell import get_vendored_tool

        # Get current tmux pane from environment
        tmux_pane = os.environ.get("TMUX_PANE")
        if not tmux_pane:
            return  # Not in tmux

        try:
            subprocess.run(
                [get_vendored_tool("tmux_ring_bell"), tmux_pane, "3", "0.1"],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass  # Script not available

    def action_show_notifications(self) -> None:
        """Show the notification modal with unread notifications."""
        self._show_notification_modal()

    def _jump_to_agent_notification(self) -> None:
        """Directly trigger the action for the current agent's notification.

        Finds the PlanApproval or UserQuestion notification matching the
        currently selected agent and directly invokes its handler, skipping
        the NotificationModal. If the target agent is hidden, auto-unhides
        agents first.
        """
        # Try current agent first
        agent: Agent | None = None
        candidate = self._get_selected_agent()  # type: ignore[attr-defined]
        if candidate is not None:
            if candidate.status in ("PLAN", "QUESTION"):
                agent = candidate

        # If current agent doesn't have a notification, auto-unhide hidden agents
        # and search for one that does
        if agent is None and self.hide_non_run_agents and self._hidden_count > 0:
            self.hide_non_run_agents = False
            self._load_agents()  # type: ignore[attr-defined]
            for i, a in enumerate(self._agents):
                if a.status in ("PLAN", "QUESTION"):
                    self.current_idx = i  # type: ignore[assignment]
                    agent = a
                    break
            if agent is None:
                # No hidden agent had a notification, restore hide state
                self.hide_non_run_agents = True
                self._load_agents()  # type: ignore[attr-defined]

        if agent is None:
            return

        from ._notification_navigation import agent_matches_notification_identity

        page = self._read_unread_notification_page_from_provider()
        unread = page.notifications

        # Find the notification matching this agent
        matched: Notification | None = None
        for notification in unread:
            if notification.action not in ("PlanApproval", "UserQuestion"):
                continue
            cl_name = notification.action_data.get("agent_cl_name")
            if cl_name != agent.cl_name:
                continue
            if not agent_matches_notification_identity(agent, notification, cl_name):
                continue
            matched = notification
            break

        if matched is None:
            # Dismissed-notification fallback: the agent is still blocked on a
            # question but the matching UserQuestion notification has already
            # been dismissed. The pending_question.json marker is the
            # authoritative source of the live request path in that case.
            if agent.status == "QUESTION" and self._open_question_modal_from_marker(
                agent
            ):
                self._refresh_notification_count()
            return

        # Directly dispatch the notification action, skipping the modal
        from ._notification_actions import handle_plan_approval, handle_user_question

        if matched.action == "PlanApproval":
            self._read_notification_pending_actions_from_provider()
            handle_plan_approval(self, matched)
        elif matched.action == "UserQuestion":
            self._read_notification_pending_actions_from_provider()
            handle_user_question(self, matched)
        else:
            # Defensive fallback: open the modal for unexpected action types
            self._show_notification_modal()
            return

        self._refresh_notification_count()

    def _open_question_modal_from_marker(self, agent: Agent) -> bool:
        """Open the UserQuestionModal for an agent whose notification was dismissed.

        Reads ``pending_question.json`` from the agent's artifacts dir to
        recover the request path, then opens the modal directly. Returns
        True if the modal was opened.
        """
        import json
        from pathlib import Path

        from ._notification_actions import open_user_question_modal_from_marker

        artifacts_dir = agent.get_artifacts_dir()
        if not artifacts_dir:
            return False
        marker_path = Path(artifacts_dir) / "pending_question.json"
        if not marker_path.exists():
            return False
        try:
            with open(marker_path, encoding="utf-8") as f:
                marker = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False
        request_path = marker.get("request_path")
        if not isinstance(request_path, str) or not request_path:
            return False
        response_dir = str(Path(request_path).parent)
        return open_user_question_modal_from_marker(self, response_dir)

    def _show_notification_modal(self, *, initial_index: int = 0) -> None:
        """Show the notification modal with optional pre-selection.

        Args:
            initial_index: Index of the notification to highlight initially.
        """
        from sase.notifications import mark_read

        from ._notification_actions import (
            handle_hitl,
            handle_jump_to_agent,
            handle_jump_to_changespec,
            handle_jump_to_mentor_review,
            handle_plan_approval,
            handle_tmux,
            handle_user_question,
            handle_view_error_report,
        )
        from ...modals import NotificationModal

        page = self._read_unread_notification_page_from_provider()
        unread = list(page.notifications)

        def _on_dismiss(result: Notification | None) -> None:
            if result is not None:
                # Don't mark PlanApproval/UserQuestion as read on selection —
                # they must stay unread until the user explicitly responds,
                # so cancelling the popup keeps the notification visible.
                if result.action not in ("PlanApproval", "UserQuestion"):
                    mark_read(result.id)

            # Always refresh count from disk — covers x-dismiss, R-read-all, Enter-select
            self._refresh_notification_count()

            if result is None:
                return

            detail = self._read_notification_detail_from_provider(result.id)
            if detail.notification is not None:
                result = detail.notification
            if result.action in ("PlanApproval", "UserQuestion", "HITL"):
                self._read_notification_pending_actions_from_provider()

            # Dispatch action
            if result.action == "JumpToChangeSpec":
                handle_jump_to_changespec(self, result)
            elif result.action == "JumpToMentorReview":
                handle_jump_to_mentor_review(self, result)
            elif result.action == "JumpToAgent":
                handle_jump_to_agent(self, result)
            elif result.action == "Tmux":
                handle_tmux(self, result)
            elif result.action == "HITL":
                handle_hitl(self, result)
            elif result.action == "PlanApproval":
                handle_plan_approval(self, result)
            elif result.action == "UserQuestion":
                handle_user_question(self, result)
            elif result.action == "ViewErrorReport":
                handle_view_error_report(self, result)

        self.push_screen(  # type: ignore[attr-defined]
            NotificationModal(unread, initial_index=initial_index), callback=_on_dismiss
        )  # type: ignore[attr-defined]
