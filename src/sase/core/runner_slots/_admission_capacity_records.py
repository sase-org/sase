"""Projection of wire records into the Rust capacity-snapshot request shape."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire

from ._admission_types import RecordLiveness, finite_positive_float
from ._queue_weight import valid_queue_weight


def _is_explicit_zero_weight(value: object) -> bool:
    """Return whether *value* is a real (non-bool) numeric zero."""
    return valid_queue_weight(value, explicit=True) == 0.0


def _record_queue_weight(
    record: AgentArtifactRecordWire,
) -> tuple[float | None, bool, bool]:
    """Return effective scan weight fields, with waiting markers overriding meta."""
    waiting = record.waiting
    if waiting is not None:
        if waiting.queue_weight_invalid:
            return None, waiting.queue_weight_explicit, True
        if waiting.queue_weight_explicit and _is_explicit_zero_weight(
            waiting.queue_weight
        ):
            return 0.0, True, False
        weight = finite_positive_float(waiting.queue_weight)
        if weight is not None:
            return weight, waiting.queue_weight_explicit, False
        if waiting.queue_weight is not None:
            return None, waiting.queue_weight_explicit, True

    meta = record.agent_meta
    if meta is None:
        return None, False, False
    if meta.queue_weight_invalid:
        return None, meta.queue_weight_explicit, True
    if meta.queue_weight_explicit and _is_explicit_zero_weight(meta.queue_weight):
        return 0.0, True, False
    weight = finite_positive_float(meta.queue_weight)
    if weight is not None:
        return weight, meta.queue_weight_explicit, False
    if meta.queue_weight is not None:
        return None, meta.queue_weight_explicit, True
    return None, False, False


def _record_wait_priority(record: AgentArtifactRecordWire) -> int | None:
    waiting = record.waiting
    if (
        waiting is not None
        and type(waiting.wait_priority) is int
        and waiting.wait_priority >= 0
    ):
        return waiting.wait_priority
    meta = record.agent_meta
    if meta is None or type(meta.wait_priority) is not int or meta.wait_priority < 0:
        return None
    return meta.wait_priority


def _record_queue_capacity(record: AgentArtifactRecordWire) -> int | None:
    waiting = record.waiting
    if (
        waiting is not None
        and type(waiting.queue_capacity) is int
        and waiting.queue_capacity >= 0
    ):
        return waiting.queue_capacity
    if (
        waiting is not None
        and type(waiting.wait_runners) is int
        and waiting.wait_runners >= 0
    ):
        return waiting.wait_runners
    meta = record.agent_meta
    if (
        meta is not None
        and type(meta.queue_capacity) is int
        and meta.queue_capacity >= 0
    ):
        return meta.queue_capacity
    if meta is not None and type(meta.wait_runners) is int and meta.wait_runners >= 0:
        return meta.wait_runners
    return None


def _record_queue_capacity_multiplier(record: AgentArtifactRecordWire) -> float | None:
    """Return the marker-preferred multiplier unless an integer shares its source."""
    from sase.xprompt.queue_directive import resolve_authored_queue_capacity_multiplier

    waiting = record.waiting
    if waiting is not None and (
        waiting.queue_capacity is not None
        or waiting.wait_runners is not None
        or waiting.queue_capacity_multiplier is not None
    ):
        source: dict[str, Any] = {}
        if waiting.queue_capacity is not None:
            source["queue_capacity"] = waiting.queue_capacity
        elif waiting.wait_runners is not None:
            source["wait_runners"] = waiting.wait_runners
        if waiting.queue_capacity_multiplier is not None:
            source["queue_capacity_multiplier"] = waiting.queue_capacity_multiplier
        return resolve_authored_queue_capacity_multiplier(source)
    meta = record.agent_meta
    if meta is None:
        return None
    source = {}
    if meta.queue_capacity is not None:
        source["queue_capacity"] = meta.queue_capacity
    elif meta.wait_runners is not None:
        source["wait_runners"] = meta.wait_runners
    if meta.queue_capacity_multiplier is not None:
        source["queue_capacity_multiplier"] = meta.queue_capacity_multiplier
    return resolve_authored_queue_capacity_multiplier(source)


def with_queue_capacity_alias(record: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(record)
    if "queue_capacity" not in item and "wait_runners" in item:
        item["queue_capacity"] = item["wait_runners"]
    if "queue_capacity_explicit" not in item and "wait_runners_explicit" in item:
        item["queue_capacity_explicit"] = item["wait_runners_explicit"]
    if "wait_runners" not in item and "queue_capacity" in item:
        item["wait_runners"] = item["queue_capacity"]
    if "wait_runners_explicit" not in item and "queue_capacity_explicit" in item:
        item["wait_runners_explicit"] = item["queue_capacity_explicit"]
    return item


def _record_pid(record: AgentArtifactRecordWire) -> int | None:
    meta = record.agent_meta
    if meta is not None and meta.pid is not None:
        return meta.pid
    running = record.running
    return None if running is None else running.pid


def capacity_session_keys_for_core(
    *,
    agent_session: str | None,
    agent_session_role: str | None,
    agent_session_parallel: bool,
    shell_kind: str | None = None,
    shell_id: str | None = None,
    shell_state: str | None = None,
) -> dict[str, Any]:
    """Runner-slot session projection for the Rust capacity engine.

    Core serializes ``agent_session_parallel`` and still accepts the legacy
    parallel-marker spelling on read.
    """
    return {
        "agent_session": agent_session,
        "agent_session_role": agent_session_role,
        "agent_session_parallel": agent_session_parallel,
        "agent_session_shell_kind": shell_kind,
        "agent_session_shell_id": shell_id,
        "agent_session_shell_state": shell_state,
    }


def capacity_record_from_scan(
    record: AgentArtifactRecordWire,
    is_live: RecordLiveness,
) -> dict[str, Any]:
    # Deferred: sase.core.agent_hold_facade sits downstream of sase.agent's
    # own init chain (runner_slots -> here), so a module-level import here
    # would make this module a circular-import root whenever agent_hold
    # code is the first thing a process touches.
    from sase.core.agent_hold_facade import candidate_created_at_from_timestamp

    from sase.core.agent_hold_identity import attach_hold_identity_scratch_from_meta

    meta = record.agent_meta
    state = record.workflow_state
    waiting = record.waiting
    shell = None if meta is None else meta.agent_session_shell
    queue_weight, queue_weight_explicit, queue_weight_invalid = _record_queue_weight(
        record
    )
    payload = with_queue_capacity_alias(
        {
            "artifact_dir": record.artifact_dir,
            "project_name": record.project_name,
            "workflow_dir_name": record.workflow_dir_name,
            "timestamp": record.timestamp,
            "agent_name": None if meta is None else meta.name,
            "workflow": (
                None
                if meta is None
                else (
                    meta.workflow_name
                    or (
                        record.workflow_state.workflow_name
                        if record.workflow_state is not None
                        else None
                    )
                )
            ),
            "clan": None if meta is None else meta.agent_clan,
            "tribe": None if meta is None else (meta.tribe or meta.clan_tribe),
            "tribes": [],
            "created_at": candidate_created_at_from_timestamp(record.timestamp),
            "has_agent_meta": meta is not None,
            "has_done_marker": record.has_done_marker,
            "appears_as_agent": True if state is None else state.appears_as_agent,
            "live": is_live(record),
            "pending_question": record.pending_question is not None,
            "pid": _record_pid(record),
            "run_started_at": None if meta is None else meta.run_started_at,
            "runner_claim_owner_key": (
                None if meta is None else meta.runner_claim_owner_key
            ),
            "parent_timestamp": None if meta is None else meta.parent_timestamp,
            **capacity_session_keys_for_core(
                agent_session=None if meta is None else meta.agent_session,
                agent_session_role=None if meta is None else meta.agent_session_role,
                agent_session_parallel=False
                if meta is None
                else meta.agent_session_parallel,
                shell_kind=None if shell is None else shell.kind,
                shell_id=None if shell is None else shell.id,
                shell_state=None if shell is None else shell.state,
            ),
            "queue_weight": queue_weight,
            "queue_weight_explicit": queue_weight_explicit,
            "queue_weight_invalid": queue_weight_invalid,
            "slot_requested_at": None if waiting is None else waiting.slot_requested_at,
            "queue_capacity": _record_queue_capacity(record),
            "queue_capacity_multiplier": _record_queue_capacity_multiplier(record),
            "queue_capacity_explicit": (
                waiting.queue_capacity_explicit or waiting.wait_runners_explicit
                if waiting is not None
                else (
                    meta.queue_capacity_explicit or meta.wait_runners_explicit
                    if meta is not None
                    else False
                )
            ),
            "wait_priority": _record_wait_priority(record),
            "eligible_since": None if waiting is None else waiting.eligible_since,
        }
    )
    attach_hold_identity_scratch_from_meta(
        payload,
        cl_name=None if meta is None else meta.cl_name,
        clan_generation=None if meta is None else meta.agent_clan_generation,
        parent_timestamp=None if meta is None else meta.parent_timestamp,
        timestamp=record.timestamp,
        meta_tribe=None if meta is None else meta.tribe,
        clan_tribe=None if meta is None else meta.clan_tribe,
        clan=None if meta is None else meta.agent_clan,
    )
    return payload


def _project_name_from_artifact_dir(artifacts_dir: str) -> str:
    from sase.core.agent_artifact_paths import parse_agent_artifact_path

    try:
        parsed = parse_agent_artifact_path(artifacts_dir)
    except (OSError, RuntimeError, ValueError):
        parsed = None
    if parsed is not None:
        return parsed.project_name
    path = Path(artifacts_dir)
    try:
        return path.parents[2].name
    except IndexError:
        return ""


def _synthetic_capacity_record(
    *,
    artifacts_dir: str,
    timestamp: str,
    slot_requested_at: str,
    queue_capacity: int | None,
    queue_capacity_explicit: bool,
    queue_capacity_multiplier: float | None,
    wait_priority: int,
    queue_weight: float,
    queue_weight_explicit: bool,
    eligible_since: str | None,
    agent_name: str | None = None,
    workflow: str | None = None,
    clan: str | None = None,
    tribe: str | None = None,
    agent_session: str | None = None,
    created_at: float | None = None,
    cl_name: str | None = None,
    clan_generation: str | None = None,
    clan_tribe: str | None = None,
    parent_timestamp: str | None = None,
) -> dict[str, Any]:
    from sase.core.agent_hold_identity import attach_hold_identity_scratch_from_meta

    payload = with_queue_capacity_alias(
        {
            "artifact_dir": artifacts_dir,
            "project_name": _project_name_from_artifact_dir(artifacts_dir),
            "workflow_dir_name": "ace-run",
            "timestamp": timestamp,
            "agent_name": agent_name,
            "workflow": workflow,
            "clan": clan,
            "tribe": tribe,
            "tribes": [tribe] if tribe else [],
            "created_at": created_at,
            "has_agent_meta": True,
            "has_done_marker": False,
            "appears_as_agent": True,
            "live": True,
            "pending_question": False,
            "pid": None,
            "run_started_at": None,
            "runner_claim_owner_key": None,
            "parent_timestamp": parent_timestamp,
            **capacity_session_keys_for_core(
                agent_session=agent_session,
                agent_session_role=None,
                agent_session_parallel=False,
                shell_kind=None,
                shell_id=None,
                shell_state=None,
            ),
            "queue_weight": queue_weight,
            "queue_weight_explicit": queue_weight_explicit,
            "queue_weight_invalid": False,
            "slot_requested_at": slot_requested_at,
            "queue_capacity": queue_capacity,
            "queue_capacity_multiplier": queue_capacity_multiplier,
            "queue_capacity_explicit": queue_capacity_explicit,
            "wait_priority": wait_priority,
            "eligible_since": eligible_since,
        }
    )
    attach_hold_identity_scratch_from_meta(
        payload,
        cl_name=cl_name,
        clan_generation=clan_generation,
        parent_timestamp=parent_timestamp,
        timestamp=timestamp,
        meta_tribe=tribe,
        clan_tribe=clan_tribe,
        clan=clan,
    )
    return payload


def runner_slot_candidate_record(
    *,
    artifacts_dir: str,
    timestamp: str,
    slot_requested_at: str,
    queue_capacity: int | None = None,
    queue_capacity_explicit: bool = False,
    queue_capacity_multiplier: float | None = None,
    wait_runners: int | None = None,
    wait_runners_explicit: bool = False,
    wait_priority: int,
    queue_weight: float,
    queue_weight_explicit: bool,
    eligible_since: str | None,
    agent_name: str | None = None,
    workflow: str | None = None,
    clan: str | None = None,
    tribe: str | None = None,
    agent_session: str | None = None,
    created_at: float | None = None,
    cl_name: str | None = None,
    clan_generation: str | None = None,
    clan_tribe: str | None = None,
    parent_timestamp: str | None = None,
) -> dict[str, Any]:
    """Build the synthetic candidate sent as the Rust request's own field."""
    if queue_capacity is None and wait_runners is not None:
        queue_capacity = wait_runners
        queue_capacity_explicit = wait_runners_explicit
    return _synthetic_capacity_record(
        artifacts_dir=artifacts_dir,
        timestamp=timestamp,
        slot_requested_at=slot_requested_at,
        queue_capacity=queue_capacity,
        queue_capacity_explicit=queue_capacity_explicit,
        queue_capacity_multiplier=queue_capacity_multiplier,
        wait_priority=wait_priority,
        queue_weight=queue_weight,
        queue_weight_explicit=queue_weight_explicit,
        eligible_since=eligible_since,
        agent_name=agent_name,
        workflow=workflow,
        clan=clan,
        tribe=tribe,
        agent_session=agent_session,
        created_at=created_at,
        cl_name=cl_name,
        clan_generation=clan_generation,
        clan_tribe=clan_tribe,
        parent_timestamp=parent_timestamp,
    )
