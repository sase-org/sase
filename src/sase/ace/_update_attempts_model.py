"""Pure model for the durable update-attempt journal.

This module holds the journal's data types, bounds, reducers, and JSON codec.
Everything here is pure: reducers take ``now`` explicitly and never touch the
clock, the filesystem, or locks. The blocking I/O facade lives in
:mod:`sase.ace.update_attempts`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import uuid4

SCHEMA_VERSION = 1
MAX_IN_FLIGHT_ATTEMPTS = 16
MAX_ERROR_CHARS = 300
MAX_OUTPUT_LINES = 200
MAX_OUTPUT_BYTES = 16 * 1024

INTERRUPTED_ERROR = (
    "ACE exited before this update finished; the install may be incomplete."
)

UpdateStage = Literal["plan", "apply"]


@dataclass(frozen=True, slots=True)
class UpdateAttemptOwner:
    """Durable identity of the ACE process that owns an in-flight attempt."""

    pid: int
    identity: str
    instance_id: str


@dataclass(frozen=True, slots=True)
class UpdateAttempt:
    """One update-lane attempt, created on the UI thread before submission."""

    attempt_id: str
    label: str
    proc_type: str
    stage: UpdateStage
    started_at: float


@dataclass(frozen=True, slots=True)
class _InFlightUpdate:
    """An attempt marker persisted while its worker is running."""

    attempt_id: str
    label: str
    proc_type: str
    stage: UpdateStage
    started_at: float
    owner: UpdateAttemptOwner


@dataclass(frozen=True, slots=True)
class UpdateFailure:
    """The most recent failed or interrupted attempt, fed to the UI."""

    attempt_id: str
    label: str
    proc_type: str
    stage: UpdateStage
    started_at: float
    finished_at: float
    error: str
    output_tail: str
    interrupted: bool = False


@dataclass(frozen=True, slots=True)
class UpdateAttemptsRecord:
    """Full durable journal state, including the monotonic revision."""

    revision: int = 0
    last_success_started_at: float = 0.0
    in_flight: tuple[_InFlightUpdate, ...] = ()
    failure: UpdateFailure | None = None


@dataclass(frozen=True, slots=True)
class UpdateAttemptsView:
    """Revisioned failure snapshot; the only thing the UI consumes."""

    revision: int = 0
    failure: UpdateFailure | None = None


def new_update_attempt(
    *,
    label: str,
    proc_type: str,
    started_at: float | None = None,
) -> UpdateAttempt:
    """Create an attempt; planning (``update-preview``) maps to stage ``plan``."""
    stage: UpdateStage = "plan" if proc_type == "update-preview" else "apply"
    return UpdateAttempt(
        attempt_id=uuid4().hex,
        label=label,
        proc_type=proc_type,
        stage=stage,
        started_at=time.time() if started_at is None else float(started_at),
    )


def empty_attempts_record() -> UpdateAttemptsRecord:
    """Return the journal state used when no file exists yet."""
    return UpdateAttemptsRecord()


def attempts_view(record: UpdateAttemptsRecord) -> UpdateAttemptsView:
    """Project the UI-facing snapshot out of a full record."""
    return UpdateAttemptsView(revision=record.revision, failure=record.failure)


def _bound_error_text(error: str | None) -> str:
    """Return the first non-empty error line, capped with an ellipsis."""
    for line in (error or "").splitlines():
        stripped = line.strip()
        if stripped:
            if len(stripped) <= MAX_ERROR_CHARS:
                return stripped
            return stripped[: MAX_ERROR_CHARS - 1].rstrip() + "…"
    return ""


def _bound_output_tail(output: str | None) -> str:
    """Return the last lines of output, capped and trimmed on a line boundary."""
    lines = (output or "").splitlines()[-MAX_OUTPUT_LINES:]
    while len("\n".join(lines).encode("utf-8")) > MAX_OUTPUT_BYTES and len(lines) > 1:
        del lines[0]
    text = "\n".join(lines)
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return text
    return encoded[-MAX_OUTPUT_BYTES:].decode("utf-8", errors="ignore")


def reduce_start(
    record: UpdateAttemptsRecord,
    attempt: UpdateAttempt,
    owner: UpdateAttemptOwner,
    *,
    now: float,
) -> tuple[UpdateAttemptsRecord, bool]:
    """Add or replace the in-flight marker for an attempt id.

    ``now`` is accepted for reducer uniformity and is otherwise unused: the
    marker carries the attempt's own ``started_at``.
    """
    _ = now
    marker = _InFlightUpdate(
        attempt_id=attempt.attempt_id,
        label=attempt.label,
        proc_type=attempt.proc_type,
        stage=attempt.stage,
        started_at=attempt.started_at,
        owner=owner,
    )
    kept = [m for m in record.in_flight if m.attempt_id != attempt.attempt_id]
    kept.append(marker)
    del kept[: max(0, len(kept) - MAX_IN_FLIGHT_ATTEMPTS)]
    in_flight = tuple(kept)
    if in_flight == record.in_flight:
        return record, False
    return replace(record, in_flight=in_flight, revision=record.revision + 1), True


def reduce_settle(
    record: UpdateAttemptsRecord,
    attempt: UpdateAttempt,
    *,
    success: bool,
    error: str | None,
    output: str | None,
    now: float,
) -> tuple[UpdateAttemptsRecord, bool]:
    """Remove the marker and fold a success or failure into the record.

    Self-contained: works even if the start marker was never written. On
    failure the newest finish wins; on success the recorded failure clears
    only when this attempt started at or after the failure finished.
    """
    in_flight = tuple(m for m in record.in_flight if m.attempt_id != attempt.attempt_id)
    last_success_started_at = record.last_success_started_at
    failure = record.failure
    if success:
        if attempt.started_at > last_success_started_at:
            last_success_started_at = attempt.started_at
        if failure is not None and attempt.started_at >= failure.finished_at:
            failure = None
    else:
        candidate = UpdateFailure(
            attempt_id=attempt.attempt_id,
            label=attempt.label,
            proc_type=attempt.proc_type,
            stage=attempt.stage,
            started_at=attempt.started_at,
            finished_at=now,
            error=_bound_error_text(error),
            output_tail=_bound_output_tail(output),
            interrupted=False,
        )
        if failure is None or now >= failure.finished_at:
            failure = candidate
    updated = replace(
        record,
        in_flight=in_flight,
        last_success_started_at=last_success_started_at,
        failure=failure,
    )
    if updated == record:
        return record, False
    return replace(updated, revision=record.revision + 1), True


def reduce_dismiss(
    record: UpdateAttemptsRecord,
    attempt_id: str,
    *,
    now: float,
) -> tuple[UpdateAttemptsRecord, bool]:
    """Clear the failure only when the attempt id matches.

    ``now`` is accepted for reducer uniformity and is otherwise unused.
    """
    _ = now
    if record.failure is None or record.failure.attempt_id != attempt_id:
        return record, False
    return replace(record, failure=None, revision=record.revision + 1), True


def reduce_reconcile(
    record: UpdateAttemptsRecord,
    is_alive: Callable[[UpdateAttemptOwner], bool],
    *,
    now: float,
) -> tuple[UpdateAttemptsRecord, bool]:
    """Drop markers whose owner died; the newest becomes an interrupted failure.

    The interrupted failure is recorded only when its attempt started after
    the last recorded success, so a later-started success suppresses it.
    """
    live: list[_InFlightUpdate] = []
    dead: list[_InFlightUpdate] = []
    for marker in record.in_flight:
        (live if is_alive(marker.owner) else dead).append(marker)
    failure = record.failure
    if dead:
        newest = max(dead, key=lambda m: (m.started_at, m.attempt_id))
        if newest.started_at > record.last_success_started_at:
            candidate = UpdateFailure(
                attempt_id=newest.attempt_id,
                label=newest.label,
                proc_type=newest.proc_type,
                stage=newest.stage,
                started_at=newest.started_at,
                finished_at=now,
                error=INTERRUPTED_ERROR,
                output_tail="",
                interrupted=True,
            )
            if failure is None or now >= failure.finished_at:
                failure = candidate
    updated = replace(record, in_flight=tuple(live), failure=failure)
    if updated == record:
        return record, False
    return replace(updated, revision=record.revision + 1), True


def attempts_record_to_json(record: UpdateAttemptsRecord) -> dict[str, Any]:
    """Serialize a record to its JSON document form."""
    return {
        "schema": SCHEMA_VERSION,
        "revision": record.revision,
        "last_success_started_at": record.last_success_started_at,
        "in_flight": [_in_flight_to_json(marker) for marker in record.in_flight],
        "failure": _failure_to_json(record.failure),
    }


def is_foreign_attempts_schema(payload: object) -> bool:
    """Return whether a decoded document carries a schema other than 1."""
    return (
        isinstance(payload, dict)
        and "schema" in payload
        and not (type(payload["schema"]) is int and payload["schema"] == SCHEMA_VERSION)
    )


def attempts_record_from_json(payload: object) -> UpdateAttemptsRecord | None:
    """Decode a record, returning ``None`` for malformed documents.

    Unknown keys are ignored at every level. A non-1 ``schema`` also yields
    ``None``; callers must check :func:`is_foreign_attempts_schema` first so a
    newer writer's file is never clobbered.
    """
    if not isinstance(payload, dict):
        return None
    schema = payload.get("schema")
    if type(schema) is not int or schema != SCHEMA_VERSION:
        return None
    revision = payload.get("revision")
    if type(revision) is not int or revision < 0:
        return None
    last_success = _float_value(payload.get("last_success_started_at"))
    if last_success is None:
        return None
    in_flight_payload = payload.get("in_flight")
    if not isinstance(in_flight_payload, list):
        return None
    in_flight: list[_InFlightUpdate] = []
    for item in in_flight_payload:
        marker = _in_flight_from_json(item)
        if marker is None:
            return None
        in_flight.append(marker)
    failure: UpdateFailure | None = None
    if payload.get("failure") is not None:
        failure = _failure_from_json(payload.get("failure"))
        if failure is None:
            return None
    return UpdateAttemptsRecord(
        revision=revision,
        last_success_started_at=last_success,
        in_flight=tuple(in_flight),
        failure=failure,
    )


def _in_flight_to_json(marker: _InFlightUpdate) -> dict[str, Any]:
    return {
        "attempt_id": marker.attempt_id,
        "label": marker.label,
        "proc_type": marker.proc_type,
        "stage": marker.stage,
        "started_at": marker.started_at,
        "owner": {
            "pid": marker.owner.pid,
            "identity": marker.owner.identity,
            "instance_id": marker.owner.instance_id,
        },
    }


def _failure_to_json(failure: UpdateFailure | None) -> dict[str, Any] | None:
    if failure is None:
        return None
    return {
        "attempt_id": failure.attempt_id,
        "label": failure.label,
        "proc_type": failure.proc_type,
        "stage": failure.stage,
        "started_at": failure.started_at,
        "finished_at": failure.finished_at,
        "error": failure.error,
        "output_tail": failure.output_tail,
        "interrupted": failure.interrupted,
    }


def _in_flight_from_json(payload: object) -> _InFlightUpdate | None:
    if not isinstance(payload, dict):
        return None
    attempt = _attempt_fields_from_json(payload)
    if attempt is None:
        return None
    owner_payload = payload.get("owner")
    if not isinstance(owner_payload, dict):
        return None
    pid = owner_payload.get("pid")
    identity = owner_payload.get("identity")
    instance_id = owner_payload.get("instance_id")
    if (
        type(pid) is not int
        or not isinstance(identity, str)
        or not isinstance(instance_id, str)
    ):
        return None
    attempt_id, label, proc_type, stage, started_at = attempt
    return _InFlightUpdate(
        attempt_id=attempt_id,
        label=label,
        proc_type=proc_type,
        stage=stage,
        started_at=started_at,
        owner=UpdateAttemptOwner(pid=pid, identity=identity, instance_id=instance_id),
    )


def _failure_from_json(payload: object) -> UpdateFailure | None:
    if not isinstance(payload, dict):
        return None
    attempt = _attempt_fields_from_json(payload)
    if attempt is None:
        return None
    finished_at = _float_value(payload.get("finished_at"))
    error = payload.get("error")
    output_tail = payload.get("output_tail")
    interrupted = payload.get("interrupted")
    if (
        finished_at is None
        or not isinstance(error, str)
        or not isinstance(output_tail, str)
        or not isinstance(interrupted, bool)
    ):
        return None
    attempt_id, label, proc_type, stage, started_at = attempt
    return UpdateFailure(
        attempt_id=attempt_id,
        label=label,
        proc_type=proc_type,
        stage=stage,
        started_at=started_at,
        finished_at=finished_at,
        error=error,
        output_tail=output_tail,
        interrupted=interrupted,
    )


def _attempt_fields_from_json(
    payload: dict[str, Any],
) -> tuple[str, str, str, UpdateStage, float] | None:
    attempt_id = payload.get("attempt_id")
    label = payload.get("label")
    proc_type = payload.get("proc_type")
    stage = payload.get("stage")
    started_at = _float_value(payload.get("started_at"))
    if (
        not isinstance(attempt_id, str)
        or not isinstance(label, str)
        or not isinstance(proc_type, str)
        or stage not in ("plan", "apply")
        or started_at is None
    ):
        return None
    stage_value: UpdateStage = stage  # type: ignore[assignment]
    return (attempt_id, label, proc_type, stage_value, started_at)


def _float_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


__all__ = [
    "INTERRUPTED_ERROR",
    "MAX_ERROR_CHARS",
    "MAX_IN_FLIGHT_ATTEMPTS",
    "MAX_OUTPUT_BYTES",
    "MAX_OUTPUT_LINES",
    "SCHEMA_VERSION",
    "_InFlightUpdate",
    "UpdateAttempt",
    "UpdateAttemptOwner",
    "UpdateAttemptsRecord",
    "UpdateAttemptsView",
    "UpdateFailure",
    "UpdateStage",
    "attempts_record_from_json",
    "attempts_record_to_json",
    "attempts_view",
    "_bound_error_text",
    "_bound_output_tail",
    "empty_attempts_record",
    "is_foreign_attempts_schema",
    "new_update_attempt",
    "reduce_dismiss",
    "reduce_reconcile",
    "reduce_settle",
    "reduce_start",
]
