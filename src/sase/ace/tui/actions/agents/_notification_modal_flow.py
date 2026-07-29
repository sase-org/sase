"""Notification modal and direct-action flows for the ACE agents TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.agent.status_buckets import agent_is_asking

from ._notification_utils import refresh_notification_agent_from_cache

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


class AgentNotificationModalMixin:
    """Open notification modals and dispatch selected notification actions."""

    def action_show_notifications(self: Any) -> None:
        """Show the notification modal with unread notifications."""
        self._show_notification_modal()

    def _jump_to_agent_notification(self: Any) -> None:
        """Directly trigger the action for the current agent's notification.

        Finds the PlanApproval or UserQuestion notification matching the
        currently selected agent and directly invokes its handler, skipping
        the NotificationModal. If the target agent is hidden, auto-unhides
        agents first.
        """
        agent: Agent | None = None
        candidate = self._get_selected_agent()  # type: ignore[attr-defined]
        if candidate is not None:
            if agent_is_asking(candidate.status):
                agent = candidate

        if (
            agent is None
            and self.hide_non_run_agents  # type: ignore[attr-defined]
            and self._hidden_count > 0  # type: ignore[attr-defined]
        ):
            # The reveal/restore scan only needs visible-filter changes; the
            # cached ``_agents_with_children`` already holds the hidden rows,
            # so the in-memory refilter is enough. Disk reconcile is deferred
            # to a single async refresh after the scan completes.
            self.hide_non_run_agents = False  # type: ignore[attr-defined]
            self._refilter_agents()  # type: ignore[attr-defined]
            for i, a in enumerate(self._agents):  # type: ignore[attr-defined]
                if agent_is_asking(a.status):
                    self.current_idx = i  # type: ignore[attr-defined]
                    agent = a
                    break
            if agent is None:
                self.hide_non_run_agents = True  # type: ignore[attr-defined]
                self._refilter_agents()  # type: ignore[attr-defined]
            elif not refresh_notification_agent_from_cache(self, agent=agent):
                self._refilter_agents()  # type: ignore[attr-defined]

        if agent is None:
            return

        from ._notification_navigation import agent_matches_notification_identity

        page = self._read_unread_notification_page_from_provider()
        unread = page.notifications

        matched: Notification | None = None
        for notification in unread:
            if notification.action not in (
                "PlanApproval",
                "EpicApproval",
                "UserQuestion",
            ):
                continue
            if not agent_matches_notification_identity(agent, notification):
                continue
            matched = notification
            break

        if matched is None:
            # Dismissed-notification fallback: pending_question.json is the
            # authoritative source of a still-live UserQuestion request path.
            if agent.status == "QUESTION" and self._open_question_modal_from_marker(
                agent
            ):
                self._refresh_notification_count()
            return

        from ._notification_actions import handle_plan_approval, handle_user_question

        if matched.action in {"PlanApproval", "EpicApproval"}:
            self._read_notification_pending_actions_from_provider()
            handle_plan_approval(self, matched)
        elif matched.action == "UserQuestion":
            self._read_notification_pending_actions_from_provider()
            handle_user_question(self, matched)
        else:
            self._show_notification_modal()
            return

        self._refresh_notification_count()

    def _open_question_modal_from_marker(self: Any, agent: Agent) -> bool:
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
        return open_user_question_modal_from_marker(self, response_dir, agent)

    def _show_notification_modal(self: Any, *, initial_index: int = 0) -> None:
        """Show the notification modal with optional pre-selection.

        Args:
            initial_index: Index of the notification to highlight initially.
        """
        from sase.notifications import mark_read

        from ._notification_actions import (
            handle_custom_gate,
            handle_hitl,
            handle_jump_to_agent,
            handle_jump_to_changespec,
            handle_jump_to_mentor_review,
            handle_launch_approval,
            handle_memory_review,
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
                # PlanApproval/UserQuestion must stay unread until response.
                if result.action not in (
                    "PlanApproval",
                    "EpicApproval",
                    "UserQuestion",
                    "LaunchApproval",
                    "CustomGate",
                ):
                    mark_read(result.id)

            self._refresh_notification_count()

            if result is None:
                return

            detail = self._read_notification_detail_from_provider(result.id)
            if detail.notification is not None:
                result = detail.notification
            if result.action in (
                "PlanApproval",
                "EpicApproval",
                "UserQuestion",
                "HITL",
                "LaunchApproval",
                "CustomGate",
            ):
                self._read_notification_pending_actions_from_provider()

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
            elif result.action in {"PlanApproval", "EpicApproval"}:
                handle_plan_approval(self, result)
            elif result.action == "UserQuestion":
                handle_user_question(self, result)
            elif result.action == "LaunchApproval":
                handle_launch_approval(self, result)
            elif result.action == "CustomGate":
                handle_custom_gate(self, result)
            elif result.action == "ViewErrorReport":
                handle_view_error_report(self, result)
            elif result.action == "memory_review":
                handle_memory_review(self, result)
            elif result.action and result.action.strip():
                self.notify(  # type: ignore[attr-defined]
                    f"Unsupported notification action: {result.action}",
                    severity="warning",
                )

        self.push_screen(  # type: ignore[attr-defined]
            NotificationModal(unread, initial_index=initial_index), callback=_on_dismiss
        )  # type: ignore[attr-defined]
