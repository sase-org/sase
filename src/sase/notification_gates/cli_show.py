"""``sase gate show`` -- print what a gate asks for and what it offers.

This is the author's check that the gate they wrote asks for what they
intended: it prints the branches, each option's declared input fields with
their types and defaults, and the declared repeatable actions, all read from
the same verified envelope every surface renders from.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn

from rich.console import Console
from rich.text import Text

from sase.gate_shell.models import GateShellRefError
from sase.gate_shell.projection import gate_shell_runtime_json
from sase.gate_shell.store import (
    find_gate_shell_by_gate_id,
    list_gate_shells,
    resolve_gate_shell_ref,
)
from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.cli_support import (
    EXIT_ERROR,
    EXIT_OK,
    GateCliError,
    emit_json,
    report_gate_error,
    resolve_gate_cli_bundle,
)
from sase.notification_gates.model_operations import GateOperation
from sase.notification_gates.model_options import GateOption
from sase.notification_gates.models import GateError
from sase.notification_gates.poller import poll_gate

#: Exit code for an unknown or ambiguous ``gate_ref`` positional argument,
#: mirroring ``sase monitor show``'s ref-resolution failure code.
EXIT_REF_ERROR = 2

_STATUS_PROJECTION = {
    "responded": "answered",
    "cancelled": "cancelled",
    "timed_out": "timeout",
}


def handle_gate_show(args: argparse.Namespace) -> NoReturn:
    """Print one gate's declared decision surface."""
    try:
        kind, request_id = _resolve_kind_and_id(args)
        payload = _show(kind, request_id)
    except GateShellRefError as exc:
        print(f"sase gate show: {exc}", file=sys.stderr)
        sys.exit(EXIT_REF_ERROR)
    except GateCliError as exc:
        print(f"sase gate show: {exc}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
    except GateError as exc:
        sys.exit(report_gate_error("show", exc))
    except OSError as exc:
        print(f"sase gate show: cannot read gate: {exc}", file=sys.stderr)
        sys.exit(EXIT_ERROR)

    if bool(getattr(args, "json", False)):
        emit_json(payload)
    else:
        _print_human_gate(payload)
    sys.exit(EXIT_OK)


def _resolve_kind_and_id(args: argparse.Namespace) -> tuple[str, str]:
    """Resolve the ``kind``/``request_id`` pair from ``--id``/``--kind`` or a ref.

    ``gate_ref`` is the only way to address a gate shell by its short id,
    member name, or owning agent name; ``--id`` plus ``--kind`` remain the
    exact, surface-neutral contract every other caller (Telegram, the mobile
    bridge, the conformance matrix) already uses.
    """
    request_id = getattr(args, "id", None)
    kind = getattr(args, "kind", None)
    gate_ref = getattr(args, "gate_ref", None)
    if request_id and kind:
        return str(kind), str(request_id)
    if request_id or kind:
        raise GateCliError("-i/--id and -k/--kind must be given together")
    if not gate_ref:
        raise GateCliError("pass a gate-shell reference, or -i/--id plus -k/--kind")
    record = resolve_gate_shell_ref(str(gate_ref), list_gate_shells())
    return record.kind, record.gate_id


def _show(kind: str, request_id: str) -> dict[str, Any]:
    bundle = resolve_gate_cli_bundle(kind, request_id)
    gate = GateBranchData.from_envelope(
        bundle.envelope, default_feedback=bundle.adapter.default_feedback
    )
    poll = poll_gate(bundle.root)
    payload: dict[str, Any] = {
        "actions": [
            _action_payload(operation) for operation in _operations(bundle.envelope)
        ],
        "branches": [list(branch) for branch in gate.branches],
        "kind": bundle.kind,
        "options": [_option_payload(option) for option in gate.options],
        "primary_branch": list(gate.primary_branch),
        "query": gate.query,
        "request_id": bundle.request_id,
        "shell": _shell_payload(bundle.envelope),
        "status": "pending" if poll is None else _STATUS_PROJECTION[poll.status],
    }
    if payload["shell"] is not None:
        gate_shell = find_gate_shell_by_gate_id(None, bundle.request_id)
        if gate_shell is not None:
            payload["gate_shell"] = gate_shell_runtime_json(gate_shell)
    return payload


def _operations(envelope: Mapping[str, Any]) -> tuple[GateOperation, ...]:
    raw_operations = envelope.get("operations")
    if not isinstance(raw_operations, list):
        return ()
    return tuple(
        GateOperation.from_mapping(raw, index)
        for index, raw in enumerate(raw_operations)
    )


def _option_payload(option: GateOption) -> dict[str, Any]:
    return {
        "default_selected": option.default_selected,
        "feedback": option.feedback,
        "icon": option.icon,
        "id": option.id,
        "input_schema": option.input_schema,
        "inputs": [field.to_dict() for field in option.inputs],
        "label": option.label,
    }


def _action_payload(operation: GateOperation) -> dict[str, Any]:
    return operation.to_dict()


def _shell_payload(envelope: Mapping[str, Any]) -> dict[str, Any] | None:
    shell = envelope.get("shell")
    return dict(shell) if isinstance(shell, Mapping) else None


def _print_human_gate(payload: Mapping[str, Any]) -> None:
    console = Console()
    header = Text()
    header.append("Gate ", style="dim")
    header.append(f"{payload['kind']}/{payload['request_id']}", style="bold")
    header.append(" · ", style="dim")
    header.append(str(payload["status"]), style=_status_style(str(payload["status"])))
    console.print(header, soft_wrap=True)

    query = Text("Query: ", style="dim")
    query.append(str(payload["query"]))
    console.print(query, soft_wrap=True)

    console.print(Text("Branches", style="bold"), soft_wrap=True)
    primary = list(payload["primary_branch"])
    for branch in payload["branches"]:
        line = Text("  ")
        line.append("★ " if list(branch) == primary else "  ", style="yellow")
        line.append(" AND ".join(str(option_id) for option_id in branch))
        console.print(line, soft_wrap=True)

    console.print(Text("Decision", style="bold"), soft_wrap=True)
    for option in payload["options"]:
        _print_option(console, option)

    actions = payload["actions"]
    if actions:
        console.print(Text("Actions", style="bold"), soft_wrap=True)
        for action in actions:
            _print_action(console, action)

    shell = payload.get("shell")
    if isinstance(shell, Mapping):
        _print_shell(console, shell)

    gate_shell = payload.get("gate_shell")
    if isinstance(gate_shell, Mapping):
        _print_gate_shell_runtime(console, gate_shell)


def _print_option(console: Console, option: Mapping[str, Any]) -> None:
    line = Text("  ")
    if option["icon"]:
        line.append(f"{option['icon']} ")
    line.append(str(option["id"]), style="bold")
    line.append(f" — {option['label']}", style="dim")
    if option["feedback"] != "disabled":
        line.append(f" · feedback {option['feedback']}", style="dim")
    if not option["default_selected"]:
        line.append(" · off by default", style="dim")
    console.print(line, soft_wrap=True)

    fields = option["inputs"]
    if fields:
        for field in fields:
            console.print(_field_line(field), soft_wrap=True)
        return
    schema = option["input_schema"]
    console.print(
        Text(f"      input: {_raw_schema_summary(schema)}", style="dim"),
        soft_wrap=True,
    )


def _field_line(field: Mapping[str, Any]) -> Text:
    line = Text("      ")
    line.append(str(field["id"]), style="cyan")
    line.append(f" ({field['type']}", style="dim")
    if field["repeatable"]:
        line.append("[]", style="dim")
    line.append(", required)" if field["required"] else ", optional)", style="dim")
    line.append(f" {field['label']}")
    if field["choices"]:
        values = ", ".join(str(choice["value"]) for choice in field["choices"])
        line.append(f" · one of {values}", style="dim")
    if field["default"] is not None:
        line.append(f" · default {field['default']!r}", style="dim")
    if field["secret"]:
        line.append(" · secret", style="magenta")
    return line


def _raw_schema_summary(schema: object) -> str:
    """Describe a raw ``input_schema`` in the words an author needs."""
    if not isinstance(schema, Mapping) or not schema:
        return "any JSON object (permissive raw schema)"
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, Mapping) or not properties:
        return "raw schema, no declared properties"
    required_names = set(required) if isinstance(required, Sequence) else set()
    rendered = ", ".join(
        f"{name}{'*' if name in required_names else ''}" for name in sorted(properties)
    )
    return f"raw schema: {rendered} (* required)"


