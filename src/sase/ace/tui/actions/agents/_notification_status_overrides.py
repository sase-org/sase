"""Notification-driven agent status overrides."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._notification_utils import refresh_notification_agent_or_request

if TYPE_CHECKING:
    from sase.notifications import Notification


class AgentNotificationStatusMixin:
    """Apply PLAN/QUESTION notification state to agent rows."""

    def _apply_notification_status_overrides(
        self: Any, unread: list[Notification]
    ) -> None:
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
        changed_agents: list[Any] = []
        for notification in unread:
            if notification.action not in ("PlanApproval", "UserQuestion"):
                continue

            # Check if PlanApproval was already responded to externally
            # (e.g. via Telegram). If so, auto-dismiss and update status.
            if notification.action == "PlanApproval":
                if self._auto_dismiss_external_plan_response(notification):
                    dismissed_any = True
                    continue

            from ._notification_navigation import agent_matches_notification_identity

            for agent in self._agents:  # type: ignore[attr-defined]
                if not agent_matches_notification_identity(agent, notification):
                    continue

                if agent.status in ("DONE", "FAILED"):
                    break

                if notification.action == "PlanApproval":
                    if self._agent_status_overrides.get(agent.identity) != "PLAN":  # type: ignore[attr-defined]
                        self._agent_status_overrides[agent.identity] = "PLAN"  # type: ignore[attr-defined]
                        changed_agents.append(agent)
                elif notification.action == "UserQuestion":
                    if agent.identity not in self._agent_pre_question_status:  # type: ignore[attr-defined]
                        self._agent_pre_question_status[agent.identity] = agent.status  # type: ignore[attr-defined]
                    if self._agent_status_overrides.get(agent.identity) != "QUESTION":  # type: ignore[attr-defined]
                        self._agent_status_overrides[agent.identity] = "QUESTION"  # type: ignore[attr-defined]
                        changed_agents.append(agent)

                break

        for agent in changed_agents:
            refresh_notification_agent_or_request(self, agent=agent)

        if dismissed_any:
            self._refresh_notification_count()

    def _auto_dismiss_external_plan_response(
        self: Any, notification: Notification
    ) -> bool:
        """Auto-dismiss a PlanApproval notification responded to externally.

        When a plan is approved/rejected via Telegram (or another external
        source), the response file (plan_response.json) exists but the TUI
        notification isn't dismissed. This detects that and handles it.

        Detection uses three signals (checked in order):
        1. plan_response.json exists: response written, handler may not have
           consumed it yet.
        2. plan_approved.marker exists: handler already processed approval.
        3. plan_request.json is gone: handler already consumed the response
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

        if response_file.exists():
            mark_dismissed(notification.id)

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
                    self._agent_status_overrides[agent.identity] = status  # type: ignore[attr-defined]
                    persist_plan_approved(
                        agent, action="tale" if is_tale else "approve"
                    )
                elif action == "epic":
                    self._agent_status_overrides[agent.identity] = "EPIC APPROVED"  # type: ignore[attr-defined]
                    persist_plan_approved(agent, action="epic")
                elif action == "legend":
                    self._agent_status_overrides[agent.identity] = "LEGEND APPROVED"  # type: ignore[attr-defined]
                    persist_plan_approved(agent, action="legend")
                else:
                    self._agent_status_overrides[agent.identity] = "RUNNING"  # type: ignore[attr-defined]
                refresh_notification_agent_or_request(self, agent=agent)

            return True

        if marker_file.exists():
            mark_dismissed(notification.id)

            agent = find_agent_for_notification(self, notification)
            if agent is not None:
                self._agent_status_overrides[agent.identity] = "PLAN APPROVED"  # type: ignore[attr-defined]
                persist_plan_approved(agent)
                refresh_notification_agent_or_request(self, agent=agent)

            return True

        if not request_file.exists() and response_dir_path.is_dir():
            mark_dismissed(notification.id)

            agent = find_agent_for_notification(self, notification)
            if agent is not None:
                self._agent_status_overrides.pop(agent.identity, None)  # type: ignore[attr-defined]
                refresh_notification_agent_or_request(self, agent=agent)

            return True

        return False
