"""Per-attempt execution journal for notification gate branches.

An AND branch runs its option commands one at a time, so a failure partway
through leaves earlier commands already executed. Without a record of that,
a second submission silently re-runs work that already happened. The journal
is that record: one append-only line per attempt boundary, written under the
bundle's ``.response.lock`` beside the response it may eventually produce.

Repeatable non-terminal actions append an ``operation_ran`` record here too.
Those carry their own one-off ``attempt_id`` and never open an attempt, so
they never affect retry resolution; they are the audit trail for what a
reviewer ran before deciding.

Raw submitted input is never written here. Input is reduced to a digest,
which is all a retry needs to decide whether a second submission is the same
submission, and which keeps secret-typed fields out of durable audit data.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.notification_gates.durability import (
    canonical_json_bytes,
    fsync_dir,
    sha256_bytes,
)

EXECUTION_JOURNAL_FILENAME = "journal.jsonl"
EXECUTION_JOURNAL_SCHEMA_VERSION = 1

#: Lifecycle events, in the sense design decision 2 (bead ``sase-zr.7.1.1``)
#: uses the term: the ones :func:`current_execution_failure` scans to decide
#: whether a pre-response failure is still current. ``option_completed``,
#: ``option_failed``, ``stage_started``, ``stage_completed``, and
#: ``operation_ran`` are not lifecycle events and never affect that scoping.
_LIFECYCLE_EVENTS = frozenset(
    {
        "attempt_started",
        "attempt_resumed",
        "attempt_failed",
        "attempt_completed",
        "attempt_superseded",
    }
)

#: Stages a post-response failure can be recorded for. Distinct from the pre-
#: response ``command``/``terminal_prepare`` stages an attempt still open
#: under ``.response.lock`` can fail at.
_POST_RESPONSE_STAGES = ("side_effects", "follow_up")


@dataclass(frozen=True)
class IncompleteAttempt:
    """One started attempt that neither finished nor was superseded."""

    attempt_id: str
    request_hash: str
    selected_option_ids: tuple[str, ...]
    input_digests: Mapping[str, str]
    completed_option_ids: tuple[str, ...] = ()
    failed_option_ids: tuple[str, ...] = ()
    results: Mapping[str, Any] = field(default_factory=dict)
    acceptance_id: str | None = None
    failed_stage: str | None = None

    def matches(
        self,
        *,
        request_hash: str,
        selected_option_ids: Sequence[str],
        input_digests: Mapping[str, str],
    ) -> bool:
        """Whether a new submission is a retry of this attempt rather than a new one."""
        return (
            self.request_hash == request_hash
            and self.selected_option_ids == tuple(selected_option_ids)
            and dict(self.input_digests) == dict(input_digests)
        )

    def describe(self) -> str:
        """Render the completed and failed option ids for an operator message."""
        if self.failed_stage == "terminal_prepare" and not self.failed_option_ids:
            return "all options completed; terminal preparation failed"
        completed = ", ".join(self.completed_option_ids) or "none"
        failed = ", ".join(self.failed_option_ids) or "none"
        return f"completed: {completed}; failed: {failed}"


@dataclass(frozen=True)
class ExecutionFailureFacts:
    """One redacted failure outcome read back from the journal.

    Matches the shape recorded by :mod:`sase.notification_gates.failure_outcome`
    for tests and operator diagnostics, and exposed to the Rust gate lifecycle
    policy as ``GateDecisionFailureOutcomeWire``.
    """

    outcome_id: str
    acceptance_id: str | None
    attempt_id: str
    stage: str
    code: str
    message: str
    at_unix: float
    error_record: str

    def to_wire(self) -> dict[str, Any]:
        """Return this failure as a ``GateDecisionFailureOutcomeWire`` JSON dict."""
        wire: dict[str, Any] = {
            "outcome_id": self.outcome_id,
            "attempt_id": failure_outcome_attempt_id(
                self.attempt_id,
                stage=self.stage,
                outcome_id=self.outcome_id,
            ),
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "at_unix": self.at_unix,
            "error_record": self.error_record,
        }
        if self.acceptance_id is not None:
            wire["acceptance_id"] = self.acceptance_id
        return wire

    @classmethod
    def _from_record(cls, record: Mapping[str, Any]) -> ExecutionFailureFacts:
        acceptance_id = record.get("acceptance_id")
        return cls(
            outcome_id=str(record.get("outcome_id") or ""),
            acceptance_id=acceptance_id if isinstance(acceptance_id, str) else None,
            attempt_id=str(record.get("attempt_id") or ""),
            stage=str(record.get("stage") or ""),
            code=str(record.get("code") or ""),
            message=str(record.get("message") or ""),
            at_unix=(
                float(record["at_unix"])
                if isinstance(record.get("at_unix"), (int, float))
                else 0.0
            ),
            error_record=str(record.get("error_record") or ""),
        )


def _receipt_acceptance_id(receipt: Mapping[str, Any] | None) -> str | None:
    if receipt is None:
        return None
    value = receipt.get("acceptance_id")
    return value if isinstance(value, str) else None


def _event_acceptance_id(record: Mapping[str, Any]) -> str | None:
    value = record.get("acceptance_id")
    return value if isinstance(value, str) else None


def value_digest(value: object) -> str:
    """Return the digest recorded in place of a raw journal value."""
    return sha256_bytes(canonical_json_bytes(value))


def failure_outcome_attempt_id(attempt_id: str, *, stage: str, outcome_id: str) -> str:
    """Return a nonempty attempt id for a failure outcome.

    Legacy journal rows used an empty id for failures that happened before an
    execution attempt existed. The Rust gate-decision policy now requires a
    stable failure identity, so those rows project to a synthetic id derived
    from their durable outcome id.
    """
    stripped = attempt_id.strip()
    if stripped:
        return stripped
    normalized_stage = stage.strip() or "unknown"
    normalized_outcome = outcome_id.strip() or "unknown"
    return f"{normalized_stage}-failure-{normalized_outcome}"


def append_journal_event(
    bundle_path: Path,
    *,
    attempt_id: str,
    request_hash: str,
    event: str,
    option_id: str | None = None,
    operation_id: str | None = None,
    input_digest: str | None = None,
    result_digest: str | None = None,
    result: object | None = None,
    selected_option_ids: Sequence[str] | None = None,
    input_digests: Mapping[str, str] | None = None,
    code: str | None = None,
    acceptance_id: str | None = None,
    stage: str | None = None,
    message: str | None = None,
    outcome_id: str | None = None,
    error_record: str | None = None,
    superseded_by_acceptance_id: str | None = None,
    owner_lost: bool | None = None,
    owner_liveness: str | None = None,
) -> None:
    """Append one attempt-boundary record; never raises into the caller's path."""
    record: dict[str, Any] = {
        "schema_version": EXECUTION_JOURNAL_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "request_hash": request_hash,
        "event": event,
        "option_id": option_id,
        "operation_id": operation_id,
        "input_digest": input_digest,
        "result_digest": result_digest,
        "code": code,
        "acceptance_id": acceptance_id,
        "stage": stage,
        "message": message,
        "outcome_id": outcome_id,
        "error_record": error_record,
        "superseded_by_acceptance_id": superseded_by_acceptance_id,
        "owner_lost": owner_lost,
        "owner_liveness": owner_liveness,
        "at_unix": time.time(),
    }
    if selected_option_ids is not None:
        record["selected_option_ids"] = list(selected_option_ids)
    if input_digests is not None:
        record["input_digests"] = dict(input_digests)
    if event == "option_completed":
        record["result"] = result
    path = bundle_path / EXECUTION_JOURNAL_FILENAME
    line = canonical_json_bytes(record) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_dir(path.parent)


