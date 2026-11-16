"""``sase agent hijack`` — stop a stalled agent but keep its work.

Synchronous: exit 0 means the agent is HIJACKED with its workspace claim
held, 2 means refused with nothing changed, and 1 means the stop failed or
an error occurred. ``-j`` emits one stable JSON envelope.
"""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.text import Text

from sase.agent.hijack.facts import resolve_and_decide
from sase.agent.hijack.stop import HijackStopResult, stop_agent_for_hijack

HIJACK_JSON_SCHEMA_VERSION = 1


def handle_agents_hijack(args: argparse.Namespace) -> int:
    """Hijack the named agent, or explain its current decision."""
    name: str = args.name
    reason = getattr(args, "reason", None)
    as_json = bool(getattr(args, "json", False))
    if bool(getattr(args, "explain", False)):
        subject, decision = resolve_and_decide(name)
        message = _explanation(subject.occupant_name or name, decision)
        result = HijackStopResult(
            status="explained",
            message=message,
            exit_code=0,
            reason=decision.get("code"),
            decision=decision,
            occupant_name=subject.occupant_name,
            occupant_reason=subject.occupant_reason,
            workspace_num=(
                None if subject.target is None else subject.target.workspace_num
            ),
        )
    else:
        result = stop_agent_for_hijack(
            name, reason=reason if isinstance(reason, str) else None
        )
    if as_json:
        decision = result.decision or {}
        print(
            json.dumps(
                {
                    "schema_version": HIJACK_JSON_SCHEMA_VERSION,
                    "ok": result.exit_code == 0,
                    "name": name,
                    "status": result.status,
                    "hijack_id": result.hijack_id,
                    "workspace_num": (
                        result.workspace_num
                        if result.workspace_num is not None
                        else (result.record or {}).get("workspace_num")
                    ),
                    "message": result.message,
                    "reason": result.reason,
                    "mode": decision.get("mode"),
                    "code": decision.get("code"),
                    "next_action": decision.get("next_action"),
                    "redirect_op": decision.get("redirect_op"),
                    "adapter": decision.get("adapter"),
                    "occupant_name": result.occupant_name,
                    "occupant_reason": result.occupant_reason,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return result.exit_code
    if result.exit_code == 0:
        style = "bold #FF5FAF" if result.status != "explained" else "bold cyan"
        Console().print(Text(result.message, style=style))
        if result.status == "explained" and result.decision is not None:
            _print_explanation_details(
                result.occupant_name,
                result.occupant_reason,
                result.decision,
            )
        return 0
    if result.exit_code == 2:
        print(result.message, file=sys.stderr)
        return 2
    Console(stderr=True).print(Text(result.message, style="bold red"))
    return 1


def _explanation(name: str, decision: dict[str, object]) -> str:
    mode = str(decision.get("mode") or "unknown")
    if mode == "immediate":
        return f"Hijack decision for {name}: immediate"
    code = decision.get("code")
    suffix = f" ({code})" if isinstance(code, str) and code else ""
    return f"Hijack decision for {name}: {mode}{suffix}"


def _print_explanation_details(
    occupant_name: str | None,
    occupant_reason: str | None,
    decision: dict[str, object],
) -> None:
    console = Console()
    console.print(Text(f"Occupant: {occupant_name or 'none'}", style="cyan"))
    if occupant_reason:
        console.print(Text(f"Selected because: {occupant_reason}", style="dim"))
    message = decision.get("message")
    next_action = decision.get("next_action")
    if isinstance(message, str) and message:
        console.print(Text(f"Reason: {message}", style="white"))
    if isinstance(next_action, str) and next_action:
        console.print(Text(f"Next: {next_action}", style="dim cyan"))


__all__ = ["HIJACK_JSON_SCHEMA_VERSION", "handle_agents_hijack"]
