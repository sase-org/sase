"""Terminal and sudo-specific preflight checks for gate execution."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.notification_gates.models import GateError, GateOption


def reject_unavailable_option_transport(
    bundle_path: Path,
    envelope: Mapping[str, Any],
    kind: str,
    selected: tuple[GateOption, ...],
    source: str,
    option_inputs: Mapping[str, object] | None,
    sudo_headless_authorization: Mapping[str, Any] | None,
    has_tty: Callable[[], bool],
) -> None:
    """Refuse terminal-only decisions before they accept the gate."""
    tty_options = tuple(option for option in selected if option.requires_tty)
    if not tty_options:
        return
    option_ids = ", ".join(option.id for option in tty_options)
    authorized_sudo_headless = _authorized_sudo_headless_selection(
        bundle_path,
        envelope,
        kind,
        selected,
        option_inputs,
        sudo_headless_authorization,
    )
    if not has_tty() and not authorized_sudo_headless:
        raise GateError(
            "tty_required",
            option_ids,
            "this gate option requires a controlling TTY; the gate remains pending",
        )
    if kind == "sudo" and source != "sudo_cli" and not authorized_sudo_headless:
        raise GateError(
            "unsupported_sudo_approval",
            option_ids,
            "sudo approval must use `sase sudo answer <id>` so the reviewed "
            "manifest is sealed and executed by the sudo runner",
        )


def _authorized_sudo_headless_selection(
    bundle_path: Path,
    envelope: Mapping[str, Any],
    kind: str,
    selected: tuple[GateOption, ...],
    option_inputs: Mapping[str, object] | None,
    authorization: Mapping[str, Any] | None,
) -> bool:
    if kind != "sudo" or authorization is None:
        return False
    if [option.id for option in selected] != ["approve"]:
        return False
    if authorization.get("authorized") is not True:
        return False
    if str(authorization.get("gate_id") or "") != str(envelope.get("request_id") or ""):
        return False
    approve_input = (
        option_inputs.get("approve") if isinstance(option_inputs, Mapping) else None
    )
    if not isinstance(approve_input, Mapping):
        return False
    command_ids = approve_input.get("command_ids")
    if not isinstance(command_ids, list) or any(
        not isinstance(item, str) for item in command_ids
    ):
        return False
    if list(authorization.get("selected_command_ids") or []) != command_ids:
        return False
    receipt = approve_input.get("receipt")
    if not isinstance(receipt, Mapping):
        return False
    if str(authorization.get("manifest_sha256") or "") != str(
        receipt.get("manifest_sha256") or ""
    ):
        return False
    authorization_id = authorization.get("authorization_id")
    if not isinstance(authorization_id, str) or not authorization_id:
        return False
    try:
        from sase.sudo.execution import load_execution_state

        state = load_execution_state(bundle_path)
    except GateError:
        raise
    except Exception:
        return False
    if state is None:
        return False
    return (
        state.authorization_id == authorization_id
        and state.manifest_sha256 == authorization.get("manifest_sha256")
        and list(state.selected_command_ids) == command_ids
    )


def preflight_sudo_approval_inputs(
    envelope: Mapping[str, Any],
    kind: str,
    selected: tuple[GateOption, ...],
    option_inputs: Mapping[str, object] | None,
) -> None:
    """Validate sudo runner receipts before accepting the gate decision."""
    if kind != "sudo" or all(option.id != "approve" for option in selected):
        return
    from sase.sudo.manifest import selected_sudo_manifest
    from sase.sudo.receipt import validate_sudo_receipt

    approve_input = (
        option_inputs.get("approve") if isinstance(option_inputs, Mapping) else None
    )
    receipt = (
        approve_input.get("receipt") if isinstance(approve_input, Mapping) else None
    )
    command_ids_value = (
        approve_input.get("command_ids") if isinstance(approve_input, Mapping) else None
    )
    if not isinstance(command_ids_value, list) or not command_ids_value:
        raise GateError(
            "invalid_sudo_selection",
            "option_inputs.approve.command_ids",
            "sudo approve requires reviewed command ids",
        )
    sudo_payload = _sudo_payload_for_preflight(envelope)
    manifest = sudo_payload["manifest"]
    _subset, command_ids, manifest_sha256 = selected_sudo_manifest(
        manifest,
        command_ids_value,
    )
    normalized = validate_sudo_receipt(
        receipt,
        manifest_sha256=manifest_sha256,
        selected_command_ids=command_ids,
    )
    for index, entry in enumerate(normalized.get("ledger", [])):
        if not isinstance(entry, Mapping):
            continue
        status = str(entry.get("status") or "")
        if status in {"authentication_failed", "cancelled", "canceled", "timeout"}:
            raise GateError(
                status,
                f"receipt.ledger[{index}]",
                "sudo runner did not approve execution; the gate remains pending",
            )


def _sudo_payload_for_preflight(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = envelope.get("payload")
    sudo_payload = payload.get("sudo") if isinstance(payload, Mapping) else None
    if not isinstance(sudo_payload, Mapping):
        raise GateError(
            "invalid_sudo_payload", "payload.sudo", "sudo payload is missing"
        )
    manifest = sudo_payload.get("manifest")
    if not isinstance(manifest, Mapping):
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.manifest",
            "sudo manifest is missing",
        )
    if not isinstance(sudo_payload.get("manifest_sha256"), str):
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.manifest_sha256",
            "sudo manifest hash is missing",
        )
    return sudo_payload


def has_controlling_tty() -> bool:
    """Return whether this process can open its controlling terminal."""
    try:
        fd = os.open("/dev/tty", os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return False
    os.close(fd)
    return True


__all__ = [
    "has_controlling_tty",
    "preflight_sudo_approval_inputs",
    "reject_unavailable_option_transport",
]