def _print_action(console: Console, action: Mapping[str, Any]) -> None:
    line = Text("  ")
    if action.get("icon"):
        line.append(f"{action['icon']} ")
    if action.get("key"):
        line.append(f"[{action['key']}] ", style="yellow")
    line.append(str(action["id"]), style="bold")
    line.append(f" — {action['label']}", style="dim")
    line.append(f" · {action['kind']}", style="dim")
    if action["kind"] == "edit_file":
        line.append(f" · edits {action['edit_target']}", style="dim")
    else:
        line.append(f" · display {action['display']}", style="dim")
    console.print(line, soft_wrap=True)
    if action.get("description"):
        console.print(
            Text(f"      {action['description']}", style="dim"), soft_wrap=True
        )


def _print_shell(console: Console, shell: Mapping[str, Any]) -> None:
    console.print(Text("Gate Shell", style="bold"), soft_wrap=True)
    line = Text("  ")
    line.append(str(shell.get("pending_status") or "GATE"), style="bold")
    line.append(" → ", style="dim")
    line.append(str(shell.get("settled_status") or "GATED"), style="bold")
    workspace = shell.get("workspace")
    if workspace:
        line.append(f" · workspace {workspace}", style="dim")
    suffix = shell.get("suffix")
    if suffix:
        line.append(f" · suffix {suffix}", style="dim")
    console.print(line, soft_wrap=True)
    next_policy = shell.get("next")
    if isinstance(next_policy, Mapping):
        output = next_policy.get("output")
        if isinstance(output, list):
            output_text = ", ".join(str(item) for item in output)
        else:
            output_text = str(output or "")
        followup = Text("      next: ", style="dim")
        followup.append(str(next_policy.get("fork") or "family"))
        if output_text:
            followup.append(f" · output {output_text}", style="dim")
        if next_policy.get("model"):
            followup.append(f" · model {next_policy['model']}", style="dim")
        console.print(followup, soft_wrap=True)


