"""Trusted host execution and terminal persistence for notification gates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.notification_gates.durability import (
    atomic_write_json,
    canonical_json_bytes,
    file_lock,
    read_json_object,
)
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.models import (
    GATE_RESPONSE_SCHEMA_VERSION,
    GateChoice,
    GateError,
    GateExecutionResult,
    GateExtra,
    GateFeedbackMode,
)
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    RESPONSE_FILENAME,
    assert_owned_bundle,
    owned_resource_path,
    open_regular_nofollow,
)


def execute_gate_choice(
    bundle_path: Path,
    choice_id: str,
    input_data: object | None = None,
    *,
    selected_extra_ids: Sequence[str] | None = None,
    feedback: str | None = None,
    source: str = "host",
) -> GateExecutionResult:
    """Run one terminal choice plus selected extras and persist one response."""
    bundle_path = assert_owned_bundle(bundle_path)
    lock_path = bundle_path / ".response.lock"
    with file_lock(lock_path):
        envelope, adapter = load_and_verify_bundle(bundle_path)
        choice = _find_choice(envelope, choice_id)
        response_path = bundle_path / RESPONSE_FILENAME
        if response_path.exists():
            existing_response = read_json_object(response_path)
            _mark_pending_handled(envelope, existing_response, source=source)
            return GateExecutionResult(
                response=existing_response, already_completed=True
            )
        cancellation_path = bundle_path / CANCELLATION_FILENAME
        if cancellation_path.exists():
            raise GateError(
                "gate_cancelled", str(cancellation_path), "gate is already cancelled"
            )

        normalized_input = {} if input_data is None else input_data
        _validate_json_instance(
            normalized_input, choice.input_schema, f"choice {choice.id} input"
        )
        selected_extras = _resolve_selected_extras(choice, selected_extra_ids)
        normalized_feedback = _normalize_feedback(choice, feedback)
        try:
            completed = _run_owned_command(
                bundle_path,
                choice.command.argv,
                expected_hash=envelope["hashes"]["resources"][choice.command.argv[0]],
                input_data=normalized_input,
            )
            _reject_command_terminal_state(
                response_path,
                cancellation_path,
                target=choice.id,
            )
        except GateError as exc:
            _record_execution_error(
                bundle_path,
                choice_id=choice.id,
                code=exc.code,
                message=str(exc),
                source=source,
            )
            raise
        if completed.returncode != 0:
            message = _decode_output(completed.stderr) or (
                f"command exited with status {completed.returncode}"
            )
            _record_execution_error(
                bundle_path,
                choice_id=choice.id,
                code="command_failed",
                message=message,
                source=source,
                returncode=completed.returncode,
                stdout=_decode_output(completed.stdout),
                stderr=_decode_output(completed.stderr),
            )
            raise GateError("command_failed", choice.id, message)

        try:
            result = _decode_json_result(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _record_execution_error(
                bundle_path,
                choice_id=choice.id,
                code="invalid_command_output",
                message=str(exc),
                source=source,
                stdout=_decode_output(completed.stdout),
                stderr=_decode_output(completed.stderr),
            )
            raise GateError(
                "invalid_command_output",
                choice.id,
                "command stdout must contain one JSON value",
            ) from exc
        try:
            _validate_json_instance(
                result, choice.result_schema, f"choice {choice.id} result"
            )
        except GateError as exc:
            _record_execution_error(
                bundle_path,
                choice_id=choice.id,
                code=exc.code,
                message=str(exc),
                source=source,
                stdout=_decode_output(completed.stdout),
                stderr=_decode_output(completed.stderr),
            )
            raise

        current_envelope, _current_adapter = load_and_verify_bundle(bundle_path)
        if current_envelope["hashes"]["request"] != envelope["hashes"]["request"]:
            raise GateError(
                "request_changed", str(bundle_path), "request changed during execution"
            )
        extra_results = [
            _execute_extra(
                bundle_path,
                extra,
                envelope=envelope,
                input_data=normalized_input,
                response_path=response_path,
                cancellation_path=cancellation_path,
                choice_id=choice.id,
                source=source,
            )
            for extra in selected_extras
        ]
        response: dict[str, Any] = {
            "schema_version": GATE_RESPONSE_SCHEMA_VERSION,
            "request_id": envelope["request_id"],
            "kind": adapter.kind,
            "choice_id": choice.id,
            "input": normalized_input,
            "result": result,
            "selected_extra_ids": [extra.id for extra in selected_extras],
            "extra_results": extra_results,
            "feedback": normalized_feedback,
            "source": source,
            "responded_at_unix": time.time(),
        }
        try:
            atomic_write_json(response_path, response, exclusive=True)
        except FileExistsError:
            existing = read_json_object(response_path)
            _mark_pending_handled(envelope, existing, source=source)
            return GateExecutionResult(response=existing, already_completed=True)
        _mark_pending_handled(envelope, response, source=source)
        try:
            adapter.apply_side_effects(bundle_path=bundle_path, response=response)
        except Exception as exc:
            _record_execution_error(
                bundle_path,
                choice_id=choice.id,
                code="side_effect_failed",
                message=str(exc),
                source=source,
            )
            raise GateError(
                "side_effect_failed", adapter.kind, f"host side effect failed: {exc}"
            ) from exc
        return GateExecutionResult(response=response)


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
        _mark_pending_handled(envelope, {"choice_id": "cancelled"}, source=source)
        return cancellation


def _find_choice(envelope: Mapping[str, Any], choice_id: str) -> GateChoice:
    choices = envelope.get("choices")
    assert isinstance(choices, list)
    default_feedback: GateFeedbackMode = (
        "optional" if envelope.get("kind") == "custom" else "disabled"
    )
    for index, raw_choice in enumerate(choices):
        choice = GateChoice.from_mapping(
            raw_choice,
            index,
            default_feedback=default_feedback,
        )
        if choice.id == choice_id:
            return choice
    raise GateError(
        "unknown_choice",
        choice_id,
        f"choice is not present in the request: {choice_id}",
    )


def _resolve_selected_extras(
    choice: GateChoice,
    selected_extra_ids: Sequence[str] | None,
) -> tuple[GateExtra, ...]:
    if selected_extra_ids is None:
        return ()
    if (
        not isinstance(selected_extra_ids, Sequence)
        or isinstance(selected_extra_ids, (str, bytes))
        or not all(isinstance(extra_id, str) for extra_id in selected_extra_ids)
    ):
        raise GateError(
            "invalid_extras",
            "selected_extra_ids",
            "selected_extra_ids must be an array of strings",
        )
    requested = tuple(selected_extra_ids)
    if len(set(requested)) != len(requested):
        raise GateError(
            "duplicate_extra",
            "selected_extra_ids",
            "selected extra ids must be unique",
        )
    available = {extra.id: extra for extra in choice.extras}
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise GateError(
            "unknown_extra",
            "selected_extra_ids",
            f"extra is not present on choice {choice.id}: {', '.join(unknown)}",
        )
    selected = set(requested)
    return tuple(extra for extra in choice.extras if extra.id in selected)


def _normalize_feedback(choice: GateChoice, feedback: str | None) -> str | None:
    if feedback is not None and not isinstance(feedback, str):
        raise GateError(
            "invalid_feedback", "feedback", "feedback must be a string or null"
        )
    if choice.feedback == "disabled":
        if feedback is not None:
            raise GateError(
                "feedback_not_allowed",
                "feedback",
                f"choice {choice.id} does not accept feedback",
            )
        return None
    normalized = feedback.strip() if isinstance(feedback, str) else None
    normalized = normalized or None
    if choice.feedback == "required" and normalized is None:
        raise GateError(
            "feedback_required",
            "feedback",
            f"choice {choice.id} requires feedback",
        )
    return normalized


def _run_owned_command(
    bundle_path: Path,
    command_argv: tuple[str, ...],
    *,
    expected_hash: str,
    input_data: object,
) -> subprocess.CompletedProcess[bytes]:
    command_path = owned_resource_path(bundle_path, command_argv[0])
    command_fd = open_regular_nofollow(command_path)
    try:
        if _sha256_fd(command_fd) != expected_hash:
            raise GateError(
                "hash_mismatch",
                command_argv[0],
                "command changed before execution",
            )
        os.lseek(command_fd, 0, os.SEEK_SET)
        argv = (f"/proc/self/fd/{command_fd}", *command_argv[1:])
        try:
            return subprocess.run(
                argv,
                input=canonical_json_bytes(input_data) + b"\n",
                capture_output=True,
                cwd=bundle_path,
                pass_fds=(command_fd,),
                shell=False,
                check=False,
            )
        except OSError as exc:
            raise GateError(
                "command_start_failed",
                command_argv[0],
                f"cannot start command: {exc}",
            ) from exc
    finally:
        os.close(command_fd)


def _reject_command_terminal_state(
    response_path: Path,
    cancellation_path: Path,
    *,
    target: str,
) -> None:
    if not response_path.exists() and not cancellation_path.exists():
        return
    _remove_untrusted_terminal(response_path)
    _remove_untrusted_terminal(cancellation_path)
    raise GateError(
        "terminal_state_changed",
        target,
        "command may not create response.json or cancellation.json",
    )


def _decode_json_result(value: bytes) -> Any:
    return json.loads(value)


def _execute_extra(
    bundle_path: Path,
    extra: GateExtra,
    *,
    envelope: Mapping[str, Any],
    input_data: object,
    response_path: Path,
    cancellation_path: Path,
    choice_id: str,
    source: str,
) -> dict[str, Any]:
    try:
        completed = _run_owned_command(
            bundle_path,
            extra.command.argv,
            expected_hash=envelope["hashes"]["resources"][extra.command.argv[0]],
            input_data=input_data,
        )
        _reject_command_terminal_state(
            response_path,
            cancellation_path,
            target=extra.id,
        )
    except GateError as exc:
        return _extra_failure(
            bundle_path,
            extra,
            choice_id=choice_id,
            code=exc.code,
            message=str(exc),
            source=source,
        )
    stdout = _decode_output(completed.stdout)
    stderr = _decode_output(completed.stderr)
    if completed.returncode != 0:
        message = stderr or f"command exited with status {completed.returncode}"
        return _extra_failure(
            bundle_path,
            extra,
            choice_id=choice_id,
            code="command_failed",
            message=message,
            source=source,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    try:
        result = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _extra_failure(
            bundle_path,
            extra,
            choice_id=choice_id,
            code="invalid_command_output",
            message="command stdout must contain one JSON value",
            source=source,
            stdout=stdout,
            stderr=stderr,
        )
    return {"id": extra.id, "status": "succeeded", "result": result}


def _extra_failure(
    bundle_path: Path,
    extra: GateExtra,
    *,
    choice_id: str,
    code: str,
    message: str,
    source: str,
    returncode: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
) -> dict[str, Any]:
    _record_execution_error(
        bundle_path,
        choice_id=choice_id,
        extra_id=extra.id,
        code=code,
        message=message,
        source=source,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
    return {
        "id": extra.id,
        "status": "failed",
        "error": {
            "code": code,
            "message": message,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        },
    }


def _validate_json_instance(value: object, schema: dict[str, Any], target: str) -> None:
    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

        Draft202012Validator(schema).validate(value)
    except Exception as exc:
        raise GateError("schema_validation_failed", target, str(exc)) from exc


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        block = os.read(fd, 1024 * 1024)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()


def _decode_output(value: bytes, *, limit: int = 16_384) -> str:
    return value[:limit].decode("utf-8", errors="replace").strip()


def _remove_untrusted_terminal(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def _record_execution_error(
    bundle_path: Path,
    *,
    choice_id: str,
    extra_id: str | None = None,
    code: str,
    message: str,
    source: str,
    returncode: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
) -> None:
    errors = bundle_path / "errors"
    payload = {
        "schema_version": GATE_RESPONSE_SCHEMA_VERSION,
        "choice_id": choice_id,
        "extra_id": extra_id,
        "code": code,
        "message": message,
        "source": source,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "created_at_unix": time.time(),
    }
    atomic_write_json(errors / f"{time.time_ns()}-{uuid4().hex}.json", payload)


def _mark_pending_handled(
    envelope: Mapping[str, Any], response: Mapping[str, Any], *, source: str
) -> None:
    notification_id = envelope.get("notification_id")
    if not isinstance(notification_id, str) or not notification_id:
        return
    from sase.notifications.pending_actions import mark_already_handled

    mark_already_handled(
        notification_id,
        source=source,
        action=str(response.get("choice_id") or "resolved"),
    )


__all__ = ["cancel_gate", "execute_gate_choice"]
