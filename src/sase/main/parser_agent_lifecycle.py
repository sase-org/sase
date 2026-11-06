"""Argument parser definitions for basic agent lifecycle subcommands."""

from __future__ import annotations

import argparse


def register_agent_drain_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent drain' subcommand."""
    from sase.ops.cli import add_operation_io_flags

    drain_parser = agents_sub.add_parser(
        "drain",
        help="Relaunch agents stranded by one hard-disabled provider",
        description=(
            "Plan and apply a provider drain. The provider must have an active "
            "hard disable; enabled and soft-disabled providers are refused so "
            "agents cannot relaunch straight back onto them. Planning finishes "
            "before anything is killed. Draining live agents discards their "
            "in-flight work; chat transcripts are kept. Exit 0 means drained "
            "or previewed, 2 means refused with nothing changed, and 1 means "
            "at least one move failed after execution started."
        ),
        epilog=(
            "examples:\n"
            "  sase agent drain claude --dry-run\n"
            "  sase agent drain claude --yes\n"
            "  sase agent drain claude -m codex/gpt-5\n"
            "  sase agent drain claude -j"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    drain_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one stable JSON envelope on stdout and nothing else",
    )
    drain_parser.add_argument(
        "-l",
        "--limit",
        default=20,
        metavar="N",
        type=int,
        help="Most agents to move (default: 20)",
    )
    drain_parser.add_argument(
        "-m",
        "--model",
        metavar="MODEL",
        help=(
            "Relaunch every moved agent on this model. Accepts "
            "[provider/]model[@effort], the same spelling `sase agent "
            "restart -m` accepts."
        ),
    )
    drain_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Print the preview and exit 0 without killing or launching",
    )
    drain_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation before discarding live work",
    )
    add_operation_io_flags(drain_parser)
    drain_parser.add_argument(
        "provider",
        metavar="PROVIDER",
        help="Hard-disabled provider to drain",
    )


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


