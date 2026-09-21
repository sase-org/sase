"""Detached sudo approve path: spawn the executor and submit the finalize proc.

Shared helpers that callers monkeypatch on ``sase.sudo.detach`` (runner entry
points, proc submission, timeouts) are resolved through a function-level import
of that facade module, so ``sase.sudo.detach.<name>`` remains the seam.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from sase.gate_shell.store import find_gate_shell_by_gate_id
from sase.notification_gates.models import GateError
from sase.ops.names import SUDO_FINALIZE
from sase.procs.request import ProcSubmitRequest
from sase.procs.submission import ProcSubmitError
from sase.sudo.answer_ops import apply_approved_receipt, operation_payload_digest
from sase.sudo.core import DEFAULT_SUDO_CORE
from sase.sudo.execution import (
    MANIFEST_FILENAME,
    SudoExecutionState,
    abandon_unstarted_attempt,
    claim_execution_record,
    create_handoff_dir,
    execution_is_live,
    execution_lock,
    handshake_from_runner_payload,
    live_execution_error,
    load_execution_state,
    recover_dead_attempt,
    write_execution_state,
)
from sase.sudo.lease import sudo_auth_lease
from sase.sudo.ssh import PRE_SPAWN_REMOTE_ERROR_CODES, allocate_remote_sudo_paths

SUDO_ANSWER_DETACH_ORIGIN = "sudo-answer-detach"


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
    from sase.sudo import detach as facade

    gate_id = bundle.request_id
    runner_payload: dict[str, Any] | None = None
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
            target_kind="local",
            startup_state="reserved",
        )
        write_execution_state(bundle.root, state)
    proc: Any
    with execution_lock(bundle.root):
        write_execution_state(
            bundle.root, replace(state, startup_state="authenticating")
        )
    with sudo_auth_lease(
        request_id=gate_id,
        run_as=str(manifest.get("run_as") or "root"),
        cwd=str(manifest.get("cwd") or ""),
        command_ids=selected_command_ids,
    ):
        try:
            with execution_lock(bundle.root):
                write_execution_state(
                    bundle.root, replace(state, startup_state="starting")
                )
            runner_payload = facade.run_sudo_runner_detached(
                handoff / MANIFEST_FILENAME,
                manifest_sha256=manifest_sha256,
                detach_dir=handoff,
                timeout_seconds=facade.runner_timeout_seconds(manifest),
            )
            if handshake_from_runner_payload(runner_payload):
                handshake = DEFAULT_SUDO_CORE.validate_handshake(
                    runner_payload, dict(manifest)
                )
            else:
                with execution_lock(bundle.root):
                    write_execution_state(
                        bundle.root, replace(state, startup_state="terminal")
                    )
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
            state = replace(state, handshake=dict(handshake), startup_state="started")
            write_execution_state(bundle.root, state)
            try:
                proc, operation_payload_digest = _submit_finalize_proc(
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
            state = replace(
                state,
                finalize_proc_id=proc.proc_id,
                operation_payload_digest=operation_payload_digest,
            )
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
    from sase.sudo import detach as facade

    gate_id = bundle.request_id
    runner_payload: dict[str, Any] | None = None
    remote_paths = allocate_remote_sudo_paths()
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
            target_kind="remote",
            target_host=host,
            startup_state="reserved",
            remote_handoff=dict(remote_paths),
        )
        write_execution_state(bundle.root, state)
    proc: Any
    with execution_lock(bundle.root):
        write_execution_state(
            bundle.root, replace(state, startup_state="authenticating")
        )
    with sudo_auth_lease(
        request_id=gate_id,
        run_as=str(manifest.get("run_as") or "root"),
        cwd=str(manifest.get("cwd") or ""),
        command_ids=selected_command_ids,
    ):
        try:
            with execution_lock(bundle.root):
                write_execution_state(
                    bundle.root, replace(state, startup_state="starting")
                )
            runner_payload, remote_paths = facade.run_remote_sudo_detached(
                host,
                manifest,
                manifest_sha256=manifest_sha256,
                timeout_seconds=facade.runner_timeout_seconds(manifest),
                paths=remote_paths,
            )
            if handshake_from_runner_payload(runner_payload):
                handshake = DEFAULT_SUDO_CORE.validate_handshake(
                    runner_payload, dict(manifest)
                )
            else:
                with execution_lock(bundle.root):
                    write_execution_state(
                        bundle.root, replace(state, startup_state="terminal")
                    )
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
        except Exception as exc:
            _preserve_or_recover_attempt(
                bundle.root, runner_payload=runner_payload, error=exc
            )
            raise
        with execution_lock(bundle.root):
            state = load_execution_state(bundle.root) or state
            state = replace(
                state,
                handshake=dict(handshake),
                startup_state="started",
                remote_handoff=dict(state.remote_handoff or remote_paths),
            )
            write_execution_state(bundle.root, state)
            try:
                proc, operation_payload_digest = _submit_finalize_proc(
                    bundle,
                    manifest,
                    state=state,
                    handshake=handshake,
                    feedback=feedback,
                    retry=retry,
                    remote={
                        "host": host,
                        "paths": dict(state.remote_handoff or remote_paths),
                    },
                )
            except Exception:
                write_execution_state(bundle.root, state)
                raise
            state = replace(
                state,
                finalize_proc_id=proc.proc_id,
                operation_payload_digest=operation_payload_digest,
            )
            write_execution_state(bundle.root, state)
    return {
        "kind": bundle.kind,
        "proc_id": proc.proc_id,
        "request_id": gate_id,
        "selected_command_ids": list(selected_command_ids),
        "status": "execution_started",
    }


def _preserve_or_recover_attempt(
    bundle_root: Path,
    *,
    runner_payload: Mapping[str, Any] | None,
    error: BaseException | None = None,
) -> None:
    if isinstance(error, GateError) and error.code in PRE_SPAWN_REMOTE_ERROR_CODES:
        abandon_unstarted_attempt(bundle_root)
        return
    state = load_execution_state(bundle_root)
    if state is None:
        return
    if state.handshake is None and runner_payload is not None:
        if handshake_from_runner_payload(runner_payload):
            state = replace(
                state, handshake=dict(runner_payload), startup_state="started"
            )
            write_execution_state(bundle_root, state)
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
) -> tuple[Any, str]:
    from sase.sudo import detach as facade

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
    payload_digest = operation_payload_digest(payload)
    shell = find_gate_shell_by_gate_id(None, state.gate_id)
    try:
        proc = facade.submit_proc_request(
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
        return proc, payload_digest
    except ProcSubmitError as exc:
        raise GateError(
            "proc_submit_failed",
            "sudo.finalize",
            f"could not submit sudo finalize proc: {exc}",
        ) from exc


def _proc_timeout_seconds(manifest: Mapping[str, Any]) -> int | None:
    from sase.sudo import detach as facade

    value = facade.runner_timeout_seconds(manifest)
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
]
