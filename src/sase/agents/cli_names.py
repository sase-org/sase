"""CLI handlers for permanent agent-name maintenance."""

from __future__ import annotations

import argparse
import json
import sys


def handle_agents_names(args: argparse.Namespace) -> None:
    """Dispatch ``sase agent names`` subcommands."""
    sub = getattr(args, "names_subcommand", None)
    if sub == "migrate-auto":
        from sase.agent.names import run_historical_auto_name_migration

        result = run_historical_auto_name_migration(
            force=bool(getattr(args, "force", False))
        )
        payload = {
            "changed": result.changed,
            "migrated_count": len(result.migrated_names),
            "migrated_names": result.migrated_names,
            "files_changed": list(result.files_changed),
            "skipped_by_marker": result.skipped_by_marker,
        }
        if getattr(args, "json", False):
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            if result.skipped_by_marker:
                print("Historical auto-name migration already completed.")
            else:
                print(
                    "Historical auto-name migration completed: "
                    f"{payload['migrated_count']} name(s), "
                    f"{len(result.files_changed)} file(s) changed."
                )
        return

    if sub == "purge-local-state":
        from sase.agents_sync.purge_local_state import purge_local_import_state

        purge_outcome = purge_local_import_state(
            apply=bool(getattr(args, "apply", False)),
        )
        if getattr(args, "json", False):
            print(json.dumps(purge_outcome.to_json_dict(), indent=2, sort_keys=True))
        else:
            _render_purge_local_state_outcome(purge_outcome)
        sys.exit(0 if purge_outcome.ok else 1)

    print("Usage: sase agent names {migrate-auto,purge-local-state}")
    sys.exit(1)


def _render_purge_local_state_outcome(outcome: object) -> None:
    from rich.console import Console
    from rich.text import Text

    from sase.agents_sync.purge_local_state import PurgeLocalStateOutcome

    assert isinstance(outcome, PurgeLocalStateOutcome)
    console = Console()
    mode = "DRY RUN" if outcome.dry_run else "APPLY"
    console.print(f"[bold cyan]Purge local import state[/bold cyan] · {mode}")
    verb = "Would remove" if outcome.dry_run else "Removed"
    if outcome.is_empty:
        console.print(Text("No locally materialized import state found.", "green"))
    for path in outcome.artifact_dirs:
        console.print(f"  {verb} artifact: [bold]{path}[/bold]")
    for path in outcome.chat_files:
        console.print(f"  {verb} chat file: [bold]{path}[/bold]")
    for path in outcome.bundle_files:
        console.print(f"  {verb} dismissed bundle: [bold]{path}[/bold]")
    if outcome.dismissed_identities:
        console.print(
            f"  {verb} {len(outcome.dismissed_identities)} dismissed identity(ies)"
        )
    for path in outcome.import_dirs:
        console.print(f"  {verb} import journals/staging: [bold]{path}[/bold]")
    for path in outcome.cache_dirs:
        console.print(f"  {verb} incoming cache dir: [bold]{path}[/bold]")
    for path in outcome.receipt_files:
        console.print(f"  {verb} import receipt file: [bold]{path}[/bold]")
    if not outcome.dry_run and outcome.surviving_import_names:
        console.print(
            Text(
                "Surviving import-origin registry rows: "
                + ", ".join(outcome.surviving_import_names),
                style="yellow",
            )
        )
    for error in outcome.errors:
        console.print(Text(error, style="red"))
    if outcome.dry_run:
        console.print("Run again with [bold]--apply[/bold] to commit.")
