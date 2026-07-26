"""Argument parser definition for the ``sase task`` CLI command."""

from __future__ import annotations

import argparse

# Mirrors ``ACTIVE_TASK_STATUSES | TERMINAL_TASK_STATUSES`` in ``sase.tasks``,
# spelled out here so building the parser never imports the task store.
TASK_STATUS_CHOICES = ("pending", "running", "success", "error", "killed")
# Mirrors ``TASK_KINDS`` in ``sase.tasks`` without importing the task store
# while the top-level parser is being built.
TASK_KIND_CHOICES = ("command", "tui", "detached")


def register_task_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register durable background-task inspection and launch commands."""

    task_parser = subparsers.add_parser(
        "task",
        help="List, inspect, run, and kill durable background tasks",
        description=(
            "Inspect and run SASE background tasks. Tasks are durable: they "
            "survive TUI restarts and are readable from any surface. Command "
            "and TUI tasks may belong to a session; detached tasks are global "
            "and belong to none. Running `sase task` defaults to "
            "`sase task list`."
        ),
    )
    task_sub = task_parser.add_subparsers(
        dest="task_subcommand",
        help="Background-task subcommands",
    )

    kill_parser = task_sub.add_parser(
        "kill",
        help="Kill one running background task",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Kill one task by id or unique id prefix (at least three "
            "characters). A task that is already finished is reported as an "
            "unchanged no-op."
        ),
        epilog=("examples:\n  sase task kill k7m2\n  sase task kill k7m2 --json"),
    )
    kill_parser.add_argument(
        "task_id",
        metavar="ID",
        help="Task id or unique id prefix",
    )
    kill_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON result",
    )

    list_parser = task_sub.add_parser(
        "list",
        help="List background tasks (rich table by default, JSON with -j)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List durable background tasks, newest first. By default this "
            "shows tasks for the current session — the ACE session of this "
            "process, else the newest live one — plus tasks that belong to no "
            "session; pass --all to see every session's work. Tasks whose "
            "supervisor died without reporting are reconciled to `error` "
            "before the list is rendered."
        ),
        epilog=(
            "examples:\n"
            "  sase task list\n"
            "  sase task list --running\n"
            "  sase task list --all --limit 10\n"
            "  sase task list --tag epic --json\n"
            "  sase task list --detached\n"
            "  sase task list --session latest --status error"
        ),
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include tasks from every session (default: this session plus unattributed)",
    )
    list_parser.add_argument(
        "-d",
        "--detached",
        action="store_true",
        help="Only detached tasks (shorthand for --kind detached)",
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
        choices=TASK_KIND_CHOICES,
        default=None,
        metavar="KIND",
        help=(
            "Only tasks of this kind; repeat to add more "
            f"({', '.join(TASK_KIND_CHOICES)})"
        ),
    )
    list_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Show at most N tasks (default: the configured tasks.history_limit)",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        default=None,
        metavar="NAME",
        help="Only tasks attributed to this project",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        default=None,
        metavar="TEXT",
        help="Case-insensitive substring filter over label, command, and ChangeSpec name",
    )
    list_parser.add_argument(
        "-r",
        "--running",
        action="store_true",
        help="Only tasks that are pending or running",
    )
    list_parser.add_argument(
        "-s",
        "--session",
        default=None,
        metavar="REF",
        help="Only tasks from this session (id, prefix, handle, current, latest, none)",
    )
    list_parser.add_argument(
        "-S",
        "--status",
        action="append",
        choices=TASK_STATUS_CHOICES,
        default=None,
        metavar="STATUS",
        help=(
            "Only tasks with this status; repeat to add more "
            f"({', '.join(TASK_STATUS_CHOICES)})"
        ),
    )
    list_parser.add_argument(
        "-t",
        "--tag",
        default=None,
        metavar="TAG",
        help="Only tasks carrying this tag",
    )

    run_parser = task_sub.add_parser(
        "run",
        help="Run a command as a detached, durable background task",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Record a task, start it under a detached supervisor, and return. "
            "The supervisor owns the command's process group and captures its "
            "combined output, so the task survives this shell and any TUI. "
            "Everything after `--` is the command to run.\n\n"
            "Targeting a session is attribution, not delegation: the task runs "
            "the same way regardless, but the chosen session's Tasks tab shows "
            "it and counts it."
        ),
        epilog=(
            "examples:\n"
            "  sase task run -- just check\n"
            "  sase task run --detached -- ./overnight.sh\n"
            "  sase task run --wait -- pytest -x\n"
            "  sase task run --label 'Nightly docs' --tag docs -- just docs\n"
            "  sase task run --session none --json -- ./slow_script.sh"
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
        help="Emit the created task as a JSON envelope",
    )
    run_parser.add_argument(
        "-l",
        "--label",
        default=None,
        metavar="TEXT",
        help="Human-facing task label (default: derived from the command)",
    )
    run_parser.add_argument(
        "-p",
        "--project",
        default=None,
        metavar="NAME",
        help="Project to attribute the task to (default: inferred from the cwd)",
    )
    run_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print only the new task id",
    )
    run_scope = run_parser.add_mutually_exclusive_group()
    run_scope.add_argument(
        "-d",
        "--detached",
        action="store_true",
        help="Make the task global instead of attributing it to a session",
    )
    run_scope.add_argument(
        "-s",
        "--session",
        default=None,
        metavar="REF",
        help=(
            "Session to attribute the task to (id, prefix, handle, current, "
            "latest, none; default: current, then latest, then none)"
        ),
    )
    run_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        default=None,
        metavar="TAG",
        help="Tag the task; repeat to add more tags",
    )
    run_parser.add_argument(
        "-w",
        "--wait",
        action="store_true",
        help="Stream the task's output and exit with its exit code",
    )
    # ``task_command`` rather than ``command``: the top-level subparsers own
    # the ``command`` destination, and a positional would overwrite it.
    run_parser.add_argument(
        "task_command",
        nargs=argparse.REMAINDER,
        metavar="-- COMMAND ...",
        help="Command to run, introduced by --",
    )

    show_parser = task_sub.add_parser(
        "show",
        help="Show one background task and its captured output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Show one task by id or unique id prefix (at least three "
            "characters), followed by the tail of its captured output. "
            "`--follow` streams new output until the task finishes and returns "
            "immediately for a task that already has; with `--format json` it "
            "waits and then emits the finished task."
        ),
        epilog=(
            "examples:\n"
            "  sase task show k7m2\n"
            "  sase task show k7m2 --follow\n"
            "  sase task show k7m2 --all-lines --output-only\n"
            "  sase task show k7m2 --format json"
        ),
    )
    show_parser.add_argument(
        "task_id",
        metavar="ID",
        help="Task id or unique id prefix",
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
        help="Stream new output until the task reaches a terminal state",
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


__all__ = ["TASK_KIND_CHOICES", "TASK_STATUS_CHOICES", "register_task_parser"]
