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
            "execs the foreground orchestrator that the service host itself runs. "
            "`sase axe start|stop|restart|status` is an alias of this command."
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
        help="Ask the service host to restart the scheduler proc",
        description=(
            "Ask the service host to stop and start the `scheduler` service "
            "proc. Waits for the host to confirm the new pid."
        ),
    )
    _add_proc_wait_options(restart_parser)

    run_parser = scheduler_sub.add_parser(
        "run",
        help="Run the foreground scheduler orchestrator",
    )
    _add_scheduler_overrides(run_parser)

    start_parser = scheduler_sub.add_parser(
        "start",
        help="Ask the service host to start the scheduler proc",
        description=(
            "Ask the service host to start the `scheduler` service proc. "
            "Waits for the host to confirm."
        ),
    )
    _add_proc_wait_options(start_parser)

    status_parser = scheduler_sub.add_parser(
        "status",
        help="Show scheduler status",
    )
    add_json_flag(status_parser)

    scheduler_sub.add_parser(
        "stop",
        help="Ask the service host to stop the scheduler proc",
        description=(
            "Ask the service host to stop the `scheduler` service proc. "
            "Returns once the request is recorded."
        ),
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


def _add_proc_wait_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-n",
        "--no-wait",
        action="store_true",
        help="Return as soon as the request is recorded",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="How long to wait for the host to confirm (default: derived from the proc's stop timeout)",
    )


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )


__all__ = [
    "add_json_flag",
    "register_scheduler_parser",
]
