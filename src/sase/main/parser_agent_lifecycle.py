"""Argument parser definitions for basic agent lifecycle subcommands."""

from __future__ import annotations

import argparse


def register_agent_list_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent list' subcommand."""
    list_parser = agents_sub.add_parser(
        "list",
        help="List running agents (pretty table by default, JSON with -j)",
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help=(
            "Include recently-completed DONE/FAILED agents"
            " (capped at 50 most-recent per project)"
        ),
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        help="Only show agents for the given project name",
    )


def register_agent_kill_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent kill' subcommand."""
    kill_parser = agents_sub.add_parser(
        "kill",
        help="SIGTERM a running agent by name",
    )
    kill_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to kill",
    )


def register_agent_show_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent show' subcommand."""
    show_parser = agents_sub.add_parser(
        "show",
        help="Render a full detail panel for one agent",
    )
    show_parser.add_argument(
        "name",
        metavar="NAME",
        help="Name of the agent to show",
    )


def register_agent_restart_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent restart' subcommand."""
    restart_parser = agents_sub.add_parser(
        "restart",
        help="Stop a named agent and immediately relaunch its stored prompt",
        description=(
            "Stop the named agent and immediately relaunch its stored prompt "
            "under the same name. Planning finishes before anything is killed. "
            "Restart deletes the previous run's artifacts; the chat transcript "
            "is kept. A live agent or a wipe that reaches related agents asks "
            "for confirmation unless -y is given; --dry-run prints the preview "
            "and exits 0. Exit 0 means restarted or previewed, 2 means refused "
            "with nothing changed, and 1 means the old run was stopped but the "
            "name wipe or relaunch failed."
        ),
        epilog=(
            "Restart deletes the previous run's artifacts (the chat transcript "
            "under ~/.sase/chats is kept). A failed relaunch writes a recovery "
            "directory under ~/.sase/restarts/. -j/--json skips confirmation.\n"
            "\n"
            "examples:\n"
            "  sase agent restart 02p\n"
            "  sase agent restart 02p --dry-run\n"
            "  sase agent restart sase-mf.1 -m opus@high\n"
            "  sase agent restart 02p -j"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    restart_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one stable JSON envelope on stdout and nothing else",
    )
    restart_parser.add_argument(
        "-m",
        "--model",
        metavar="MODEL",
        help=(
            "Relaunch under a different model. Accepts [provider/]model[@effort], "
            "the same spelling %%model: accepts. -m opus replaces the model only "
            "and leaves a standalone %%effort: in place. -m opus@high replaces "
            "the model and removes %%effort: so the combined directive is the "
            "only source of truth."
        ),
    )
    restart_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print the preview and exit 0 without killing or launching",
    )
    restart_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=(
            "Skip the interactive confirmation for a live agent or a wipe "
            "that deletes related agents' artifacts"
        ),
    )
    restart_parser.add_argument(
        "name",
        metavar="NAME",
        help="Name of the agent to restart",
    )


def register_agent_wait_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent wait' subcommand."""
    wait_parser = agents_sub.add_parser(
        "wait",
        help="Block until named agents (or every running agent) reach a terminal state",
        description=(
            "Block until the agents you name (or every agent running right now, "
            "with -a) reach a terminal state, then exit with a status code that "
            "says what happened. NAME is resolved the same way %wait resolves "
            "it: clan, then agent family, then workflow, then exact agent name. "
            "Exit codes: 0 every target succeeded, 1 at least one failed, 2 a "
            "usage error, 3 at least one target is blocked on a human (without "
            "-w), 4 the timeout expired, 130/143 interrupted by SIGINT/SIGTERM. "
            "Precedence when more than one applies: 1 > 3 > 4. Progress goes to "
            "stderr; the settle summary and the -j envelope go to stdout."
        ),
        epilog=(
            "examples:\n"
            "  sase agent wait sase-s7.2 && just check-full\n"
            "  sase agent wait -a -t 2h\n"
            "  sase monitor start -s WAITING -S WAITED -n 'agents finished; land "
            "the epic' -- sase agent wait -a"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    wait_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Wait for every agent running when the command starts (rejects NAME)",
    )
    wait_parser.add_argument(
        "-i",
        "--interval",
        metavar="DURATION",
        help="Fixed poll interval, e.g. 90, 90s, 45m, 2h (default: adaptive)",
    )
    wait_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one JSON envelope on settle; suppresses progress output",
    )
    wait_parser.add_argument(
        "-p",
        "--project",
        metavar="NAME",
        help="Limit --all targets, and scope name resolution, to one project",
    )
    wait_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress; print only the final summary line",
    )
    wait_parser.add_argument(
        "-t",
        "--timeout",
        metavar="DURATION",
        help="Give up after DURATION, e.g. 90, 90s, 45m, 2h (default: no timeout)",
    )
    wait_parser.add_argument(
        "-w",
        "--wait-blocked",
        action="store_true",
        help="Keep waiting through pauses that need a human instead of exiting 3",
    )
    wait_parser.add_argument(
        "names",
        metavar="NAME",
        nargs="*",
        help="Agent, family, clan, or workflow name to wait for (repeatable)",
    )
