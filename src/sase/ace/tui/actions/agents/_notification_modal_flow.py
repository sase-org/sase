"""Notification modal and direct-action flows for the ACE agents TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.notification_gates.registry import PRIVILEGED_GATE_ACTIONS

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


class AgentNotificationModalMixin:
    """Open notification modals and dispatch selected notification actions."""

    def action_show_notifications(self: Any) -> None:
        """Show the notification modal with unread notifications."""
        self._show_notification_modal()

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

        from ._notification_actions import REMOTE_ATTENTION_NOTIFICATION_ACTION
        from ._notification_dispatch import open_notification_action
        from ...modals import NotificationModal

        page = self._read_unread_notification_page_from_provider()
        unread = list(page.notifications)
        read_protected_actions = (PRIVILEGED_GATE_ACTIONS - {"HITL"}) | {
            REMOTE_ATTENTION_NOTIFICATION_ACTION
        }

        def _on_dismiss(result: Notification | None) -> None:
            if result is not None:
                # PlanApproval/UserQuestion must stay unread until response.
                if result.action not in read_protected_actions:
                    mark_read(result.id)

            self._refresh_notification_count()

            if result is None:
                return

            detail = self._read_notification_detail_from_provider(result.id)
            if detail.notification is not None:
                result = detail.notification
            open_notification_action(self, result)

        self.push_screen(  # type: ignore[attr-defined]
            NotificationModal(
                unread,
                initial_index=initial_index,
                section_modes=getattr(self, "_notification_section_modes", None),
            ),
            callback=_on_dismiss,
        )  # type: ignore[attr-defined]
