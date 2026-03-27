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
        "-r",
        "--refresh-interval",
        type=int,
        default=10,
        help="Auto-refresh interval in seconds (default: 10, 0 to disable)",
    )
    ace_parser.add_argument(
        "-a",
        "--agent",
        action="store_true",
        help="Run in headless agent mode (returns JSON to stdout)",
    )
    ace_parser.add_argument(
        "-k",
        "--keys",
        nargs="*",
        help="Key names to press in agent mode (e.g., j j Enter)",
    )
    ace_parser.add_argument(
        "-s",
        "--size",
        default="120x40",
        help="Terminal size as WIDTHxHEIGHT for agent mode (default: 120x40)",
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
    # Only --vcs-provider and --restart-axe live on the root axe parser (apply globally)
    axe_parser.add_argument(
        "-v",
        "--vcs-provider",
        choices=["git", "hg", "auto"],
        default=None,
        help="Override VCS provider ('git', 'hg', or 'auto' for auto-detection)",
    )
    axe_parser.add_argument(
        "--restart-axe",
        action="store_true",
        default=False,
        help="Restart the axe daemon in the background (no-op if not running)",
    )

    # Nested subparsers for axe
    axe_subparsers = axe_parser.add_subparsers(
        dest="axe_subcommand", help="Axe subcommands"
    )

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
    axe_subparsers.add_parser("stop", help="Stop the running axe orchestrator")

    # --- axe chop ---
    axe_chop_parser = axe_subparsers.add_parser("chop", help="Chop management commands")
    axe_chop_subparsers = axe_chop_parser.add_subparsers(
        dest="axe_chop_subcommand", help="Chop subcommands"
    )

    # sase axe chop list
    axe_chop_subparsers.add_parser("list", help="List all registered chops")

    # sase axe chop run <name>
    axe_chop_run_parser = axe_chop_subparsers.add_parser(
        "run", help="Run a single chop once in the foreground"
    )
    axe_chop_run_parser.add_argument("chop_name", help="Name of the chop to run")

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
