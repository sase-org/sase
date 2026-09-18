"""Argument parser definitions for the canonical ``sase scheduler`` command."""

from __future__ import annotations

import argparse


def register_scheduler_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register scheduler lifecycle commands."""
    scheduler_parser = subparsers.add_parser(
        "scheduler",
        help="Control the SASE scheduler",
        description=(
            "Control the SASE scheduler. With the service_host beta flag enabled, "
            "start, stop, restart, and status route through `sase service proc "
            "scheduler`; with the flag disabled they preserve the legacy AXE "
            "lifecycle behavior."
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
    restart_parser.add_argument(
        "-t",
        "--verify-timeout",
        type=float,
        default=15.0,
        metavar="SECONDS",
        help="Legacy AXE heartbeat verification timeout (default: 15)",
    )

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

    stop_parser = scheduler_sub.add_parser(
        "stop",
        help="Stop the scheduler",
    )
    stop_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Legacy AXE force stop when the service host flag is disabled",
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
