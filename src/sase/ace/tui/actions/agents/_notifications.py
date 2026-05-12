"""Notification polling and display methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

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

    async def _poll_agent_completions(self) -> None:
        """Poll notification store for new unread notifications.

        Detects when unread count increases and triggers bell/toast.
        Called on every auto-refresh regardless of current tab. The disk
        parse happens off the main thread so the polling tick doesn't
        block the event loop while the user is settling into the TUI.
        """
        import asyncio

        from sase.notifications import read_notification_snapshot

        from ._toasts import format_batch_toasts

        snapshot = await asyncio.to_thread(
            read_notification_snapshot,
            False,
            True,
        )
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
        selected_identity = None
        agents = getattr(self, "_agents", None) or []
        if (
            getattr(self, "current_tab", None) == "agents"
            and getattr(self, "_current_group_key", None) is None
            and 0 <= getattr(self, "current_idx", -1) < len(agents)
        ):
            selected_identity = agents[self.current_idx].identity
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
        from sase.notifications import read_notification_snapshot

        from ...widgets import NotificationIndicator

        snapshot = read_notification_snapshot()
        unread_priority, unread_errors, unread_rest, _ = _unread_notification_buckets(
            snapshot.notifications
        )
        counts = snapshot.counts

        self._last_unread_ids = {
            n.id for n in unread_priority + unread_errors + unread_rest
        }

        indicator = self.query_one(  # type: ignore[attr-defined]
            "#notification-indicator", NotificationIndicator
        )
        indicator.set_counts(counts.priority + counts.errors, counts.rest, counts.muted)

    async def _refresh_notification_count_async(self) -> None:
        """Async variant that reads the notifications file off the main thread.

        The widget update still runs on the asyncio event loop (main thread).
        """
        import asyncio

        from sase.notifications import read_notification_snapshot

        from ...widgets import NotificationIndicator

        snapshot = await asyncio.to_thread(read_notification_snapshot)
        unread_priority, unread_errors, unread_rest, _ = _unread_notification_buckets(
            snapshot.notifications
        )
        counts = snapshot.counts

        self._last_unread_ids = {
            n.id for n in unread_priority + unread_errors + unread_rest
        }

        indicator = self.query_one(  # type: ignore[attr-defined]
            "#notification-indicator", NotificationIndicator
        )
        indicator.set_counts(counts.priority + counts.errors, counts.rest, counts.muted)

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

        from sase.notifications import read_notification_snapshot

        from ._notification_navigation import agent_matches_notification_identity

        snapshot = read_notification_snapshot()
        notifications = snapshot.notifications
        unread = [n for n in notifications if not n.read]

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
            handle_plan_approval(self, matched)
        elif matched.action == "UserQuestion":
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
        from sase.notifications import mark_read, read_notification_snapshot

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

        snapshot = read_notification_snapshot()
        notifications = snapshot.notifications
        unread = [n for n in notifications if not n.read and not n.silent]

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
