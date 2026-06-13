"""Compatibility wrappers for mobile notification action side effects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.integrations._mobile_notification_models import MobileNotificationBridgeRow
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    dismiss_notification_best_effort,
    run_plan_side_effects as _run_plan_side_effects,
)


def run_plan_side_effects(
    notification: MobileNotificationBridgeRow,
    choice: str,
    response_path: Path,
    response_json: dict[str, Any],
) -> None:
    _run_plan_side_effects(
        PlanApprovalActionContext(
            id=notification.id,
            host_files=tuple(notification.host_files),
            host_action_data=dict(notification.host_action_data),
        ),
        choice,
        response_path,
        response_json,
    )
