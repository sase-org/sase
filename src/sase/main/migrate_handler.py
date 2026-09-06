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
    if sub == "list":
        _handle_list(args)
        return
    if sub == "plan":
        _handle_plan(args)
        return
    if sub == "restore":
        _handle_restore(args)
        return
    if sub == "resume":
        _handle_resume(args)
        return
    if sub == "run":
        _handle_run(args)
        return
    if sub == "status":
        _handle_status(args)
        return
    if sub == "verify":
        _handle_verify(args)
        return
    print(
        "Usage: sase migrate {backup,list,plan,restore,resume,run,status,verify}",
        file=sys.stderr,
    )
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


def _handle_list(args: argparse.Namespace) -> None:
    from sase.migration_kit.driver import list_operations

    outcome = list_operations(
        root=Path(args.root) if getattr(args, "root", None) else None,
        home=Path(args.home) if getattr(args, "home", None) else None,
    )
    _print_driver_outcome(outcome, json_output=bool(getattr(args, "json", False)))


def _handle_plan(args: argparse.Namespace) -> None:
    from sase.migration_kit.driver import plan_operation

    outcome = plan_operation(
        args.operation,
        root=Path(args.root) if getattr(args, "root", None) else None,
        home=Path(args.home) if getattr(args, "home", None) else None,
        backup_id=getattr(args, "backup_id", None),
    )
    _print_driver_outcome(outcome, json_output=bool(getattr(args, "json", False)))


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


def _handle_resume(args: argparse.Namespace) -> None:
    from sase.migration_kit.driver import resume_run

    outcome = resume_run(
        args.run_id,
        apply=bool(getattr(args, "apply", False)),
        lock_timeout_ms=int(getattr(args, "lock_timeout_ms", 5000)),
    )
    _print_driver_outcome(outcome, json_output=bool(getattr(args, "json", False)))


def _handle_run(args: argparse.Namespace) -> None:
    from sase.migration_kit.driver import run_manifest

    outcome = run_manifest(
        Path(args.manifest),
        apply=bool(getattr(args, "apply", False)),
        lock_timeout_ms=int(getattr(args, "lock_timeout_ms", 5000)),
    )
    _print_driver_outcome(outcome, json_output=bool(getattr(args, "json", False)))


def _handle_status(args: argparse.Namespace) -> None:
    from sase.migration_kit.driver import status_runs

    outcome = status_runs()
    _print_driver_outcome(outcome, json_output=bool(getattr(args, "json", False)))


def _handle_verify(args: argparse.Namespace) -> None:
    from sase.migration_kit.driver import verify_run

    outcome = verify_run(args.run_id)
    _print_driver_outcome(outcome, json_output=bool(getattr(args, "json", False)))


def _print_driver_outcome(outcome: object, *, json_output: bool) -> None:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    from sase.migration_kit.driver import MigrationCommandOutcome

    assert isinstance(outcome, MigrationCommandOutcome)
    if json_output:
        print(json.dumps(outcome.to_json_dict(), indent=2, sort_keys=True))
        sys.exit(0 if outcome.ok else 1)

    console = Console()
    color = "green" if outcome.ok else "red"
    console.print(
        f"[bold {color}]sase migrate {outcome.command}[/bold {color}] · "
        f"{outcome.message}"
    )
    if outcome.run_id:
        console.print(f"  run id: [bold]{outcome.run_id}[/bold]")
    if outcome.manifest_path:
        console.print(f"  manifest: [bold]{outcome.manifest_path}[/bold]")
    if outcome.receipt_path:
        console.print(f"  receipt: [bold]{outcome.receipt_path}[/bold]")

    if outcome.command == "list":
        table = Table("operation", "backup", "apply", "roots", box=None)
        for row in outcome.details.get("operations", []):
            if not isinstance(row, dict):
                continue
            table.add_row(
                str(row["name"]),
                "yes" if row.get("backup_required") else "no",
                "yes" if row.get("apply_supported") else "no",
                ", ".join(str(item) for item in row.get("roots", [])),
            )
        console.print(table)
    elif outcome.command == "status":
        table = Table("run", "operation", "state", "resumable", box=None)
        for row in outcome.details.get("runs", []):
            if not isinstance(row, dict):
                continue
            table.add_row(
                str(row.get("run_id") or ""),
                str(row.get("operation") or ""),
                str(row.get("state") or ""),
                "yes" if row.get("resumable") else "no",
            )
        console.print(table)

    for error in outcome.errors:
        console.print(Text(error, style="red"))
    sys.exit(0 if outcome.ok else 1)
