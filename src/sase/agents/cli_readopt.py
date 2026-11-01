"""``sase agent readopt`` — retry one staged-handoff adoption."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.agent.names import find_agent_session, find_named_agent
from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME
from sase.axe.run_agent_exec_staged_recovery import (
    StagedRecoveryResult,
    recover_staged_handoff,
)


def handle_agent_readopt(args: argparse.Namespace) -> int:
    """Recover one unambiguous staged turn and render the outcome."""
    selector = str(args.agent)
    artifacts_dir, error = _resolve_origin(selector)
    if error is not None:
        _render(
            args,
            selector,
            None,
            error=error,
        )
        return 1

    assert artifacts_dir is not None
    result = recover_staged_handoff(artifacts_dir, mode="explicit")
    _render(args, selector, result, artifacts_dir=artifacts_dir)
    return 0 if result.adopted else 1


def _resolve_origin(selector: str) -> tuple[str | None, str | None]:
    """Resolve a name or session to exactly one artifact with a staged record."""
    session = find_agent_session(selector)
    if session is not None:
        candidates = sorted(
            (
                (member.name, str(member.artifacts_dir))
                for member in session.members
                if (member.artifacts_dir / STAGED_HANDOFF_FILENAME).is_file()
            ),
            key=lambda item: item[1],
        )
        if len(candidates) == 1:
            return candidates[0][1], None
        if len(candidates) > 1:
            names = ", ".join(name for name, _path in candidates)
            return (
                None,
                f"session '{selector}' has multiple staged turns ({names}); "
                "select one exact originating agent name",
            )

    agent = find_named_agent(selector)
    if agent is None:
        return None, f"no agent or session found with name '{selector}'"
    artifacts_dir = Path(agent.artifacts_dir)
    if not (artifacts_dir / STAGED_HANDOFF_FILENAME).is_file():
        return None, f"agent '{selector}' has no staged handoff to re-adopt"
    return str(artifacts_dir), None


def _render(
    args: argparse.Namespace,
    selector: str,
    result: StagedRecoveryResult | None,
    *,
    artifacts_dir: str | None = None,
    error: str | None = None,
) -> None:
    """Render the stable JSON envelope or a readable recovery summary."""
    payload: dict[str, Any] = {
        "selector": selector,
        "artifacts_dir": artifacts_dir,
        "adopted": bool(result and result.adopted),
        "already_adopted": bool(result and result.already_adopted),
        "action": result.action if result else "refuse",
        "kind": result.kind if result else None,
        "origin_agent": result.origin_agent if result else None,
        "destination": result.destination if result else None,
        "reason": result.reason if result else error,
        "repair_action": result.repair_action if result else None,
    }
    if args.json:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    status = "Adopted" if payload["adopted"] else "Held / refused"
    body = Text()
    body.append("Origin: ", style="bold")
    body.append(str(payload["origin_agent"] or selector) + "\n")
    if payload["kind"]:
        body.append("Handoff: ", style="bold")
        body.append(str(payload["kind"]) + "\n")
    if payload["destination"]:
        body.append("Destination refs: ", style="bold")
        body.append(json.dumps(payload["destination"], sort_keys=True) + "\n")
    if payload["reason"]:
        body.append("Result: ", style="bold")
        body.append(str(payload["reason"]) + "\n")
    if payload["repair_action"]:
        body.append("Next step: ", style="bold")
        body.append(str(payload["repair_action"]) + "\n")
    Console().print(
        Panel(
            body, title=status, border_style="green" if payload["adopted"] else "yellow"
        )
    )


__all__ = ["handle_agent_readopt"]
