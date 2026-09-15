"""Validation contract for SudoRequest gates."""

from __future__ import annotations

from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.models import GateError, GateSpec, stamp_schema_dialect
from sase.sudo.core import DEFAULT_SUDO_CORE
from sase.sudo.feature import require_sudo_requests_enabled
from sase.sudo.models import normalize_sudo_request
from sase.sudo.target import resolve_sudo_target

APPROVE_OPTION_ID = "approve"
DENY_OPTION_ID = "deny"
APPROVE_COMMAND_PATH = "commands/approve"
DENY_COMMAND_PATH = "commands/deny"


def validate_sudo_spec(spec: GateSpec) -> None:
    """Keep sudo gates feature-flagged and on the registered command contract."""
    require_sudo_requests_enabled("sudo")
    _validate_payload(spec)
    _validate_structure(spec)
    _validate_commands(spec)


def _validate_payload(spec: GateSpec) -> None:
    sudo_payload = spec.payload.get("sudo")
    if not isinstance(sudo_payload, dict):
        raise GateError(
            "invalid_sudo_payload", "payload.sudo", "sudo payload is required"
        )
    request = normalize_sudo_request(sudo_payload.get("request"))
    manifest = sudo_payload.get("manifest")
    if not isinstance(manifest, dict):
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.manifest",
            "sudo manifest is required",
        )
    target = resolve_sudo_target(request.machine)
    expected_manifest = DEFAULT_SUDO_CORE.validate_manifest(
        {
            "schema_version": 1,
            "request_id": spec.request_id or "",
            "host": target.host,
            "host_is_remote": target.remote,
            "run_as": request.run_as,
            "cwd": request.cwd,
            "env": dict(sorted(request.env.items())),
            "stop_on_failure": request.stop_on_failure,
            "output_to_agent": request.output_to_agent,
            "commands": [
                {
                    "id": command.id,
                    "argv": list(command.argv),
                    "why": command.why,
                    "timeout_seconds": command.timeout_seconds,
                    "shell": command.shell,
                }
                if command.timeout_seconds is not None
                else {
                    "id": command.id,
                    "argv": list(command.argv),
                    "why": command.why,
                    "shell": command.shell,
                }
                for command in request.commands
            ],
            "resume_from": None,
        }
    )
    normalized_manifest = DEFAULT_SUDO_CORE.validate_manifest(manifest)
    if normalized_manifest != expected_manifest:
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.manifest",
            "sudo manifest must match the normalized request",
        )
    manifest_sha256 = sudo_payload.get("manifest_sha256")
    if not isinstance(manifest_sha256, str):
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.manifest_sha256",
            "sudo manifest hash is required",
        )
    if manifest_sha256 != DEFAULT_SUDO_CORE.manifest_sha256(normalized_manifest):
        raise GateError(
            "invalid_sudo_payload",
            "payload.sudo.manifest_sha256",
            "sudo manifest hash does not match the sealed manifest",
        )


def _validate_structure(spec: GateSpec) -> None:
    if spec.query != "approve OR deny" or spec.branches != (("approve",), ("deny",)):
        raise GateError(
            "invalid_sudo_options", "query", "sudo gates require query: approve OR deny"
        )
    by_id = {option.id: option for option in spec.options}
    if set(by_id) != {APPROVE_OPTION_ID, DENY_OPTION_ID}:
        raise GateError(
            "invalid_sudo_options",
            "options",
            "sudo gates require approve and deny options",
        )
    approve = by_id[APPROVE_OPTION_ID]
    deny = by_id[DENY_OPTION_ID]
    if approve.command.argv != (APPROVE_COMMAND_PATH,) or not approve.requires_tty:
        raise GateError(
            "invalid_sudo_options",
            "options.approve",
            "sudo approve must run the registered TTY-required command",
        )
    if deny.command.argv != (DENY_COMMAND_PATH,) or deny.requires_tty:
        raise GateError(
            "invalid_sudo_options",
            "options.deny",
            "sudo deny must run the registered headless-safe command",
        )
    expected_approve_input = stamp_schema_dialect(
        {
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
        }
    )
    if approve.input_schema != expected_approve_input:
        raise GateError(
            "invalid_sudo_schema",
            "options.approve.input_schema",
            "sudo approve requires a runner receipt input",
        )


def _validate_commands(spec: GateSpec) -> None:
    from sase.sudo.commands import sudo_approve_command_script, sudo_deny_command_script

    resources = {resource.path: resource for resource in spec.resources}
    expected = {
        APPROVE_COMMAND_PATH: sudo_approve_command_script(),
        DENY_COMMAND_PATH: sudo_deny_command_script(),
    }
    if not set(expected).issubset(resources):
        raise GateError(
            "invalid_sudo_resources",
            "resources",
            "sudo gates require registered approve and deny commands",
        )
    for path, content in expected.items():
        resource = resources[path]
        actual = read_gate_resource(
            resource,
            code="invalid_sudo_command",
            description="sudo command",
        )
        if actual != content:
            raise GateError(
                "invalid_sudo_command",
                path,
                "sudo command does not match the registered adapter",
            )


__all__ = ["validate_sudo_spec"]
