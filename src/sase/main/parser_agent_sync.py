"""Argument parser definitions for agent-sidecar sync subcommands."""

from __future__ import annotations

import argparse


def register_agent_retire_v1_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent retire-v1' subcommand."""
    retire_v1_parser = agents_sub.add_parser(
        "retire-v1",
        help="Safely retire this machine's legacy-v1 sidecar payload",
        description=(
            "Preview retirement of this machine's legacy-v1 agents-sidecar "
            "payload. Retirement is refused unless the current owner's v2 "
            "manifest covers every v1 hood. The command is a dry run unless "
            "--apply is explicitly supplied."
        ),
    )
    retire_v1_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Remove the covered payload, then commit and push through agents sync",
    )
    retire_v1_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a stable machine-readable JSON report",
    )
    retire_v1_parser.add_argument(
        "-p",
        "--project",
        action="append",
        default=[],
        help="Limit to a project name or alias (repeatable)",
    )


def register_agent_sync_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent sync' subcommand."""
    sync_parser = agents_sub.add_parser(
        "sync",
        help="Run full-duplex agent-sidecar sync or inspect cached incoming status",
        description=(
            "Without flags, fetch and reconcile enabled agents sidecars, import "
            "foreign history, drain publication retries, publish locally "
            "commit-eligible hoods, and push. --check is local and network-free; "
            "--check --refresh fetches and validates incoming remote hoods without "
            "importing or publishing them."
        ),
    )
    sync_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help=(
            "Reconcile cached incoming status and receipts without network, "
            "import, publication, commit, or push"
        ),
    )
    sync_parser.add_argument(
        "-d",
        "--drop-retired",
        action="store_true",
        help=(
            "Drop publication requests that were retired as unpublishable, "
            "reporting how many were dropped and why"
        ),
    )
    sync_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit stable machine-readable JSON instead of a colored table",
    )
    sync_parser.add_argument(
        "-p",
        "--project",
        action="append",
        default=[],
        help="Limit to a project name or alias (repeatable)",
    )
    sync_parser.add_argument(
        "-r",
        "--refresh",
        action="store_true",
        help=(
            "With --check, fetch remote refs and validate/cache incoming hoods "
            "without importing them"
        ),
    )
    sync_parser.add_argument(
        "--repair-digests",
        action="store_true",
        help=(
            "Re-sign locally owned hood-snapshot file references that have "
            "drifted from their on-disk payload, instead of running a normal sync"
        ),
    )
    sync_parser.add_argument(
        "-m",
        "--repair-manifest",
        action="store_true",
        help=(
            "Rebuild owner-manifest entries for on-disk hoods the manifest is "
            "missing, instead of running a normal sync"
        ),
    )
    sync_parser.add_argument(
        "-q",
        "--retry-quarantined",
        action="store_true",
        help=(
            "Clear quarantined publication requests and retry them during "
            "this full sync"
        ),
    )
