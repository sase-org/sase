"""Argument parser definitions for the canonical ``sase scheduler`` command."""

from __future__ import annotations

import argparse


def register_scheduler_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register scheduler lifecycle commands."""
    scheduler_parser = subparsers.add_parser(
        "scheduler",
        help="Control the SASE scheduler",
        description=(
            "Control the SASE scheduler. start, stop, restart, and status route "
            "through the `scheduler` service proc on the SASE service host; run "
            "execs the foreground orchestrator that the service host itself runs."
        ),
    )
    scheduler_parser.set_defaults(scheduler_subcommand="status")
    scheduler_sub = scheduler_parser.add_subparsers(
        dest="scheduler_subcommand",
        help="Scheduler subcommands",
        metavar="{restart,run,start,status,stop}",
    )

    restart_parser = scheduler_sub.add_parser(
        "restart",
        help="Restart the scheduler",
    )
    _add_scheduler_overrides(restart_parser)
    _add_json_flag(restart_parser)

    run_parser = scheduler_sub.add_parser(
        "run",
        help="Run the foreground scheduler orchestrator",
    )
    _add_scheduler_overrides(run_parser)

    start_parser = scheduler_sub.add_parser(
        "start",
        help="Start the scheduler",
    )
    _add_scheduler_overrides(start_parser)

    status_parser = scheduler_sub.add_parser(
        "status",
        help="Show scheduler status",
    )
    _add_json_flag(status_parser)

    scheduler_sub.add_parser(
        "stop",
        help="Stop the scheduler",
    )


def _add_scheduler_overrides(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-A",
        "--max-agent-runners",
        type=int,
        default=None,
        help="Maximum concurrent agent runners (default: config value)",
    )
    parser.add_argument(
        "-H",
        "--max-hook-runners",
        type=int,
        default=None,
        help="Maximum concurrent hook runners (default: config value)",
    )
    parser.add_argument(
        "-q",
        "--query",
        default="",
        help="Query string for filtering Patches (empty = config value)",
    )
    parser.add_argument(
        "-z",
        "--zombie-timeout",
        type=int,
        default=None,
        help="Zombie detection timeout in seconds (default: config value)",
    )


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )


__all__ = ["register_scheduler_parser"]
