"""Argument parser definitions for the TUI and axe subcommands."""

import argparse

from sase.ace.saved_queries import load_first_saved_query, load_last_query
from sase.ace.tui.actions.event_refresh._constants import FULL_SANITY_REFRESH_SECONDS
from sase.completion.compat import set_completion_compat_choices
from sase.completion.shorten import set_completion_summary


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc
    if not parsed > 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def register_ace_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'tui' subcommand parser."""
    ace_parser = subparsers.add_parser(
        "tui",
        help=(
            "Open sase's TUI for agents, Patches, artifacts, notifications, "
            "and Services"
        ),
    )
    # Optional positional argument with default
    ace_parser.add_argument(
        "query",
        nargs="?",
        default=load_last_query() or load_first_saved_query("patches") or "!!!",
        help="Query string for filtering Patches (default: last used Patches query, "
        "first saved Patches query, or '!!!' for error suffixes). "
        'Examples: \'"feature" AND "Ready"\', \'"myproject" OR "bugfix"\', '
        "'!!! AND @myproject'",
    )
    # Options for 'tui' (keep sorted alphabetically by long option name)
    ace_parser.add_argument(
        "-m",
        "--model-tier",
        choices=["large", "small"],
        default=None,
        help="Override model tier for ALL LLM provider instances (large or small)",
    )
    ace_parser.add_argument(
        "-M",
        "--model-size",
        choices=["big", "little"],
        default=None,
        help="Deprecated: use --model-tier instead",
    )
    ace_parser.add_argument(
        "-p",
        "--profile",
        nargs="?",
        const="",
        default=None,
        help="Profile the TUI session with pyinstrument. Optionally provide a file path "
        "for the output (default: $SASE_TMPDIR/ace_profile_<timestamp>.txt)",
    )
    ace_parser.add_argument(
        "-r",
        "--refresh-interval",
        type=int,
        default=10,
        help="Auto-refresh interval in seconds (default: 10, 0 to disable)",
    )
    ace_parser.add_argument(
        "-R",
        "--restart-service",
        "--restart-axe",
        dest="restart_axe",
        action="store_true",
        help="Restart the service host on startup (no-op if it is not running)",
    )
    ace_parser.add_argument(
        "-s",
        "--sanity-refresh-interval",
        type=_positive_int,
        default=int(FULL_SANITY_REFRESH_SECONDS),
        help="Full sanity-refresh interval in seconds (default: "
        f"{int(FULL_SANITY_REFRESH_SECONDS)}). Missed watcher or token "
        "changes are still reconciled at least this often.",
    )
    tab = ace_parser.add_argument(
        "-t",
        "--tab",
        choices=[
            "artifacts",
            "changespecs",  # legacy tab id
            "patches",
            "agents",
            "services",
            "axe",
        ],
        default="agents",
        help="Tab to focus on startup; 'services' is the Services tab, and "
        "'changespecs'/'patches' remain legacy aliases for 'artifacts' "
        "(default: agents)",
    )
    set_completion_compat_choices(tab, "changespecs", "patches", "axe")
    set_completion_summary(tab, "Tab to focus on startup (default: agents)")
    ace_parser.add_argument(
        "-T",
        "--tmux",
        action="store_true",
        help="Launch the TUI in a new tmux window named 'sase_tmux_<N>' and "
        "print its session/window target on stdout. Useful for agents that "
        "need to drive the TUI via 'tmux send-keys' and observe it via "
        "'tmux capture-pane'.",
    )
    ace_parser.add_argument(
        "-x",
        "--no-service",
        "--no-axe",
        dest="no_axe",
        action="store_true",
        help="Disable auto-starting the service host on startup",
    )
    ace_parser.add_argument(
        "-v",
        "--vcs-provider",
        choices=["git", "hg", "auto"],
        default=None,
        help="Override VCS provider ('git', 'hg', or 'auto' for auto-detection)",
    )


def register_axe_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'axe' subcommand parser."""
    from sase.ops.cli import add_operation_io_flags

    axe_parser = subparsers.add_parser(
        "axe",
        help="Schedule-based daemon for continuous Patch status updates",
    )
    # Only --vcs-provider lives on the root axe parser (applies globally)
    axe_parser.add_argument(
        "-v",
        "--vcs-provider",
        choices=["git", "hg", "auto"],
        default=None,
        help="Override VCS provider ('git', 'hg', or 'auto' for auto-detection)",
    )

    # Nested subparsers for axe
    axe_subparsers = axe_parser.add_subparsers(
        dest="axe_subcommand",
        help="Axe subcommands",
        metavar="{ensure,job,maintenance,restart,routine,start,status,stop}",
    )

    axe_bgcmd_parser = axe_subparsers.add_parser(
        "bgcmd-launch",
        help=argparse.SUPPRESS,
    )
    axe_bgcmd_parser.add_argument("slot", type=int)
    axe_bgcmd_parser.add_argument("project")
    axe_bgcmd_parser.add_argument("workspace_num", type=int)
    axe_bgcmd_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    add_operation_io_flags(axe_bgcmd_parser)

    _add_axe_job_group(axe_subparsers, name="job", hidden=False)
    _add_axe_job_group(axe_subparsers, name="chop", hidden=True)

    # --- axe ensure ---
    axe_ensure_parser = axe_subparsers.add_parser(
        "ensure",
        help="Heal a downed axe or manage its optional watchdog timer",
        description=(
            "Ensure axe matches its persistent desired state. Bare `sase axe ensure` "
            "starts a missing orchestrator unless axe was explicitly stopped. The "
            "optional user systemd timer provides the same check on idle hosts."
        ),
        epilog=(
            "Examples:\n"
            "  sase axe ensure\n"
            "  sase axe ensure install\n"
            "  sase axe ensure uninstall"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    axe_ensure_subparsers = axe_ensure_parser.add_subparsers(
        dest="axe_ensure_subcommand",
        help="Ensure watchdog commands (omit one to heal now)",
    )
    axe_ensure_subparsers.add_parser(
        "install",
        help="Install and start the user systemd watchdog timer",
    )
    axe_ensure_subparsers.add_parser(
        "uninstall",
        help="Stop and remove the user systemd watchdog timer",
    )

    _add_axe_routine_group(axe_subparsers, name="routine", hidden=False)
    _add_axe_routine_group(axe_subparsers, name="lumberjack", hidden=True)

    # --- axe maintenance ---
    axe_maintenance_parser = axe_subparsers.add_parser(
        "maintenance", help="Manage axe maintenance mode"
    )
    axe_maintenance_subparsers = axe_maintenance_parser.add_subparsers(
        dest="axe_maintenance_subcommand", help="Maintenance subcommands"
    )

    axe_maintenance_enter_parser = axe_maintenance_subparsers.add_parser(
        "enter", help="Enter maintenance mode"
    )
    axe_maintenance_enter_parser.add_argument(
        "-r",
        "--reason",
        required=True,
        help="Reason for entering maintenance mode",
    )
    axe_maintenance_subparsers.add_parser("exit", help="Exit maintenance mode")
    axe_maintenance_subparsers.add_parser("status", help="Show maintenance status")

    # --- axe restart ---
    axe_restart_parser = axe_subparsers.add_parser(
        "restart",
        help="Restart the axe orchestrator and verify fresh worker heartbeats "
        "(works even when axe is not running)",
    )
    axe_restart_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Suppress progress output and emit one deterministic JSON result object",
    )
    axe_restart_parser.add_argument(
        "-A",
        "--max-agent-runners",
        type=int,
        default=None,
        help="Maximum concurrent agent runners (default: config value)",
    )
    axe_restart_parser.add_argument(
        "-H",
        "--max-hook-runners",
        type=int,
        default=None,
        help="Maximum concurrent hook runners (default: config value)",
    )
    axe_restart_parser.add_argument(
        "-q",
        "--query",
        default="",
        help="Query string for filtering Patches (empty = config value)",
    )
    axe_restart_parser.add_argument(
        "-t",
        "--verify-timeout",
        type=_positive_float,
        default=15.0,
        help="Heartbeat verification timeout per start attempt, in seconds "
        "(default: 15)",
    )
    axe_restart_parser.add_argument(
        "-z",
        "--zombie-timeout",
        type=int,
        default=None,
        help="Zombie detection timeout in seconds (default: config value)",
    )

    # --- axe status ---
    axe_status_parser = axe_subparsers.add_parser(
        "status",
        help="Show a read-only, whole-system AXE health snapshot",
        description="Show a read-only, whole-system AXE health snapshot.",
    )
    axe_status_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the machine-readable status object",
    )

    # --- axe start ---
    axe_start_parser = axe_subparsers.add_parser(
        "start", help="Start the axe orchestrator (spawns all routines)"
    )
    axe_start_parser.add_argument(
        "-H",
        "--max-hook-runners",
        type=int,
        default=None,
        help="Maximum concurrent hook runners (default: 3)",
    )
    axe_start_parser.add_argument(
        "-A",
        "--max-agent-runners",
        type=int,
        default=None,
        help="Maximum concurrent agent runners (default: 3)",
    )
    axe_start_parser.add_argument(
        "-q",
        "--query",
        default="",
        help="Query string for filtering Patches (empty = all Patches). "
        "Examples: '\"feature\" AND %%d', '+myproject', '!!! OR @@@'",
    )
    axe_start_parser.add_argument(
        "-z",
        "--zombie-timeout",
        type=int,
        default=None,
        help="Zombie detection timeout in seconds (default: 7200 = 2 hours). "
        "Hooks and CRS workflows running longer than this are marked as ZOMBIE.",
    )

    # --- axe stop ---
    axe_stop_parser = axe_subparsers.add_parser(
        "stop", help="Stop the running axe orchestrator"
    )
    axe_stop_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Sweep orphaned axe processes and reset PID state",
    )


