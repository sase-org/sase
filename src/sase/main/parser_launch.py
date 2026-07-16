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
        help="Optional feedback to return with the launch rejection",
    )

    request_parser = launch_subparsers.add_parser(
        "request",
        help="Create a pending launch approval request",
        description=(
            "Create a LaunchApproval request from a structured JSON payload or "
            "prompt flags. Agent-side callers wait for the response; no agent "
            "is spawned unless host dispatch is approved and succeeds."
        ),
    )
    request_parser.add_argument(
        "payload",
        nargs="?",
        help="Inline JSON payload, or @PATH to read JSON from a file.",
    )
    request_parser.add_argument(
        "-a",
        "--approval",
        default="required",
        help="Approval policy to request (currently: required).",
    )
    request_parser.add_argument(
        "-f",
        "--file",
        dest="payload_file",
        help="Read the structured launch request JSON from PATH.",
    )
    request_parser.add_argument(
        "-m",
        "--max-slots",
        type=int,
        default=1,
        help="Maximum number of launch slots this request may expand to.",
    )
    request_parser.add_argument(
        "-o",
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    request_parser.add_argument(
        "-p",
        "--prompt",
        help="Prompt to request when not passing a JSON payload.",
    )
    request_parser.add_argument(
        "-r",
        "--reason",
        help="Short reason shown to the approver.",
    )
    request_parser.add_argument(
        "-s",
        "--source",
        help="Source surface label for the launch preview.",
    )
