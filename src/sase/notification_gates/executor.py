"""Trusted host execution and terminal persistence for notification gates."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from sase.notification_gates.command_runner import (
    decode_json_result,
    decode_output,
    record_execution_error,
    recorded_rejection,
    reject_command_terminal_state,
    run_owned_command,
    validate_json_instance,
)
from sase.notification_gates.durability import (
    atomic_write_json,
    file_lock,
    read_json_object,
)
from sase.notification_gates.executor_inputs import (
    redact_option_inputs,
    resolve_option_inputs,
)
from sase.notification_gates.feedback_input import apply_feedback_input
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.input_bounds import check_input_bounds
from sase.notification_gates.journal import (
    IncompleteAttempt,
    append_journal_event,
    incomplete_attempt,
    value_digest,
)
from sase.notification_gates.models import (
    GATE_RESPONSE_SCHEMA_VERSION,
    GateError,
    GateExecutionResult,
    GateFeedbackMode,
    GateOption,
)
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    RESPONSE_FILENAME,
    assert_owned_bundle,
)

if TYPE_CHECKING:
    from sase.bead.epic_launch import EpicLaunchOrigin

log = logging.getLogger(__name__)


def execute_gate_selection(
    bundle_path: Path,
    selected_option_ids: Sequence[str],
    input_data: object | None = None,
    *,
    feedback: str | None = None,
    source: str = "host",
    retry: Literal["resume", "restart"] | None = None,
    epic_launch_origin: EpicLaunchOrigin | None = None,
    option_inputs: Mapping[str, object] | None = None,
    on_command_start: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    on_output_line: Callable[[str, str, str, str], None] | None = None,
    on_process_state: Callable[[subprocess.Popen[bytes], bool], None] | None = None,
) -> GateExecutionResult:
    """Execute a non-empty subset of one branch and persist one response.

    Submitted ids are normalized to query order before command execution and
    persistence.

    ``input_data`` and ``option_inputs`` are mutually exclusive submission
    contracts. With ``input_data`` (or neither given), every selected option
    receives the same JSON input value, as before. With ``option_inputs``, a
    mapping of selected option id to that option's own submitted JSON value,
    each selected option receives its own value and a selected option with no
    entry is judged against its own schema with ``{}``. Supplying both raises
    ``conflicting_input``; an ``option_inputs`` key outside the selection
    raises ``unknown_option``. The reviewer's note is then injected as
    ``input.feedback`` for each selected option whose schema declares that
    property. That rule lives here rather than in any surface so every
    client -- ACE, mobile, Telegram, and headless callers -- answers one
    gate the same way.

    An AND branch runs its commands one at a time, and a later member may
    fail after earlier members already took effect. Every attempt is recorded
    in the bundle's execution journal, and an identical resubmission over an
    incomplete attempt raises ``partial_attempt`` instead of silently
    re-running the completed commands; the caller then chooses ``retry``:

    - ``"resume"`` skips the options already recorded complete and replays
      their recorded results, starting at the option that failed.
    - ``"restart"`` runs the whole branch again under a fresh attempt.

    Because ``restart`` is a supported reviewer choice, **option commands in
    an AND branch must tolerate being run again** after a later member fails.
    Write them to be idempotent.
    """
    bundle_path = assert_owned_bundle(bundle_path)
    response_path = bundle_path / RESPONSE_FILENAME
    cancellation_path = bundle_path / CANCELLATION_FILENAME
    with file_lock(bundle_path / ".response.lock"):
        envelope, adapter = load_and_verify_bundle(bundle_path)
        options = _options_from_envelope(envelope)
        selected = _resolve_selection(envelope, options, selected_option_ids)
        if response_path.exists():
            existing_response = read_json_object(response_path)
            _settle_gate_notification(envelope, existing_response, source=source)
            return GateExecutionResult(
                response=existing_response,
                already_completed=True,
            )
        if cancellation_path.exists():
            raise GateError(
                "gate_cancelled",
                str(cancellation_path),
                "gate is already cancelled",
            )

        normalized_input = {} if input_data is None else input_data
        with recorded_rejection(bundle_path, selected[0].id, source):
            normalized_feedback = _normalize_feedback(selected, feedback)
        with recorded_rejection(bundle_path, selected[0].id, source):
            resolved_inputs = resolve_option_inputs(selected, input_data, option_inputs)
        resolved_inputs = apply_feedback_input(
            selected,
            resolved_inputs,
            normalized_feedback,
        )
        for option in selected:
            target = f"option {option.id} input"
            with recorded_rejection(bundle_path, option.id, source):
                check_input_bounds(resolved_inputs[option.id], target)
                validate_json_instance(
                    resolved_inputs[option.id], option.input_schema, target
                )
        with recorded_rejection(bundle_path, selected[0].id, source):
            adapter.validate_selection(
                selected_option_ids=tuple(option.id for option in selected),
                feedback=normalized_feedback,
            )

        request_hash = str(envelope["hashes"]["request"])
        input_digests = {
            option.id: value_digest(resolved_inputs[option.id]) for option in selected
        }
        attempt_id, replayed = _begin_attempt(
            bundle_path,
            request_hash=request_hash,
            selected=selected,
            input_digests=input_digests,
            retry=retry,
        )

        option_results: list[dict[str, Any]] = []
        for option in selected:
            if option.id in replayed:
                option_results.append({"id": option.id, "result": replayed[option.id]})
                continue
            try:
                result = _execute_one_option(
                    bundle_path,
                    option,
                    envelope=envelope,
                    normalized_input=resolved_inputs[option.id],
                    response_path=response_path,
                    cancellation_path=cancellation_path,
                    source=source,
                    on_command_start=on_command_start,
                    on_output_line=on_output_line,
                    on_process_state=on_process_state,
                )
            except GateError as exc:
                append_journal_event(
                    bundle_path,
                    attempt_id=attempt_id,
                    request_hash=request_hash,
                    event="option_failed",
                    option_id=option.id,
                    input_digest=input_digests[option.id],
                    code=exc.code,
                )
                raise
            option_results.append({"id": option.id, "result": result})
            append_journal_event(
                bundle_path,
                attempt_id=attempt_id,
                request_hash=request_hash,
                event="option_completed",
                option_id=option.id,
                input_digest=input_digests[option.id],
                result_digest=value_digest(result),
                result=result,
            )

        append_journal_event(
            bundle_path,
            attempt_id=attempt_id,
            request_hash=request_hash,
            event="attempt_completed",
        )
        response: dict[str, Any] = {
            "schema_version": GATE_RESPONSE_SCHEMA_VERSION,
            "request_id": envelope["request_id"],
            "kind": adapter.kind,
            "selected_option_ids": [option.id for option in selected],
            "input": normalized_input,
            "option_inputs": redact_option_inputs(selected, resolved_inputs),
            "option_results": option_results,
            "feedback": normalized_feedback,
            "source": source,
            "responded_at_unix": time.time(),
        }
        try:
            atomic_write_json(response_path, response, exclusive=True)
        except FileExistsError:
            existing = read_json_object(response_path)
            _settle_gate_notification(envelope, existing, source=source)
            return GateExecutionResult(response=existing, already_completed=True)
        _settle_gate_notification(envelope, response, source=source)
        try:
            adapter.apply_side_effects(
                bundle_path=bundle_path,
                response=response,
                epic_launch_origin=epic_launch_origin,
            )
        except GateError as exc:
            record_execution_error(
                bundle_path,
                option_id=selected[0].id,
                code=exc.code,
                message=str(exc),
                source=source,
            )
            raise
        except Exception as exc:
            record_execution_error(
                bundle_path,
                option_id=selected[0].id,
                code="side_effect_failed",
                message=str(exc),
                source=source,
            )
            raise GateError(
                "side_effect_failed",
                adapter.kind,
                f"host side effect failed: {exc}",
            ) from exc
        return GateExecutionResult(response=response)


def _execute_one_option(
    bundle_path: Path,
    option: GateOption,
    *,
    envelope: Mapping[str, Any],
    normalized_input: object,
    response_path: Path,
    cancellation_path: Path,
    source: str,
    on_command_start: Callable[[str, str, str, tuple[str, ...]], None] | None,
    on_output_line: Callable[[str, str, str, str], None] | None,
    on_process_state: Callable[[subprocess.Popen[bytes], bool], None] | None,
) -> Any:
    """Run one selected option's command and return its validated result."""
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
        record_execution_error(
            bundle_path,
            option_id=option.id,
            code=exc.code,
            message=str(exc),
            source=source,
        )
        raise
    if completed.returncode != 0:
        message = decode_output(completed.stderr) or (
            f"command exited with status {completed.returncode}"
        )
        record_execution_error(
            bundle_path,
            option_id=option.id,
            code="command_failed",
            message=message,
            source=source,
            returncode=completed.returncode,
            stdout=decode_output(completed.stdout),
            stderr=decode_output(completed.stderr),
        )
        raise GateError("command_failed", option.id, message)

    try:
        result = decode_json_result(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        record_execution_error(
            bundle_path,
            option_id=option.id,
            code="invalid_command_output",
            message=str(exc),
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
        record_execution_error(
            bundle_path,
            option_id=option.id,
            code=exc.code,
            message=str(exc),
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


def _begin_attempt(
    bundle_path: Path,
    *,
    request_hash: str,
    selected: tuple[GateOption, ...],
    input_digests: Mapping[str, str],
    retry: Literal["resume", "restart"] | None,
) -> tuple[str, dict[str, Any]]:
    """Open or continue an attempt and return its id plus any replayed results."""
    selected_ids = tuple(option.id for option in selected)
    pending = incomplete_attempt(bundle_path)
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
        if pending is not None:
            append_journal_event(
                bundle_path,
                attempt_id=pending.attempt_id,
                request_hash=pending.request_hash,
                event="attempt_superseded",
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
    elif retry == "resume":
        assert pending is not None
        return pending.attempt_id, _replayed_results(pending, selected_ids)

    attempt_id = uuid4().hex
    append_journal_event(
        bundle_path,
        attempt_id=attempt_id,
        request_hash=request_hash,
        event="attempt_started",
        selected_option_ids=selected_ids,
        input_digests=input_digests,
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


def cancel_gate(
    bundle_path: Path,
    *,
    reason: str = "requester_cancelled",
    source: str = "requester",
) -> dict[str, Any]:
    """Persist a write-once cancellation if the gate has no response."""
    bundle_path = assert_owned_bundle(bundle_path)
    with file_lock(bundle_path / ".response.lock"):
        envelope, _adapter = load_and_verify_bundle(bundle_path)
        response_path = bundle_path / RESPONSE_FILENAME
        if response_path.exists():
            raise GateError(
                "already_answered", str(response_path), "gate already has a response"
            )
        path = bundle_path / CANCELLATION_FILENAME
        if path.exists():
            return read_json_object(path)
        cancellation = {
            "schema_version": GATE_RESPONSE_SCHEMA_VERSION,
            "request_id": envelope["request_id"],
            "kind": envelope["kind"],
            "reason": reason,
            "source": source,
            "cancelled_at_unix": time.time(),
        }
        atomic_write_json(path, cancellation, exclusive=True)
        _settle_gate_notification(envelope, {}, source=source, action="cancelled")
        return cancellation


def _options_from_envelope(envelope: Mapping[str, Any]) -> tuple[GateOption, ...]:
    from sase.notification_gates.registry import adapter_for_kind

    raw_options = envelope.get("options")
    assert isinstance(raw_options, list)
    kind = envelope.get("kind")
    assert isinstance(kind, str)
    default_feedback = adapter_for_kind(kind).default_feedback
    return tuple(
        GateOption.from_mapping(
            raw_option,
            index,
            default_feedback=default_feedback,
        )
        for index, raw_option in enumerate(raw_options)
    )


def _resolve_selection(
    envelope: Mapping[str, Any],
    options: tuple[GateOption, ...],
    selected_option_ids: Sequence[str],
) -> tuple[GateOption, ...]:
    if (
        not isinstance(selected_option_ids, Sequence)
        or isinstance(selected_option_ids, (str, bytes))
        or not all(isinstance(option_id, str) for option_id in selected_option_ids)
    ):
        raise GateError(
            "invalid_selection",
            "selected_option_ids",
            "selected_option_ids must be an array of strings",
        )
    requested = tuple(selected_option_ids)
    if not requested:
        raise GateError(
            "empty_selection",
            "selected_option_ids",
            "at least one option must be selected",
        )
    if len(set(requested)) != len(requested):
        raise GateError(
            "duplicate_option",
            "selected_option_ids",
            "selected option ids must be unique",
        )
    by_id = {option.id: option for option in options}
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise GateError(
            "unknown_option",
            "selected_option_ids",
            f"option is not present in the request: {', '.join(unknown)}",
        )
    raw_branches = envelope.get("branches")
    assert isinstance(raw_branches, list)
    selected_set = set(requested)
    matching = [
        tuple(str(option_id) for option_id in branch)
        for branch in raw_branches
        if isinstance(branch, list) and selected_set <= set(branch)
    ]
    if len(matching) != 1:
        raise GateError(
            "selection_crosses_branches",
            "selected_option_ids",
            "selected options must be a non-empty subset of exactly one branch",
        )
    branch = matching[0]
    return tuple(by_id[option_id] for option_id in branch if option_id in selected_set)


def _normalize_feedback(
    selected: tuple[GateOption, ...], feedback: str | None
) -> str | None:
    if feedback is not None and not isinstance(feedback, str):
        raise GateError(
            "invalid_feedback", "feedback", "feedback must be a string or null"
        )
    ranks: dict[GateFeedbackMode, int] = {
        "disabled": 0,
        "optional": 1,
        "required": 2,
    }
    effective = max((option.feedback for option in selected), key=ranks.__getitem__)
    selected_text = ", ".join(option.id for option in selected)
    if effective == "disabled":
        if feedback is not None:
            raise GateError(
                "feedback_not_allowed",
                "feedback",
                f"selected option(s) do not accept feedback: {selected_text}",
            )
        return None
    normalized = feedback.strip() if isinstance(feedback, str) else None
    normalized = normalized or None
    if effective == "required" and normalized is None:
        raise GateError(
            "feedback_required",
            "feedback",
            f"selected option(s) require feedback: {selected_text}",
        )
    return normalized


def _bind_output_callback(
    callback: Callable[[str, str, str, str], None], option_id: str
) -> Callable[[str, str], None]:
    def emit(stream: str, line: str) -> None:
        callback("option", option_id, stream, line)

    return emit


def _settle_gate_notification(
    envelope: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    source: str,
    action: str | None = None,
) -> None:
    """Mark one gate's notification handled and dismiss its inbox row.

    Runs for every terminal transition of every gate kind, from every client,
    so no surface has to remember to dismiss the row itself.
    """
    notification_id = envelope.get("notification_id")
    if not isinstance(notification_id, str) or not notification_id:
        return
    from sase.notifications.pending_actions import mark_already_handled

    raw_selected = response.get("selected_option_ids")
    selected = (
        [str(option_id) for option_id in raw_selected]
        if isinstance(raw_selected, list)
        else []
    )
    mark_already_handled(
        notification_id,
        source=source,
        action=action or "+".join(selected) or "resolved",
    )
    _dismiss_gate_notification_best_effort(notification_id)


def _dismiss_gate_notification_best_effort(notification_id: str) -> None:
    """Hide a settled gate row without ever failing a persisted response."""
    try:
        from sase.notifications.store import mark_dismissed

        mark_dismissed(notification_id)
    except Exception:
        log.warning("Failed to dismiss notification for settled gate", exc_info=True)


__all__ = ["cancel_gate", "execute_gate_selection"]
