"""Validation contract for privileged launch gates."""

from __future__ import annotations

from collections.abc import Mapping

from sase.notification_gates.kind_validation.resources import read_gate_resource
from sase.notification_gates.models import GateError, GateSpec

_LAUNCH_COMMAND_PATHS = {
    "approve": "commands/approve",
    "reject": "commands/reject",
}


def validate_launch_spec(spec: GateSpec) -> None:
    """Keep privileged launch gates on the registered command contract."""
    _validate_launch_structure(spec)
    _validate_launch_commands(spec)
    _validate_launch_payload(spec)


def _validate_launch_structure(spec: GateSpec) -> None:
    expected_query = "approve OR reject"
    expected_branches = (("approve",), ("reject",))
    if spec.query != expected_query or spec.branches != expected_branches:
        raise GateError(
            "invalid_launch_query",
            "query",
            f"launch gates require query: {expected_query}",
        )
    actual_commands = {option.id: option.command.argv[0] for option in spec.options}
    if actual_commands != _LAUNCH_COMMAND_PATHS:
        raise GateError(
            "invalid_launch_options",
            "options",
            "launch gates require exactly the approve and reject options",
        )


def _validate_launch_commands(spec: GateSpec) -> None:
    from sase.agent.launch_request import launch_gate_command_script

    resources = {resource.path: resource for resource in spec.resources}
    for option_id, path in _LAUNCH_COMMAND_PATHS.items():
        content = read_gate_resource(
            resources[path],
            code="invalid_launch_command",
            description="launch command",
        )
        if content != launch_gate_command_script(option_id):
            raise GateError(
                "invalid_launch_command",
                path,
                "launch command does not match the registered adapter",
            )


def _validate_launch_payload(spec: GateSpec) -> None:
    dispatch = spec.payload.get("dispatch")
    if not isinstance(dispatch, Mapping):
        raise GateError(
            "invalid_launch_payload",
            "payload.dispatch",
            "launch payload requires a dispatch object",
        )
    if (
        not isinstance(dispatch.get("prompt"), str)
        or not str(dispatch.get("prompt")).strip()
    ):
        raise GateError(
            "invalid_launch_payload",
            "payload.dispatch.prompt",
            "launch payload requires a prompt",
        )
    if not isinstance(dispatch.get("cwd"), str) or not dispatch.get("cwd"):
        raise GateError(
            "invalid_launch_payload",
            "payload.dispatch.cwd",
            "launch payload requires a cwd",
        )