def register_agent_load_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent load' subcommand."""
    load_parser = agents_sub.add_parser(
        "load",
        help="Show this machine's runner capacity from the authoritative report",
        description=(
            "Show this machine's runner capacity the way admission sees it: a "
            "verdict and gauge, who is using capacity, who is queued and why, "
            "live agents holding nothing, and inactive records counted rather "
            "than listed. Reads the same scan cache and Rust snapshot "
            "admission uses; display reads never take the admission lock. "
            "Exit 0 always: an invalid snapshot reads as blocked, never as "
            "free capacity."
        ),
        epilog=(
            "examples:\n  sase agent load\n  sase agent load -j\n  sase agent load -r"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    load_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the exact capacity report as JSON (stable schema)",
    )
    load_parser.add_argument(
        "-r",
        "--rescan",
        action="store_true",
        help="Force a fresh capacity scan instead of reusing the scan cache",
    )


def register_agent_hijack_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent hijack' subcommand."""
    hijack_parser = agents_sub.add_parser(
        "hijack",
        help="Stop a stalled agent but keep its workspace",
        description=(
            "Stop the named agent without releasing its workspace claim. "
            "The agent's process tree is verified dead, its workspace stays "
            "held, and its evidence is snapshotted, so it can be recovered "
            "with `sase agent recover NAME`. What is kept: the workspace, "
            "the Agents-tab node, and the evidence. What is stopped: the "
            "process tree. Exit 0 means HIJACKED, 2 means refused with "
            "nothing changed, and 1 means the stop failed or an error "
            "occurred."
        ),
        epilog=(
            "examples:\n"
            "  sase agent hijack sase-7f.2\n"
            '  sase agent hijack sase-7f.2 -r "stalled on lint"\n'
            "  sase agent hijack sase-7f.2 -j"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    hijack_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one stable JSON envelope on stdout and nothing else",
    )
    hijack_parser.add_argument(
        "-r",
        "--reason",
        default=None,
        metavar="REASON",
        help="Record why the agent was hijacked",
    )
    hijack_parser.add_argument(
        "name",
        metavar="NAME",
        help="Name of the agent to hijack",
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


def register_agent_recover_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent recover' subcommand."""
    recover_parser = agents_sub.add_parser(
        "recover",
        help="Recover a hijacked agent: keep, restart, or dismiss its work",
        description=(
            "Preview or resolve a held hijack. Without --action, print the shared "
            "recovery menu. Keep-the-work actions (continue, escalate) relaunch in "
            "the held workspace; --prompt-file with continue supplies the full "
            "edited continuation prompt (Instruct). Release actions verify the "
            "recovery snapshot first: restart relaunches the same prompt under "
            "the same name in a fresh workspace (--prompt-file relaunches an "
            "edited prompt instead, the Edit backend), and dismiss retires the "
            "row and releases the workspace. Recovery remains available when "
            "the hijack ingress flag is off. Exit 0 means menu, queued, or "
            "launched; 2 means refused with no new recovery; 1 means an "
            "operation error."
        ),
        epilog=(
            "examples:\n"
            "  sase agent recover sase-7f.2\n"
            "  sase agent recover -a escalate sase-7f.2\n"
            "  sase agent recover -a continue -n sase-7f.2\n"
            "  sase agent recover -a continue -p /tmp/continue.md -m opus@high "
            "sase-7f.2\n"
            "  sase agent recover -a escalate -j sase-7f.2\n"
            "  sase agent recover -a restart sase-7f.2\n"
            "  sase agent recover -a restart -p /tmp/edited.md sase-7f.2\n"
            "  sase agent recover -a dismiss sase-7f.2"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    recover_parser.add_argument(
        "-a",
        "--action",
        choices=("continue", "dismiss", "escalate", "restart"),
        metavar="ACTION",
        help="Resolve the hijack (without this, print the menu)",
    )
    recover_parser.add_argument(
        "-D",
        "--discard-without-snapshot",
        action="store_true",
        help=(
            "DANGEROUS: release a hijacked workspace with restart or dismiss "
            "even when the recovery snapshot fails; uncommitted work may be lost"
        ),
    )
    recover_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Preview one keep-work action without changing the ledger",
    )
    recover_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one stable JSON envelope on stdout and nothing else",
    )
    recover_parser.add_argument(
        "-m",
        "--model",
        metavar="MODEL",
        help=(
            "Pin a concrete target for continue or escalate; a continue prompt's "
            "%%model: is overridden by this value"
        ),
    )
    recover_parser.add_argument(
        "-p",
        "--prompt-file",
        metavar="PATH",
        help=(
            "Use this full edited prompt: the continuation prompt with continue "
            "(Instruct), or the relaunched prompt with restart (Edit); read and "
            "validate it before claiming recovery"
        ),
    )
    recover_parser.add_argument(
        "name",
        metavar="NAME",
        help="Name of the hijacked agent to recover",
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
            "it: clan, then agent session, then workflow, then exact agent name. "
            "-T/--target session (the default) waits for that whole session; "
            "turn pins each NAME's current turn at invocation and waits on that "
            "member (clans and workflows refuse turn). Exit codes: 0 every "
            "target succeeded, 1 at least one failed, 2 a usage error, 3 at "
            "least one target is blocked on a human (without -w), 4 the timeout "
            "expired, 130/143 interrupted by SIGINT/SIGTERM. Precedence when "
            "more than one applies: 1 > 3 > 4. Progress goes to stderr; the "
            "settle summary and the -j envelope go to stdout."
        ),
        epilog=(
            "examples:\n"
            "  sase agent wait sase-s7.2 && just check-full\n"
            "  sase agent wait -T turn 16h\n"
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
        "-T",
        "--target",
        choices=("session", "turn"),
        default="session",
        metavar="{session,turn}",
        help=(
            "Wait scope for each NAME: session waits for the whole agent "
            "session (the default); turn pins the session's current turn when "
            "the command starts and waits on that member. Clans and workflows "
            "reject turn. -a/--all keeps session scope only"
        ),
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
        help="Agent, agent session, clan, or workflow name to wait for (repeatable)",
    )
