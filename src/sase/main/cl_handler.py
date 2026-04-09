"""Command handlers for CL-related operations."""

import argparse
import sys
from typing import NoReturn

from sase.workflows.commit import CommitWorkflow
from rich.console import Console
from rich.markup import escape as _esc


def handle_commit_command(args: argparse.Namespace) -> NoReturn:
    """Handle the 'commit' command.

    Args:
        args: Parsed command-line arguments.
    """
    import os

    # Resolve commit message from inline string or file
    message = ""
    if args.message:
        message = args.message
    elif args.message_file:
        path = args.message_file
        if not os.path.isfile(path):
            print(f"Error: message file not found: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path) as f:
            message = f.read().rstrip()
        try:
            os.remove(path)
        except OSError:
            pass

    from sase.workflows.commit.workflow import METHOD_ALIASES

    method = args.method or os.environ.get("SASE_COMMIT_METHOD", "create_commit")
    method = METHOD_ALIASES.get(method, method)

    payload: dict[str, object] = {
        "message": message,
        "files": args.files or [],
    }
    if args.name:
        payload["name"] = args.name
    if args.bead_id:
        payload["bead_id"] = args.bead_id
    if args.bug_id:
        payload["bug_id"] = str(args.bug_id)
    if args.checkout_target != "HEAD~1":
        payload["checkout_target"] = args.checkout_target
    workflow = CommitWorkflow(payload=payload, method=method)
    success = workflow.run()
    if success:
        try:
            from sase.logs.run_log import log_event

            log_event(event="commit_created", method=method)
        except Exception:
            pass
    sys.exit(0 if success else 1)


def handle_restore_command(args: argparse.Namespace) -> NoReturn:
    """Handle the 'restore' command.

    Args:
        args: Parsed command-line arguments.
    """
    from sase.ace.changespec import find_all_changespecs
    from sase.ace.restore import list_reverted_changespecs, restore_changespec

    console = Console()

    # Handle --list flag
    if args.list:
        reverted = list_reverted_changespecs()
        if not reverted:
            console.print("[yellow]No reverted ChangeSpecs found.[/yellow]")
        else:
            console.print("[bold]Reverted ChangeSpecs:[/bold]")
            for cs in reverted:
                console.print(f"  {cs.name}")
        sys.exit(0)

    # Validate required argument when not using --list
    if not args.name:
        console.print("[red]Error: name is required (unless using --list)[/red]")
        sys.exit(1)

    # Find the ChangeSpec by name
    all_changespecs = find_all_changespecs()
    target_changespec = None
    for cs in all_changespecs:
        if cs.name == args.name:
            target_changespec = cs
            break

    if target_changespec is None:
        console.print(f"[red]Error: ChangeSpec '{_esc(args.name)}' not found[/red]")
        sys.exit(1)

    success, error = restore_changespec(target_changespec, console)
    if not success:
        console.print(f"[red]Error: {_esc(str(error))}[/red]")
        sys.exit(1)

    try:
        from sase.logs.run_log import log_event

        log_event(event="changespec_restored", cl_name=args.name)
    except Exception:
        pass
    console.print("[green]ChangeSpec restored successfully[/green]")
    sys.exit(0)


def handle_revert_command(args: argparse.Namespace) -> NoReturn:
    """Handle the 'revert' command.

    Args:
        args: Parsed command-line arguments.
    """
    from sase.ace.changespec import find_all_changespecs
    from sase.ace.revert import revert_changespec

    console = Console()

    # Find the ChangeSpec by name
    all_changespecs = find_all_changespecs()
    target_changespec = None
    for cs in all_changespecs:
        if cs.name == args.name:
            target_changespec = cs
            break

    if target_changespec is None:
        console.print(f"[red]Error: ChangeSpec '{_esc(args.name)}' not found[/red]")
        sys.exit(1)

    success, error = revert_changespec(target_changespec, console)
    if not success:
        console.print(f"[red]Error: {_esc(str(error))}[/red]")
        sys.exit(1)

    try:
        from sase.logs.run_log import log_event

        log_event(event="changespec_reverted", cl_name=args.name)
    except Exception:
        pass
    console.print("[green]ChangeSpec reverted successfully[/green]")
    sys.exit(0)