def append_journal_event_once(
    bundle_path: Path,
    *,
    event: str,
    acceptance_id: str | None,
    attempt_id: str,
    request_hash: str,
    option_id: str | None = None,
    operation_id: str | None = None,
    input_digest: str | None = None,
    result_digest: str | None = None,
    result: object | None = None,
    selected_option_ids: Sequence[str] | None = None,
    input_digests: Mapping[str, str] | None = None,
    code: str | None = None,
    stage: str | None = None,
    message: str | None = None,
    outcome_id: str | None = None,
    error_record: str | None = None,
    superseded_by_acceptance_id: str | None = None,
    owner_lost: bool | None = None,
    owner_liveness: str | None = None,
) -> bool:
    """Append *event* unless the same transition is already journaled.

    Transition events are keyed by their name plus the receipt acceptance id
    they close out. ``decision_superseded`` also keys on the replacement
    acceptance id so one old receipt cannot be recorded as superseded by two
    different decisions without being visible in the journal.
    """
    for record in read_journal_records(bundle_path):
        if record.get("event") != event:
            continue
        if _event_acceptance_id(record) != acceptance_id:
            continue
        if (
            event == "decision_superseded"
            and record.get("superseded_by_acceptance_id") != superseded_by_acceptance_id
        ):
            continue
        append_needed = False
        break
    else:
        append_needed = True

    if not append_needed:
        return False
    append_journal_event(
        bundle_path,
        attempt_id=attempt_id,
        request_hash=request_hash,
        event=event,
        option_id=option_id,
        operation_id=operation_id,
        input_digest=input_digest,
        result_digest=result_digest,
        result=result,
        selected_option_ids=selected_option_ids,
        input_digests=input_digests,
        code=code,
        acceptance_id=acceptance_id,
        stage=stage,
        message=message,
        outcome_id=outcome_id,
        error_record=error_record,
        superseded_by_acceptance_id=superseded_by_acceptance_id,
        owner_lost=owner_lost,
        owner_liveness=owner_liveness,
    )
    return True


