"""CLI handlers for permanent agent-name maintenance."""

from __future__ import annotations

import argparse
import json
import sys


def handle_agents_names(args: argparse.Namespace) -> None:
    """Dispatch ``sase agent names`` subcommands."""
    sub = getattr(args, "names_subcommand", None)
    if sub == "forget-import":
        from sase.agents_sync.v1_forget_import import forget_v1_import

        outcome = forget_v1_import(
            args.machine,
            apply=bool(getattr(args, "apply", False)),
        )
        if getattr(args, "json", False):
            print(json.dumps(outcome.to_json_dict(), indent=2, sort_keys=True))
        else:
            _render_forget_import_outcome(outcome)
        sys.exit(0 if outcome.ok else 1)

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

    print("Usage: sase agent names {forget-import,migrate-auto}")
    sys.exit(1)


def _render_forget_import_outcome(outcome: object) -> None:
    from rich.console import Console
    from rich.text import Text

    from sase.agents_sync.v1_forget_import import V1ForgetImportOutcome

    assert isinstance(outcome, V1ForgetImportOutcome)
    console = Console()
    mode = "DRY RUN" if outcome.dry_run else "APPLY"
    console.print(f"[bold cyan]{outcome.machine}[/bold cyan] · {mode}")
    verb = "Would remove" if outcome.dry_run else "Removed"
    if not (
        outcome.artifact_dirs
        or outcome.chat_files
        or outcome.bundle_files
        or outcome.dismissed_identities
        or outcome.receipts
    ):
        console.print(
            Text("No legacy v1 import closure found for this machine.", "green")
        )
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
    for project_key, key in outcome.receipts:
        console.print(f"  {verb} import receipt: [bold]{project_key}: {key[3]}[/bold]")
    if not outcome.dry_run and outcome.surviving_import_v1_names:
        console.print(
            Text(
                "Surviving import_v1 registry rows: "
                + ", ".join(outcome.surviving_import_v1_names),
                style="yellow",
            )
        )
    for error in outcome.errors:
        console.print(Text(error, style="red"))
    if outcome.dry_run:
        console.print("Run again with [bold]--apply[/bold] to commit.")