def _print_gate_shell_runtime(console: Console, gate_shell: Mapping[str, Any]) -> None:
    """Print the live gate-shell state ``sase gate show`` extends onto §5."""
    console.print(Text("Gate Shell Runtime", style="bold"), soft_wrap=True)
    line = Text("  ")
    line.append(str(gate_shell["gate_state"]), style="bold")
    line.append(f" · {gate_shell['status_label']}", style="dim")
    line.append(f" · member {gate_shell['member_agent_name']}", style="dim")
    console.print(line, soft_wrap=True)
    if gate_shell.get("holds_workspace_claim"):
        console.print(
            Text("  holds a workspace claim", style="bold yellow"), soft_wrap=True
        )
    if gate_shell.get("followup_agent"):
        line = Text("  follow-up: ", style="dim")
        line.append(str(gate_shell["followup_agent"]), style="bold")
        if gate_shell.get("followup_outcome"):
            line.append(f" ({gate_shell['followup_outcome']})", style="dim")
        console.print(line, soft_wrap=True)
    if gate_shell.get("followup_needs_attention"):
        reason = gate_shell.get("followup_error") or gate_shell.get(
            "followup_degraded_reason"
        )
        console.print(
            Text(f"  ⚑ follow-up needs attention: {reason}", style="bold yellow"),
            soft_wrap=True,
        )


def _status_style(status: str) -> str:
    return {
        "pending": "bold cyan",
        "answered": "bold green",
        "cancelled": "bold yellow",
        "timeout": "bold yellow",
    }[status]


__all__ = ["handle_gate_show"]