def read_journal_records(bundle_path: Path) -> tuple[dict[str, Any], ...]:
    """Return every well-formed journal record in append order.

    Read-only and best-effort: a missing or unreadable ``journal.jsonl``
    yields an empty tuple rather than raising, matching every other bounded
    diagnostic reader in this package.
    """
    path = bundle_path / EXECUTION_JOURNAL_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return ()
    except OSError:
        return ()
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("attempt_id"), str):
            events.append(value)
    return tuple(events)


def incomplete_attempt(
    bundle_path: Path, *, response_exists: bool
) -> IncompleteAttempt | None:
    """Return the newest started attempt that never reached a terminal event.

    ``attempt_completed`` is terminal only when ``response_exists`` -- a
    legacy bundle journaled it before archive/terminal preparation ran (the
    old stage order), so an early-completed journal with no
    ``response.json`` on disk must still read back as incomplete, or a retry
    would silently re-run commands that already succeeded.
    ``attempt_superseded`` is always terminal.
    """
    events = read_journal_records(bundle_path)
    started: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    terminal: set[str] = set()
    for record in events:
        attempt_id = str(record["attempt_id"])
        event = record.get("event")
        if event == "attempt_started":
            started[attempt_id] = record
            order.append(attempt_id)
        elif event == "attempt_superseded":
            terminal.add(attempt_id)
        elif event == "attempt_completed" and response_exists:
            terminal.add(attempt_id)
    open_ids = [
        attempt_id
        for attempt_id in order
        if attempt_id not in terminal and attempt_id in started
    ]
    if not open_ids:
        return None
    attempt_id = open_ids[-1]
    start = started[attempt_id]
    completed: list[str] = []
    failed: list[str] = []
    results: dict[str, Any] = {}
    failed_stage: str | None = None
    for record in events:
        if str(record["attempt_id"]) != attempt_id:
            continue
        if record.get("event") == "attempt_failed":
            stage = record.get("stage")
            failed_stage = stage if isinstance(stage, str) else None
        option_id = record.get("option_id")
        if not isinstance(option_id, str):
            continue
        if record.get("event") == "option_completed":
            if option_id not in completed:
                completed.append(option_id)
            results[option_id] = record.get("result")
        elif record.get("event") == "option_failed" and option_id not in failed:
            failed.append(option_id)
    raw_selected = start.get("selected_option_ids")
    raw_digests = start.get("input_digests")
    return IncompleteAttempt(
        attempt_id=attempt_id,
        request_hash=str(start.get("request_hash") or ""),
        selected_option_ids=(
            tuple(str(value) for value in raw_selected)
            if isinstance(raw_selected, list)
            else ()
        ),
        input_digests=(
            {str(key): str(value) for key, value in raw_digests.items()}
            if isinstance(raw_digests, dict)
            else {}
        ),
        completed_option_ids=tuple(completed),
        failed_option_ids=tuple(failed),
        results=results,
        acceptance_id=_event_acceptance_id(start),
        failed_stage=failed_stage,
    )


def current_execution_failure(
    bundle_path: Path,
    receipt: Mapping[str, Any] | None,
    *,
    response_exists: bool,
) -> ExecutionFailureFacts | None:
    """Return the current pre-response failure for *receipt*, or ``None``.

    A pre-response failure is current when the last lifecycle event scoped to
    the receipt's acceptance id is ``attempt_failed``. A later
    ``attempt_resumed``, ``attempt_completed``, or ``attempt_superseded``
    clears it. A published response makes any pre-response failure moot.
    """
    if response_exists:
        return None
    acceptance_id = _receipt_acceptance_id(receipt)
    last_lifecycle_event: dict[str, Any] | None = None
    for record in read_journal_records(bundle_path):
        if record.get("event") not in _LIFECYCLE_EVENTS:
            continue
        if _event_acceptance_id(record) != acceptance_id:
            continue
        last_lifecycle_event = record
    if last_lifecycle_event is None:
        return None
    if last_lifecycle_event.get("event") != "attempt_failed":
        return None
    return ExecutionFailureFacts._from_record(last_lifecycle_event)


