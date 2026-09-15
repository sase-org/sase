"""Terminal front doors for typed sudo gates."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from rich.console import Console
from rich.table import Table

from sase.gate_shell.models import GateShellRefError, GateShellRecord
from sase.gate_shell.status import effective_gate_status, gate_status_pair
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.store import (
    find_gate_shell_by_gate_id,
    list_gate_shells,
    resolve_gate_shell_ref,
)
from sase.notification_gates.cli_support import (
    GateCliError,
    emit_json,
    resolve_gate_cli_bundle,
)
from sase.notification_gates.executor import execute_gate_selection, has_controlling_tty
from sase.notification_gates.models import GateError
from sase.sudo.feature import require_sudo_requests_enabled
from sase.sudo.gate import APPROVE_OPTION_ID, DENY_OPTION_ID, build_sudo_gate_request
from sase.sudo.lease import sudo_auth_lease
from sase.sudo.manifest import selected_sudo_manifest
from sase.sudo.receipt import validate_sudo_receipt
from sase.sudo.runner import run_sudo_runner, run_sudo_runner_file
from sase.sudo.ssh import run_remote_sudo


def handle_sudo_command(args: argparse.Namespace) -> int:
    """Dispatch one parsed sudo command."""
    subcommand = getattr(args, "sudo_subcommand", None)
    if subcommand == "answer":
        return _answer(args)
    try:
        require_sudo_requests_enabled("sudo")
        if subcommand == "exec":
            return _exec(args)
        if subcommand == "list":
            return _list(args)
        if subcommand == "request":
            return _request(args)
        if subcommand == "show":
            return _show(args)
    except GateError as exc:
        if bool(getattr(args, "json", False)) and subcommand in {"list", "show"}:
            emit_json(_error_payload(_raw_request_ref(args), exc))
            return _error_exit_code(exc)
        raise
    print("Usage: sase sudo {answer,exec,list,request,show}", file=sys.stderr)
    return 1


def _exec(args: argparse.Namespace) -> int:
    """Target-side manifest execution entrypoint for SSH handoffs."""
    if bool(getattr(args, "contract", False)):
        emit_json(
            {
                "schema_version": 1,
                "kind": "sase_sudo_exec",
                "sudo_manifest_schema_version": 1,
                "sudo_ledger_schema_version": 1,
            }
        )
        return 0
    manifest_path = getattr(args, "manifest", None)
    expected_sha256 = getattr(args, "expected_sha256", None)
    ledger_path = getattr(args, "ledger", None)
    if not manifest_path or not expected_sha256 or not ledger_path:
        raise GateError(
            "invalid_sudo_exec",
            "sudo.exec",
            "--manifest, --expected-sha256, and --ledger are required",
        )
    if not has_controlling_tty():
        raise GateError(
            "tty_required",
            "sudo.exec",
            "sudo target execution requires a controlling TTY",
        )
    ledger = run_sudo_runner_file(
        Path(str(manifest_path)),
        manifest_sha256=str(expected_sha256),
    )
    destination = Path(str(ledger_path))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(ledger, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def _request(args: argparse.Namespace) -> int:
    """Create a sudo gate shell from stdin."""
    value = _read_stdin_object()
    spec = build_sudo_gate_request(
        value,
        producer=(
            {"agent": str(args.origin_agent)}
            if getattr(args, "origin_agent", None)
            else None
        ),
    )
    from sase.gate_shell import (
        create_gate_shell,
        maybe_handoff_gate_from_agent,
        will_handoff_gate_to_agent_runner,
    )

    creation = create_gate_shell(spec)
    payload = creation.to_dict()
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        print(json.dumps(payload, sort_keys=True))
    sys.stdout.flush()
    if creation.should_handoff and will_handoff_gate_to_agent_runner():
        maybe_handoff_gate_from_agent(creation)
    return 0


def _answer(args: argparse.Namespace) -> int:
    raw_ref = str(args.gate_ref)
    gate_id = raw_ref
    try:
        require_sudo_requests_enabled("sudo")
        gate_id = _resolve_sudo_gate_id(raw_ref)
        decision = _decision(args)
        retry = _retry(args)
        if decision == "deny":
            payload = _deny(
                gate_id, feedback=getattr(args, "feedback", None), retry=retry
            )
        else:
            payload = _approve(
                gate_id,
                command_ids=_selected_command_ids(args),
                feedback=getattr(args, "feedback", None),
                retry=retry,
            )
    except GateError as exc:
        if not bool(getattr(args, "json", False)):
            raise
        emit_json(_error_payload(gate_id, exc))
        return _error_exit_code(exc)
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        _print_answer(payload)
    return 0


def _raw_request_ref(args: argparse.Namespace) -> str:
    ref = getattr(args, "gate_ref", None)
    if ref is not None:
        return str(ref)
    return "sudo"


def _selected_command_ids(args: argparse.Namespace) -> tuple[str, ...]:
    value = getattr(args, "sudo_command", None)
    if value is None:
        legacy_value = getattr(args, "command", None)
        value = legacy_value if isinstance(legacy_value, list) else None
    return tuple(value or ())


def _approve(
    gate_id: str,
    *,
    command_ids: tuple[str, ...],
    feedback: str | None,
    retry: Literal["resume", "restart"] | None,
) -> dict[str, Any]:
    if not has_controlling_tty():
        raise GateError(
            "tty_required",
            "approve",
            "sudo approval requires a controlling TTY; the gate remains pending",
        )
    bundle = resolve_gate_cli_bundle("sudo", gate_id)
    sudo_payload = _sudo_payload(bundle.envelope)
    manifest, selected_command_ids, manifest_sha256 = selected_sudo_manifest(
        dict(sudo_payload["manifest"]),
        command_ids,
    )
    target = sudo_payload.get("target")
    with sudo_auth_lease(
        request_id=gate_id,
        run_as=str(manifest.get("run_as") or "root"),
        cwd=str(manifest.get("cwd") or ""),
        command_ids=selected_command_ids,
    ):
        if isinstance(target, Mapping) and bool(target.get("remote")):
            host = str(target.get("host") or "")
            receipt = run_remote_sudo(
                host,
                manifest,
                manifest_sha256=manifest_sha256,
                timeout_seconds=_runner_timeout_seconds(manifest),
            )
        else:
            receipt = run_sudo_runner(
                manifest,
                manifest_sha256=manifest_sha256,
                timeout_seconds=_runner_timeout_seconds(manifest),
            )
    _reject_non_terminal_auth(receipt)
    normalized_receipt = validate_sudo_receipt(
        receipt,
        manifest_sha256=manifest_sha256,
        selected_command_ids=selected_command_ids,
        manifest=manifest,
    )
    execution = execute_gate_selection(
        bundle.root,
        [APPROVE_OPTION_ID],
        feedback=feedback,
        source="sudo_cli",
        retry=retry,
        option_inputs={
            APPROVE_OPTION_ID: {
                "command_ids": list(selected_command_ids),
                "receipt": normalized_receipt,
            }
        },
    )
    _settle_shell(gate_id, retry=retry)
    return _answer_payload(
        bundle.kind,
        gate_id,
        execution.response,
        selected_command_ids=selected_command_ids,
    )


def _deny(
    gate_id: str,
    *,
    feedback: str | None,
    retry: Literal["resume", "restart"] | None,
) -> dict[str, Any]:
    bundle = resolve_gate_cli_bundle("sudo", gate_id)
    execution = execute_gate_selection(
        bundle.root,
        [DENY_OPTION_ID],
        feedback=feedback,
        source="sudo_cli",
        retry=retry,
    )
    _settle_shell(gate_id, retry=retry)
    return _answer_payload(bundle.kind, gate_id, execution.response)


def _list(args: argparse.Namespace) -> int:
    rows = _sudo_shells(project=getattr(args, "project", None))
    if not getattr(args, "all", False):
        rows = [row for row in rows if not row.is_terminal]
    limit = getattr(args, "limit", None)
    if isinstance(limit, int) and limit >= 0:
        rows = rows[:limit]
    payload = {"gates": [_shell_payload(row) for row in rows]}
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        _print_list(rows)
    return 0


def _show(args: argparse.Namespace) -> int:
    gate_id = _resolve_sudo_gate_id(str(args.gate_ref))
    from sase.notification_gates.cli_show import print_human_gate, show_gate

    payload = show_gate("sudo", gate_id)
    bundle = resolve_gate_cli_bundle("sudo", gate_id)
    payload["sudo"] = _sudo_payload(bundle.envelope)
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        print_human_gate(payload)
    return 0


def _decision(args: argparse.Namespace) -> Literal["run", "deny"]:
    if bool(getattr(args, "approve", False)) or bool(getattr(args, "run", False)):
        return "run"
    if bool(getattr(args, "deny", False)):
        return "deny"
    if not has_controlling_tty():
        raise GateError(
            "tty_required",
            "answer",
            "choose --approve or --deny when not running interactively",
        )
    answer = input("Approve sudo request? [y/N] ").strip().lower()
    return "run" if answer in {"y", "yes"} else "deny"


def _retry(args: argparse.Namespace) -> Literal["resume", "restart"] | None:
    if bool(getattr(args, "resume", False)):
        return "resume"
    if bool(getattr(args, "restart", False)):
        return "restart"
    return None


def _reject_non_terminal_auth(receipt: Mapping[str, Any]) -> None:
    outcome = str(receipt.get("outcome") or "")
    code_by_outcome = {
        "auth_failed": "authentication_failed",
        "cancelled": "cancelled",
        "tty_unavailable": "tty_required",
        "runner_error": "runner_failed",
    }
    if outcome in code_by_outcome:
        code = code_by_outcome[outcome]
        raise GateError(
            code,
            "sase_sudo_runner",
            "sudo runner did not approve execution; the gate remains pending",
        )


def _sudo_payload(envelope: Mapping[str, Any]) -> dict[str, Any]:
    payload = envelope.get("payload")
    sudo_payload = payload.get("sudo") if isinstance(payload, Mapping) else None
    if not isinstance(sudo_payload, Mapping):
        raise GateError(
            "invalid_sudo_payload", "payload.sudo", "sudo payload is missing"
        )
    return dict(sudo_payload)


def _resolve_sudo_gate_id(ref: str) -> str:
    try:
        resolve_gate_cli_bundle("sudo", ref)
        return ref
    except GateCliError:
        pass
    try:
        record = resolve_gate_shell_ref(ref, _sudo_shells(project=None))
    except GateShellRefError as exc:
        raise GateError("not_found", ref, str(exc)) from exc
    return record.gate_id


def _sudo_shells(*, project: str | None) -> list[GateShellRecord]:
    return [row for row in list_gate_shells(project=project) if row.kind == "sudo"]


def _settle_shell(gate_id: str, *, retry: Literal["resume", "restart"] | None) -> None:
    gate_shell = find_gate_shell_by_gate_id(None, gate_id)
    if gate_shell is None:
        return
    settle_gate_shell(
        gate_shell,
        gate_state="answered",
        reason="sudo gate answered",
        resume=retry == "resume",
    )


def _answer_payload(
    kind: str,
    gate_id: str,
    response: Mapping[str, Any],
    *,
    selected_command_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    option_results = response.get("option_results", [])
    return {
        "kind": kind,
        "request_id": gate_id,
        "selected_option_ids": list(response.get("selected_option_ids", [])),
        "selected_command_ids": list(selected_command_ids),
        "option_results": option_results,
        "outcome": _response_outcome(option_results),
        "status": "answered",
    }


def _error_payload(gate_id: str, exc: GateError) -> dict[str, Any]:
    return {
        "request_id": gate_id,
        "status": "pending",
        "settled": False,
        "outcome": _error_outcome(exc.code),
        "code": exc.code,
        "target": exc.target,
        "message": str(exc),
    }


def _response_outcome(option_results: object) -> str:
    if isinstance(option_results, list):
        for option in option_results:
            if not isinstance(option, Mapping):
                continue
            result = option.get("result")
            if not isinstance(result, Mapping):
                continue
            ledger = result.get("ledger")
            if isinstance(ledger, list):
                for entry in ledger:
                    if isinstance(entry, Mapping) and entry.get("status") == "failed":
                        return "command_failed"
    return "completed"


def _error_outcome(code: str) -> str:
    if code == "authentication_failed":
        return "authentication_failed"
    if code in {"cancelled", "canceled"}:
        return "cancellation"
    if code == "timeout":
        return "timeout"
    if code in {"auth_lease_busy", "lock_timeout"}:
        return "lock_contention"
    if code == "tty_required":
        return "missing_tty"
    return "runner_error"


def _error_exit_code(exc: GateError) -> int:
    return 2 if _error_outcome(exc.code) != "runner_error" else 1


def _runner_timeout_seconds(manifest: Mapping[str, Any]) -> float | None:
    commands = manifest.get("commands")
    if not isinstance(commands, list):
        return None
    total = 0.0
    for command in commands:
        if not isinstance(command, Mapping):
            continue
        value = command.get("timeout_seconds")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            total += 300.0
        else:
            total += max(1.0, float(value))
    return total + 30.0 if total else None


def _shell_payload(row: GateShellRecord) -> dict[str, Any]:
    return {
        "gate_id": row.gate_id,
        "member_agent_name": row.member_agent_name,
        "project_name": row.project_name,
        "state": row.gate_state,
        "status": _shell_status_label(row),
        "reason": row.reason,
    }


def _shell_status_label(row: GateShellRecord) -> str:
    pair = gate_status_pair(row.start_status, row.stop_status)
    return effective_gate_status(
        pair,
        gate_state=row.gate_state,
        settled=row.is_terminal,
    )


def _print_answer(payload: Mapping[str, Any]) -> None:
    selected = ", ".join(str(item) for item in payload.get("selected_option_ids", []))
    print(f"Sudo gate {payload['request_id']} answered: {selected}")


def _print_list(rows: list[GateShellRecord]) -> None:
    table = Table(title="Sudo Gates")
    table.add_column("ID")
    table.add_column("State")
    table.add_column("Status")
    table.add_column("Member")
    table.add_column("Reason")
    for row in rows:
        table.add_row(
            row.gate_id,
            row.gate_state,
            _shell_status_label(row),
            row.member_agent_name,
            row.reason,
        )
    Console().print(table)


def _read_stdin_object() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        raise GateError(
            "invalid_sudo_request", "stdin", "sudo request JSON is required on stdin"
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GateError("invalid_json", "stdin", "invalid JSON on stdin") from exc
    if not isinstance(value, dict):
        raise GateError("invalid_sudo_request", "stdin", "stdin JSON must be an object")
    return value


__all__ = ["handle_sudo_command"]
