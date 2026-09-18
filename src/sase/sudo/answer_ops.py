"""Shared sudo answer helpers used by the CLI and detached finalizer."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from sase.gate_shell.models import GateShellRefError, GateShellRecord
from sase.gate_shell.settlement import settle_gate_shell
from sase.gate_shell.store import (
    find_gate_shell_by_gate_id,
    list_gate_shells,
    resolve_gate_shell_ref,
)
from sase.notification_gates.cli_support import GateCliError, resolve_gate_cli_bundle
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.sudo.gate import APPROVE_OPTION_ID
from sase.sudo.receipt import validate_sudo_receipt


def _reject_non_terminal_auth(receipt: Mapping[str, Any]) -> None:
    """Raise when a runner ledger is a non-terminal auth outcome."""
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


def sudo_payload(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Return the typed sudo payload from a gate envelope."""
    payload = envelope.get("payload")
    value = payload.get("sudo") if isinstance(payload, Mapping) else None
    if not isinstance(value, Mapping):
        raise GateError(
            "invalid_sudo_payload", "payload.sudo", "sudo payload is missing"
        )
    return dict(value)


def resolve_sudo_gate_id(ref: str) -> str:
    """Resolve a sudo gate id or shell ref."""
    try:
        resolve_gate_cli_bundle("sudo", ref)
        return ref
    except GateCliError:
        pass
    try:
        record = resolve_gate_shell_ref(ref, sudo_shells(project=None))
    except GateShellRefError as exc:
        raise GateError("not_found", ref, str(exc)) from exc
    return record.gate_id


def sudo_shells(*, project: str | None) -> list[GateShellRecord]:
    """Return sudo gate-shell rows, optionally filtered by project."""
    return [row for row in list_gate_shells(project=project) if row.kind == "sudo"]


def settle_shell(gate_id: str, *, retry: Literal["resume", "restart"] | None) -> None:
    """Settle the sudo gate shell after a durable answer."""
    gate_shell = find_gate_shell_by_gate_id(None, gate_id)
    if gate_shell is None:
        return
    settle_gate_shell(
        gate_shell,
        gate_state="answered",
        reason="sudo gate answered",
        resume=retry == "resume",
    )


def apply_approved_receipt(
    bundle: Any,
    receipt: Mapping[str, Any],
    *,
    selected_command_ids: tuple[str, ...],
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    feedback: str | None,
    retry: Literal["resume", "restart"] | None,
) -> dict[str, Any]:
    """Validate a terminal ledger, execute the approve option, and settle."""
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
    settle_shell(bundle.request_id, retry=retry)
    return answer_payload(
        bundle.kind,
        bundle.request_id,
        execution.response,
        selected_command_ids=selected_command_ids,
    )


def answer_payload(
    kind: str,
    gate_id: str,
    response: Mapping[str, Any],
    *,
    selected_command_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return the stable answered-gate projection."""
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


def error_payload(gate_id: str, exc: GateError) -> dict[str, Any]:
    """Return the stable pending-error envelope."""
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
    """Return completed or command_failed from option results."""
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
    """Map a GateError code onto the sudo JSON outcome field."""
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
    if code == "execution_in_progress":
        return "execution_in_progress"
    if code == "detach_unsupported":
        return "detach_unsupported"
    if code == "killed":
        return "killed"
    return "runner_error"


def error_exit_code(exc: GateError) -> int:
    """Return 2 for expected operator errors and 1 for runner failures."""
    return 2 if _error_outcome(exc.code) != "runner_error" else 1


def runner_timeout_seconds(manifest: Mapping[str, Any]) -> float | None:
    """Return the summed command timeout plus auth slack."""
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


def print_answer(payload: Mapping[str, Any]) -> None:
    """Print the human form of an answer or execution-started payload."""
    if payload.get("status") == "execution_started":
        print(
            f"Sudo gate {payload['request_id']} execution started: "
            f"proc {payload.get('proc_id')}"
        )
        return
    selected = ", ".join(str(item) for item in payload.get("selected_option_ids", []))
    print(f"Sudo gate {payload['request_id']} answered: {selected}")


__all__ = [
    "answer_payload",
    "apply_approved_receipt",
    "error_exit_code",
    "error_payload",
    "print_answer",
    "resolve_sudo_gate_id",
    "runner_timeout_seconds",
    "settle_shell",
    "sudo_payload",
    "sudo_shells",
]
