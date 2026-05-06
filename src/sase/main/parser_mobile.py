"""Argument parser definition for the ``sase mobile`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_mobile_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase mobile`` subcommand parser."""
    mobile_parser = subparsers.add_parser(
        "mobile",
        help="Run mobile integration helpers",
    )
    mobile_subparsers = mobile_parser.add_subparsers(
        dest="mobile_subcommand", help="Mobile subcommands"
    )

    agent_bridge_parser = mobile_subparsers.add_parser(
        "agent-bridge",
        help=argparse.SUPPRESS,
    )
    agent_bridge_subparsers = agent_bridge_parser.add_subparsers(
        dest="mobile_agent_bridge_subcommand",
    )
    agent_bridge_subparsers.add_parser(
        "list-agents",
        help=argparse.SUPPRESS,
    )
    agent_bridge_subparsers.add_parser(
        "resume-options",
        help=argparse.SUPPRESS,
    )

    gateway_parser = mobile_subparsers.add_parser(
        "gateway",
        help="Manage the workstation-hosted mobile gateway",
    )
    gateway_subparsers = gateway_parser.add_subparsers(
        dest="mobile_gateway_subcommand", help="Mobile gateway subcommands"
    )

    start_parser = gateway_subparsers.add_parser(
        "start",
        help="Start the mobile gateway in the foreground",
    )
    start_parser.add_argument(
        "-b",
        "--bind-address",
        help="Host address to bind (default: config or 127.0.0.1)",
    )
    start_parser.add_argument(
        "-p",
        "--port",
        type=int,
        help="Port to bind (default: config or 7629)",
    )
    start_parser.add_argument(
        "-H",
        "--state-dir",
        help="SASE state root for gateway storage",
    )
    start_parser.add_argument(
        "-L",
        "--allow-non-loopback",
        action="store_true",
        help="Allow explicit LAN or tailnet binds",
    )
    start_parser.add_argument(
        "-c",
        "--command",
        dest="gateway_command",
        help="Gateway command override, parsed without a shell",
    )
    start_parser.add_argument(
        "-T",
        "--startup-timeout",
        type=float,
        help="Seconds to wait for startup before exiting",
    )
    start_parser.add_argument(
        "-A",
        "--agent-bridge-command",
        help=argparse.SUPPRESS,
    )
