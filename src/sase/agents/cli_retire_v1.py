"""CLI rendering for explicit legacy-v1 agents-sidecar retirement."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.text import Text

from sase.agents_sync.v1_retirement import (
    V1RetirementOutcome,
    retire_v1_payloads,
)


def handle_agents_retire_v1(args: argparse.Namespace) -> int:
    """Preview or apply evidence-gated retirement and return a truthful code."""

    apply = bool(getattr(args, "apply", False))
    outcomes = retire_v1_payloads(
        tuple(getattr(args, "project", ()) or ()),
        apply=apply,
    )
    if bool(getattr(args, "json", False)):
        json.dump(
            {
                "schema_version": 1,
                "mode": "apply" if apply else "dry-run",
                "projects": [outcome.to_json_dict() for outcome in outcomes],
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
    else:
        _render_outcomes(outcomes)
    return int(any(not outcome.ok for outcome in outcomes))


def _render_outcomes(outcomes: tuple[V1RetirementOutcome, ...]) -> None:
    console = Console()
    for outcome in outcomes:
        mode = "APPLY" if not outcome.dry_run else "DRY RUN"
        console.print(f"[bold cyan]{outcome.project}[/bold cyan] · {mode}")
        if outcome.error:
            console.print(Text(outcome.error, style="red"))
            continue
        if outcome.skip_reason:
            console.print(Text(outcome.skip_reason, style="yellow"))
            continue
        if outcome.uncovered_hoods:
            console.print(
                Text(
                    "REFUSED · v2 manifest does not cover: "
                    + ", ".join(outcome.uncovered_hoods),
                    style="red",
                )
            )
            continue
        if not outcome.manifest_entries:
            console.print(Text("No current-machine legacy-v1 payload found.", "green"))
            continue
        verb = "Would remove" if outcome.dry_run else "Removed"
        for path in outcome.payload_paths:
            console.print(f"  {verb}: [bold]{path}[/bold]")
        if "manifest.json" not in outcome.payload_paths:
            for entry in outcome.manifest_entries:
                console.print(f"  {verb} manifest entry: [bold]{entry}[/bold]")
        if outcome.dry_run:
            console.print("Run again with [bold]--apply[/bold] to commit and push.")
        elif outcome.pushed:
            console.print(Text("Committed and pushed.", "green"))
        elif outcome.committed:
            console.print(Text("Committed; push did not complete.", "yellow"))


__all__ = ["handle_agents_retire_v1"]
