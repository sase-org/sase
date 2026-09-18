"""Detached sudo answer path and internal finalize proc."""

from __future__ import annotations

import argparse
import math
import signal
import sys
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from sase.gate_shell.store import find_gate_shell_by_gate_id
from sase.notification_gates.cli_support import emit_json, resolve_gate_cli_bundle
from sase.notification_gates.command_runner import record_execution_error
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.journal import append_journal_event
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import RESPONSE_FILENAME
from sase.ops.cli import emit_operation_result, load_request
from sase.ops.errors import OperationIOError
from sase.ops.names import SUDO_FINALIZE
from sase.procs.request import ProcSubmitRequest
from sase.procs.submission import ProcSubmitError, submit_proc_request
from sase.sudo.answer_ops import (
    answer_payload,
    apply_approved_receipt,
    error_exit_code,
    error_payload,
    print_answer,
    resolve_sudo_gate_id,
    runner_timeout_seconds,
    settle_shell,
    sudo_payload,
)
from sase.sudo.core import DEFAULT_SUDO_CORE
from sase.sudo.execution import (
    LOG_FILENAME,
    MANIFEST_FILENAME,
    SudoExecutionState,
    claim_execution_record,
    clear_execution_state,
    cleanup_handoff,
    copy_output_log,
    create_handoff_dir,
    execution_is_live,
    execution_lock,
    executor_is_live,
    handshake_from_runner_payload,
    live_execution_error,
    load_execution_state,
    read_handoff_ledger,
    recover_dead_attempt,
    write_execution_state,
    write_stop_file,
)
from sase.sudo.gate import APPROVE_OPTION_ID
from sase.sudo.lease import sudo_auth_lease
from sase.sudo.manifest import selected_sudo_manifest
from sase.sudo.runner import run_sudo_runner_detached
from sase.sudo.ssh import (
    cleanup_remote_sudo,
    run_remote_sudo_detached,
    wait_for_remote_sudo_ledger,
)

SUDO_ANSWER_DETACH_ORIGIN = "sudo-answer-detach"
_EXECUTOR_DEATH_GRACE_SECONDS = 1.0
_OUTPUT_POLL_SECONDS = 0.05
_STOP_GRACE_SECONDS = 5.0


def approve_detached(
    bundle: Any,
    manifest: Mapping[str, Any],
    *,
    selected_command_ids: tuple[str, ...],
    manifest_sha256: str,
    feedback: str | None,
    retry: Literal["resume", "restart"] | None,
) -> dict[str, Any]:
    """Authenticate, spawn the executor, and submit the finalize proc."""
    gate_id = bundle.request_id
    runner_payload: dict[str, Any] | None = None
    with sudo_auth_lease(
        request_id=gate_id,
        run_as=str(manifest.get("run_as") or "root"),
        cwd=str(manifest.get("cwd") or ""),
        command_ids=selected_command_ids,
    ):
        with execution_lock(bundle.root):
            existing = claim_execution_record(bundle.root, gate_id=gate_id)
            if existing is not None:
                raise live_execution_error(existing)
            handoff = create_handoff_dir(gate_id, manifest)
            state = SudoExecutionState(
                gate_id=gate_id,
                selected_command_ids=selected_command_ids,
                manifest_sha256=manifest_sha256,
                handoff_dir=str(handoff),
            )
            write_execution_state(bundle.root, state)
        try:
            runner_payload = run_sudo_runner_detached(
                handoff / MANIFEST_FILENAME,
                manifest_sha256=manifest_sha256,
                detach_dir=handoff,
                timeout_seconds=runner_timeout_seconds(manifest),
            )
            if handshake_from_runner_payload(runner_payload):
                handshake = DEFAULT_SUDO_CORE.validate_handshake(
                    runner_payload, dict(manifest)
                )
            else:
                recover_dead_attempt(bundle.root)
                return apply_approved_receipt(
                    bundle,
                    runner_payload,
                    selected_command_ids=selected_command_ids,
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    feedback=feedback,
                    retry=retry,
                )
        except Exception:
            _preserve_or_recover_attempt(bundle.root, runner_payload=runner_payload)
            raise
        with execution_lock(bundle.root):
            state = load_execution_state(bundle.root) or state
            state = replace(state, handshake=dict(handshake))
            write_execution_state(bundle.root, state)
            try:
                proc = _submit_finalize_proc(
                    bundle,
                    manifest,
                    state=state,
                    handshake=handshake,
                    feedback=feedback,
                    retry=retry,
                )
            except Exception:
                write_execution_state(bundle.root, state)
                raise
            state = replace(state, finalize_proc_id=proc.proc_id)
            write_execution_state(bundle.root, state)
    return {
        "kind": bundle.kind,
        "proc_id": proc.proc_id,
        "request_id": gate_id,
        "selected_command_ids": list(selected_command_ids),
        "status": "execution_started",
    }


