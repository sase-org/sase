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

_STATUS_PROJECTION = {
    "responded": "answered",
    "cancelled": "cancelled",
    "timed_out": "timeout",
}


def handle_gate_show(args: argparse.Namespace) -> NoReturn:
    """Print one gate's declared decision surface."""
    try:
        payload = _show(args)
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


def _show(args: argparse.Namespace) -> dict[str, Any]:
    bundle = resolve_gate_cli_bundle(str(args.kind), str(args.id))
    gate = GateBranchData.from_envelope(
        bundle.envelope, default_feedback=bundle.adapter.default_feedback
    )
    poll = poll_gate(bundle.root)
    return {
        "actions": [
            _action_payload(operation) for operation in _operations(bundle.envelope)
        ],
        "branches": [list(branch) for branch in gate.branches],
        "kind": bundle.kind,
        "options": [_option_payload(option) for option in gate.options],
        "primary_branch": list(gate.primary_branch),
        "query": gate.query,
        "request_id": bundle.request_id,
        "status": "pending" if poll is None else _STATUS_PROJECTION[poll.status],
    }


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


def _status_style(status: str) -> str:
    return {
        "pending": "bold cyan",
        "answered": "bold green",
        "cancelled": "bold yellow",
        "timeout": "bold yellow",
    }[status]


__all__ = ["handle_gate_show"]
