"""CLI handler for the ``sase revive-log`` command."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, NoReturn

from rich.console import Console
from rich.table import Table

from sase.logs.run_log import iter_revive_events


def _resolve_since(raw: str | None) -> Any:
    if raw is None:
        return None
    from sase.logs.daterange import parse_daterange

    start, _ = parse_daterange(raw)
    return start.replace(tzinfo=None)


def _outcome_for(record: dict[str, Any]) -> str:
    outcome = record.get("outcome")
    if outcome:
        return str(outcome)
    event = record.get("event")
    if event == "agent_revived":
        return "success"
    if event == "agent_revive_failed":
        return "failure"
    if event == "agent_revive_started":
        return "started"
    return ""


def _reason_for(record: dict[str, Any]) -> str:
    if record.get("event") == "agent_revive_failed":
        reason = record.get("reason")
        if reason:
            return str(reason)
        stage = record.get("stage")
        error_type = record.get("error_type")
        if stage and error_type:
            return f"{stage}: {error_type}"
        if stage:
            return str(stage)
        if error_type:
            return str(error_type)
    return ""


def handle_revive_log_command(args: argparse.Namespace) -> NoReturn:
    """Handle the ``sase revive-log`` command."""
    console = Console()

    try:
        since = _resolve_since(args.since)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)

    records: list[dict[str, Any]] = []
    limit = None if args.all else max(int(args.limit), 1)
    for record in iter_revive_events(since=since, outcome=args.outcome):
        records.append(record)
        if limit is not None and len(records) >= limit:
            break

    if args.as_json:
        for record in records:
            sys.stdout.write(json.dumps(record) + "\n")
        sys.exit(0)

    if not records:
        console.print("[dim]No revive events recorded.[/dim]")
        sys.exit(0)

    table = Table(title="Agent revive log", show_lines=False)
    table.add_column("timestamp", style="cyan", no_wrap=True)
    table.add_column("cl_name", style="bold")
    table.add_column("raw_suffix")
    table.add_column("outcome")
    table.add_column("reason / stage")

    for record in records:
        outcome = _outcome_for(record)
        outcome_style = {
            "success": "[green]success[/green]",
            "failure": "[red]failure[/red]",
            "started": "[yellow]started[/yellow]",
        }.get(outcome, outcome)
        table.add_row(
            str(record.get("timestamp", "")),
            str(record.get("cl_name", "") or ""),
            str(record.get("raw_suffix", "") or ""),
            outcome_style,
            _reason_for(record),
        )

    console.print(table)
    sys.exit(0)
