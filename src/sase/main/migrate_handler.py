"""Handler for ``sase migrate`` subcommands.

TEMPORARY: deletion owner sase-x7.14. Imports ``sase.migration_kit`` lazily
from inside the dispatch functions below so the package is never touched by
interpreter startup, plugin discovery, completion, or agent launch.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def handle_migrate_command(args: argparse.Namespace) -> None:
    """Dispatch ``sase migrate`` subcommands."""
    sub = getattr(args, "migrate_subcommand", None)
    if sub == "backup":
        _handle_backup(args)
        return
    if sub == "restore":
        _handle_restore(args)
        return
    print("Usage: sase migrate {backup,restore}", file=sys.stderr)
    sys.exit(1)


def _handle_backup(args: argparse.Namespace) -> None:
    from sase.migration_kit.backup import capture_backup

    secondary = getattr(args, "secondary", None)
    outcome = capture_backup(
        Path(args.root),
        apply=bool(getattr(args, "apply", False)),
        secondary=Path(secondary) if secondary else None,
    )
    if getattr(args, "json", False):
        print(json.dumps(outcome.to_json_dict(), indent=2, sort_keys=True))
    else:
        _render_backup_outcome(outcome)
    sys.exit(0 if outcome.ok else 1)


def _render_backup_outcome(outcome: object) -> None:
    from rich.console import Console
    from rich.text import Text

    from sase.migration_kit.backup import BackupOutcome

    assert isinstance(outcome, BackupOutcome)
    console = Console()
    mode = "DRY RUN" if outcome.dry_run else "APPLY"
    console.print(f"[bold cyan]Migration kit backup[/bold cyan] · {mode}")
    console.print(f"  root: [bold]{outcome.resolved_root}[/bold]")
    if outcome.backup_id:
        console.print(f"  backup id: [bold]{outcome.backup_id}[/bold]")
    if outcome.destination:
        verb = "Would write to" if outcome.dry_run else "Wrote to"
        console.print(f"  {verb}: [bold]{outcome.destination}[/bold]")
    console.print(
        f"  size: {outcome.total_size_bytes} bytes "
        f"(need {outcome.required_bytes}, free {outcome.free_bytes})"
    )
    console.print(
        f"  members: {outcome.member_count} "
        f"({outcome.sqlite_member_count} sqlite, {outcome.symlink_count} symlink)"
    )
    if not outcome.backup_root_contained:
        console.print(
            Text(
                "Cutover backup root is NOT contained outside every SASE runtime root.",
                style="red",
            )
        )
    for error in outcome.errors:
        console.print(Text(error, style="red"))
    if outcome.ok and outcome.dry_run:
        console.print("Run again with [bold]--apply[/bold] to commit.")


def _handle_restore(args: argparse.Namespace) -> None:
    from sase.migration_kit.restore import restore_backup

    root = getattr(args, "root", None)
    outcome = restore_backup(
        args.backup_id,
        apply=bool(getattr(args, "apply", False)),
        live_root=Path(root) if root else None,
    )
    if getattr(args, "json", False):
        print(json.dumps(outcome.to_json_dict(), indent=2, sort_keys=True))
    else:
        _render_restore_outcome(outcome)
    sys.exit(0 if outcome.ok else 1)


def _render_restore_outcome(outcome: object) -> None:
    from rich.console import Console
    from rich.text import Text

    from sase.migration_kit.restore import RestoreOutcome

    assert isinstance(outcome, RestoreOutcome)
    console = Console()
    mode = "DRY RUN" if outcome.dry_run else "APPLY"
    console.print(f"[bold cyan]Migration kit restore[/bold cyan] · {mode}")
    console.print(f"  backup id: [bold]{outcome.backup_id}[/bold]")
    if outcome.checksum_failures:
        console.print(Text("Checksum verification FAILED:", style="red"))
        for failure in outcome.checksum_failures:
            console.print(f"  {failure}")
        return
    console.print(f"  staged at: [bold]{outcome.staging_path}[/bold]")
    console.print(f"  live root: {outcome.live_root}")
    console.print(f"  verified members: {outcome.verified_member_count}")
    for path in outcome.diff_added:
        console.print(f"  [green]+ {path}[/green]")
    for path in outcome.diff_removed:
        console.print(f"  [red]- {path}[/red]")
    for path in outcome.diff_changed:
        console.print(f"  [yellow]~ {path}[/yellow]")
    for delta in outcome.ownership_deltas:
        console.print(
            Text(
                f"ownership delta {delta.relative_path}: backed up "
                f"{delta.backed_up_uid}:{delta.backed_up_gid}, live "
                f"{delta.live_uid}:{delta.live_gid}",
                style="yellow",
            )
        )
    if outcome.applied:
        console.print("[bold green]Swapped the staged restore into place.[/bold green]")
    elif outcome.ok:
        console.print("Run again with [bold]--apply[/bold] to swap it into place.")
    for error in outcome.errors:
        console.print(Text(error, style="red"))
