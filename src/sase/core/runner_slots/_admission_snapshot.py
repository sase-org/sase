"""Rust-backed weighted runner-capacity snapshot computation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib import import_module
from typing import Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire

from ._admission_capacity_records import (
    capacity_record_from_scan,
    with_queue_capacity_alias,
)
from ._admission_types import RecordLiveness


def _core_runner_capacity_snapshot(request: dict[str, Any]) -> dict[str, Any]:
    """Return the Rust runner-capacity projection for *request*."""
    try:
        snapshot = import_module("sase_core_rs").runner_capacity_snapshot
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            "sase_core_rs.runner_capacity_snapshot is required for weighted "
            "runner-slot admission; rebuild sase_core_rs from the matching "
            "sase-core checkout."
        ) from exc
    try:
        result = snapshot(request)
    except ValueError as exc:
        if "queue_capacity" not in str(exc):
            raise
        result = snapshot(_legacy_runner_capacity_request(request))
    if not isinstance(result, dict):
        raise RuntimeError("sase_core_rs returned an invalid runner capacity snapshot")
    return result


def _legacy_runner_capacity_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Drop queue-capacity aliases for Rust wheels before the rename."""
    legacy = dict(request)
    legacy["records"] = [
        _drop_queue_capacity_alias(record)
        for record in request.get("records", [])
        if isinstance(record, Mapping)
    ]
    candidate = request.get("candidate")
    legacy["candidate"] = (
        _drop_queue_capacity_alias(candidate)
        if isinstance(candidate, Mapping)
        else None
    )
    return legacy


def _drop_queue_capacity_alias(record: Mapping[str, Any]) -> dict[str, Any]:
    item = with_queue_capacity_alias(record)
    item.pop("queue_capacity", None)
    item.pop("queue_capacity_explicit", None)
    return item


def runner_capacity_snapshot(
    records: Iterable[AgentArtifactRecordWire],
    is_live: RecordLiveness,
    *,
    effective_limit: float,
    now: str | None = None,
    deference_seconds_per_step: int = 0,
    deference_max_seconds: int = 0,
    candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the authoritative weighted runner-capacity snapshot.

    *candidate*, when given, is sent to Rust as the request's dedicated
    ``candidate`` field rather than merged into *records*. Rust excludes any
    scanned record sharing the candidate's ``artifact_dir`` from claim/waiter
    accounting and evaluates the candidate's own decision from the fresh
    values supplied here -- a not-yet-admitted record's stale on-disk
    ``run_started_at``/``queue_weight`` can never grant itself a claim.
    """
    capacity_records = [
        capacity_record_from_scan(record, is_live) for record in records
    ]
    return runner_capacity_snapshot_from_capacity_records(
        capacity_records,
        effective_limit=effective_limit,
        now=now,
        deference_seconds_per_step=deference_seconds_per_step,
        deference_max_seconds=deference_max_seconds,
        candidate=candidate,
    )


def runner_capacity_snapshot_from_capacity_records(
    records: Iterable[Mapping[str, Any]],
    *,
    effective_limit: float,
    now: str | None = None,
    deference_seconds_per_step: int = 0,
    deference_max_seconds: int = 0,
    candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the Rust capacity snapshot for already-projected record dicts."""
    records_list = [with_queue_capacity_alias(record) for record in records]
    candidate_record = (
        None if candidate is None else with_queue_capacity_alias(candidate)
    )
    request = {
        "effective_limit": float(effective_limit),
        "records": records_list,
        "candidate": candidate_record,
        "now": now,
        "deference_seconds_per_step": int(deference_seconds_per_step),
        "deference_max_seconds": int(deference_max_seconds),
    }
    from sase.xprompt.queue_directive import launch_feature_flag_keys

    request["feature_flags"] = launch_feature_flag_keys()
    snapshot = _core_runner_capacity_snapshot(request)
    _restore_waiter_thresholds(
        snapshot,
        [*records_list, *([] if candidate_record is None else [candidate_record])],
    )
    return snapshot


def _restore_waiter_thresholds(
    snapshot: dict[str, Any],
    records: Iterable[Mapping[str, Any]],
) -> None:
    thresholds = {
        str(record.get("artifact_dir") or ""): threshold
        for record in records
        if (threshold := _record_capacity_threshold(record)) is not None
    }
    waiters = snapshot.get("waiters")
    if not isinstance(waiters, list):
        return
    for waiter in waiters:
        if not isinstance(waiter, dict):
            continue
        if "wait_runners" in waiter or "queue_capacity" in waiter:
            continue
        threshold = thresholds.get(str(waiter.get("artifact_dir") or ""))
        if threshold is not None:
            waiter["queue_capacity"] = threshold


def _record_capacity_threshold(record: Mapping[str, Any]) -> int | None:
    value = record.get("queue_capacity")
    if type(value) is not int:
        value = record.get("wait_runners")
    return int(value) if type(value) is int and value >= 0 else None
