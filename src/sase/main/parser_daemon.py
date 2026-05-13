"""Argument parser definition for the ``sase daemon`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_daemon_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase daemon`` subcommand parser."""
    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Manage the local SASE daemon",
    )
    daemon_subparsers = daemon_parser.add_subparsers(
        dest="daemon_subcommand", help="Daemon subcommands"
    )

    start_parser = daemon_subparsers.add_parser(
        "start",
        help="Start the local daemon",
    )
    _add_runtime_options(start_parser)
    start_parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run the daemon in the foreground",
    )
    start_parser.add_argument(
        "--disable-mobile-http",
        action="store_true",
        help="Disable the mobile HTTP API inside daemon mode",
    )
    start_parser.add_argument(
        "-b",
        "--bind",
        dest="bind_address",
        help="Mobile HTTP host:port bind passed through to sase_gateway daemon",
    )
    start_parser.add_argument(
        "-L",
        "--allow-non-loopback",
        action="store_true",
        help="Allow explicit non-loopback mobile HTTP binds",
    )
    start_parser.add_argument(
        "-A",
        "--agent-bridge-command",
        help=argparse.SUPPRESS,
    )
    start_parser.add_argument(
        "-J",
        "--helper-bridge-command",
        help=argparse.SUPPRESS,
    )
    start_parser.add_argument(
        "-c",
        "--command",
        dest="daemon_command",
        help="Gateway command override, parsed without a shell",
    )
    start_parser.add_argument(
        "-T",
        "--startup-timeout",
        type=float,
        help="Seconds to wait for background startup metadata",
    )

    stop_parser = daemon_subparsers.add_parser(
        "stop",
        help="Stop the local daemon",
    )
    _add_runtime_options(stop_parser)
    stop_parser.add_argument(
        "-T",
        "--timeout",
        type=float,
        dest="stop_timeout",
        help="Seconds to wait after sending the stop signal",
    )

    status_parser = daemon_subparsers.add_parser(
        "status",
        help="Show local daemon status",
    )
    _add_runtime_options(status_parser)
    status_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable status JSON",
    )

    doctor_parser = daemon_subparsers.add_parser(
        "doctor",
        help="Run daemon lifecycle diagnostics",
    )
    _add_runtime_options(doctor_parser)
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable diagnostic JSON",
    )

    rebuild_parser = daemon_subparsers.add_parser(
        "rebuild",
        help="Rebuild daemon projections",
    )
    _add_runtime_options(rebuild_parser)


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-H",
        "--sase-home",
        help="SASE state root (default: SASE_HOME or ~/.sase)",
    )
    parser.add_argument(
        "--run-root",
        help="Host-local daemon runtime directory",
    )
    parser.add_argument(
        "--socket-path",
        help="Local daemon socket path",
    )
