"""Command handlers for restore and revert operations."""

import argparse
import sys
from typing import NoReturn

from rich.console import Console
from rich.markup import escape as _esc


def handle_restore_command(args: argparse.Namespace) -> NoReturn:
    """Handle the 'restore' command.

    Args:
        args: Parsed command-line arguments.
    """
    from sase.ace.patch import find_all_patches
    from sase.ace.restore import list_reverted_patches, restore_patch

    console = Console()

    # Handle --list flag
    if args.list:
        reverted = list_reverted_patches()
        if not reverted:
            console.print("[yellow]No reverted Patches found.[/yellow]")
        else:
            console.print("[bold]Reverted Patches:[/bold]")
            from sase.project_display_names import humanize_cl_name

            for cs in reverted:
                console.print(f"  {humanize_cl_name(cs.name)}")
        sys.exit(0)

    # Validate required argument when not using --list
    if not args.name:
        console.print("[red]Error: name is required (unless using --list)[/red]")
        sys.exit(1)

    # Find the Patch by name
    all_patches = find_all_patches()
    target_patch = None
    for cs in all_patches:
        if cs.name == args.name:
            target_patch = cs
            break

    if target_patch is None:
        console.print(f"[red]Error: Patch '{_esc(args.name)}' not found[/red]")
        sys.exit(1)

    success, error = restore_patch(target_patch, console)
    if not success:
        console.print(f"[red]Error: {_esc(str(error))}[/red]")
        sys.exit(1)

    try:
        from sase.logs.run_log import log_event

        log_event(event="patch_restored", cl_name=args.name)
    except Exception:
        pass
    console.print("[green]Patch restored successfully[/green]")
    sys.exit(0)


def handle_revert_command(args: argparse.Namespace) -> NoReturn:
    """Handle the 'revert' command.

    Args:
        args: Parsed command-line arguments.
    """
    from sase.ace.patch import find_all_patches
    from sase.ace.revert import revert_patch

    console = Console()

    # Find the Patch by name
    all_patches = find_all_patches()
    target_patch = None
    for cs in all_patches:
        if cs.name == args.name:
            target_patch = cs
            break

    if target_patch is None:
        console.print(f"[red]Error: Patch '{_esc(args.name)}' not found[/red]")
        sys.exit(1)

    success, error = revert_patch(target_patch, console)
    if not success:
        console.print(f"[red]Error: {_esc(str(error))}[/red]")
        sys.exit(1)

    try:
        from sase.logs.run_log import log_event

        log_event(event="patch_reverted", cl_name=args.name)
    except Exception:
        pass
    console.print("[green]Patch reverted successfully[/green]")
    sys.exit(0)
