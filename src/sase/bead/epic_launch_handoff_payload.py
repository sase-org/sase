"""Payload construction helpers for epic launch completion handoffs."""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from sase.bead.epic_launch_handoff_io import artifact_timestamp
from sase.bead.epic_launch_handoff_model import (
    CompletionNotificationPayload,
    DeferredCompletion,
)


def send_completion_payload(
    payload: CompletionNotificationPayload,
    *,
    notification_id: str | None = None,
) -> None:
    """Send a previously serialized completion notification."""
    from sase.notifications.senders import notify_workflow_complete

    kwargs = payload.to_dict()
    if notification_id:
        kwargs["notification_id"] = notification_id
    notify_workflow_complete(**kwargs)


def settlement_notification_action_data(
    artifacts_dir: str | Path | None,
    *,
    cl_name: str | None,
    action_data: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return agent identity fields for settlement-triggered notifications."""
    data = dict(action_data or {})
    if cl_name:
        data.setdefault("cl_name", cl_name)
    raw_suffix = data.get("raw_suffix") or artifact_timestamp(artifacts_dir)
    if raw_suffix:
        data.setdefault("raw_suffix", raw_suffix)
    root_suffix = (
        data.get("family_root_suffix") or data.get("agent_root_timestamp") or raw_suffix
    )
    if root_suffix:
        data.setdefault("family_root_suffix", root_suffix)
        data.setdefault("agent_root_timestamp", root_suffix)
    return data


def fold_epic_launch_outcome(
    deferred: DeferredCompletion,
    *,
    success: bool,
    epic_id: str | None,
    plan_file: str,
    archived_plan_path: str | Path | None,
    detail: str,
    resume_argv: list[str],
) -> CompletionNotificationPayload:
    """Append the launch result to a planner completion payload."""
    payload = deferred.payload
    notes = list(payload.notes)
    if success:
        notes.extend(
            [
                f"Epic {epic_id} launched from {Path(plan_file).name}",
                f"Plan: {archived_plan_path or plan_file}",
            ]
        )
        tags = payload.tags
    else:
        notes.extend(
            [
                f"Epic launch failed: {detail}",
                f"Resume with: {shlex.join(resume_argv)}",
            ]
        )
        tags = [tag for tag in payload.tags or [] if tag != "done"] or None
    return replace(
        payload,
        success=success,
        notes=notes,
        action="JumpToAgent",
        action_data=settlement_notification_action_data(
            deferred.artifacts_dir,
            cl_name=payload.cl_name,
            action_data=payload.action_data,
        ),
        tags=tags,
    )


def unknown_outcome_payload(
    deferred: DeferredCompletion,
) -> CompletionNotificationPayload:
    from sase.bead.epic_launch import build_epic_launch_argv

    plan_file = deferred.plan_file or "<approved-plan>"
    argv = list(
        deferred.resume_argv
        or build_epic_launch_argv(
            plan_file,
            artifacts_dir=deferred.artifacts_dir,
            cl_name=deferred.payload.cl_name,
            yes_to_all=False,
        )
    )
    tags = [tag for tag in deferred.payload.tags or [] if tag != "done"] or None
    return replace(
        deferred.payload,
        success=False,
        notes=[
            *deferred.payload.notes,
            "Epic launch outcome is unknown.",
            f"Resume with: {shlex.join(argv)}",
        ],
        action="JumpToAgent",
        action_data=settlement_notification_action_data(
            deferred.artifacts_dir,
            cl_name=deferred.payload.cl_name,
            action_data=deferred.payload.action_data,
        ),
        tags=tags,
    )
