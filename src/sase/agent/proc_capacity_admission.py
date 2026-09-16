"""Queue-capacity admission for stand-alone typed `%proc` units."""

from __future__ import annotations

import fcntl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_launch_wire import LaunchUnitWire, ProcUnitWire
from sase.core.runner_slots import (
    DEFAULT_WAIT_PRIORITY,
    runner_capacity_snapshot,
    runner_slot_candidate_record,
)


@dataclass(frozen=True)
class ProcCapacityAdmission:
    """Authoritative capacity decision for one proc launch candidate."""

    admitted: bool
    invalid: bool = False
    message: str | None = None
    blockers: tuple[dict[str, Any], ...] = ()
    decision: dict[str, Any] | None = None


def proc_requires_capacity_admission(unit: LaunchUnitWire) -> bool:
    payload = unit.payload
    return isinstance(payload, ProcUnitWire) and payload.has_authored_queue_fields()


def evaluate_proc_capacity_admission(
    unit: LaunchUnitWire,
    *,
    admission_dir: Path,
    request_id: str,
    selected_project: str | None,
    requested_at: str,
    eligible_since: str | None,
    now: datetime,
) -> ProcCapacityAdmission:
    """Evaluate proc queue intent through the shared runner-capacity engine."""

    payload = unit.payload
    if not isinstance(payload, ProcUnitWire):
        return ProcCapacityAdmission(False, invalid=True, message="not_a_proc_unit")
    if not payload.has_authored_queue_fields():
        return ProcCapacityAdmission(True)

    from sase.axe.run_agent_wait_slot_candidate import (
        decision_blocker_message,
        require_candidate_decision,
    )
    from sase.axe.run_agent_wait_slots import (
        record_liveness_probe,
        runner_slot_lock_path,
        scan_runner_slot_records,
    )
    from sase.config.core import (
        get_max_running_agents,
        get_runner_slot_deference_max_seconds,
        get_runner_slot_deference_seconds_per_step,
    )

    artifact_dir = str(admission_dir / "proc_capacity" / unit.logical_id)
    priority = (
        payload.wait_priority
        if type(payload.wait_priority) is int and payload.wait_priority >= 0
        else DEFAULT_WAIT_PRIORITY
    )
    queue_weight = (
        float(payload.queue_weight) if payload.queue_weight is not None else 0.0
    )
    candidate = runner_slot_candidate_record(
        artifacts_dir=artifact_dir,
        timestamp=_candidate_timestamp(request_id, unit.logical_id),
        slot_requested_at=requested_at,
        queue_capacity=payload.queue_capacity,
        queue_capacity_explicit=payload.queue_capacity is not None,
        wait_priority=priority,
        queue_weight=queue_weight,
        queue_weight_explicit=payload.queue_weight_explicit or queue_weight == 0.0,
        eligible_since=eligible_since,
    )
    if selected_project:
        candidate["project_name"] = selected_project

    lock_path = runner_slot_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            try:
                effective_limit = float(get_max_running_agents())
            except Exception as exc:  # noqa: BLE001 - admission fails closed.
                return ProcCapacityAdmission(
                    False,
                    invalid=True,
                    message=f"runner capacity limit unavailable: {exc}",
                )
            records = scan_runner_slot_records()
            snapshot = runner_capacity_snapshot(
                records,
                record_liveness_probe(),
                effective_limit=effective_limit,
                now=now.isoformat(),
                deference_seconds_per_step=(
                    get_runner_slot_deference_seconds_per_step()
                    if priority > DEFAULT_WAIT_PRIORITY
                    else 0
                ),
                deference_max_seconds=(
                    get_runner_slot_deference_max_seconds()
                    if priority > DEFAULT_WAIT_PRIORITY
                    else 0
                ),
                candidate=candidate,
            )
            try:
                decision = require_candidate_decision(snapshot, artifact_dir)
            except Exception as exc:  # noqa: BLE001 - malformed is not admissible.
                return ProcCapacityAdmission(
                    False,
                    invalid=True,
                    message=str(exc),
                )
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    blockers = _blockers(decision)
    if decision["decision"] in {"acquire_capacity", "reuse_existing_claim"}:
        return ProcCapacityAdmission(True, decision=decision)
    if decision["decision"] == "invalid":
        return ProcCapacityAdmission(
            False,
            invalid=True,
            message=decision_blocker_message(decision),
            blockers=blockers,
            decision=decision,
        )
    return ProcCapacityAdmission(
        False,
        message=decision_blocker_message(decision),
        blockers=blockers,
        decision=decision,
    )


def _blockers(decision: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    raw = decision.get("blockers")
    if not isinstance(raw, list):
        return ()
    return tuple(dict(item) for item in raw if isinstance(item, Mapping))


def _candidate_timestamp(request_id: str, logical_id: str) -> str:
    prefix = request_id.strip() or "request"
    return f"proc-{prefix}-{logical_id}"


def iso_from_unix(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat()
