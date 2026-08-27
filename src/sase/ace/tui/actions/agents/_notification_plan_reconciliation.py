"""Legacy plan notification lifecycle reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._notification_utils import (
    apply_disappeared_plan_notification_refresh,
)

if TYPE_CHECKING:
    from sase.notification_gates.paths import ResolvedGateBundle
    from sase.notifications import Notification


@dataclass(frozen=True)
class _PreparedExternalPlanResponse:
    """Worker-prepared lifecycle transition for a resolved legacy plan review."""

    notification: Notification
    clear_override: bool = False
    artifact_dir: Path | None = None


@dataclass(frozen=True)
class PreparedPlanNotificationReconciliation:
    """Worker-prepared plan-notification reconciliation for one poll snapshot."""

    external_responses: dict[str, _PreparedExternalPlanResponse]


def prepare_plan_notification_reconciliation(
    app: Any,
    notifications: list[Notification],
) -> PreparedPlanNotificationReconciliation:
    """Resolve legacy external responses without UI-thread I/O."""
    from sase.notification_gates.paths import resolve_notification_bundle

    prepared: dict[str, _PreparedExternalPlanResponse] = {}
    for notification in notifications:
        if notification.action not in {"PlanApproval", "EpicApproval"}:
            continue
        bundle = resolve_notification_bundle(notification)
        if bundle is None or not bundle.legacy:
            continue
        transition = _prepare_external_plan_response(
            app,
            notification,
            bundle,
        )
        if transition is not None:
            prepared[notification.id] = transition
    return PreparedPlanNotificationReconciliation(
        external_responses=prepared,
    )


def _prepare_external_plan_response(
    app: Any,
    notification: Notification,
    bundle: ResolvedGateBundle,
) -> _PreparedExternalPlanResponse | None:
    """Perform legacy response-file compatibility I/O."""
    import json

    from sase.notifications import mark_dismissed
    from sase.plan_approval_actions import persisted_plan_action

    from ._notification_actions import (
        find_agent_for_notification,
        persist_plan_approved,
    )

    response_dir_path = bundle.root
    response_file = bundle.response
    request_file = bundle.request
    marker_file = response_dir_path / "plan_approved.marker"
    agent = find_agent_for_notification(app, notification)
    artifact_dir: Path | None = None
    if agent is not None:
        get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
        if callable(get_artifacts_dir):
            raw_artifact_dir = get_artifacts_dir()
            if isinstance(raw_artifact_dir, str) and raw_artifact_dir:
                artifact_dir = Path(raw_artifact_dir)

    if response_file.exists():
        mark_dismissed(notification.id)
        try:
            with response_file.open(encoding="utf-8") as file_obj:
                response = json.load(file_obj)
        except (json.JSONDecodeError, OSError):
            return _PreparedExternalPlanResponse(
                notification,
                clear_override=True,
                artifact_dir=artifact_dir,
            )
        if not isinstance(response, dict):
            return _PreparedExternalPlanResponse(
                notification,
                clear_override=True,
                artifact_dir=artifact_dir,
            )

        plan_action = persisted_plan_action(response)
        if plan_action is not None and agent is not None:
            persist_plan_approved(agent, action=plan_action)
        return _PreparedExternalPlanResponse(
            notification,
            clear_override=True,
            artifact_dir=artifact_dir,
        )

    if marker_file.exists():
        mark_dismissed(notification.id)
        if agent is not None:
            persist_plan_approved(agent)
        return _PreparedExternalPlanResponse(
            notification,
            clear_override=True,
            artifact_dir=artifact_dir,
        )

    if not request_file.exists() and response_dir_path.is_dir():
        mark_dismissed(notification.id)
        return _PreparedExternalPlanResponse(
            notification,
            clear_override=True,
            artifact_dir=artifact_dir,
        )

    return None


class AgentNotificationPlanReconciliationMixin:
    """Reconcile legacy plan notifications that were resolved out of band."""

    def _reconcile_plan_notification_lifecycle(
        self: Any,
        unread: list[Notification],
        *,
        prepared_external_plan_responses: dict[str, _PreparedExternalPlanResponse]
        | None = None,
    ) -> set[str]:
        """Dismiss legacy plan notifications resolved from another surface."""
        dismissed_ids: set[str] = set()
        for notification in unread:
            if notification.action not in {"PlanApproval", "EpicApproval"}:
                continue

            transition = (
                prepared_external_plan_responses.get(notification.id)
                if prepared_external_plan_responses is not None
                else None
            )
            if transition is not None:
                self._apply_prepared_external_plan_response(transition)
                dismissed_ids.add(notification.id)
                continue
            if (
                prepared_external_plan_responses is None
                and self._auto_dismiss_external_plan_response(notification)
            ):
                dismissed_ids.add(notification.id)

        if dismissed_ids:
            if prepared_external_plan_responses is None:
                self._refresh_notification_count()  # type: ignore[attr-defined]
            else:
                schedule_refresh = getattr(
                    self,
                    "_schedule_notification_snapshot_refresh",
                    None,
                )
                if callable(schedule_refresh):
                    schedule_refresh()

        return dismissed_ids

    def _apply_prepared_external_plan_response(
        self: Any,
        transition: _PreparedExternalPlanResponse,
    ) -> None:
        """Apply a prepared legacy response transition without filesystem access."""
        from ._notification_navigation import find_agent_for_notification

        agent = find_agent_for_notification(self, transition.notification)
        if agent is None:
            apply_disappeared_plan_notification_refresh(
                self,
                (() if transition.artifact_dir is None else (transition.artifact_dir,)),
                needs_broad_fallback=transition.artifact_dir is None,
            )
            return
        if transition.clear_override:
            self._agent_status_overrides.pop(agent.identity, None)  # type: ignore[attr-defined]
        apply_disappeared_plan_notification_refresh(
            self,
            (() if transition.artifact_dir is None else (transition.artifact_dir,)),
            needs_broad_fallback=transition.artifact_dir is None,
        )

    def _auto_dismiss_external_plan_response(
        self: Any, notification: Notification
    ) -> bool:
        """Synchronous compatibility wrapper for non-poller callers/tests."""

        prepared = prepare_plan_notification_reconciliation(self, [notification])
        transition = prepared.external_responses.get(notification.id)
        if transition is None:
            return False
        self._apply_prepared_external_plan_response(transition)
        return True
