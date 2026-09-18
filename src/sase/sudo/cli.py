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

from sase.agent.gate_intent import begin_gate_intent, clear_gate_intent
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.status import effective_gate_status, gate_status_pair
from sase.notification_gates.cli_support import emit_json, resolve_gate_cli_bundle
from sase.notification_gates.executor import execute_gate_selection, has_controlling_tty
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import bundle_paths
from sase.sudo.answer_ops import (
    apply_approved_receipt,
    error_exit_code,
    error_payload,
    print_answer,
    resolve_sudo_gate_id,
    runner_timeout_seconds,
    settle_shell,
    sudo_payload as _sudo_payload,
    sudo_shells,
    answer_payload,
)
from sase.sudo.detach import (
    SUDO_ANSWER_DETACH_ORIGIN,
    approve_detached,
    approve_remote_detached,
    finalize,
)
from sase.sudo.execution import handshake_from_runner_payload, project_execution
from sase.sudo.feature import require_sudo_requests_enabled
from sase.sudo.gate import DENY_OPTION_ID, build_sudo_gate_request
from sase.sudo.lease import sudo_auth_lease
from sase.sudo.manifest import selected_sudo_manifest
from sase.sudo.runner import (
    run_sudo_runner,
    run_sudo_runner_detached,
    run_sudo_runner_file,
    runner_supports_detached_execution,
)
from sase.sudo.ssh import remote_supports_detached_execution, run_remote_sudo

_DETACH_FALLBACK_NOTICE = (
    "installed sase_sudo_runner does not advertise detached_execution; "
    "running synchronously"
)
_REMOTE_DETACH_FALLBACK_NOTICE = (
    "target sudo exec does not advertise detached_execution; running synchronously"
)


def handle_sudo_command(args: argparse.Namespace) -> int:
    """Dispatch one parsed sudo command."""
    subcommand = getattr(args, "sudo_subcommand", None)
    if subcommand == "answer":
        return _answer(args)
    try:
        require_sudo_requests_enabled("sudo")
        if subcommand == "exec":
            return _exec(args)
        if subcommand == "finalize":
            return finalize(args)
        if subcommand == "list":
            return _list(args)
        if subcommand == "request":
            return _request(args)
        if subcommand == "show":
            return _show(args)
    except GateError as exc:
        if bool(getattr(args, "json", False)) and subcommand in {
            "finalize",
            "list",
            "show",
        }:
            emit_json(error_payload(_raw_request_ref(args), exc))
            return error_exit_code(exc)
        raise
    print(
        "Usage: sase sudo {answer,exec,finalize,list,request,show}",
        file=sys.stderr,
    )
    return 1


