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

    def _poll_agent_completions(self) -> None:
        """Poll notification store for new unread notifications.

        Detects when unread count increases and triggers bell/toast.
        Called on every auto-refresh regardless of current tab.
        """
        from sase.notifications import load_notifications

        from ._toasts import format_batch_toasts

        notifications = load_notifications()
        unread_active = [
            n for n in notifications if not n.read and not n.silent and not n.muted
        ]
        unread_muted = [
            n for n in notifications if not n.read and not n.silent and n.muted
        ]

        current_ids = {n.id for n in unread_active}
        new_ids = current_ids - self._last_unread_ids
        new_notifications = [n for n in unread_active if n.id in new_ids]

        # Detect newly arrived notifications (muted arrivals don't toast/bell)
        if new_notifications:
            self._ring_tmux_bell()
            for message, severity in format_batch_toasts(new_notifications):
                self.notify(  # type: ignore[attr-defined]
                    message,
                    severity=severity,
                    timeout=8,
                )

        self._last_unread_ids = current_ids

        # Update persistent notification indicator
        from ...widgets import NotificationIndicator

        indicator = self.query_one(  # type: ignore[attr-defined]
            "#notification-indicator", NotificationIndicator
        )
        indicator.set_counts(len(unread_active), len(unread_muted))

        # Status overrides apply regardless of mute — muting quiets the
        # indicator, it shouldn't break the agent's lifecycle.
        self._apply_notification_status_overrides(unread_active + unread_muted)

    def _apply_notification_status_overrides(self, unread: list[Notification]) -> None:
        """Scan unread notifications and set PLANNING/QUESTION status overrides.

        For PlanApproval notifications, sets the matching agent's override to
        PLANNING. For UserQuestion notifications, sets the override to QUESTION
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

            agent_timestamp = notification.action_data.get("agent_timestamp")

            # Normalize timestamp to 14-digit format for comparison with
            # agent.raw_suffix (which is always normalized to 14-digit).
            # The env var SASE_AGENT_TIMESTAMP uses YYmmdd_HHMMSS (13-char)
            # but raw_suffix uses YYYYmmddHHMMSS (14-digit).
            from ...models._timestamps import normalize_to_14_digit

            agent_timestamp = normalize_to_14_digit(agent_timestamp)

            # Find matching agent
            for agent in self._agents:
                if agent.cl_name != cl_name:
                    continue
                if agent_timestamp and agent.raw_suffix != agent_timestamp:
                    continue

                # Skip finished agents — overrides don't apply
                if agent.status in ("DONE", "FAILED"):
                    break

                if notification.action == "PlanApproval":
                    self._agent_status_overrides[agent.identity] = "PLANNING"
                elif notification.action == "UserQuestion":
                    # Save pre-question status only if not already saved
                    if agent.identity not in self._agent_pre_question_status:
                        self._agent_pre_question_status[agent.identity] = agent.status
                    self._agent_status_overrides[agent.identity] = "QUESTION"

                break

        if dismissed_any:
            self._refresh_notification_count()

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
                    self._agent_status_overrides[agent.identity] = "PLAN APPROVED"
                    persist_plan_approved(agent)
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
        from sase.notifications import load_notifications

        from ...widgets import NotificationIndicator

        notifications = load_notifications()
        unread_active = [
            n for n in notifications if not n.read and not n.silent and not n.muted
        ]
        unread_muted = [
            n for n in notifications if not n.read and not n.silent and n.muted
        ]

        self._last_unread_ids = {n.id for n in unread_active}

        indicator = self.query_one(  # type: ignore[attr-defined]
            "#notification-indicator", NotificationIndicator
        )
        indicator.set_counts(len(unread_active), len(unread_muted))

    async def _refresh_notification_count_async(self) -> None:
        """Async variant that reads the notifications file off the main thread.

        The widget update still runs on the asyncio event loop (main thread).
        """
        import asyncio

        from sase.notifications import load_notifications

        from ...widgets import NotificationIndicator

        notifications = await asyncio.to_thread(load_notifications)
        unread_active = [
            n for n in notifications if not n.read and not n.silent and not n.muted
        ]
        unread_muted = [
            n for n in notifications if not n.read and not n.silent and n.muted
        ]

        self._last_unread_ids = {n.id for n in unread_active}

        indicator = self.query_one(  # type: ignore[attr-defined]
            "#notification-indicator", NotificationIndicator
        )
        indicator.set_counts(len(unread_active), len(unread_muted))

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
            if candidate.status in ("PLANNING", "QUESTION"):
                agent = candidate

        # If current agent doesn't have a notification, auto-unhide hidden agents
        # and search for one that does
        if agent is None and self.hide_non_run_agents and self._hidden_count > 0:
            self.hide_non_run_agents = False
            self._load_agents()  # type: ignore[attr-defined]
            for i, a in enumerate(self._agents):
                if a.status in ("PLANNING", "QUESTION"):
                    self.current_idx = i  # type: ignore[assignment]
                    agent = a
                    break
            if agent is None:
                # No hidden agent had a notification, restore hide state
                self.hide_non_run_agents = True
                self._load_agents()  # type: ignore[attr-defined]

        if agent is None:
            return

        from sase.notifications import load_notifications

        from ...models._timestamps import normalize_to_14_digit

        notifications = load_notifications()
        unread = [n for n in notifications if not n.read]

        # Find the notification matching this agent
        matched: Notification | None = None
        for notification in unread:
            if notification.action not in ("PlanApproval", "UserQuestion"):
                continue
            cl_name = notification.action_data.get("agent_cl_name")
            if cl_name != agent.cl_name:
                continue
            agent_timestamp = notification.action_data.get("agent_timestamp")
            agent_timestamp = normalize_to_14_digit(agent_timestamp)
            if agent_timestamp and agent.raw_suffix != agent_timestamp:
                continue
            matched = notification
            break

        if matched is None:
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

    def _show_notification_modal(self, *, initial_index: int = 0) -> None:
        """Show the notification modal with optional pre-selection.

        Args:
            initial_index: Index of the notification to highlight initially.
        """
        from sase.notifications import load_notifications, mark_read

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

        notifications = load_notifications()
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
