"""Build the canonical notification-gate request for a sudo request."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from sase.notification_gates.models import GATE_REQUEST_SCHEMA_VERSION
from sase.sudo.commands import sudo_approve_command_script, sudo_deny_command_script
from sase.sudo.core import DEFAULT_SUDO_CORE, SudoCoreBinding
from sase.sudo.models import (
    SudoRequest,
    normalize_sudo_request,
    sudo_request_executable_paths,
    sudo_request_machine,
)
from sase.sudo.snapshot import host_facts, tcc_warning
from sase.sudo.ssh_snapshot import snapshot_remote_executables
from sase.sudo.target import SudoExecutionTarget, resolve_sudo_target

APPROVE_OPTION_ID = "approve"
DENY_OPTION_ID = "deny"
APPROVE_COMMAND_PATH = "commands/approve"
DENY_COMMAND_PATH = "commands/deny"


def build_sudo_gate_request(
    value: Mapping[str, Any] | SudoRequest,
    *,
    producer: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    core: SudoCoreBinding = DEFAULT_SUDO_CORE,
) -> dict[str, Any]:
    """Return a v3 gate-turn request for one normalized sudo request."""
    request, target, target_payload = _normalize_build_request(value)
    request_id = request_id or f"sudo-{uuid4()}"
    manifest = core.validate_manifest(_manifest(request, request_id, target))
    manifest_sha256 = core.manifest_sha256(manifest)
    risk_badges = core.risk_badges(manifest)
    title = f"Sudo request: {request.commands[0].argv[0]}"
    if len(request.commands) > 1:
        title += f" (+{len(request.commands) - 1})"
    next_prompt = request.next_prompt
    return {
        "schema_version": GATE_REQUEST_SCHEMA_VERSION,
        "kind": "sudo",
        "request_id": request_id,
        "producer": dict(
            producer or {"agent": os.environ.get("SASE_AGENT_NAME", "agent")}
        ),
        "continuation_mode": "gate_turn",
        "gate_timeout_seconds": float(request.gate_timeout_seconds),
        "payload": {
            "sudo": {
                "request": request.to_dict(),
                "manifest": manifest,
                "manifest_sha256": manifest_sha256,
                "risk_badges": list(risk_badges),
                "target": target_payload,
            }
        },
        "presentation": {
            "icon": "🔐",
            "title": title,
            "notes": _notes(request, risk_badges),
            "tags": ["sudo", "gate"],
            "preview": "sudo-request.md",
            "chip": {"glyph": "🔐", "label": "sudo", "color": "#FFAF5F"},
        },
        "query": "approve OR deny",
        "primary_branch": ["approve"],
        "options": [_approve_option(), _deny_option()],
        "resources": [
            {
                "path": APPROVE_COMMAND_PATH,
                "role": "command",
                "content": sudo_approve_command_script(),
            },
            {
                "path": DENY_COMMAND_PATH,
                "role": "command",
                "content": sudo_deny_command_script(),
            },
            {
                "path": "sudo-request.md",
                "role": "preview",
                "content": _preview(
                    request, manifest_sha256, risk_badges, target_payload
                ),
            },
        ],
        "shell": {
            "pending_status": "SUDO",
            "settled_status": "SUDOED",
            "accent": "#FFAF5F",
            "next": {"prompt": next_prompt, "output": ["results"], "fork": "session"},
            "branches": {
                "approve": {"status": "SUDOED", "accent": "#00D787"},
                "deny": {
                    "status": "DENIED",
                    "accent": "#FF5F5F",
                    "prompt": None,
                },
            },
        },
    }


def _normalize_build_request(
    value: Mapping[str, Any] | SudoRequest,
) -> tuple[SudoRequest, SudoExecutionTarget, dict[str, Any]]:
    raw: object = value.to_dict() if isinstance(value, SudoRequest) else value
    machine = sudo_request_machine(raw)
    target = resolve_sudo_target(machine)
    if target.remote:
        remote = snapshot_remote_executables(
            target.host, sudo_request_executable_paths(raw)
        )
        request = normalize_sudo_request(raw, snapshots=remote.by_path())
        facts = dict(remote.host_facts)
        taken_on = "target"
    else:
        request = normalize_sudo_request(raw)
        facts = host_facts()
        taken_on = "local"
    return request, target, _target_payload(target, taken_on=taken_on, host_facts=facts)


def _manifest(
    request: SudoRequest,
    request_id: str,
    target: SudoExecutionTarget,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": request_id,
        "host": target.host,
        "host_is_remote": target.remote,
        "run_as": request.run_as,
        "cwd": request.cwd,
        "env": dict(sorted(request.env.items())),
        "stop_on_failure": request.stop_on_failure,
        "output_to_agent": request.output_to_agent,
        "commands": [_manifest_command(command) for command in request.commands],
        "resume_from": None,
    }


def _manifest_command(command: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": command.id,
        "argv": list(command.argv),
        "why": command.why,
        "shell": command.shell,
    }
    if command.timeout_seconds is not None:
        payload["timeout_seconds"] = command.timeout_seconds
    return payload


def _target_payload(
    target: SudoExecutionTarget,
    *,
    taken_on: str,
    host_facts: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "host": target.host,
        "requested_machine": target.requested_machine,
        "enrolled_alias": target.enrolled_alias,
        "enrolled": target.enrolled,
        "remote": target.remote,
        "unenrolled": target.unenrolled,
        "snapshot": {"taken_on": taken_on, "host_facts": dict(host_facts)},
    }


def _approve_option() -> dict[str, Any]:
    return {
        "id": APPROVE_OPTION_ID,
        "label": "Approve with sudo",
        "icon": "🔐",
        "command": {"argv": [APPROVE_COMMAND_PATH]},
        "requires_tty": True,
        "input_schema": {
            "type": "object",
            "required": ["command_ids", "receipt"],
            "properties": {
                "command_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "receipt": {"type": "object"},
            },
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "required": ["status", "command_ids", "receipt", "ledger"],
            "properties": {
                "status": {"const": "approved"},
                "command_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "uniqueItems": True,
                },
                "receipt": {"type": "object"},
                "ledger": {"type": "array"},
            },
        },
    }


def _deny_option() -> dict[str, Any]:
    return {
        "id": DENY_OPTION_ID,
        "label": "Deny",
        "icon": "✕",
        "command": {"argv": [DENY_COMMAND_PATH]},
        "default_selected": False,
        "feedback": "optional",
        "input_schema": {
            "type": "object",
            "properties": {"feedback": {"type": "string"}},
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "required": ["status"],
            "properties": {
                "status": {"const": "denied"},
                "feedback": {"type": ["string", "null"]},
            },
        },
    }


def _notes(request: SudoRequest, risk_badges: tuple[str, ...]) -> list[str]:
    return [
        f"Reason: {request.reason}",
        f"Run as: {request.run_as} in {request.cwd}",
        f"Target: {request.machine or 'local'}",
        "Risk: " + (", ".join(risk_badges) or "none"),
        "Commands: " + ", ".join(command.id for command in request.commands),
    ]


def _preview(
    request: SudoRequest,
    manifest_sha256: str,
    risk_badges: tuple[str, ...],
    target_payload: Mapping[str, Any] | None = None,
) -> str:
    lines = [
        "# Sudo Request",
        "",
        f"Reason: {request.reason}",
        f"Run as: `{request.run_as}`",
        f"Working directory: `{request.cwd}`",
        f"Target: `{request.machine or 'local'}`",
    ]
    facts_line = _target_facts_line(target_payload)
    if facts_line is not None:
        lines.append(facts_line)
    lines.extend(
        [
            f"Manifest SHA-256: `{manifest_sha256}`",
            f"Risk: {', '.join(risk_badges) or 'none'}",
            "",
        ]
    )
    warning = tcc_warning(target_payload)
    if warning:
        lines.extend([f"> {warning}", ""])
    lines.extend(["Commands:", ""])
    for command in request.commands:
        lines.extend(
            [
                f"## {command.id}",
                "",
                "```sh",
                shlex.join(command.argv),
                "```",
                "",
                f"Executable SHA-256: `{command.executable_sha256}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _target_facts_line(target_payload: Mapping[str, Any] | None) -> str | None:
    if not isinstance(target_payload, Mapping):
        return None
    snapshot = target_payload.get("snapshot")
    if not isinstance(snapshot, Mapping):
        return None
    facts = snapshot.get("host_facts")
    if not isinstance(facts, Mapping):
        return None
    platform = facts.get("platform")
    if not isinstance(platform, str) or not platform:
        return None
    fda = facts.get("full_disk_access")
    if fda is True:
        fda_text = "yes"
    elif fda is False:
        fda_text = "no"
    else:
        fda_text = "n/a"
    return f"Target facts: platform={platform}, full_disk_access={fda_text}"


__all__ = [
    "APPROVE_COMMAND_PATH",
    "APPROVE_OPTION_ID",
    "DENY_COMMAND_PATH",
    "DENY_OPTION_ID",
    "build_sudo_gate_request",
]