def _exec(args: argparse.Namespace) -> int:
    """Target-side manifest execution entrypoint for SSH handoffs."""
    if bool(getattr(args, "contract", False)):
        capabilities: list[str] = []
        try:
            if runner_supports_detached_execution():
                capabilities.append("detached_execution")
        except GateError:
            pass
        emit_json(
            {
                "capabilities": capabilities,
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
    detach = bool(getattr(args, "detach", False))
    handshake_path = getattr(args, "handshake", None)
    if not manifest_path or not expected_sha256 or not ledger_path:
        raise GateError(
            "invalid_sudo_exec",
            "sudo.exec",
            "--manifest, --expected-sha256, and --ledger are required",
        )
    if detach and not handshake_path:
        raise GateError(
            "invalid_sudo_exec",
            "sudo.exec",
            "--handshake is required with --detach",
        )
    if not has_controlling_tty():
        raise GateError(
            "tty_required",
            "sudo.exec",
            "sudo target execution requires a controlling TTY",
        )
    if detach:
        runner_payload = run_sudo_runner_detached(
            Path(str(manifest_path)),
            manifest_sha256=str(expected_sha256),
            detach_dir=Path(str(manifest_path)).parent,
        )
        if handshake_from_runner_payload(runner_payload):
            _write_json_file(Path(str(handshake_path)), runner_payload)
            return 0
        _write_json_file(Path(str(ledger_path)), runner_payload)
        return _exec_exit_code_for_payload(runner_payload)
    ledger = run_sudo_runner_file(
        Path(str(manifest_path)),
        manifest_sha256=str(expected_sha256),
    )
    _write_json_file(Path(str(ledger_path)), ledger)
    return 0


def _request(args: argparse.Namespace) -> int:
    """Create a sudo gate shell from stdin."""
    begin_gate_intent("sudo", source="sase sudo request")
    try:
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
    except Exception:
        clear_gate_intent()
        raise

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
        gate_id = resolve_sudo_gate_id(raw_ref)
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
                detach=_wants_detach(args),
            )
    except GateError as exc:
        if not bool(getattr(args, "json", False)):
            raise
        emit_json(error_payload(gate_id, exc))
        return error_exit_code(exc)
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        print_answer(payload)
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


def _wants_detach(args: argparse.Namespace) -> bool:
    if bool(getattr(args, "no_detach", False)):
        return False
    if bool(getattr(args, "detach", False)):
        return True
    return True


def _approve(
    gate_id: str,
    *,
    command_ids: tuple[str, ...],
    feedback: str | None,
    retry: Literal["resume", "restart"] | None,
    detach: bool = False,
) -> dict[str, Any]:
    if not has_controlling_tty():
        raise GateError(
            "tty_required",
            "approve",
            "sudo approval requires a controlling TTY; the gate remains pending",
        )
    bundle = resolve_gate_cli_bundle("sudo", gate_id)
    payload = _sudo_payload(bundle.envelope)
    manifest, selected_command_ids, manifest_sha256 = selected_sudo_manifest(
        dict(payload["manifest"]),
        command_ids,
    )
    target = payload.get("target")
    remote = isinstance(target, Mapping) and bool(target.get("remote"))
    if detach and remote:
        assert isinstance(target, Mapping)
        host = str(target.get("host") or "")
        if remote_supports_detached_execution(host):
            return approve_remote_detached(
                bundle,
                host,
                manifest,
                selected_command_ids=selected_command_ids,
                manifest_sha256=manifest_sha256,
                feedback=feedback,
                retry=retry,
            )
        print(f"sase sudo: {_REMOTE_DETACH_FALLBACK_NOTICE}", file=sys.stderr)
        detach = False
    if detach and not remote and not runner_supports_detached_execution():
        print(f"sase sudo: {_DETACH_FALLBACK_NOTICE}", file=sys.stderr)
        detach = False
    if detach:
        return approve_detached(
            bundle,
            manifest,
            selected_command_ids=selected_command_ids,
            manifest_sha256=manifest_sha256,
            feedback=feedback,
            retry=retry,
        )
    with sudo_auth_lease(
        request_id=gate_id,
        run_as=str(manifest.get("run_as") or "root"),
        cwd=str(manifest.get("cwd") or ""),
        command_ids=selected_command_ids,
    ):
        if remote:
            host = str(target.get("host") or "") if isinstance(target, Mapping) else ""
            receipt = run_remote_sudo(
                host,
                manifest,
                manifest_sha256=manifest_sha256,
                timeout_seconds=runner_timeout_seconds(manifest),
            )
        else:
            receipt = run_sudo_runner(
                manifest,
                manifest_sha256=manifest_sha256,
                timeout_seconds=runner_timeout_seconds(manifest),
            )
    return apply_approved_receipt(
        bundle,
        receipt,
        selected_command_ids=selected_command_ids,
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        feedback=feedback,
        retry=retry,
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
    settle_shell(gate_id, retry=retry)
    return answer_payload(bundle.kind, gate_id, execution.response)


def _list(args: argparse.Namespace) -> int:
    rows = sudo_shells(project=getattr(args, "project", None))
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
    gate_id = resolve_sudo_gate_id(str(args.gate_ref))
    from sase.notification_gates.cli_show import print_human_gate, show_gate

    payload = show_gate("sudo", gate_id)
    bundle = resolve_gate_cli_bundle("sudo", gate_id)
    sudo = _sudo_payload(bundle.envelope)
    sudo.update(_execution_fields(gate_id))
    payload["sudo"] = sudo
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        print_human_gate(payload)
        _print_execution(sudo)
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


def _execution_fields(gate_id: str) -> dict[str, Any]:
    try:
        root = bundle_paths("sudo", gate_id).root
    except GateError:
        return {"executing": False, "finalize_proc_id": None}
    projection = project_execution(root)
    return {
        "executing": projection.executing,
        "finalize_proc_id": projection.finalize_proc_id,
    }


def _shell_payload(row: GateShellRecord) -> dict[str, Any]:
    payload = {
        "gate_id": row.gate_id,
        "member_agent_name": row.member_agent_name,
        "project_name": row.project_name,
        "state": row.gate_state,
        "status": _shell_status_label(row),
        "reason": row.reason,
    }
    payload.update(_execution_fields(row.gate_id))
    return payload


def _shell_status_label(row: GateShellRecord) -> str:
    pair = gate_status_pair(row.start_status, row.stop_status)
    return effective_gate_status(
        pair,
        gate_state=row.gate_state,
        settled=row.is_terminal,
    )


def _print_execution(sudo: Mapping[str, Any]) -> None:
    if not bool(sudo.get("executing")):
        return
    proc_id = sudo.get("finalize_proc_id") or "unknown"
    print(f"Executing in background proc {proc_id}")


def _print_list(rows: list[GateShellRecord]) -> None:
    table = Table(title="Sudo Gates")
    table.add_column("ID")
    table.add_column("State")
    table.add_column("Status")
    table.add_column("Exec")
    table.add_column("Member")
    table.add_column("Reason")
    for row in rows:
        fields = _execution_fields(row.gate_id)
        executing = "executing" if fields.get("executing") else ""
        proc_id = str(fields.get("finalize_proc_id") or "")
        exec_label = proc_id or executing
        table.add_row(
            row.gate_id,
            row.gate_state,
            _shell_status_label(row),
            exec_label,
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


def _write_json_file(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), sort_keys=True) + "\n", encoding="utf-8")


def _exec_exit_code_for_payload(payload: Mapping[str, Any]) -> int:
    return {
        "auth_failed": 10,
        "cancelled": 11,
        "tty_unavailable": 12,
        "runner_error": 14,
    }.get(str(payload.get("outcome") or ""), 0)


__all__ = ["SUDO_ANSWER_DETACH_ORIGIN", "handle_sudo_command"]