def current_post_response_failure(
    bundle_path: Path,
    receipt: Mapping[str, Any] | None,
    *,
    stage: str,
) -> ExecutionFailureFacts | None:
    """Return the current failure for one post-response *stage*, or ``None``.

    Design decision 2: a post-response failure is current when no later
    ``stage_completed`` for the same stage and acceptance id exists.
    ``stage`` is one of :data:`_POST_RESPONSE_STAGES` (``side_effects`` or
    ``follow_up``).
    """
    acceptance_id = _receipt_acceptance_id(receipt)
    for record in reversed(read_journal_records(bundle_path)):
        if record.get("stage") != stage:
            continue
        if _event_acceptance_id(record) != acceptance_id:
            continue
        event = record.get("event")
        if event == "stage_completed":
            return None
        if event == "attempt_failed":
            return ExecutionFailureFacts._from_record(record)
    return None


def current_gate_execution_failure(
    bundle_path: Path,
    receipt: Mapping[str, Any] | None,
    *,
    response_exists: bool,
) -> ExecutionFailureFacts | None:
    """Return the current failure outcome visible to gate requesters.

    Pre-response failures block response publication, while post-response
    failures mean the durable response exists but host side effects or shell
    follow-up still need recovery. ``poll_gate`` reports either kind as a
    failed terminal observation until a later retry clears it.
    """
    failure = current_execution_failure(
        bundle_path, receipt, response_exists=response_exists
    )
    if failure is not None:
        return failure
    if not response_exists:
        return None
    for stage in _POST_RESPONSE_STAGES:
        failure = current_post_response_failure(bundle_path, receipt, stage=stage)
        if failure is not None:
            return failure
    return None


def current_execution_stage(
    bundle_path: Path,
    receipt: Mapping[str, Any] | None,
) -> tuple[str, str]:
    """Return ``(stage, attempt_id)`` for a lost owner failure outcome.

    Owner death is recorded against the last started execution stage, defaulting
    to the command stage when no stage marker exists yet.
    """
    acceptance_id = _receipt_acceptance_id(receipt)
    for record in reversed(read_journal_records(bundle_path)):
        if _event_acceptance_id(record) != acceptance_id:
            continue
        if record.get("event") == "stage_started":
            stage = record.get("stage")
            if isinstance(stage, str) and stage:
                return stage, str(record.get("attempt_id") or "")
        if record.get("event") in {"attempt_started", "attempt_resumed"}:
            return "command", str(record.get("attempt_id") or "")
    return "command", ""


def executed_operations(bundle_path: Path) -> tuple[dict[str, Any], ...]:
    """Return every ``operation_ran`` record, oldest first.

    A compact projection for headless consumers (``sase gate wait --json``):
    which repeatable action ran, when, and whether it succeeded. The full
    record -- attempt id, digests -- stays in the journal for ``d``/Gate
    Debug, which renders the raw history instead.
    """
    executed: list[dict[str, Any]] = []
    for record in read_journal_records(bundle_path):
        if record.get("event") != "operation_ran":
            continue
        operation_id = record.get("operation_id")
        if not isinstance(operation_id, str):
            continue
        at_unix = record.get("at_unix")
        code = record.get("code")
        executed.append(
            {
                "operation_id": operation_id,
                "at_unix": at_unix if isinstance(at_unix, (int, float)) else None,
                "ok": code is None,
                "code": code if isinstance(code, str) else None,
            }
        )
    return tuple(executed)


__all__ = [
    "EXECUTION_JOURNAL_FILENAME",
    "EXECUTION_JOURNAL_SCHEMA_VERSION",
    "ExecutionFailureFacts",
    "IncompleteAttempt",
    "append_journal_event",
    "append_journal_event_once",
    "current_execution_stage",
    "current_execution_failure",
    "current_gate_execution_failure",
    "current_post_response_failure",
    "executed_operations",
    "failure_outcome_attempt_id",
    "incomplete_attempt",
    "read_journal_records",
    "value_digest",
]
