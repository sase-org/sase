"""Argument parser definitions for ace and axe subcommands."""

import argparse

from sase.ace.saved_queries import load_first_saved_query, load_last_query


def register_ace_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'ace' subcommand parser."""
    ace_parser = subparsers.add_parser(
        "ace",
        help="Interactively navigate through ChangeSpecs matching a query",
    )
    # Optional positional argument with default
    ace_parser.add_argument(
        "query",
        nargs="?",
        default=load_last_query() or load_first_saved_query() or "!!!",
        help="Query string for filtering ChangeSpecs (default: first saved query, "
        "or '!!!' for error suffixes). "
        'Examples: \'"feature" AND "Ready"\', \'"myproject" OR "bugfix"\', '
        "'!!! AND @myproject'",
    )
    # Options for 'ace' (keep sorted alphabetically by long option name)
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
        "--restart-axe",
        action="store_true",
        help="Restart the axe daemon on startup (no-op if axe is not running)",
    )
    ace_parser.add_argument(
        "-t",
        "--tab",
        choices=["artifacts", "changespecs", "agents", "axe"],
        default="agents",
        help="Tab to focus on startup; 'changespecs' remains a legacy alias for "
        "'artifacts' (default: agents)",
    )
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
        "--no-axe",
        action="store_true",
        help="Disable auto-starting the axe daemon on startup",
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
    axe_parser = subparsers.add_parser(
        "axe",
        help="Schedule-based daemon for continuous ChangeSpec status updates",
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
        dest="axe_subcommand", help="Axe subcommands"
    )

    # --- axe chop ---
    axe_chop_parser = axe_subparsers.add_parser(
        "chop",
        help="Inspect and run chops (bare `chop` defaults to `chop list`)",
    )
    axe_chop_subparsers = axe_chop_parser.add_subparsers(
        dest="axe_chop_subcommand", help="Chop subcommands"
    )

    # sase axe chop doctor
    axe_chop_doctor_parser = axe_chop_subparsers.add_parser(
        "doctor", help="Diagnose configured and available chop setup"
    )
    _add_chop_diagnostic_flags(axe_chop_doctor_parser)

    # sase axe chop list
    axe_chop_list_parser = axe_chop_subparsers.add_parser(
        "list", help="List configured chops and their status"
    )
    axe_chop_list_parser.add_argument(
        "-a",
        "--available",
        action="store_true",
        help="Also show discoverable executable chop scripts, including "
        "unconfigured ones",
    )
    _add_chop_diagnostic_flags(axe_chop_list_parser)

    # sase axe chop run <name>
    axe_chop_run_parser = axe_chop_subparsers.add_parser(
        "run", help="Run a single chop once in the foreground"
    )
    axe_chop_run_parser.add_argument("chop_name", help="Name of the chop to run")
    axe_chop_run_parser.add_argument(
        "-L",
        "--lumberjack",
        default=None,
        help="Configured lumberjack to attribute the run to (required when the "
        "chop name appears in multiple lumberjacks)",
    )

    # --- axe lumberjack ---
    axe_lumberjack_parser = axe_subparsers.add_parser(
        "lumberjack", help="Lumberjack management commands"
    )
    axe_lumberjack_subparsers = axe_lumberjack_parser.add_subparsers(
        dest="axe_lumberjack_subcommand", help="Lumberjack subcommands"
    )

    # sase axe lumberjack list
    axe_lumberjack_subparsers.add_parser("list", help="List configured lumberjacks")

    # sase axe lumberjack run <name>
    axe_lumberjack_run_parser = axe_lumberjack_subparsers.add_parser(
        "run", help="Run a single lumberjack in the foreground"
    )
    axe_lumberjack_run_parser.add_argument(
        "lumberjack_name", help="Name of the lumberjack to run"
    )
    # These flags are forwarded by the orchestrator when spawning lumberjacks
    axe_lumberjack_run_parser.add_argument(
        "-q",
        "--query",
        default="",
        help="Query string for filtering ChangeSpecs",
    )
    axe_lumberjack_run_parser.add_argument(
        "-H",
        "--max-hook-runners",
        type=int,
        default=None,
        help="Maximum concurrent hook runners",
    )
    axe_lumberjack_run_parser.add_argument(
        "-A",
        "--max-agent-runners",
        type=int,
        default=None,
        help="Maximum concurrent agent runners",
    )
    axe_lumberjack_run_parser.add_argument(
        "-z",
        "--zombie-timeout",
        type=int,
        default=None,
        help="Zombie detection timeout in seconds",
    )

    # sase axe lumberjack status
    axe_lumberjack_subparsers.add_parser(
        "status", help="Show status of all lumberjacks"
    )

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

    # --- axe start ---
    axe_start_parser = axe_subparsers.add_parser(
        "start", help="Start the axe orchestrator (spawns all lumberjacks)"
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
        help="Query string for filtering ChangeSpecs (empty = all ChangeSpecs). "
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


def _add_chop_diagnostic_flags(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``-j/--json`` and ``-v/--verbose`` chop output flags."""
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
