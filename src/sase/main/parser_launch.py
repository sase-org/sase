"""Argument parser definition for the ``sase launch`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_launch_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase launch`` command group."""
    launch_parser = subparsers.add_parser(
        "launch",
        help="Resolve pending LaunchApproval requests",
        description=(
            "Resolve pending launch approval requests created before detached "
            "agents are spawned."
        ),
    )
    launch_subparsers = launch_parser.add_subparsers(
        dest="launch_subcommand", help="Launch approval subcommands", required=True
    )

    approve_parser = launch_subparsers.add_parser(
        "approve",
        help="Approve a pending launch request",
        description="Approve a pending launch request by request id or notification prefix.",
    )
    approve_parser.add_argument(
        "selector",
        help="Launch request id, notification id, or unique notification prefix",
    )

    reject_parser = launch_subparsers.add_parser(
        "reject",
        help="Reject a pending launch request",
        description="Reject a pending launch request by request id or notification prefix.",
    )
    reject_parser.add_argument(
        "selector",
        help="Launch request id, notification id, or unique notification prefix",
    )
    reject_parser.add_argument(
        "-f",
        "--feedback",
        help="Optional feedback to write into launch_response.json",
    )
