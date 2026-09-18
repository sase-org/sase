"""Redacted, durable failure-outcome recording for gate execution.

An accepted gate decision must never look silently stuck: every failure past
acceptance -- an option command, terminal (archive) preparation, a host side
effect, or a shell's follow-up settlement -- gets one durable, redacted
``attempt_failed`` journal event referencing the existing ``errors/*.json``
record :func:`~sase.notification_gates.command_runner.record_execution_error`
already writes, rather than a second parallel store. See design decision 7 in
``plan:202609/gate_decision_integrity_1.md``.

Lifecycle, cancel, and gate-show paths read the current outcome to decide
whether the accepted receipt is recoverable. The ``failure_surfacing`` phase
(bead ``sase-zr.7.1.1.4``) feeds the same outcomes to ``poll_gate`` and a
recovery notification.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.notification_gates.command_runner import record_execution_error
from sase.notification_gates.decision import (
    ACCEPTANCE_LOCK_FILENAME,
    ACCEPTANCE_LOCK_TIMEOUT_SECONDS,
)
from sase.notification_gates.durability import file_lock
from sase.notification_gates.executor_inputs import scrub_submitted_secrets
from sase.notification_gates.failure_notifications import publish_gate_execution_failed
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.journal import (
    ExecutionFailureFacts,
    append_journal_event,
    append_journal_event_once,
    current_execution_stage,
    current_gate_execution_failure,
    failure_outcome_attempt_id,
)
from sase.notification_gates.model_options import GateOption
from sase.notification_gates.models import GateError

#: Design decision 7: a message this long is still useful to a reviewer, and
#: bounding it keeps one verbose exception from bloating the journal.
_MESSAGE_LIMIT = 1000

#: For these two codes the message is a fixed summary naming the option and
#: (for ``command_failed``) its exit status -- never stdout or stderr, which
#: a reviewer already reads through ``errors/*.json`` via ``d``.
_FIXED_SUMMARY_CODES = frozenset({"command_failed", "invalid_command_output"})

PRE_ATTEMPT_FAILURE_ATTEMPT_ID = ""
OWNER_LOST_ATTEMPT_ID = "owner_lost"
SIDE_EFFECTS_ATTEMPT_ID = "side_effects"
FOLLOW_UP_ATTEMPT_ID = "follow_up"


def record_failure_outcome(
    bundle_path: Path,
    *,
    acceptance_id: str | None,
    attempt_id: str,
    stage: str,
    error: BaseException,
    selected: Sequence[GateOption] = (),
    resolved_inputs: Mapping[str, Any] | None = None,
    source: str,
    request_hash: str = "",
    returncode: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    default_code: str = "execution_interrupted",
) -> ExecutionFailureFacts:
    """Record one durable, redacted failure outcome and return it.

    Writes exactly one ``errors/*.json`` record (via the now stage/attempt/
    outcome-tagged :func:`record_execution_error`) and one ``attempt_failed``
    journal event referencing it -- callers must not also call
    :func:`record_execution_error` themselves for the same failure.

    ``stage`` is one of ``command``, ``terminal_prepare``, ``side_effects``,
    or ``follow_up``. Pre-attempt revalidation failures (before an execution
    attempt id exists) get a synthetic id from their durable outcome id.
    ``default_code``
    names *error* when it is not a
    :class:`GateError` -- ``execution_interrupted`` for a true interruption
    (a ``BaseException`` escaping option-command or stage execution), or
    ``adapter_rejected`` for an adapter's own non-``GateError`` rejection
    type, matching :func:`sase.notification_gates.command_runner.recorded_rejection`.
    """
    code = error.code if isinstance(error, GateError) else default_code
    option_id = selected[0].id if selected else ""
    message = _redacted_message(code, error, selected, resolved_inputs, returncode)
    outcome_id = uuid4().hex
    attempt_id = failure_outcome_attempt_id(
        attempt_id,
        stage=stage,
        outcome_id=outcome_id,
    )
    error_record = record_execution_error(
        bundle_path,
        option_id=option_id,
        code=code,
        message=str(error),
        source=source,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        stage=stage,
        attempt_id=attempt_id,
        outcome_id=outcome_id,
    )
    at_unix = time.time()
    append_journal_event(
        bundle_path,
        attempt_id=attempt_id,
        request_hash=request_hash,
        event="attempt_failed",
        code=code,
        stage=stage,
        message=message,
        outcome_id=outcome_id,
        error_record=error_record,
        acceptance_id=acceptance_id,
    )
    failure = ExecutionFailureFacts(
        outcome_id=outcome_id,
        acceptance_id=acceptance_id,
        attempt_id=attempt_id,
        stage=stage,
        code=code,
        message=message,
        at_unix=at_unix,
        error_record=error_record,
    )
    _publish_failure_notification(
        bundle_path,
        failure,
        source=source,
    )
    return failure


def record_owner_lost_outcome(
    bundle_path: Path,
    *,
    receipt: Mapping[str, Any] | None,
    source: str,
) -> ExecutionFailureFacts | None:
    """Record the current accepted execution owner as lost, idempotently."""
    response_exists = (bundle_path / "response.json").exists()
    current = current_gate_execution_failure(
        bundle_path,
        receipt,
        response_exists=response_exists,
    )
    request_hash = str((receipt or {}).get("request_hash") or "")
    if current is not None:
        if current.code == "execution_owner_lost":
            _append_owner_lost_transition(
                bundle_path, current, request_hash=request_hash
            )
        _publish_failure_notification(bundle_path, current, source=source)
        return current
    acceptance_id = _receipt_acceptance_id(receipt)
    stage, attempt_id = current_execution_stage(bundle_path, receipt)
    if not attempt_id:
        attempt_id = OWNER_LOST_ATTEMPT_ID
    failure = record_failure_outcome(
        bundle_path,
        acceptance_id=acceptance_id,
        attempt_id=attempt_id,
        stage=stage,
        error=GateError(
            "execution_owner_lost",
            "execution_owner",
            "gate execution owner appears to have stopped",
        ),
        source=source,
        request_hash=request_hash,
    )
    _append_owner_lost_transition(bundle_path, failure, request_hash=request_hash)
    return failure


def record_owner_lost_outcome_if_current(
    bundle_path: Path,
    *,
    source: str,
    now: float,
    deadline: float | None,
    grace_seconds: float,
    lock_timeout_seconds: float | None = ACCEPTANCE_LOCK_TIMEOUT_SECONDS,
) -> ExecutionFailureFacts | None:
    """Recheck owner liveness under the acceptance lock before recording loss."""
    from sase.gate_shell.lifecycle import (
        DISPOSITION_ACCEPTED_FAILED,
        DISPOSITION_ACCEPTED_OWNER_LOST,
        classify_gate_lifecycle,
        collect_gate_lifecycle_facts,
    )

    with file_lock(
        bundle_path / ACCEPTANCE_LOCK_FILENAME,
        timeout=lock_timeout_seconds,
    ):
        try:
            envelope, _adapter = load_and_verify_bundle(bundle_path)
            facts = collect_gate_lifecycle_facts(
                bundle_path,
                envelope,
                now=now,
                deadline=deadline,
                grace_seconds=grace_seconds,
            )
            disposition = classify_gate_lifecycle(facts)["disposition"]
        except Exception:
            return None
        if disposition == DISPOSITION_ACCEPTED_FAILED:
            return current_gate_execution_failure(
                bundle_path,
                facts.receipt,
                response_exists=(bundle_path / "response.json").exists(),
            )
        if disposition != DISPOSITION_ACCEPTED_OWNER_LOST:
            return None
        return record_owner_lost_outcome(
            bundle_path,
            receipt=facts.receipt,
            source=source,
        )


@contextmanager
def recorded_attempt_failure(
    bundle_path: Path,
    *,
    acceptance_id: str | None,
    attempt_id: str = PRE_ATTEMPT_FAILURE_ATTEMPT_ID,
    stage: str = "command",
    selected: Sequence[GateOption] = (),
    resolved_inputs: Mapping[str, Any] | None,
    source: str,
) -> Iterator[None]:
    """Record one failure outcome for an exception raised in the block.

    Pre-attempt revalidation (feedback normalization, input resolution,
    bounds and schema checks) happens after acceptance but before an execution
    attempt id exists, so it uses ``stage="command"`` and lets
    :func:`record_failure_outcome` derive the durable failure id. Combines what
    :func:`sase.notification_gates.command_runner.recorded_rejection` does
    for a pre-acceptance rejection with the journal's ``attempt_failed``
    event in one write, so a caller past acceptance never records two
    outcomes for the same failure.
    """
    try:
        yield
    except BaseException as exc:
        default_code = (
            "adapter_rejected"
            if isinstance(exc, Exception)
            else "execution_interrupted"
        )
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=attempt_id,
            stage=stage,
            error=exc,
            selected=selected,
            resolved_inputs=resolved_inputs,
            source=source,
            default_code=default_code,
        )
        raise


def with_follow_up_stage_tracking[T](
    bundle_path: Path,
    *,
    acceptance_id: str | None,
    source: str,
    run: Callable[[], T],
) -> T:
    """Run *run* (a shell settlement) bracketed by ``follow_up`` stage events.

    The ``follow_up`` stage covers ``settle_gate_shell`` itself raising --
    not the follow-up launch failures it already records in
    ``gate_followup_error`` metadata and tolerates internally. Used by
    :mod:`sase.notification_gates.cli_answer` and
    :mod:`sase.plan_approval_actions` around their own ``settle_gate_shell``
    calls, since a gate answered through either surface can hit this stage.
    """
    append_journal_event(
        bundle_path,
        attempt_id=FOLLOW_UP_ATTEMPT_ID,
        request_hash="",
        event="stage_started",
        stage="follow_up",
        acceptance_id=acceptance_id,
    )
    try:
        result = run()
    except BaseException as exc:
        default_code = (
            "adapter_rejected"
            if isinstance(exc, Exception)
            else "execution_interrupted"
        )
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=FOLLOW_UP_ATTEMPT_ID,
            stage="follow_up",
            error=exc,
            source=source,
            default_code=default_code,
        )
        raise
    append_journal_event(
        bundle_path,
        attempt_id=FOLLOW_UP_ATTEMPT_ID,
        request_hash="",
        event="stage_completed",
        stage="follow_up",
        acceptance_id=acceptance_id,
    )
    return result


def _publish_failure_notification(
    bundle_path: Path,
    failure: ExecutionFailureFacts,
    *,
    source: str,
) -> None:
    try:
        envelope, _adapter = load_and_verify_bundle(bundle_path)
    except Exception:
        return
    publish_gate_execution_failed(
        bundle_path,
        envelope,
        failure,
        source=source,
    )


def _append_owner_lost_transition(
    bundle_path: Path, failure: ExecutionFailureFacts, *, request_hash: str = ""
) -> None:
    if failure.acceptance_id is None:
        return
    append_journal_event_once(
        bundle_path,
        event="owner_lost",
        acceptance_id=failure.acceptance_id,
        attempt_id=failure.attempt_id,
        request_hash=request_hash,
        code=failure.code,
        stage=failure.stage,
        message=failure.message,
        outcome_id=failure.outcome_id,
        error_record=failure.error_record,
    )


def _receipt_acceptance_id(receipt: Mapping[str, Any] | None) -> str | None:
    if receipt is None:
        return None
    value = receipt.get("acceptance_id")
    return value if isinstance(value, str) else None


def _redacted_message(
    code: str,
    error: BaseException,
    selected: Sequence[GateOption],
    resolved_inputs: Mapping[str, Any] | None,
    returncode: int | None,
) -> str:
    option_id = selected[0].id if selected else ""
    if code in _FIXED_SUMMARY_CODES:
        if code == "command_failed" and returncode is not None:
            return f"option {option_id} failed with exit status {returncode}"
        return f"option {option_id} failed: {code}"
    scrubbed = scrub_submitted_secrets(selected, resolved_inputs, str(error))
    return scrubbed[:_MESSAGE_LIMIT]


__all__ = [
    "record_failure_outcome",
    "record_owner_lost_outcome",
    "record_owner_lost_outcome_if_current",
    "recorded_attempt_failure",
    "with_follow_up_stage_tracking",
    "FOLLOW_UP_ATTEMPT_ID",
    "OWNER_LOST_ATTEMPT_ID",
    "PRE_ATTEMPT_FAILURE_ATTEMPT_ID",
    "SIDE_EFFECTS_ATTEMPT_ID",
]
