"""``sase gate wait`` — mechanically wait for a durable gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

from rich.console import Console
from rich.text import Text

from sase.notification_gates.models import GateError
from sase.notification_gates.paths import bundle_paths
from sase.notification_gates.poller import GatePollResult, wait_for_gate

_EXIT_CODES = {"answered": 0, "cancelled": 3, "timeout": 4}
_STATUS_PROJECTION = {
    "responded": "answered",
    "cancelled": "cancelled",
    "timed_out": "timeout",
}


def handle_gate_wait(args: argparse.Namespace) -> NoReturn:
    """Wait for one gate and emit its stable terminal projection."""
    request_id = str(args.id)
    kind = str(args.kind)
    try:
        paths = bundle_paths(kind, request_id)
        result = wait_for_gate(
            paths.root,
            timeout_seconds=getattr(args, "timeout", None),
        )
    except GateError as exc:
        print(
            f"sase gate wait: error [{exc.code}] {exc.target}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    except OSError as exc:
        print(f"sase gate wait: cannot read gate: {exc}", file=sys.stderr)
        sys.exit(1)

    payload = _terminal_payload(result, paths.response)
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_human_summary(
            payload,
            request_id=request_id,
            kind=kind,
        )
    sys.exit(_EXIT_CODES[str(payload["status"])])


def _terminal_payload(result: GatePollResult, response_path: Path) -> dict[str, object]:
    return {
        "status": _STATUS_PROJECTION[result.status],
        "selected_option_ids": list(result.selected_option_ids),
        "feedback": result.feedback,
        "response_path": str(response_path),
    }


def _print_human_summary(
    payload: dict[str, object],
    *,
    request_id: str,
    kind: str,
) -> None:
    status = str(payload["status"])
    symbol, label, style = {
        "answered": ("✓", "answered", "bold green"),
        "cancelled": ("⊘", "cancelled", "bold yellow"),
        "timeout": ("⌛", "timed out", "bold yellow"),
    }[status]
    summary = Text()
    summary.append(symbol, style=style)
    summary.append(f" Gate {kind}/{request_id} ")
    summary.append(label, style=style)
    selected = payload["selected_option_ids"]
    if isinstance(selected, list) and selected:
        summary.append(" · options ", style="dim")
        summary.append(
            ", ".join(str(option_id) for option_id in selected), style="bold"
        )
    feedback = payload["feedback"]
    if feedback is not None:
        summary.append(" · feedback ", style="dim")
        summary.append(str(feedback))

    console = Console()
    console.print(summary, soft_wrap=True)
    response = Text("Response path: ", style="dim")
    response.append(str(payload["response_path"]))
    console.print(response, soft_wrap=True)


__all__ = ["handle_gate_wait"]