def approve_remote_detached(
    bundle: Any,
    host: str,
    manifest: Mapping[str, Any],
    *,
    selected_command_ids: tuple[str, ...],
    manifest_sha256: str,
    feedback: str | None,
    retry: Literal["resume", "restart"] | None,
) -> dict[str, Any]:
    """Authenticate over SSH, start a remote executor, and submit finalize."""
    gate_id = bundle.request_id
    runner_payload: dict[str, Any] | None = None
    remote_paths: dict[str, Any] | None = None
    with sudo_auth_lease(
        request_id=gate_id,
        run_as=str(manifest.get("run_as") or "root"),
        cwd=str(manifest.get("cwd") or ""),
        command_ids=selected_command_ids,
    ):
        with execution_lock(bundle.root):
            existing = claim_execution_record(bundle.root, gate_id=gate_id)
            if existing is not None:
                raise live_execution_error(existing)
            handoff = create_handoff_dir(gate_id, manifest)
            state = SudoExecutionState(
                gate_id=gate_id,
                selected_command_ids=selected_command_ids,
                manifest_sha256=manifest_sha256,
                handoff_dir=str(handoff),
            )
            write_execution_state(bundle.root, state)
        try:
            runner_payload, remote_paths = run_remote_sudo_detached(
                host,
                manifest,
                manifest_sha256=manifest_sha256,
                timeout_seconds=runner_timeout_seconds(manifest),
            )
            if handshake_from_runner_payload(runner_payload):
                handshake = DEFAULT_SUDO_CORE.validate_handshake(
                    runner_payload, dict(manifest)
                )
            else:
                recover_dead_attempt(bundle.root)
                return apply_approved_receipt(
                    bundle,
                    runner_payload,
                    selected_command_ids=selected_command_ids,
                    manifest=manifest,
                    manifest_sha256=manifest_sha256,
                    feedback=feedback,
                    retry=retry,
                )
        except Exception:
            _preserve_or_recover_attempt(bundle.root, runner_payload=runner_payload)
            raise
        with execution_lock(bundle.root):
            state = load_execution_state(bundle.root) or state
            state = replace(state, handshake=dict(handshake))
            write_execution_state(bundle.root, state)
            try:
                proc = _submit_finalize_proc(
                    bundle,
                    manifest,
                    state=state,
                    handshake=handshake,
                    feedback=feedback,
                    retry=retry,
                    remote={"host": host, "paths": dict(remote_paths or {})},
                )
            except Exception:
                write_execution_state(bundle.root, state)
                raise
            state = replace(state, finalize_proc_id=proc.proc_id)
            write_execution_state(bundle.root, state)
    return {
        "kind": bundle.kind,
        "proc_id": proc.proc_id,
        "request_id": gate_id,
        "selected_command_ids": list(selected_command_ids),
        "status": "execution_started",
    }


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


def _preserve_or_recover_attempt(
    bundle_root: Path,
    *,
    runner_payload: Mapping[str, Any] | None,
) -> None:
    state = load_execution_state(bundle_root)
    if state is None:
        return
    handshake = state.handshake
    if handshake is None and runner_payload is not None:
        pid = runner_payload.get("executor_pid")
        identity = runner_payload.get("executor_identity")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            handshake = {
                "executor_pid": pid,
                "executor_identity": identity if isinstance(identity, str) else "",
            }
            write_execution_state(bundle_root, replace(state, handshake=handshake))
            state = replace(state, handshake=handshake)
    if execution_is_live(state):
        return
    recover_dead_attempt(bundle_root)


