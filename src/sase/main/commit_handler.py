"""Command handlers for commit, restore, and revert operations."""

import argparse
import sys
from typing import NoReturn

from sase.workflows.commit import CommitWorkflow
from rich.console import Console
from rich.markup import escape as _esc


def _resolve_env_bead_id() -> str | None:
    """Return the SASE_BEAD_ID value for new commit attempts, if set."""
    import os

    bead_id = os.environ.get("SASE_BEAD_ID", "").strip()
    return bead_id or None


def handle_commit_command(args: argparse.Namespace) -> NoReturn:
    """Handle the 'commit' command.

    Args:
        args: Parsed command-line arguments.
    """
    import os

    if args.resume:
        from sase.workflows.commit.workflow import EXIT_CODE_CONFLICT, RunResult

        result = CommitWorkflow.resume()
        if result == RunResult.OK:
            try:
                from sase.logs.run_log import log_event

                log_event(event="commit_resumed")
            except Exception:
                pass
            sys.exit(0)
        if result == RunResult.CONFLICT:
            sys.exit(EXIT_CODE_CONFLICT)
        sys.exit(int(result))

    # Resolve commit message from inline string or file. Message files are
    # deleted only after a successful workflow so failed attempts are retryable.
    message = ""
    message_file_path: str | None = None
    if args.message:
        message = args.message
    elif args.message_file:
        path = args.message_file
        if not os.path.isfile(path):
            print(f"Error: message file not found: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path) as f:
            message = f.read().rstrip()
        message_file_path = path

    from sase.workflows.commit.workflow import METHOD_ALIASES

    cli_method = args.method
    env_method = os.environ.get("SASE_COMMIT_METHOD", "")

    # Canonicalize both sources independently.
    if cli_method:
        cli_method = METHOD_ALIASES.get(cli_method, cli_method)
    if env_method:
        env_method = METHOD_ALIASES.get(env_method, env_method)

    # Detect conflicting CLI vs env methods.
    if (
        cli_method
        and env_method
        and cli_method != env_method
        and not os.environ.get("SASE_COMMIT_METHOD_ALLOW_OVERRIDE")
    ):
        print(
            f"Error: CLI commit method '{cli_method}' conflicts with "
            f"SASE_COMMIT_METHOD='{env_method}'. "
            "Set SASE_COMMIT_METHOD_ALLOW_OVERRIDE=1 to force the ChangeSpecI method.",
            file=sys.stderr,
        )
        sys.exit(1)

    method = cli_method or env_method or "create_commit"

    payload: dict[str, object] = {
        "message": message,
        "files": args.files or [],
    }
    if args.name:
        payload["name"] = args.name
    if bead_id := _resolve_env_bead_id():
        payload["bead_id"] = bead_id
    if args.bug_id:
        payload["bug_id"] = str(args.bug_id)
    if args.checkout_target != "HEAD~1":
        payload["checkout_target"] = args.checkout_target
    if args.parent:
        payload["parent"] = args.parent
    from sase.workflows.commit.workflow import EXIT_CODE_CONFLICT, RunResult

    workflow = CommitWorkflow(payload=payload, method=method)
    result = workflow.run()
    if result == RunResult.OK:
        if message_file_path:
            try:
                os.remove(message_file_path)
            except OSError:
                pass
        try:
            from sase.logs.run_log import log_event

            log_event(event="commit_created", method=method)
        except Exception:
            pass
        sys.exit(0)
    if message_file_path:
        print(
            "Commit message preserved at "
            f"{message_file_path} — re-run with the same -M flag after fixing.",
            file=sys.stderr,
        )
    if result == RunResult.CONFLICT:
        try:
            from sase.logs.run_log import log_event

            log_event(event="commit_conflict", method=method)
        except Exception:
            pass
        sys.exit(EXIT_CODE_CONFLICT)
    sys.exit(int(result))


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
            from sase.project_display_names import humanize_cl_name

            for cs in reverted:
                console.print(f"  {humanize_cl_name(cs.name)}")
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