def _add_axe_job_group(
    axe_subparsers: argparse._SubParsersAction,
    *,
    name: str,
    hidden: bool,
) -> None:
    """Register public ``job`` commands and hidden legacy ``chop`` commands."""
    group_help = (
        argparse.SUPPRESS
        if hidden
        else ("Inspect and run jobs (bare `job` defaults to `job list`)")
    )
    parser = axe_subparsers.add_parser(name, help=group_help)
    subparsers = parser.add_subparsers(
        dest="axe_chop_subcommand", help="Job subcommands"
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Diagnose configured and available job setup"
    )
    _add_chop_diagnostic_flags(doctor_parser)

    list_parser = subparsers.add_parser(
        "list", help="List configured jobs and their status"
    )
    list_parser.add_argument(
        "-a",
        "--available",
        action="store_true",
        help="Also show discoverable executable job scripts, including unconfigured ones",
    )
    _add_chop_diagnostic_flags(list_parser)

    run_parser = subparsers.add_parser(
        "run", help="Run a single job once in the foreground"
    )
    run_parser.add_argument("chop_name", metavar="JOB", help="Name of the job to run")
    run_parser.add_argument(
        "-V",
        "--job-verbose",
        dest="chop_verbose",
        action="store_true",
        help="Enable verbose script diagnostics and show the full structured result",
    )
    run_parser.add_argument(
        "--chop-verbose",
        dest="chop_verbose",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    run_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Run the script and preview validated agent proposals without launching",
    )
    run_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Bypass declarative guards for this manual run (triggers are already bypassed)",
    )
    run_parser.add_argument(
        "-L",
        "--routine",
        dest="routine",
        metavar="ROUTINE",
        default=None,
        help="Configured routine to attribute the run to (required when the "
        "job name appears in multiple routines)",
    )
    run_parser.add_argument(
        "--lumberjack",
        dest="lumberjack",
        default=None,
        help=argparse.SUPPRESS,
    )