def _submit_finalize_proc(
    bundle: Any,
    manifest: Mapping[str, Any],
    *,
    state: SudoExecutionState,
    handshake: Mapping[str, Any],
    feedback: str | None,
    retry: Literal["resume", "restart"] | None,
    remote: Mapping[str, Any] | None = None,
) -> Any:
    payload: dict[str, Any] = {
        "gate_id": state.gate_id,
        "handoff_dir": state.handoff_dir,
        "handshake": dict(handshake),
        "manifest_sha256": state.manifest_sha256,
        "selected_command_ids": list(state.selected_command_ids),
    }
    if feedback is not None:
        payload["feedback"] = feedback
    if retry is not None:
        payload["retry"] = retry
    if remote is not None:
        payload["remote"] = dict(remote)
    shell = find_gate_shell_by_gate_id(None, state.gate_id)
    try:
        return submit_proc_request(
            ProcSubmitRequest(
                argv=["sase", "sudo", "finalize", state.gate_id, "--json"],
                label=_sudo_run_label(manifest, state.gate_id),
                cwd=str(Path.cwd()),
                origin=SUDO_ANSWER_DETACH_ORIGIN,
                project=None if shell is None else shell.project_name,
                shell_kind="gate",
                timeout_seconds=_proc_timeout_seconds(manifest),
                operation=SUDO_FINALIZE,
                operation_payload=payload,
            )
        )
    except ProcSubmitError as exc:
        raise GateError(
            "proc_submit_failed",
            "sudo.finalize",
            f"could not submit sudo finalize proc: {exc}",
        ) from exc


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
        remote = _finalize_remote(payload)
        if remote is None:
            receipt = _wait_for_executor_ledger(
                handoff,
                handshake=handshake,
                timeout_seconds=runner_timeout_seconds(manifest),
            )
        else:
            receipt = wait_for_remote_sudo_ledger(
                remote["host"],
                remote["paths"],
                handshake=handshake,
                timeout_seconds=runner_timeout_seconds(manifest),
            )
        result = apply_approved_receipt(
            bundle,
            receipt,
            selected_command_ids=selected_command_ids,
            manifest=manifest,
            manifest_sha256=manifest_sha256,
            feedback=feedback,
            retry=retry,
        )
    except GateError as exc:
        _record_finalize_failure(bundle.root, exc)
        recover_dead_attempt(bundle.root)
        raise
    if remote is not None:
        cleanup_remote_sudo(remote["host"], remote["paths"])
    with execution_lock(bundle.root):
        cleanup_handoff(handoff)
        clear_execution_state(bundle.root)
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
            cleanup_handoff(Path(state.handoff_dir))
            clear_execution_state(bundle.root)
    return answer_payload(
        bundle.kind, bundle.request_id, response, selected_command_ids=selected
    )


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


def _wait_for_executor_ledger(
    handoff: Path,
    *,
    handshake: Mapping[str, Any],
    timeout_seconds: float | None,
) -> dict[str, Any]:
    """Stream output.log and wait for ledger.json or a terminal failure."""
    timeout = 330.0 if timeout_seconds is None else max(0.0, float(timeout_seconds))
    deadline = time.monotonic() + timeout
    stop_deadline: float | None = None
    offset = 0
    log_path = handoff / LOG_FILENAME

    def _on_stop(_signum: int, _frame: object | None) -> None:
        nonlocal stop_deadline
        write_stop_file(handoff)
        if stop_deadline is None:
            stop_deadline = time.monotonic() + _STOP_GRACE_SECONDS

    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)
    try:
        while True:
            offset = copy_output_log(log_path, offset=offset, dest=sys.stdout)
            ledger = read_handoff_ledger(handoff)
            if ledger is not None:
                copy_output_log(log_path, offset=offset, dest=sys.stdout)
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
            if handshake and not executor_is_live(handshake):
                death_deadline = time.monotonic() + _EXECUTOR_DEATH_GRACE_SECONDS
                while time.monotonic() < death_deadline:
                    offset = copy_output_log(log_path, offset=offset, dest=sys.stdout)
                    ledger = read_handoff_ledger(handoff)
                    if ledger is not None:
                        copy_output_log(log_path, offset=offset, dest=sys.stdout)
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


def _proc_timeout_seconds(manifest: Mapping[str, Any]) -> int | None:
    value = runner_timeout_seconds(manifest)
    if value is None:
        return None
    return max(1, math.ceil(value))


def _sudo_run_label(manifest: Mapping[str, Any], gate_id: str) -> str:
    commands = manifest.get("commands")
    argv0 = "sudo"
    if isinstance(commands, list) and commands:
        first = commands[0]
        if isinstance(first, Mapping):
            argv = first.get("argv")
            if isinstance(argv, list) and argv:
                argv0 = Path(str(argv[0])).name or str(argv[0])
    return f"Sudo run: {argv0} ({gate_id})"


__all__ = [
    "SUDO_ANSWER_DETACH_ORIGIN",
    "approve_detached",
    "approve_remote_detached",
    "finalize",
]
