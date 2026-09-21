"""Internal ``sase sudo finalize`` proc: wait for the executor, settle the gate.

Shared helpers that callers monkeypatch on ``sase.sudo.detach`` (ledger
readers, timeouts, timing constants) are resolved through a function-level
import of that facade module, so ``sase.sudo.detach.<name>`` remains the seam.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from sase.notification_gates.cli_support import emit_json, resolve_gate_cli_bundle
from sase.notification_gates.command_runner import record_execution_error
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.journal import append_journal_event
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import RESPONSE_FILENAME
from sase.ops.cli import emit_operation_result, load_request
from sase.ops.errors import OperationIOError
from sase.ops.names import SUDO_FINALIZE
from sase.sudo.answer_ops import (
    answer_payload,
    apply_approved_receipt,
    error_exit_code,
    error_payload,
    operation_payload_digest,
    print_answer,
    resolve_sudo_gate_id,
    settle_shell,
    sudo_payload,
)
from sase.sudo.core import DEFAULT_SUDO_CORE
from sase.sudo.execution import (
    LOG_FILENAME,
    SudoExecutionState,
    cleanup_handoff,
    clear_execution_state,
    execution_lock,
    load_execution_state,
    recover_dead_attempt,
    write_execution_state,
    write_stop_file,
)
from sase.sudo.gate import APPROVE_OPTION_ID
from sase.sudo.manifest import selected_sudo_manifest
from sase.sudo.ssh import cleanup_remote_sudo, wait_for_remote_sudo_ledger

_OUTPUT_POLL_SECONDS = 0.05


def finalize(args: argparse.Namespace) -> int:
    """Internal ``sase sudo finalize`` handler."""
    gate_id = str(getattr(args, "gate_ref", "") or "sudo")
    try:
        payload = _run_finalize(args)
    except OperationIOError as exc:
        error = GateError("invalid_sudo_finalize", "operation", str(exc))
        return _finalize_failure(args, gate_id, error)
    except GateError as exc:
        return _finalize_failure(args, gate_id, exc)
    emit_operation_result(
        operation=SUDO_FINALIZE,
        success=True,
        message=f"Sudo gate {payload.get('request_id', gate_id)} answered",
        payload=payload,
        args=args,
    )
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        print_answer(payload)
    return 0


def _finalize_failure(args: argparse.Namespace, gate_id: str, exc: GateError) -> int:
    emit_operation_result(
        operation=SUDO_FINALIZE,
        success=False,
        message=str(exc),
        error=str(exc),
        payload=error_payload(gate_id, exc),
        args=args,
    )
    if bool(getattr(args, "json", False)):
        emit_json(error_payload(gate_id, exc))
        return error_exit_code(exc)
    raise exc


def _run_finalize(args: argparse.Namespace) -> dict[str, Any]:
    from sase.sudo import detach as facade

    gate_id = resolve_sudo_gate_id(str(args.gate_ref))
    request = load_request(SUDO_FINALIZE, args, required=True)
    payload = dict(request.payload)
    bundle = resolve_gate_cli_bundle("sudo", gate_id)
    response_path = bundle.root / RESPONSE_FILENAME
    state = load_execution_state(bundle.root)
    retry = _finalize_retry(payload)
    feedback = _finalize_feedback(payload)
    if response_path.is_file():
        return _finalize_existing_response(
            bundle, state=state, payload=payload, retry=retry
        )
    if state is None:
        raise GateError(
            "missing_sudo_execution_state",
            gate_id,
            "sudo finalize is missing an in-flight execution record",
        )
    _cross_check_finalize_payload(payload, gate_id=gate_id, state=state)
    if state.operation_payload_digest is not None:
        actual_digest = operation_payload_digest(payload)
        if actual_digest != state.operation_payload_digest:
            raise GateError(
                "invalid_sudo_finalize",
                "operation_payload_digest",
                "finalize operation payload digest does not match the execution record",
            )
    handshake = dict(state.handshake or {})
    if payload.get("handshake") and not handshake:
        raw = payload.get("handshake")
        handshake = dict(raw) if isinstance(raw, Mapping) else handshake
    handoff = Path(state.handoff_dir)
    selected_command_ids = state.selected_command_ids
    envelope_payload = sudo_payload(bundle.envelope)
    manifest, _, manifest_sha256 = selected_sudo_manifest(
        dict(envelope_payload["manifest"]),
        selected_command_ids,
    )
    if manifest_sha256 != state.manifest_sha256:
        raise GateError(
            "invalid_sudo_finalize",
            "manifest_sha256",
            "finalize sidecar manifest digest does not match the execution record",
        )
    try:
        remote = _finalize_remote_from_state(state, payload)
        if remote is None:
            receipt = wait_for_executor_ledger(
                handoff,
                handshake=handshake,
                timeout_seconds=facade.runner_timeout_seconds(manifest),
            )
        else:
            receipt = wait_for_remote_sudo_ledger(
                remote["host"],
                remote["paths"],
                handshake=handshake,
                timeout_seconds=facade.runner_timeout_seconds(manifest),
            )
        authorization = _authorize_finalize_settlement(
            bundle.root,
            state=state,
            payload=payload,
            receipt=receipt,
            handshake=handshake,
        )
        result = apply_approved_receipt(
            bundle,
            receipt,
            selected_command_ids=selected_command_ids,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            feedback=feedback,
            retry=retry,
            settlement_authorization=authorization,
        )
    except GateError as exc:
        _record_finalize_failure(bundle.root, exc)
        recover_dead_attempt(bundle.root)
        raise
    _retire_after_settlement(bundle.root, state=state, remote=remote)
    return result


def _finalize_existing_response(
    bundle: Any,
    *,
    state: SudoExecutionState | None,
    payload: Mapping[str, Any],
    retry: Literal["resume", "restart"] | None,
) -> dict[str, Any]:
    response = read_json_object(bundle.response_path)
    selected = tuple(
        str(item)
        for item in (
            (state.selected_command_ids if state is not None else None)
            or payload.get("selected_command_ids")
            or ()
        )
    )
    settle_shell(bundle.request_id, retry=retry)
    if state is not None:
        with execution_lock(bundle.root):
            write_execution_state(bundle.root, replace(state, startup_state="settled"))
        _retire_after_settlement(
            bundle.root,
            state=replace(state, startup_state="settled"),
            remote=_finalize_remote_from_state(state, payload),
        )
    return answer_payload(
        bundle.kind, bundle.request_id, response, selected_command_ids=selected
    )


def _authorize_finalize_settlement(
    bundle_root: Path,
    *,
    state: SudoExecutionState,
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    handshake: Mapping[str, Any],
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "attempt": state.to_dict(),
        "ledger": dict(receipt),
    }
    if handshake:
        request["handshake"] = dict(handshake)
    if state.operation_payload_digest is not None:
        request["operation_payload_digest"] = operation_payload_digest(payload)
    authorization = DEFAULT_SUDO_CORE.authorize_settlement(request)
    authorization_id = authorization.get("authorization_id")
    if not isinstance(authorization_id, str) or not authorization_id:
        raise GateError(
            "invalid_sudo_finalize",
            "authorization_id",
            "sudo settlement authorization did not include an authorization id",
        )
    with execution_lock(bundle_root):
        current = load_execution_state(bundle_root) or state
        write_execution_state(
            bundle_root,
            replace(
                current,
                authorization_id=authorization_id,
                startup_state="settling",
            ),
        )
    return authorization


def _cross_check_finalize_payload(
    payload: Mapping[str, Any],
    *,
    gate_id: str,
    state: SudoExecutionState,
) -> None:
    payload_gate = payload.get("gate_id")
    if payload_gate is not None and str(payload_gate) != gate_id:
        raise GateError(
            "invalid_sudo_finalize",
            "gate_id",
            "finalize sidecar gate id does not match the execution record",
        )
    handoff = payload.get("handoff_dir")
    if handoff is not None and str(handoff) != state.handoff_dir:
        raise GateError(
            "invalid_sudo_finalize",
            "handoff_dir",
            "finalize sidecar handoff directory does not match the execution record",
        )
    digest = payload.get("manifest_sha256")
    if digest is not None and str(digest) != state.manifest_sha256:
        raise GateError(
            "invalid_sudo_finalize",
            "manifest_sha256",
            "finalize sidecar manifest digest does not match the execution record",
        )
    selected = payload.get("selected_command_ids")
    if selected is not None:
        if not isinstance(selected, list) or tuple(str(item) for item in selected) != (
            state.selected_command_ids
        ):
            raise GateError(
                "invalid_sudo_finalize",
                "selected_command_ids",
                "finalize sidecar command ids do not match the execution record",
            )
    handshake = payload.get("handshake")
    recorded = state.handshake or {}
    if handshake is not None:
        if not isinstance(handshake, Mapping):
            raise GateError(
                "invalid_sudo_finalize",
                "handshake",
                "finalize sidecar handshake must be an object",
            )
        for key in ("executor_pid", "executor_identity"):
            if handshake.get(key) != recorded.get(key):
                raise GateError(
                    "invalid_sudo_finalize",
                    key,
                    "finalize sidecar handshake does not match the execution record",
                )


def _finalize_retry(
    payload: Mapping[str, Any],
) -> Literal["resume", "restart"] | None:
    retry = payload.get("retry")
    if retry in {None, "resume", "restart"}:
        return retry
    raise GateError(
        "invalid_sudo_finalize",
        "retry",
        "finalize sidecar retry must be resume or restart",
    )


def _finalize_feedback(payload: Mapping[str, Any]) -> str | None:
    feedback = payload.get("feedback")
    if feedback is None:
        return None
    return str(feedback)


def _finalize_remote(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    remote = payload.get("remote")
    if remote is None:
        return None
    if not isinstance(remote, Mapping):
        raise GateError(
            "invalid_sudo_finalize",
            "remote",
            "finalize sidecar remote metadata must be an object",
        )
    host = remote.get("host")
    paths = remote.get("paths")
    if not isinstance(host, str) or not host:
        raise GateError(
            "invalid_sudo_finalize",
            "remote.host",
            "finalize sidecar remote host is required",
        )
    if not isinstance(paths, Mapping):
        raise GateError(
            "invalid_sudo_finalize",
            "remote.paths",
            "finalize sidecar remote paths must be an object",
        )
    return {"host": host, "paths": dict(paths)}


def _finalize_remote_from_state(
    state: SudoExecutionState,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    sidecar = _finalize_remote(payload)
    if state.target_kind == "remote" and state.target_host and state.remote_handoff:
        recorded = {"host": state.target_host, "paths": dict(state.remote_handoff)}
        if sidecar is not None:
            if sidecar["host"] != recorded["host"]:
                raise GateError(
                    "invalid_sudo_finalize",
                    "remote.host",
                    "finalize sidecar remote host does not match the execution record",
                )
        return recorded
    return sidecar


def _retire_after_settlement(
    bundle_root: Path,
    *,
    state: SudoExecutionState,
    remote: Mapping[str, Any] | None,
) -> None:
    cleaned = True
    if remote is not None:
        cleaned = cleanup_remote_sudo(str(remote["host"]), remote["paths"])
    with execution_lock(bundle_root):
        current = load_execution_state(bundle_root) or state
        if not cleaned:
            write_execution_state(
                bundle_root, replace(current, startup_state="settled")
            )
            return
        cleanup_handoff(Path(current.handoff_dir))
        clear_execution_state(bundle_root)


def wait_for_executor_ledger(
    handoff: Path,
    *,
    handshake: Mapping[str, Any],
    timeout_seconds: float | None,
) -> dict[str, Any]:
    """Stream output.log and wait for ledger.json or a terminal failure."""
    from sase.sudo import detach as facade

    timeout = 330.0 if timeout_seconds is None else max(0.0, float(timeout_seconds))
    deadline = time.monotonic() + timeout
    stop_deadline: float | None = None
    offset = 0
    log_path = handoff / LOG_FILENAME

    def _on_stop(_signum: int, _frame: object | None) -> None:
        nonlocal stop_deadline
        write_stop_file(handoff)
        if stop_deadline is None:
            stop_deadline = time.monotonic() + facade._STOP_GRACE_SECONDS

    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)
    try:
        while True:
            offset = facade.copy_output_log(log_path, offset=offset, dest=sys.stdout)
            ledger = facade.read_handoff_ledger(handoff)
            if ledger is not None:
                facade.copy_output_log(log_path, offset=offset, dest=sys.stdout)
                return ledger
            now = time.monotonic()
            if stop_deadline is not None and now >= stop_deadline:
                raise GateError(
                    "killed",
                    "sudo.finalize",
                    "sudo finalize was stopped; the gate remains pending",
                )
            if now >= deadline:
                raise GateError(
                    "timeout",
                    "sudo.finalize",
                    "sudo executor timed out; the gate remains pending",
                )
            if handshake and not facade.executor_is_live(handshake):
                death_deadline = time.monotonic() + facade._EXECUTOR_DEATH_GRACE_SECONDS
                while time.monotonic() < death_deadline:
                    offset = facade.copy_output_log(
                        log_path, offset=offset, dest=sys.stdout
                    )
                    ledger = facade.read_handoff_ledger(handoff)
                    if ledger is not None:
                        facade.copy_output_log(log_path, offset=offset, dest=sys.stdout)
                        return ledger
                    time.sleep(_OUTPUT_POLL_SECONDS)
                raise GateError(
                    "executor_died",
                    "sudo.finalize",
                    "sudo executor exited without a ledger; the gate remains pending",
                )
            time.sleep(_OUTPUT_POLL_SECONDS)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


def _record_finalize_failure(bundle_root: Path, exc: GateError) -> None:
    error_record = record_execution_error(
        bundle_root,
        option_id=APPROVE_OPTION_ID,
        code=exc.code,
        message=str(exc),
        source="sudo_finalize",
        stage="command",
    )
    append_journal_event(
        bundle_root,
        attempt_id="sudo_finalize",
        request_hash="",
        event="operation_ran",
        operation_id="sudo_finalize",
        option_id=APPROVE_OPTION_ID,
        code=exc.code,
        message=str(exc),
        error_record=error_record,
        stage="command",
    )


__all__ = [
    "finalize",
    "wait_for_executor_ledger",
]