def _add_axe_routine_group(
    axe_subparsers: argparse._SubParsersAction,
    *,
    name: str,
    hidden: bool,
) -> None:
    """Register public ``routine`` commands and hidden legacy aliases."""
    group_help = argparse.SUPPRESS if hidden else "Routine management commands"
    parser = axe_subparsers.add_parser(name, help=group_help)
    subparsers = parser.add_subparsers(
        dest="axe_lumberjack_subcommand", help="Routine subcommands"
    )

    list_parser = subparsers.add_parser("list", help="List configured routines")
    list_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show full routine descriptions",
    )

    run_parser = subparsers.add_parser(
        "run", help="Run a single routine in the foreground"
    )
    run_parser.add_argument(
        "lumberjack_name", metavar="ROUTINE", help="Name of the routine to run"
    )
    # These flags are forwarded by the orchestrator when spawning routines.
    run_parser.add_argument(
        "-q",
        "--query",
        default="",
        help="Query string for filtering Patches",
    )
    run_parser.add_argument(
        "-H",
        "--max-hook-runners",
        type=int,
        default=None,
        help="Maximum concurrent hook runners",
    )
    run_parser.add_argument(
        "-A",
        "--max-agent-runners",
        type=int,
        default=None,
        help="Maximum concurrent agent runners",
    )
    run_parser.add_argument(
        "-z",
        "--zombie-timeout",
        type=int,
        default=None,
        help="Zombie detection timeout in seconds",
    )

    subparsers.add_parser("status", help="Show status of all routines")


def _add_chop_diagnostic_flags(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-j/--json`` and ``-v/--verbose`` job output flags."""
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show descriptions, resolution paths, and search-dir detail",
    )
