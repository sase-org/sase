"""Terminal front doors for typed sudo gates."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from typing import Any, Literal

from rich.console import Console
from rich.table import Table

from sase.gate_shell.models import GateShellRefError, GateShellRecord
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
from sase.sudo.receipt import validate_sudo_receipt
from sase.sudo.runner import run_sudo_runner


def handle_sudo_command(args: argparse.Namespace) -> int:
    """Dispatch one parsed sudo command."""
    require_sudo_requests_enabled("sudo")
    subcommand = getattr(args, "sudo_subcommand", None)
    if subcommand == "answer":
        return _answer(args)
    if subcommand == "list":
        return _list(args)
    if subcommand == "request":
        return _request(args)
    if subcommand == "show":
        return _show(args)
    print("Usage: sase sudo {answer,list,request,show}", file=sys.stderr)
    return 1


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
    gate_id = _resolve_sudo_gate_id(str(args.gate_ref))
    decision = _decision(args)
    retry = _retry(args)
    if decision == "deny":
        payload = _deny(gate_id, feedback=getattr(args, "feedback", None), retry=retry)
    else:
        payload = _approve(
            gate_id, feedback=getattr(args, "feedback", None), retry=retry
        )
    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        _print_answer(payload)
    return 0


def _approve(
    gate_id: str,
    *,
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
    manifest = dict(sudo_payload["manifest"])
    receipt = run_sudo_runner(
        {
            "request_id": gate_id,
            "manifest": manifest,
            "manifest_sha256": sudo_payload["manifest_sha256"],
        }
    )
    _reject_non_terminal_auth(receipt)
    command_ids = [
        str(item["id"])
        for item in manifest.get("commands", [])
        if isinstance(item, Mapping)
    ]
    normalized_receipt = validate_sudo_receipt(
        receipt,
        manifest_sha256=str(sudo_payload["manifest_sha256"]),
        selected_command_ids=command_ids,
    )
    execution = execute_gate_selection(
        bundle.root,
        [APPROVE_OPTION_ID],
        feedback=feedback,
        source="sudo_cli",
        retry=retry,
        option_inputs={APPROVE_OPTION_ID: {"receipt": normalized_receipt}},
    )
    _settle_shell(gate_id, retry=retry)
    return _answer_payload(bundle.kind, gate_id, execution.response)


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


def _decision(args: argparse.Namespace) -> Literal["approve", "deny"]:
    if bool(getattr(args, "approve", False)):
        return "approve"
    if bool(getattr(args, "deny", False)):
        return "deny"
    if not has_controlling_tty():
        raise GateError(
            "tty_required",
            "answer",
            "choose --approve or --deny when not running interactively",
        )
    answer = input("Approve sudo request? [y/N] ").strip().lower()
    return "approve" if answer in {"y", "yes"} else "deny"


def _retry(args: argparse.Namespace) -> Literal["resume", "restart"] | None:
    if bool(getattr(args, "resume", False)):
        return "resume"
    if bool(getattr(args, "restart", False)):
        return "restart"
    return None


def _reject_non_terminal_auth(receipt: Mapping[str, Any]) -> None:
    status = str(receipt.get("status") or "")
    if status in {"authentication_failed", "cancelled"}:
        raise GateError(
            status,
            "sase_sudo_runner",
            "sudo runner did not approve execution; the gate remains pending",
        )
    ledger = receipt.get("ledger")
    if isinstance(ledger, list):
        for index, entry in enumerate(ledger):
            if not isinstance(entry, Mapping):
                continue
            entry_status = str(entry.get("status") or "")
            if entry_status in {"authentication_failed", "cancelled"}:
                raise GateError(
                    entry_status,
                    f"sase_sudo_runner.ledger[{index}]",
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
    kind: str, gate_id: str, response: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "kind": kind,
        "request_id": gate_id,
        "selected_option_ids": list(response.get("selected_option_ids", [])),
        "option_results": response.get("option_results", []),
        "status": "answered",
    }


def _shell_payload(row: GateShellRecord) -> dict[str, Any]:
    return {
        "gate_id": row.gate_id,
        "member_agent_name": row.member_agent_name,
        "project_name": row.project_name,
        "state": row.gate_state,
        "status": row.status_bucket,
        "reason": row.reason,
    }


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
            row.status_bucket,
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
