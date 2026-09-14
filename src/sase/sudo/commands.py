"""Bundle-owned command resources for sudo gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NoReturn

from sase.notification_gates.durability import read_json_object
from sase.notification_gates.entrypoints import (
    gate_command_entrypoint,
    python_gate_command_script,
)
from sase.sudo.manifest import selected_sudo_manifest
from sase.sudo.receipt import validate_sudo_receipt


def sudo_approve_command_script() -> str:
    return python_gate_command_script(
        "from sase.sudo.commands import sudo_approve_entrypoint\n"
        "sudo_approve_entrypoint()\n"
    )


def sudo_deny_command_script() -> str:
    return python_gate_command_script(
        "from sase.sudo.commands import sudo_deny_entrypoint\nsudo_deny_entrypoint()\n"
    )


@gate_command_entrypoint
def sudo_approve_entrypoint() -> NoReturn:
    """Validate a runner receipt and echo the trusted approval result."""
    submitted = json.load(sys.stdin)
    receipt = submitted.get("receipt") if isinstance(submitted, dict) else None
    submitted_command_ids = (
        submitted.get("command_ids") if isinstance(submitted, dict) else None
    )
    request = read_json_object(Path("request.json"))
    payload = request.get("payload")
    sudo_payload = payload.get("sudo") if isinstance(payload, dict) else None
    if not isinstance(sudo_payload, dict):
        raise SystemExit("request payload is missing sudo manifest")
    manifest = sudo_payload.get("manifest")
    if not isinstance(manifest, dict):
        raise SystemExit("request payload is missing sudo manifest")
    command_ids_value = (
        submitted_command_ids if isinstance(submitted_command_ids, list) else None
    )
    _subset, command_ids, manifest_sha256 = selected_sudo_manifest(
        manifest,
        command_ids_value,
    )
    normalized = validate_sudo_receipt(
        receipt,
        manifest_sha256=manifest_sha256,
        selected_command_ids=command_ids,
    )
    print(
        json.dumps(
            {
                "status": "approved",
                "command_ids": list(command_ids),
                "receipt": normalized,
                "ledger": normalized.get("ledger", []),
            },
            sort_keys=True,
        )
    )
    raise SystemExit(0)


@gate_command_entrypoint
def sudo_deny_entrypoint() -> NoReturn:
    """Record a denial without requiring a TTY."""
    submitted = json.load(sys.stdin)
    feedback = submitted.get("feedback") if isinstance(submitted, dict) else None
    print(json.dumps({"status": "denied", "feedback": feedback}, sort_keys=True))
    raise SystemExit(0)


__all__ = [
    "sudo_approve_command_script",
    "sudo_approve_entrypoint",
    "sudo_deny_command_script",
    "sudo_deny_entrypoint",
]
