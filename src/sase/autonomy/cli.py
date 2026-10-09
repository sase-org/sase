"""Dispatch for the ``sase autonomy`` CLI group.

Every ``%auto`` outcome comes from one core ``evaluate()`` applied to one
persisted ``agent_meta.autonomy`` record. This group only inspects that
record through the thin adapter: ``explain`` predicts each decision
exactly, ``list``/``show`` print the built-in profiles, and ``log`` reads
the host decision log. Python never re-implements the schema, the
profiles, or the decision algorithm here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


def handle_autonomy_command(args: argparse.Namespace) -> int:
    """Dispatch a parsed ``sase autonomy ...`` command."""
    sub = getattr(args, "autonomy_subcommand", None) or "list"
    if sub == "explain":
        from sase.autonomy.cli_explain import handle_autonomy_explain

        return handle_autonomy_explain(args)
    if sub == "list":
        from sase.autonomy.cli_profiles import handle_autonomy_list

        return handle_autonomy_list(args)
    if sub == "log":
        from sase.autonomy.cli_log import handle_autonomy_log

        return handle_autonomy_log(args)
    if sub == "show":
        from sase.autonomy.cli_profiles import handle_autonomy_show

        return handle_autonomy_show(args)
    print(
        "Usage: sase autonomy {explain,list,log,show}",
        file=sys.stderr,
    )
    sys.exit(1)


def resolve_agent_record(
    name: str,
) -> tuple[str, Path, dict[str, Any]]:
    """Resolve an agent name the way ``sase agent show`` does.

    Returns ``(name, artifacts_dir, record)``. Exits 2 when the agent is
    unknown and 1 when it carries no autonomy record (a pre-record agent
    whose meta has neither a record nor legacy keys).
    """
    from sase.agent.names import find_named_agent
    from sase.autonomy.record import live_record

    agent = find_named_agent(name)
    if agent is None:
        print(f"No agent found with name '{name}'", file=sys.stderr)
        sys.exit(2)
    artifacts_dir = Path(agent.artifacts_dir)
    record = live_record(artifacts_dir)
    if record is None:
        print(
            f"Agent '{name}' carries no autonomy record",
            file=sys.stderr,
        )
        sys.exit(1)
    return agent.name or name, artifacts_dir, record


def read_gate_policy(gate_ref: str) -> tuple[str, str, dict[str, Any]]:
    """Return ``(kind, request_id, policy)`` for one settled gate.

    *gate_ref* is ``KIND/REQUEST_ID`` or a gate-turn reference (short id,
    member name, or owning agent name, as in ``sase gate show``). The
    policy block is the revision that decided the gate. Exits 1 when the
    bundle is missing and 2 when the reference is unknown or ambiguous.
    """
    from sase.gate_turn.store import list_gate_turns, resolve_gate_turn_ref
    from sase.notification_gates.cli_show import show_gate

    kind: str | None = None
    request_id: str | None = None
    if "/" in gate_ref:
        kind, request_id = gate_ref.split("/", 1)
        kind, request_id = kind.strip(), request_id.strip()
    if not kind or not request_id:
        try:
            record = resolve_gate_turn_ref(gate_ref, list_gate_turns())
        except Exception as exc:
            print(f"sase autonomy explain: {exc}", file=sys.stderr)
            sys.exit(2)
        kind, request_id = record.kind, record.gate_id
    try:
        payload = show_gate(kind, request_id)
    except Exception as exc:
        print(f"sase autonomy explain: cannot read gate: {exc}", file=sys.stderr)
        sys.exit(1)
    policy = payload.get("policy")
    if not isinstance(policy, dict) or not policy:
        print(
            f"sase autonomy explain: gate {kind}/{request_id} carries no "
            "autonomy policy block",
            file=sys.stderr,
        )
        sys.exit(1)
    return kind, request_id, dict(policy)


__all__ = ["handle_autonomy_command", "read_gate_policy", "resolve_agent_record"]
