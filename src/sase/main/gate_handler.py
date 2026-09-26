"""Handler for the ``sase gate`` CLI command group."""

from __future__ import annotations

import argparse
import json
import sys
from typing import NoReturn

from sase.gate_turn.models import GateTurnError
from sase.notification_gates.models import GateError
from sase.notifications.models import normalize_notification_tags


def handle_gate_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch gate subcommands."""
    subcommand = getattr(args, "gate_subcommand", None)
    if subcommand == "act":
        from sase.notification_gates.cli_act import handle_gate_act

        handle_gate_act(args)
    if subcommand == "answer":
        from sase.notification_gates.cli_answer import handle_gate_answer

        handle_gate_answer(args)
    if subcommand == "cancel":
        from sase.main.gate_turn_handler import handle_gate_turn_cancel

        handle_gate_turn_cancel(args)
    if subcommand == "create":
        _handle_gate_create(args)
    if subcommand == "list":
        from sase.main.gate_turn_handler import handle_gate_turn_list

        handle_gate_turn_list(args)
    if subcommand == "show":
        from sase.notification_gates.cli_show import handle_gate_show

        handle_gate_show(args)
    if subcommand == "wait":
        from sase.notifications.cli_wait import handle_gate_wait

        handle_gate_wait(args)

    print("Usage: sase gate {act,answer,cancel,create,list,show,wait}", file=sys.stderr)
    sys.exit(1)


def _handle_gate_create(args: argparse.Namespace) -> NoReturn:
    """Create a durable gate from a JSON specification read from stdin."""
    data = _read_stdin_object()
    origin_agent = getattr(args, "origin_agent", None)
    panel = getattr(args, "panel", None)
    panel_icon = getattr(args, "panel_icon", None)
    sender = getattr(args, "sender", None)
    cli_tags = getattr(args, "tag", None)
    _merge_shell_cli_overrides(data, args)
    if (
        origin_agent is not None
        or panel is not None
        or panel_icon is not None
        or sender is not None
        or cli_tags
    ):
        presentation = data.get("presentation", data.get("notification", {}))
        if not isinstance(presentation, dict):
            print("Error: presentation must be an object", file=sys.stderr)
            sys.exit(1)
        presentation = dict(presentation)
        if origin_agent is not None:
            presentation["origin_agent"] = origin_agent
        if panel is not None:
            presentation["panel"] = panel
        if panel_icon is not None:
            presentation["panel_icon"] = panel_icon
        if sender is not None:
            presentation["sender"] = sender
        if cli_tags:
            presentation["tags"] = _create_tags(presentation.get("tags"), cli_tags)
        data["presentation"] = presentation

    try:
        if isinstance(data.get("shell"), dict):
            from sase.gate_turn import (
                create_gate_turn,
                maybe_handoff_gate_from_agent,
                will_handoff_gate_to_agent_runner,
            )

            creation = create_gate_turn(data)
            print(json.dumps(creation.to_dict(), sort_keys=True))
            sys.stdout.flush()
            if creation.should_handoff and will_handoff_gate_to_agent_runner():
                maybe_handoff_gate_from_agent(creation)
            sys.exit(0)
        from sase.notification_gates.service import create_gate

        result = create_gate(data)
    except GateError as exc:
        print(f"Error [{exc.code}] {exc.target}: {exc}", file=sys.stderr)
        sys.exit(1)
    except GateTurnError as exc:
        print(f"Error: gate shell creation failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"Error: gate creation failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result.to_dict(), sort_keys=True))
    sys.exit(0)


def _merge_shell_cli_overrides(
    data: dict[str, object], args: argparse.Namespace
) -> None:
    from sase.agent.legacy_sase_shell_syntax import normalize_gate_shell_bool_args

    raw_args = {
        "turn": bool(getattr(args, "turn", False)),
        "turn_status": getattr(args, "turn_status", None),
        "turn_stop_status": getattr(args, "turn_stop_status", None),
        "shell": bool(getattr(args, "shell", False)),
        "shell_status": getattr(args, "shell_status", None),
        "shell_stop_status": getattr(args, "shell_stop_status", None),
    }
    try:
        normalized = normalize_gate_shell_bool_args(raw_args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    turn_requested = bool(normalized.get("turn", False))
    next_prompt = getattr(args, "next", None)
    next_fork = getattr(args, "next_fork", None)
    next_model = getattr(args, "next_model", None)
    next_output = getattr(args, "next_output", None)
    turn_status = normalized.get("turn_status", None)
    turn_stop_status = normalized.get("turn_stop_status", None)
    if not any(
        (
            turn_requested,
            next_prompt is not None,
            next_fork is not None,
            next_model is not None,
            bool(next_output),
            turn_status is not None,
            turn_stop_status is not None,
        )
    ):
        return
    from sase.agent.legacy_sase_shell_syntax import (
        normalize_persisted_gate_spec_block,
    )

    _normalized_spec = normalize_persisted_gate_spec_block(dict(data))
    data.clear()
    data.update(_normalized_spec)
    raw_turn = data.get("turn", {})
    if not isinstance(raw_turn, dict):
        print("Error: turn must be an object", file=sys.stderr)
        sys.exit(1)
    turn = dict(raw_turn)
    raw_next = turn.get("next", {})
    if not isinstance(raw_next, dict):
        print("Error: turn.next must be an object", file=sys.stderr)
        sys.exit(1)
    next_policy = dict(raw_next)
    if next_prompt is not None:
        next_policy["prompt"] = next_prompt
    if next_fork is not None:
        next_policy["fork"] = next_fork
    if next_model is not None:
        next_policy["model"] = next_model
    if next_output:
        next_policy["output"] = list(next_output)
    if next_policy:
        turn["next"] = next_policy
    if turn_status is not None:
        turn["pending_status"] = turn_status
    if turn_stop_status is not None:
        turn["settled_status"] = turn_stop_status
    data["turn"] = turn


def _read_stdin_object() -> dict[str, object]:
    raw = sys.stdin.read().strip()
    if not raw:
        print("Error: gate specification JSON is required on stdin", file=sys.stderr)
        sys.exit(1)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        print("Error: invalid JSON on stdin", file=sys.stderr)
        sys.exit(1)
    if not isinstance(parsed, dict):
        print("Error: stdin JSON must be an object", file=sys.stderr)
        sys.exit(1)
    return parsed


def _create_tags(json_tags: object, cli_tags: list[str]) -> list[str]:
    values: list[str] = []
    if isinstance(json_tags, str):
        values.append(json_tags)
    elif isinstance(json_tags, list):
        values.extend(str(tag) for tag in json_tags)
    elif json_tags is not None:
        values.append(str(json_tags))
    values.extend(cli_tags)
    return normalize_notification_tags(values)


__all__ = ["handle_gate_command"]
