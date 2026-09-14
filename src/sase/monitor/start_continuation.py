"""Continuation-record helpers used while starting a monitor."""

from __future__ import annotations

import os
from typing import Any

from . import store
from .models import MonitorError, MonitorRecord
from .request import StartMonitorRequest
from .start_lane import LaneStart, StartIdentity
from .start_metadata import read_start_meta


def reject_versioned_start_controls_when_disabled(
    request: StartMonitorRequest,
) -> None:
    if not (
        request.checkpoint_ref
        or request.checkpoint_document
        or request.completion_ref
        or request.outcome_policy
        or request.policy_digest
        or request.profile
    ):
        return
    raise MonitorError(
        "checkpoint, outcome-policy, profile, and host-completion monitor "
        "controls require feature flag monitor_continuation_records"
    )


def persist_monitor_start_intent_after_ack(
    request: StartMonitorRequest,
    record: MonitorRecord,
    *,
    lane_start: LaneStart,
    request_fingerprint: str,
    starter_artifacts_dir: str | None,
    records_enabled: bool,
) -> None:
    if not records_enabled:
        return
    parent_node_ids = list(request.parent_node_ids) or _continuation_parent_node_ids(
        lane_start.member_meta
    )
    from sase.continuation_capture import persist_monitor_start_intent_best_effort

    persist_monitor_start_intent_best_effort(
        artifacts_dir=record.artifacts_dir,
        monitor_id=record.monitor_id,
        member_agent_name=record.member_agent_name,
        project_name=record.project_name,
        command=record.command,
        cwd=record.cwd,
        next_action=record.next_action,
        next_model=record.next_model,
        next_output=record.next_output,
        request_fingerprint=request_fingerprint,
        parent_node_ids=parent_node_ids,
        starter_agent=lane_start.starter_agent,
        checkpoint_ref=request.checkpoint_ref,
        checkpoint_document=request.checkpoint_document,
        starter_artifacts_dir=starter_artifacts_dir,
    )


def inherited_route(
    starter_artifacts_dir: str | None,
) -> tuple[str | None, str | None]:
    """Return the selected parent's model and effort, if they can be read."""

    if not starter_artifacts_dir:
        return None, None
    try:
        from sase.monitor.outcome_policy import inherited_route_from_meta

        return inherited_route_from_meta(read_start_meta(starter_artifacts_dir))
    except (OSError, MonitorError):
        return None, None


def peek_continuation_parents(
    request: StartMonitorRequest,
    identity: StartIdentity,
) -> tuple[list[str], str | None, str | None]:
    """Resolve exact parent identities without mutating the selected lane."""

    try:
        lane_ctx = (
            identity.context
            if identity.context is not None
            else store.resolve_lane(request.project_name, identity.target)
        )
    except Exception:
        return [], None, None
    artifact_dir = lane_ctx.record.artifact_dir
    starter_run_id = os.path.basename(str(artifact_dir).rstrip("/")) or None
    try:
        meta = read_start_meta(artifact_dir)
    except (OSError, MonitorError):
        return [], starter_run_id, artifact_dir
    return _continuation_parent_node_ids(meta), starter_run_id, artifact_dir


def _continuation_parent_node_ids(meta: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    raw_node_id = meta.get("continuation_node_id")
    if isinstance(raw_node_id, str) and raw_node_id:
        ids.append(raw_node_id)
    raw_parent_ids = meta.get("continuation_parent_node_ids")
    if isinstance(raw_parent_ids, list):
        ids.extend(item for item in raw_parent_ids if isinstance(item, str) and item)
    seen: set[str] = set()
    result: list[str] = []
    for node_id in ids:
        if node_id in seen:
            continue
        seen.add(node_id)
        result.append(node_id)
    return result


__all__ = [
    "inherited_route",
    "peek_continuation_parents",
    "persist_monitor_start_intent_after_ack",
    "reject_versioned_start_controls_when_disabled",
]
