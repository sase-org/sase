"""Execution of repeatable non-terminal gate actions.

An action differs from a gate option in exactly four ways, and those four
differences are the whole point of the mechanism:

1. It never writes ``response.json`` and never settles the notification, so
   the gate stays pending and answerable.
2. It may be run any number of times.
3. It refuses to run once the gate has a response or a cancellation.
4. After the command exits, **every** resource is re-hashed. A path the action
   declared under ``targets`` is revalidated through the adapter and re-hashed
   exactly as an accepted edit is; a change to any resource the action did not
   declare is a ``hash_mismatch`` and the action is reported as failed.

Point 4 is what keeps a display command from quietly rewriting the very
command the reviewer is about to approve.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
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
    request_sha256,
    sha256_file,
    verify_mode,
)
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.input_bounds import check_input_bounds
from sase.notification_gates.journal import append_journal_event, value_digest
from sase.notification_gates.model_operations import (
    GateActionDisplay,
    GateOperation,
    gate_operation_from_envelope,
)
from sase.notification_gates.model_results import GateOperationResult
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    RESPONSE_FILENAME,
    assert_owned_bundle,
    owned_resource_path,
)
from sase.notification_gates.registry import GateAdapter


def execute_gate_operation(
    bundle_path: Path,
    operation_id: str,
    *,
    input_data: object | None = None,
    source: str = "host",
    on_command_start: Callable[[str, str, str, tuple[str, ...]], None] | None = None,
    on_output_line: Callable[[str, str, str, str], None] | None = None,
    on_process_state: Callable[[subprocess.Popen[bytes], bool], None] | None = None,
) -> GateOperationResult:
    """Run one declared ``run_command`` action, leaving the gate answerable."""
    bundle_path = assert_owned_bundle(bundle_path)
    response_path = bundle_path / RESPONSE_FILENAME
    cancellation_path = bundle_path / CANCELLATION_FILENAME
    with file_lock(bundle_path / ".response.lock"):
        envelope, adapter = load_and_verify_bundle(bundle_path)
        operation = gate_operation_from_envelope(
            envelope, operation_id, kind="run_command"
        )
        assert operation.command is not None
        _reject_terminal_gate(response_path, cancellation_path, operation_id)

        normalized_input = {} if input_data is None else input_data
        target = f"action {operation_id} input"
        with recorded_rejection(bundle_path, operation_id, source):
            check_input_bounds(normalized_input, target)
            validate_json_instance(normalized_input, operation.input_schema, target)

        # Successful and failed runs are both journalled: the journal is the
        # audit trail for what a reviewer ran before deciding, and a run that
        # failed is part of that story.
        journal = _action_journal(
            bundle_path,
            operation_id,
            request_hash=str(envelope["hashes"]["request"]),
            input_digest=value_digest(normalized_input),
        )
        try:
            result = _run_action_command(
                bundle_path,
                operation,
                envelope=envelope,
                normalized_input=normalized_input,
                response_path=response_path,
                cancellation_path=cancellation_path,
                source=source,
                on_command_start=on_command_start,
                on_output_line=on_output_line,
                on_process_state=on_process_state,
            )
            hashes, review_revision = _accept_action_targets(
                bundle_path,
                operation,
                envelope=envelope,
                adapter=adapter,
                source=source,
            )
        except GateError as exc:
            journal(code=exc.code)
            raise
        journal(result_digest=value_digest(result))
        return GateOperationResult(
            operation_id=operation_id,
            result=result,
            display=GateActionDisplay.from_result(result),
            display_format=operation.display,
            review_revision=review_revision,
            hashes=hashes,
        )


def _action_journal(
    bundle_path: Path,
    operation_id: str,
    *,
    request_hash: str,
    input_digest: str,
) -> Callable[..., None]:
    """Bind one ``operation_ran`` record, written on success or on failure.

    An action opens no attempt, so it carries a one-off ``attempt_id`` that
    retry resolution never looks at.
    """
    attempt_id = uuid4().hex

    def write(*, result_digest: str | None = None, code: str | None = None) -> None:
        append_journal_event(
            bundle_path,
            attempt_id=attempt_id,
            request_hash=request_hash,
            event="operation_ran",
            operation_id=operation_id,
            input_digest=input_digest,
            result_digest=result_digest,
            code=code,
        )

    return write


def _reject_terminal_gate(
    response_path: Path, cancellation_path: Path, operation_id: str
) -> None:
    """Refuse to run an action once the gate is no longer answerable."""
    if response_path.exists():
        raise GateError(
            "already_answered",
            operation_id,
            "answered gates cannot run actions",
        )
    if cancellation_path.exists():
        raise GateError(
            "gate_cancelled",
            operation_id,
            "cancelled gates cannot run actions",
        )


def _run_action_command(
    bundle_path: Path,
    operation: GateOperation,
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
    """Run one action's command and return its schema-validated result."""
    assert operation.command is not None
    argv = operation.command.argv
    stream_output = (
        None
        if on_output_line is None
        else _bind_action_output(on_output_line, operation.id)
    )
    try:
        if on_command_start is not None:
            on_command_start("action", operation.id, operation.label, argv)
        completed = run_owned_command(
            bundle_path,
            argv,
            expected_hash=envelope["hashes"]["resources"][argv[0]],
            input_data=normalized_input,
            on_output_line=stream_output,
            on_process_state=on_process_state,
        )
        reject_command_terminal_state(
            response_path, cancellation_path, target=operation.id
        )
    except GateError as exc:
        record_execution_error(
            bundle_path,
            option_id=operation.id,
            code=exc.code,
            message=str(exc),
            source=source,
        )
        raise
    if completed.returncode != 0:
        message = decode_output(completed.stderr) or (
            f"action exited with status {completed.returncode}"
        )
        record_execution_error(
            bundle_path,
            option_id=operation.id,
            code="command_failed",
            message=message,
            source=source,
            returncode=completed.returncode,
            stdout=decode_output(completed.stdout),
            stderr=decode_output(completed.stderr),
        )
        raise GateError("command_failed", operation.id, message)
    try:
        result = decode_json_result(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        record_execution_error(
            bundle_path,
            option_id=operation.id,
            code="invalid_command_output",
            message=str(exc),
            source=source,
            stdout=decode_output(completed.stdout),
            stderr=decode_output(completed.stderr),
        )
        raise GateError(
            "invalid_command_output",
            operation.id,
            "action stdout must contain one JSON value",
        ) from exc
    with recorded_rejection(bundle_path, operation.id, source):
        validate_json_instance(
            result, operation.result_schema, f"action {operation.id} result"
        )
    return result


def _accept_action_targets(
    bundle_path: Path,
    operation: GateOperation,
    *,
    envelope: Mapping[str, Any],
    adapter: GateAdapter,
    source: str,
) -> tuple[dict[str, Any], int]:
    """Re-hash every resource, accepting changes only to declared targets."""
    resources = envelope.get("resources")
    if not isinstance(resources, list):
        raise GateError("invalid_request", "resources", "resources are missing")
    expected = dict(envelope.get("hashes", {}).get("resources", {}))
    changed: list[str] = []
    for raw_resource in resources:
        if not isinstance(raw_resource, Mapping):
            raise GateError("invalid_request", "resources", "invalid resource")
        relative = str(raw_resource.get("path"))
        path = owned_resource_path(bundle_path, relative)
        with recorded_rejection(bundle_path, operation.id, source):
            verify_mode(path, executable=bool(raw_resource.get("executable", False)))
            if sha256_file(path) == expected.get(relative):
                continue
            if relative not in operation.targets:
                raise GateError(
                    "hash_mismatch",
                    relative,
                    f"action {operation.id} rewrote an undeclared resource: {relative}",
                )
            adapter.validate_edited_resource(path=path)
        changed.append(relative)
    review_revision = int(envelope.get("review_revision", 1))
    if not changed:
        return dict(envelope["hashes"]), review_revision

    adapter.regenerate_previews(bundle_path=bundle_path)
    resource_hashes = {
        str(raw["path"]): sha256_file(
            owned_resource_path(bundle_path, str(raw["path"]))
        )
        for raw in resources
        if isinstance(raw, Mapping) and "path" in raw
    }
    # Rewrite the stored envelope, never the projection load_and_verify_bundle
    # returned: the projection normalizes fields a legacy bundle never had, and
    # persisting those would change what the reviewer accepted.
    request_path = bundle_path / "request.json"
    stored = read_json_object(request_path)
    review_revision += 1
    stored["review_revision"] = review_revision
    stored["hashes"] = {"resources": resource_hashes}
    stored["hashes"]["request"] = request_sha256(stored)
    atomic_write_json(request_path, stored)
    return dict(stored["hashes"]), review_revision


def _bind_action_output(
    callback: Callable[[str, str, str, str], None], operation_id: str
) -> Callable[[str, str], None]:
    def emit(stream: str, line: str) -> None:
        callback("action", operation_id, stream, line)

    return emit


__all__ = ["execute_gate_operation"]
