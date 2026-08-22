"""Argument parser definition for the ``sase monitor`` CLI command."""

from __future__ import annotations

import argparse

from sase.ops.cli import add_operation_io_flags

# Mirrors ``sase.monitor.models.MONITOR_STATES``, spelled out here so
# building the parser never imports the monitor engine package.
MONITOR_STATE_CHOICES = (
    "running",
    "completed",
    "failed",
    "timeout",
    "stopped",
    "lost",
)

# Mirrors ``sase.monitor.followup_prompt.NEXT_OUTPUT_CHOICES``, spelled out
# here for the same reason.
NEXT_OUTPUT_CHOICES = ("none", "tail", "file")


def register_monitor_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register long-running-command monitor family members."""

    monitor_parser = subparsers.add_parser(
        "monitor",
        help="Start, stop, list, and inspect monitored long-running commands",
        description=(
            "Hand a slow command off to a detached supervisor that runs as a "
            "real agent-family member, with streaming output, a timeout, and "
            "an optional follow-up agent. Running `sase monitor` defaults to "
            "`sase monitor list`."
        ),
    )
    monitor_sub = monitor_parser.add_subparsers(
        dest="monitor_subcommand",
        help="Monitor subcommands",
        metavar="{list,show,start,stop}",
    )

    list_parser = monitor_sub.add_parser(
        "list",
        help="List monitors (rich table by default, -j/--json for JSON)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List monitor family members, newest first. By default this "
            "shows only active (running) monitors; pass --all to include "
            "finished ones too. Note: here -a is --all; unlike `monitor "
            "start`, use -l/--agent to filter by agent."
        ),
        epilog=(
            "examples:\n"
            "  sase monitor list\n"
            "  sase monitor list --all --agent acme\n"
            "  sase monitor list --status failed --status timeout\n"
            "  sase monitor list --format markdown\n"
            "  sase monitor list --json"
        ),
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include finished monitors, not just running ones",
    )
    list_parser.add_argument(
        "-f",
        "--format",
        choices=("table", "markdown", "json"),
        default="table",
        help="Output format: 'table' (default), 'markdown', or 'json'",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON envelope (shorthand for --format json)",
    )
    list_parser.add_argument(
        "-l",
        "--agent",
        default=None,
        metavar="NAME",
        help="Only monitors belonging to this agent",
    )
    list_parser.add_argument(
        "--lane",
        dest="agent",
        default=None,
        metavar="NAME",
        help=argparse.SUPPRESS,
    )
    list_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Show at most N monitors",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        default=None,
        metavar="NAME",
        help="Only monitors from this project (default: every project)",
    )
    list_parser.add_argument(
        "-s",
        "--status",
        action="append",
        choices=MONITOR_STATE_CHOICES,
        default=None,
        metavar="STATE",
        help=(
            "Only monitors in this state; repeat to add more "
            f"({', '.join(MONITOR_STATE_CHOICES)})"
        ),
    )

    show_parser = monitor_sub.add_parser(
        "show",
        help="Show one monitor and its captured output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Show one monitor by id (or unique id prefix), member agent "
            "name, or owning agent name, followed by the tail of its "
            "captured output. `--follow` streams new output until the "
            "monitor reaches a terminal state, exactly like `sase proc "
            "show --follow`."
        ),
        epilog=(
            "examples:\n"
            "  sase monitor show a1b2c3\n"
            "  sase monitor show acme --follow\n"
            "  sase monitor show acme--mon --all-lines --output-only\n"
            "  sase monitor show a1b2c3 --format json"
        ),
    )
    show_parser.add_argument(
        "monitor_id",
        metavar="ID",
        help="Monitor id (or unique prefix), member agent name, or owning agent name",
    )
    show_parser.add_argument(
        "-A",
        "--all-lines",
        action="store_true",
        help="Print the whole retained output instead of a tail",
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
        help="Stream new output until the monitor reaches a terminal state",
    )
    show_parser.add_argument(
        "-l",
        "--log-lines",
        type=int,
        default=200,
        metavar="N",
        help="Output lines to show (default: 200)",
    )
    show_parser.add_argument(
        "-o",
        "--output-only",
        action="store_true",
        help="Print only the captured output, with no surrounding detail",
    )

    start_parser = monitor_sub.add_parser(
        "start",
        help="Start a command as a monitor family member",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Start a command under a detached supervisor and return. The "
            "supervisor owns the command's process group and streams its "
            "combined output, so the command outlives this process. When run "
            "inside an agent, this is the last output the agent produces "
            "before it is killed — the runner adopts the handoff and the "
            "monitor keeps running in the same agent and workspace."
        ),
        epilog=(
            "examples:\n"
            "  sase monitor start -s TESTING -S TESTED -- just check-full\n"
            "  sase monitor start -s TESTING -S TESTED -r 'verify the fix' "
            "-t 20m -- just check-full\n"
            "  sase monitor start -s DEPLOYING -S DEPLOYED -n 'confirm the "
            "deploy succeeded' -- ./deploy.sh\n"
            "  sase monitor start -s TESTING -S TESTED -n 'fix failures' "
            "-m '@small' -- just check-full\n"
            "  sase monitor start -s TESTING -S TESTED --json -- just "
            "check-full"
        ),
    )
    start_parser.add_argument(
        "-a",
        "--agent",
        default=None,
        metavar="NAME",
        help="Target agent (default: the calling agent). Note: unlike "
        "`monitor list`, here -a is --agent, not --all",
    )
    start_parser.add_argument(
        "--lane",
        dest="agent",
        default=None,
        metavar="NAME",
        help=argparse.SUPPRESS,
    )
    start_parser.add_argument(
        "-c",
        "--command",
        # Hidden compatibility alias for the command remainder. ``dest`` is
        # ``monitor_command`` so it cannot overwrite the root parser's
        # ``command`` routing field.
        dest="monitor_command",
        default=None,
        metavar="CMD",
        help=argparse.SUPPRESS,
    )
    start_parser.add_argument(
        "-C",
        "--cwd",
        default=None,
        metavar="DIR",
        help="Working directory (default: the agent's workspace, else $PWD)",
    )
    start_parser.add_argument(
        "-i",
        "--idle-timeout",
        default=None,
        metavar="DURATION",
        help=(
            "Optional no-output timeout; kills commands that stop producing "
            "bytes for this long, while quiet commands remain supported when omitted"
        ),
    )
    start_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the started monitor as a JSON envelope",
    )
    start_parser.add_argument(
        "-L",
        "--label",
        default=None,
        metavar="TEXT",
        help="Short row label (default: derived from the command)",
    )
    start_parser.add_argument(
        "-m",
        "--model",
        default=None,
        metavar="MODEL",
        help=(
            "Model or alias for the follow-up agent (opus, opus@high, sonnet, "
            "codex/gpt-5). Requires -n/--next. Default: inherit the starter's "
            "model"
        ),
    )
    start_parser.add_argument(
        "-n",
        "--next",
        default=None,
        metavar="TEXT",
        help="Next action for the follow-up agent; omit for no follow-up",
    )
    start_parser.add_argument(
        "--next-output",
        choices=NEXT_OUTPUT_CHOICES,
        default=None,
        help=(
            "How much retained output to hand the follow-up agent: 'tail' "
            "(default) embeds the last --tail-lines lines fenced as "
            "untrusted data, 'file' points at the on-disk log path instead, "
            "'none' gives only the outcome summary and a `sase monitor "
            "show --all-lines` pointer"
        ),
    )
    start_parser.add_argument(
        "-r",
        "--reason",
        default=None,
        metavar="TEXT",
        help="Why this command is being monitored (default: 'run command')",
    )
    start_parser.add_argument(
        "-s",
        "--start-status",
        default=None,
        metavar="TEXT",
        help=(
            "Required label shown while the command runs (present tense, "
            "e.g. TESTING). Pair with -S/--stop-status. Max 20 characters"
        ),
    )
    start_parser.add_argument(
        "-S",
        "--stop-status",
        default=None,
        metavar="TEXT",
        help=(
            "Required label shown when the command finishes (past tense, "
            "e.g. TESTED). Pair with -s/--start-status. Max 20 characters"
        ),
    )
    start_parser.add_argument(
        "-T",
        "--tail-lines",
        type=int,
        default=None,
        metavar="N",
        help="Output tail handed to the follow-up (default: 200)",
    )
    start_parser.add_argument(
        "-t",
        "--timeout",
        default=None,
        metavar="DURATION",
        help=("Timeout: bare seconds or a duration like 90s / 45m / 2h (default: 1h)"),
    )
    # ``monitor_command_words`` rather than ``command``: the top-level
    # subparsers own the ``command`` destination for command routing.
    start_parser.add_argument(
        "monitor_command_words",
        nargs=argparse.REMAINDER,
        metavar="-- COMMAND",
        help="The command to run and monitor, introduced by --",
    )

    stop_parser = monitor_sub.add_parser(
        "stop",
        help="Stop a running monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Stop a running monitor by id (or unique id prefix), member "
            "agent name, or owning agent name; omitted, targets the "
            "calling agent's active monitor. No follow-up agent is "
            "launched, even when a next action was recorded."
        ),
        epilog=(
            "examples:\n"
            "  sase monitor stop\n"
            "  sase monitor stop a1b2c3\n"
            "  sase monitor stop acme --json"
        ),
    )
    stop_parser.add_argument(
        "monitor_id",
        nargs="?",
        default=None,
        metavar="ID",
        help="Monitor id (or unique prefix), member agent name, or owning agent name",
    )
    stop_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON result",
    )
    add_operation_io_flags(stop_parser)

    supervise_parser = monitor_sub.add_parser(
        "_supervise",
        help=argparse.SUPPRESS,
    )
    supervise_parser.add_argument("--artifacts-dir", required=True)


__all__ = ["MONITOR_STATE_CHOICES", "NEXT_OUTPUT_CHOICES", "register_monitor_parser"]
