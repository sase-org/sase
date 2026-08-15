"""Argument parser definition for the ``sase proc`` CLI command."""

from __future__ import annotations

import argparse

# Mirrors ``ACTIVE_PROC_STATUSES | TERMINAL_PROC_STATUSES`` in ``sase.procs``,
# spelled out here so building the parser never imports the proc store.
PROC_STATUS_CHOICES = ("pending", "running", "settling", "success", "error", "killed")
# Mirrors ``PROC_KINDS`` in ``sase.procs`` without importing the proc store
# while the top-level parser is being built.
PROC_KIND_CHOICES = ("command", "tui", "detached")


def register_proc_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register durable proc inspection and launch commands."""

    proc_parser = subparsers.add_parser(
        "proc",
        aliases=["task"],
        help="List, inspect, run, and kill durable procs",
        description=(
            "Inspect and run SASE procs. Procs are durable: they "
            "survive TUI restarts and are readable from any surface. Command "
            "and TUI procs may belong to a session; detached procs are global "
            "and belong to none. Running `sase proc` defaults to "
            "`sase proc list`. `sase task` remains accepted as a legacy alias."
        ),
    )
    proc_sub = proc_parser.add_subparsers(
        dest="proc_subcommand",
        help="Proc subcommands",
    )

    kill_parser = proc_sub.add_parser(
        "kill",
        help="Kill one running proc",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Kill one proc by id or unique id prefix (at least three "
            "characters). A proc that is already finished is reported as an "
            "unchanged no-op."
        ),
        epilog=("examples:\n  sase proc kill k7m2\n  sase proc kill k7m2 --json"),
    )
    kill_parser.add_argument(
        "proc_id",
        metavar="ID",
        help="Proc id or unique id prefix",
    )
    kill_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON result",
    )

    list_parser = proc_sub.add_parser(
        "list",
        help="List procs (rich table by default, JSON with -j)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List durable procs, newest first. By default this "
            "shows procs for the current session — the ACE session of this "
            "process, else the newest live one — plus procs that belong to no "
            "session; pass --all to see every session's work. Procs whose "
            "supervisor died without reporting are reconciled to `error` "
            "before the list is rendered."
        ),
        epilog=(
            "examples:\n"
            "  sase proc list\n"
            "  sase proc list --running\n"
            "  sase proc list --all --limit 10\n"
            "  sase proc list --tag epic --json\n"
            "  sase proc list --detached\n"
            "  sase proc list --session latest --status error"
        ),
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include procs from every session (default: this session plus unattributed)",
    )
    list_parser.add_argument(
        "-d",
        "--detached",
        action="store_true",
        help="Only detached procs (shorthand for --kind detached)",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON envelope (stable schema)",
    )
    list_parser.add_argument(
        "-k",
        "--kind",
        action="append",
        choices=PROC_KIND_CHOICES,
        default=None,
        metavar="KIND",
        help=(
            "Only procs of this kind; repeat to add more "
            f"({', '.join(PROC_KIND_CHOICES)})"
        ),
    )
    list_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Show at most N procs (default: the configured procs.history_limit)",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        default=None,
        metavar="NAME",
        help="Only procs attributed to this project",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        default=None,
        metavar="TEXT",
        help="Case-insensitive substring filter over label, command, and Patch name",
    )
    list_parser.add_argument(
        "-r",
        "--running",
        action="store_true",
        help="Only procs that are pending, running, or settling",
    )
    list_parser.add_argument(
        "-s",
        "--session",
        default=None,
        metavar="REF",
        help="Only procs from this session (id, prefix, handle, current, latest, none)",
    )
    list_parser.add_argument(
        "-S",
        "--status",
        action="append",
        choices=PROC_STATUS_CHOICES,
        default=None,
        metavar="STATUS",
        help=(
            "Only procs with this status; repeat to add more "
            f"({', '.join(PROC_STATUS_CHOICES)})"
        ),
    )
    list_parser.add_argument(
        "-t",
        "--tag",
        default=None,
        metavar="TAG",
        help="Only procs carrying this tag",
    )

    run_parser = proc_sub.add_parser(
        "run",
        help="Run a command as a detached, durable proc",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Record a proc, start it under a detached supervisor, and return. "
            "The supervisor owns the command's process group and captures its "
            "combined output, so the proc survives this shell and any TUI. "
            "Everything after `--` is the command to run.\n\n"
            "Targeting a session is attribution, not delegation: the proc runs "
            "the same way regardless, but the chosen session's Procs tab shows "
            "it and counts it."
        ),
        epilog=(
            "examples:\n"
            "  sase proc run -- just check\n"
            "  sase proc run --detached -- ./overnight.sh\n"
            "  sase proc run --wait -- pytest -x\n"
            "  sase proc run --label 'Nightly docs' --tag docs -- just docs\n"
            "  sase proc run --session none --json -- ./slow_script.sh"
        ),
    )
    run_parser.add_argument(
        "-c",
        "--cwd",
        default=None,
        metavar="DIR",
        help="Working directory for the command (default: the current directory)",
    )
    run_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the created proc as a JSON envelope",
    )
    run_parser.add_argument(
        "-l",
        "--label",
        default=None,
        metavar="TEXT",
        help="Human-facing proc label (default: derived from the command)",
    )
    run_parser.add_argument(
        "-p",
        "--project",
        default=None,
        metavar="NAME",
        help="Project to attribute the proc to (default: inferred from the cwd)",
    )
    run_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print only the new proc id",
    )
    run_scope = run_parser.add_mutually_exclusive_group()
    run_scope.add_argument(
        "-d",
        "--detached",
        action="store_true",
        help="Make the proc global instead of attributing it to a session",
    )
    run_scope.add_argument(
        "-s",
        "--session",
        default=None,
        metavar="REF",
        help=(
            "Session to attribute the proc to (id, prefix, handle, current, "
            "latest, none; default: current, then latest, then none)"
        ),
    )
    run_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=None,
        metavar="TAG",
        help="Tag the proc; repeat to add more tags",
    )
    run_parser.add_argument(
        "-w",
        "--wait",
        action="store_true",
        help="Stream the proc's output and exit with its exit code",
    )
    # ``proc_command`` rather than ``command``: the top-level subparsers own
    # the ``command`` destination, and a positional would overwrite it.
    run_parser.add_argument(
        "proc_command",
        nargs=argparse.REMAINDER,
        metavar="-- COMMAND ...",
        help="Command to run, introduced by --",
    )

    show_parser = proc_sub.add_parser(
        "show",
        help="Show one proc and its captured output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Show one proc by id or unique id prefix (at least three "
            "characters), followed by the tail of its captured output. "
            "`--follow` streams new output until the proc finishes and returns "
            "immediately for a proc that already has; with `--format json` it "
            "waits and then emits the finished proc."
        ),
        epilog=(
            "examples:\n"
            "  sase proc show k7m2\n"
            "  sase proc show k7m2 --follow\n"
            "  sase proc show k7m2 --all-lines --output-only\n"
            "  sase proc show k7m2 --format json"
        ),
    )
    show_parser.add_argument(
        "proc_id",
        metavar="ID",
        help="Proc id or unique id prefix",
    )
    show_parser.add_argument(
        "-A",
        "--all-lines",
        action="store_true",
        help="Print the whole retained log instead of a tail",
    )
    show_parser.add_argument(
        "-f",
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format: 'markdown' (default) or 'json'",
    )
    show_parser.add_argument(
        "-F",
        "--follow",
        action="store_true",
        help="Stream new output until the proc reaches a terminal state",
    )
    show_parser.add_argument(
        "-l",
        "--log-lines",
        type=int,
        default=200,
        metavar="N",
        help="Log lines to show (default: 200)",
    )
    show_parser.add_argument(
        "-o",
        "--output-only",
        action="store_true",
        help="Print only the captured log, with no surrounding detail",
    )


TASK_KIND_CHOICES = PROC_KIND_CHOICES
TASK_STATUS_CHOICES = PROC_STATUS_CHOICES
register_task_parser = register_proc_parser  # legacy parser alias

__all__ = [
    "PROC_KIND_CHOICES",
    "PROC_STATUS_CHOICES",
    "TASK_KIND_CHOICES",
    "TASK_STATUS_CHOICES",
    "register_proc_parser",
    "register_task_parser",
]
