"""Attempt planning, opening, and resume for notification gate execution.

Split out of :mod:`sase.notification_gates.executor` (bead ``sase-zr.7.1.1.2``)
to keep that module under the ``toobig`` FYI threshold as it grows failure-
outcome and stage-tracking logic. An AND branch's completed-option replay on
resume lives here too, since it is inseparable from deciding whether a
submission continues an existing attempt.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from sase.notification_gates.command_runner import (
    decode_json_result,
    decode_output,
    reject_command_terminal_state,
    run_owned_command,
    validate_json_instance,
)
from sase.notification_gates.failure_outcome import record_failure_outcome
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.journal import (
    IncompleteAttempt,
    append_journal_event,
    incomplete_attempt,
)
from sase.notification_gates.model_options import GateOption
from sase.notification_gates.models import GateError


@dataclass(frozen=True)
class _AttemptPlan:
    """A write-free decision about how the next execution attempt should open."""

    request_hash: str
    selected_option_ids: tuple[str, ...]
    input_digests: Mapping[str, str]
    retry: Literal["resume", "restart"] | None
    pending: IncompleteAttempt | None
    matching: bool


def plan_attempt(
    bundle_path: Path,
    *,
    request_hash: str,
    selected: tuple[GateOption, ...],
    input_digests: Mapping[str, str],
    retry: Literal["resume", "restart"] | None,
) -> _AttemptPlan:
    """Validate retry semantics without writing to the execution journal."""
    selected_ids = tuple(option.id for option in selected)
    pending = incomplete_attempt(bundle_path, response_exists=False)
    matching = pending is not None and pending.matches(
        request_hash=request_hash,
        selected_option_ids=selected_ids,
        input_digests=input_digests,
    )
    if not matching:
        if retry is not None:
            raise GateError(
                "no_partial_attempt",
                "retry",
                "this submission has no incomplete attempt to resume or restart",
            )
    elif retry is None:
        assert pending is not None
        raise GateError(
            "partial_attempt",
            pending.attempt_id,
            "this branch was already partially executed "
            f"({pending.describe()}); resume after the failed option or "
            "restart the whole branch",
        )
    return _AttemptPlan(
        request_hash=request_hash,
        selected_option_ids=selected_ids,
        input_digests=input_digests,
        retry=retry,
        pending=pending,
        matching=matching,
    )


def open_planned_attempt(
    bundle_path: Path,
    plan: _AttemptPlan,
    *,
    acceptance_id: str | None,
) -> tuple[str, dict[str, Any]]:
    """Append the attempt events for a previously validated plan."""
    pending = plan.pending
    if not plan.matching and pending is not None:
        append_journal_event(
            bundle_path,
            attempt_id=pending.attempt_id,
            request_hash=pending.request_hash,
            event="attempt_superseded",
            acceptance_id=acceptance_id,
        )
    elif plan.retry == "resume":
        assert pending is not None
        append_journal_event(
            bundle_path,
            attempt_id=pending.attempt_id,
            request_hash=pending.request_hash,
            event="attempt_resumed",
            acceptance_id=acceptance_id,
        )
        return pending.attempt_id, _replayed_results(pending, plan.selected_option_ids)

    attempt_id = uuid4().hex
    append_journal_event(
        bundle_path,
        attempt_id=attempt_id,
        request_hash=plan.request_hash,
        event="attempt_started",
        selected_option_ids=plan.selected_option_ids,
        input_digests=plan.input_digests,
        acceptance_id=acceptance_id,
    )
    return attempt_id, {}


def _replayed_results(
    pending: IncompleteAttempt, selected_ids: tuple[str, ...]
) -> dict[str, Any]:
    return {
        option_id: pending.results[option_id]
        for option_id in selected_ids
        if option_id in pending.completed_option_ids and option_id in pending.results
    }


def execute_one_option(
    bundle_path: Path,
    option: GateOption,
    *,
    envelope: Mapping[str, Any],
    normalized_input: object,
    response_path: Path,
    cancellation_path: Path,
    source: str,
    acceptance_id: str | None,
    attempt_id: str,
    on_command_start: Callable[[str, str, str, tuple[str, ...]], None] | None,
    on_output_line: Callable[[str, str, str, str], None] | None,
    on_process_state: Callable[[subprocess.Popen[bytes], bool], None] | None,
) -> Any:
    """Run one selected option's command and return its validated result."""
    resolved_inputs = {option.id: normalized_input}
    stream_output = (
        None
        if on_output_line is None
        else _bind_output_callback(on_output_line, option.id)
    )
    try:
        if on_command_start is not None:
            on_command_start("option", option.id, option.label, option.command.argv)
        completed = run_owned_command(
            bundle_path,
            option.command.argv,
            expected_hash=envelope["hashes"]["resources"][option.command.argv[0]],
            input_data=normalized_input,
            on_output_line=stream_output,
            on_process_state=on_process_state,
        )
        reject_command_terminal_state(
            response_path,
            cancellation_path,
            target=option.id,
        )
    except GateError as exc:
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=attempt_id,
            stage="command",
            error=exc,
            selected=(option,),
            resolved_inputs=resolved_inputs,
            source=source,
        )
        raise
    if completed.returncode != 0:
        message = decode_output(completed.stderr) or (
            f"command exited with status {completed.returncode}"
        )
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=attempt_id,
            stage="command",
            error=GateError("command_failed", option.id, message),
            selected=(option,),
            resolved_inputs=resolved_inputs,
            source=source,
            returncode=completed.returncode,
            stdout=decode_output(completed.stdout),
            stderr=decode_output(completed.stderr),
        )
        raise GateError("command_failed", option.id, message)

    try:
        result = decode_json_result(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=attempt_id,
            stage="command",
            error=GateError(
                "invalid_command_output",
                option.id,
                "command stdout must contain one JSON value",
            ),
            selected=(option,),
            resolved_inputs=resolved_inputs,
            source=source,
            stdout=decode_output(completed.stdout),
            stderr=decode_output(completed.stderr),
        )
        raise GateError(
            "invalid_command_output",
            option.id,
            "command stdout must contain one JSON value",
        ) from exc
    try:
        validate_json_instance(
            result,
            option.result_schema,
            f"option {option.id} result",
        )
    except GateError as exc:
        record_failure_outcome(
            bundle_path,
            acceptance_id=acceptance_id,
            attempt_id=attempt_id,
            stage="command",
            error=exc,
            selected=(option,),
            resolved_inputs=resolved_inputs,
            source=source,
            stdout=decode_output(completed.stdout),
            stderr=decode_output(completed.stderr),
        )
        raise

    current_envelope, _current_adapter = load_and_verify_bundle(bundle_path)
    if current_envelope["hashes"]["request"] != envelope["hashes"]["request"]:
        raise GateError(
            "request_changed",
            str(bundle_path),
            "request changed during execution",
        )
    return result


def _bind_output_callback(
    callback: Callable[[str, str, str, str], None], option_id: str
) -> Callable[[str, str], None]:
    def emit(stream: str, line: str) -> None:
        callback("option", option_id, stream, line)

    return emit


__all__ = [
    "execute_one_option",
    "open_planned_attempt",
    "plan_attempt",
]
