"""Trusted host execution and terminal persistence for notification gates."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Mapping
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
    source: str = "host",
) -> GateExecutionResult:
    """Run one hash-verified terminal choice and persist a write-once response."""
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
        command_path = owned_resource_path(bundle_path, choice.command.argv[0])
        command_fd = open_regular_nofollow(command_path)
        try:
            expected_hash = envelope["hashes"]["resources"][choice.command.argv[0]]
            if _sha256_fd(command_fd) != expected_hash:
                raise GateError(
                    "hash_mismatch",
                    choice.command.argv[0],
                    "command changed before execution",
                )
            os.lseek(command_fd, 0, os.SEEK_SET)
            argv = (f"/proc/self/fd/{command_fd}", *choice.command.argv[1:])
            try:
                completed = subprocess.run(
                    argv,
                    input=canonical_json_bytes(normalized_input) + b"\n",
                    capture_output=True,
                    cwd=bundle_path,
                    pass_fds=(command_fd,),
                    shell=False,
                    check=False,
                )
            except OSError as exc:
                _record_execution_error(
                    bundle_path,
                    choice_id=choice.id,
                    code="command_start_failed",
                    message=str(exc),
                    source=source,
                )
                raise GateError(
                    "command_start_failed", choice.id, f"cannot start command: {exc}"
                ) from exc
        finally:
            os.close(command_fd)

        if response_path.exists() or cancellation_path.exists():
            _remove_untrusted_terminal(response_path)
            _remove_untrusted_terminal(cancellation_path)
            _record_execution_error(
                bundle_path,
                choice_id=choice.id,
                code="terminal_state_changed",
                message="command attempted to create terminal gate state",
                source=source,
            )
            raise GateError(
                "terminal_state_changed",
                choice.id,
                "command may not create response.json or cancellation.json",
            )
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
            result = json.loads(completed.stdout)
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
        response: dict[str, Any] = {
            "schema_version": GATE_RESPONSE_SCHEMA_VERSION,
            "request_id": envelope["request_id"],
            "kind": adapter.kind,
            "choice_id": choice.id,
            "input": normalized_input,
            "result": result,
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
    for index, raw_choice in enumerate(choices):
        choice = GateChoice.from_mapping(raw_choice, index)
        if choice.id == choice_id:
            return choice
    raise GateError(
        "unknown_choice",
        choice_id,
        f"choice is not present in the request: {choice_id}",
    )


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
