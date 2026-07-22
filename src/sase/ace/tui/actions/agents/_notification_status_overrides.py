"""Notification-driven agent status overrides."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.status_buckets import PENDING_EPIC_STATUS, PENDING_TALE_STATUS

from ._notification_utils import (
    apply_disappeared_plan_notification_refresh,
    refresh_notification_agent_from_cache,
    refresh_notification_agent_or_request,
)

if TYPE_CHECKING:
    from sase.notification_gates.paths import ResolvedGateBundle
    from sase.notifications import Notification


@dataclass(frozen=True)
class _PreparedExternalPlanResponse:
    """Worker-prepared UI transition for an externally resolved plan gate."""

    notification: Notification
    status: str | None = None
    clear_override: bool = False
    plan_action: str | None = None
    artifact_dir: Path | None = None


@dataclass(frozen=True)
class PreparedPlanNotificationReconciliation:
    """All worker-prepared plan-notification state for one poll snapshot."""

    external_responses: dict[str, _PreparedExternalPlanResponse]
    neutral_notification_ids: frozenset[str]


def prepare_plan_notification_reconciliation(
    app: Any,
    notifications: list[Notification],
) -> PreparedPlanNotificationReconciliation:
    """Resolve neutral tiers and external responses without UI-thread I/O."""
    from sase.notification_gates.paths import resolve_notification_bundle

    prepared: dict[str, _PreparedExternalPlanResponse] = {}
    neutral_ids: set[str] = set()
    for notification in notifications:
        if notification.action not in {"PlanApproval", "EpicApproval"}:
            continue
        bundle = resolve_notification_bundle(notification)
        if bundle is None:
            continue
        if not bundle.legacy:
            neutral_ids.add(notification.id)
        transition = _prepare_external_plan_response(
            app,
            notification,
            bundle,
        )
        if transition is not None:
            prepared[notification.id] = transition
    return PreparedPlanNotificationReconciliation(
        external_responses=prepared,
        neutral_notification_ids=frozenset(neutral_ids),
    )


def _prepare_external_plan_response(
    app: Any,
    notification: Notification,
    bundle: ResolvedGateBundle,
) -> _PreparedExternalPlanResponse | None:
    """Perform response-file compatibility I/O and return a UI-only result."""
    import json

    from sase.ace.tui.models._loaders._meta_enrichment_common import (
        plan_enrichment_status,
    )
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
            return _PreparedExternalPlanResponse(notification)
        if not isinstance(response, dict):
            return _PreparedExternalPlanResponse(
                notification,
                status="RUNNING",
                artifact_dir=artifact_dir,
            )

        translated = response
        if not bundle.legacy:
            try:
                from sase.notification_gates.models import GateError
                from sase.plan_gate import translate_plan_gate_response

                translated = translate_plan_gate_response(bundle.root, response)
            except GateError:
                translated = {}
        plan_action = persisted_plan_action(translated)
        if plan_action is None:
            return _PreparedExternalPlanResponse(
                notification,
                status="RUNNING",
                artifact_dir=artifact_dir,
            )

        status = plan_enrichment_status(
            plan_approved=True,
            plan_action=plan_action,
            plan_submitted=False,
            auto_approved=False,
        )
        # The shared v2 executor already owns metadata persistence and launch /
        # archive effects. Only legacy responses need ACE's compatibility write.
        if bundle.legacy and agent is not None:
            persist_plan_approved(agent, action=plan_action)
        return _PreparedExternalPlanResponse(
            notification,
            status=status,
            plan_action=plan_action,
            artifact_dir=artifact_dir,
        )

    if bundle.legacy and marker_file.exists():
        mark_dismissed(notification.id)
        if agent is not None:
            persist_plan_approved(agent)
        return _PreparedExternalPlanResponse(
            notification,
            status="PLAN APPROVED",
            plan_action="approve",
            artifact_dir=artifact_dir,
        )

    if bundle.legacy and not request_file.exists() and response_dir_path.is_dir():
        mark_dismissed(notification.id)
        return _PreparedExternalPlanResponse(
            notification,
            clear_override=True,
            artifact_dir=artifact_dir,
        )

    return None


class AgentNotificationStatusMixin:
    """Apply pending-plan/question notification state to agent rows."""

    def _apply_notification_status_overrides(
        self: Any,
        unread: list[Notification],
        *,
        prepared_external_plan_responses: dict[str, _PreparedExternalPlanResponse]
        | None = None,
        prepared_neutral_plan_notification_ids: frozenset[str] | None = None,
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
                    continue

            pending_plan_status: str | None = None
            if notification.action in {"PlanApproval", "EpicApproval"}:
                is_neutral = (
                    notification.id in prepared_neutral_plan_notification_ids
                    if prepared_neutral_plan_notification_ids is not None
                    else None
                )
                if is_neutral is None:
                    from sase.notification_gates.paths import (
                        resolve_notification_bundle,
                    )

                    bundle = resolve_notification_bundle(notification)
                    is_neutral = bundle is not None and not bundle.legacy
                if is_neutral:
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
                    current_override = self._agent_status_overrides.get(  # type: ignore[attr-defined]
                        agent.identity
                    )
                    if current_override != pending_plan_status:
                        self._agent_status_overrides[agent.identity] = (  # type: ignore[attr-defined]
                            pending_plan_status
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
        """Apply a prepared response transition without filesystem access."""
        if transition.status is None and not transition.clear_override:
            return
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
        elif transition.status is not None:
            self._agent_status_overrides[agent.identity] = transition.status  # type: ignore[attr-defined]
        if refresh_notification_agent_from_cache(self, agent=agent):
            return
        apply_disappeared_plan_notification_refresh(
            self,
            (() if transition.artifact_dir is None else (transition.artifact_dir,)),
            needs_broad_fallback=transition.artifact_dir is None,
        )

    def _auto_dismiss_external_plan_response(
        self: Any, notification: Notification
    ) -> bool:
        """Synchronous compatibility wrapper for non-poller callers/tests.

        Production polling prepares this transition on a worker thread. The
        wrapper remains for legacy direct invocations and keeps one canonical
        interpretation of both response formats.
        """
        prepared = prepare_plan_notification_reconciliation(self, [notification])
        transition = prepared.external_responses.get(notification.id)
        if transition is None:
            return False
        self._apply_prepared_external_plan_response(transition)
        return True
