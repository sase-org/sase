"""Notification-driven agent status overrides."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.agent.status_buckets import PENDING_EPIC_STATUS, PENDING_TALE_STATUS

from ._notification_utils import refresh_notification_agent_or_request

if TYPE_CHECKING:
    from sase.notifications import Notification


class AgentNotificationStatusMixin:
    """Apply pending-plan/question notification state to agent rows."""

    def _apply_notification_status_overrides(
        self: Any, unread: list[Notification]
    ) -> set[str]:
        """Scan unread notifications and set plan/question status overrides.

        For plan-approval notifications, sets the first matching agent's
        override to its tier-aware pending status. For UserQuestion
        notifications, sets the override to QUESTION on every matched row (a
        single notification can reference both the asking child and the
        root/aggregate row) and conditionally saves each row's pre-question
        status (only if not already saved, to preserve the original status
        across multiple questions). The answer path clears every matched row
        symmetrically.

        Also auto-dismisses PlanApproval notifications that were responded to
        externally (e.g. user approved via Telegram), updating agent status
        accordingly. Returns the IDs of notifications auto-dismissed during
        this reconciliation pass.
        """
        dismissed_ids: set[str] = set()
        changed_agents: list[Any] = []
        for notification in unread:
            if notification.action not in (
                "PlanApproval",
                "EpicApproval",
                "UserQuestion",
            ):
                continue

            # Check if PlanApproval was already responded to externally
            # (e.g. via Telegram). If so, auto-dismiss and update status.
            if notification.action in {"PlanApproval", "EpicApproval"}:
                if self._auto_dismiss_external_plan_response(notification):
                    dismissed_ids.add(notification.id)
                    continue

            pending_plan_status: str | None = None
            if notification.action in {"PlanApproval", "EpicApproval"}:
                from sase.notification_gates.paths import (
                    resolve_notification_bundle,
                )

                bundle = resolve_notification_bundle(notification)
                if bundle is not None and not bundle.legacy:
                    pending_plan_status = (
                        PENDING_EPIC_STATUS
                        if notification.action == "EpicApproval"
                        else PENDING_TALE_STATUS
                    )

            from ._notification_navigation import agent_matches_notification_identity

            is_question = notification.action == "UserQuestion"
            for agent in self._agents:  # type: ignore[attr-defined]
                if not agent_matches_notification_identity(agent, notification):
                    continue

                if agent.status in ("DONE", "FAILED"):
                    # Skip terminal rows. A UserQuestion can reference both the
                    # asking child and the root row, so keep scanning to give
                    # any other matched row its QUESTION override.
                    if is_question:
                        continue
                    break

                if notification.action in {"PlanApproval", "EpicApproval"}:
                    if pending_plan_status is None:
                        from ...models._agent_status_family import (
                            pending_plan_status_for_agent,
                        )

                        pending_plan_status = pending_plan_status_for_agent(agent)
                    if (  # type: ignore[attr-defined]
                        self._agent_status_overrides.get(agent.identity)
                        != pending_plan_status
                    ):
                        self._agent_status_overrides[agent.identity] = (
                            pending_plan_status  # type: ignore[attr-defined]
                        )
                        changed_agents.append(agent)
                    break

                # UserQuestion: mark every matched row (asking child + root) so
                # the visible aggregate row and the row that actually asked stay
                # in sync; the answer path clears them symmetrically.
                if agent.identity not in self._agent_pre_question_status:  # type: ignore[attr-defined]
                    self._agent_pre_question_status[agent.identity] = agent.status  # type: ignore[attr-defined]
                if self._agent_status_overrides.get(agent.identity) != "QUESTION":  # type: ignore[attr-defined]
                    self._agent_status_overrides[agent.identity] = "QUESTION"  # type: ignore[attr-defined]
                    changed_agents.append(agent)

        for agent in changed_agents:
            refresh_notification_agent_or_request(self, agent=agent)

        if dismissed_ids:
            self._refresh_notification_count()

        return dismissed_ids

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

        from sase.ace.tui.models._loaders._meta_enrichment_common import (
            plan_enrichment_status,
        )
        from sase.notifications import mark_dismissed
        from sase.plan_approval_actions import persisted_plan_action

        from ._notification_actions import (
            find_agent_for_notification,
            persist_plan_approved,
        )

        from sase.notification_gates.paths import resolve_notification_bundle

        bundle = resolve_notification_bundle(notification)
        if bundle is None:
            return False

        response_dir_path = bundle.root
        response_file = bundle.response
        request_file = bundle.request
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
                result = response.get("result") if not bundle.legacy else response
                plan_action = persisted_plan_action(
                    result if isinstance(result, dict) else {}
                )
                if plan_action is not None:
                    status = plan_enrichment_status(
                        plan_approved=True,
                        plan_action=plan_action,
                        plan_submitted=False,
                        auto_approved=False,
                    )
                    if status is not None:
                        self._agent_status_overrides[agent.identity] = status  # type: ignore[attr-defined]
                    persist_plan_approved(agent, action=plan_action)
                else:
                    self._agent_status_overrides[agent.identity] = "RUNNING"  # type: ignore[attr-defined]
                refresh_notification_agent_or_request(self, agent=agent)

            return True

        if bundle.legacy and marker_file.exists():
            mark_dismissed(notification.id)

            agent = find_agent_for_notification(self, notification)
            if agent is not None:
                self._agent_status_overrides[agent.identity] = "PLAN APPROVED"  # type: ignore[attr-defined]
                persist_plan_approved(agent)
                refresh_notification_agent_or_request(self, agent=agent)

            return True

        if bundle.legacy and not request_file.exists() and response_dir_path.is_dir():
            mark_dismissed(notification.id)

            agent = find_agent_for_notification(self, notification)
            if agent is not None:
                self._agent_status_overrides.pop(agent.identity, None)  # type: ignore[attr-defined]
                refresh_notification_agent_or_request(self, agent=agent)

            return True

        return False
