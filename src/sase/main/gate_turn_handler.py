"""Handlers for ``sase gate list`` and ``sase gate cancel``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import NoReturn

from rich.console import Console

from sase.gate_turn.cancel import DEFAULT_CANCEL_REASON, cancel_gate_turn
from sase.gate_turn.models import GateTurnRefError
from sase.gate_turn.naming import short_gate_turn_id
from sase.gate_turn.store import list_gate_turns, resolve_gate_turn_ref
from sase.notification_gates.cli_support import resolve_gate_cli_bundle
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.models import GateError

from .gate_turn_render import (
    empty_gate_turn_panel,
    gate_turn_cancel_json,
    gate_turn_list_json,
    gate_turn_list_markdown,
    gate_turn_table,
)

#: Exit code for an unknown or ambiguous gate-turn reference, mirroring
#: ``sase gate show``'s ref-resolution failure code.
EXIT_REF_ERROR = 2


def handle_gate_turn_list(args: argparse.Namespace) -> NoReturn:
    """Render gate turns as a table, markdown, or JSON."""
    project = getattr(args, "project", None)
    agent = getattr(args, "agent", None)
    states = set(getattr(args, "state", None) or ())
    include_all = bool(getattr(args, "all", False))
    limit = getattr(args, "limit", None)
    fmt = (
        "json"
        if bool(getattr(args, "json", False))
        else getattr(args, "format", "table")
    )

    try:
        records = list_gate_turns(project=project)
    except Exception as exc:
        print(f"sase gate list: cannot read gate turns: {exc}", file=sys.stderr)
        sys.exit(1)

    if agent:
        records = [record for record in records if record.lane == agent]
    if states:
        records = [record for record in records if record.gate_state in states]
    elif not include_all:
        records = [record for record in records if not record.is_terminal]
    if limit is not None:
        records = records[: max(0, limit)]

    if fmt == "json":
        scope = {
            "all": include_all,
            "project": project,
            "agent": agent,
            "state": sorted(states) or None,
        }
        json.dump(gate_turn_list_json(records, scope=scope), sys.stdout, indent=2)
        sys.stdout.write("\n")
        sys.exit(0)
    if fmt == "markdown":
        sys.stdout.write(gate_turn_list_markdown(records))
        sys.exit(0)

    console = Console()
    title = f"Gate turns · {_scope_label(project=project, agent=agent, include_all=include_all)} ({len(records)})"
    if records:
        console.print(gate_turn_table(records, title=title))
    else:
        hint = (
            None
            if include_all
            else "No pending gate turns; pass -a/--all to include settled ones."
        )
        console.print(empty_gate_turn_panel(title, hint=hint))
    sys.exit(0)


def handle_gate_turn_cancel(args: argparse.Namespace) -> NoReturn:
    """Cancel one pending gate turn, resolving the same refs as ``gate show``."""
    request_id = getattr(args, "id", None)
    kind = getattr(args, "kind", None)
    gate_ref = str(getattr(args, "gate_ref", "") or "")
    if request_id or kind:
        _handle_gate_cancel_by_kind_and_id(args, kind=kind, request_id=request_id)

    if not gate_ref:
        print(
            "sase gate cancel: pass a gate-turn reference, or -i/--id plus -k/--kind",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        record = resolve_gate_turn_ref(gate_ref, list_gate_turns())
    except GateTurnRefError as exc:
        message = f"sase gate cancel: {exc}"
        print(message, file=sys.stderr)
        sys.exit(EXIT_REF_ERROR)

    was_pending = not record.is_terminal
    reason = getattr(args, "reason", None) or DEFAULT_CANCEL_REASON
    result = cancel_gate_turn(record, reason=reason)
    changed = was_pending and result.is_terminal
    short_id = short_gate_turn_id(result.gate_id)
    message = (
        f"Cancelled gate turn {short_id}."
        if changed
        else f"Gate turn {short_id} is already {result.gate_state}; nothing to do."
    )

    if bool(getattr(args, "json", False)):
        json.dump(gate_turn_cancel_json(result, changed=changed), sys.stdout, indent=2)
        sys.stdout.write("\n")
        sys.exit(0)

    print(message)
    sys.exit(0)


def _handle_gate_cancel_by_kind_and_id(
    args: argparse.Namespace, *, kind: object, request_id: object
) -> NoReturn:
    if not kind or not request_id:
        print(
            "sase gate cancel: -i/--id and -k/--kind must be given together",
            file=sys.stderr,
        )
        sys.exit(1)
    if getattr(args, "gate_ref", None):
        print(
            "sase gate cancel: pass either a gate-turn reference or -i/--id plus -k/--kind",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        bundle = resolve_gate_cli_bundle(str(kind), str(request_id))
        cancellation = cancel_gate(
            bundle.root,
            reason=getattr(args, "reason", None) or DEFAULT_CANCEL_REASON,
            source="cli",
        )
    except GateError as exc:
        if bool(getattr(args, "json", False)):
            json.dump(
                {
                    "success": False,
                    "code": exc.code,
                    "target": exc.target,
                    "message": str(exc),
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            print(
                f"sase gate cancel: error [{exc.code}] {exc.target}: {exc}",
                file=sys.stderr,
            )
        sys.exit(1)
    except Exception as exc:
        print(f"sase gate cancel: cannot cancel gate: {exc}", file=sys.stderr)
        sys.exit(1)

    if bool(getattr(args, "json", False)):
        json.dump(cancellation, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"Cancelled gate {kind}/{request_id}.")
    sys.exit(0)


def _scope_label(*, project: str | None, agent: str | None, include_all: bool) -> str:
    parts = ["all projects" if project is None else f"project {project}"]
    if agent:
        parts.append(f"agent {agent}")
    parts.append("all" if include_all else "pending")
    return ", ".join(parts)


__all__ = ["handle_gate_turn_cancel", "handle_gate_turn_list"]
