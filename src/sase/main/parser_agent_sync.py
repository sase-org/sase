"""Argument parser definitions for agent-sidecar sync subcommands."""

from __future__ import annotations

import argparse


def register_agent_sync_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent sync' subcommand."""
    sync_parser = agents_sub.add_parser(
        "sync",
        help="Publish local agent hoods and inspect sidecar git status",
        description=(
            "Without flags, pull enabled agents sidecars, publish locally "
            "commit-eligible hoods, restore deferred prompt archives, push, and "
            "drain publication retries. --check is local and network-free; "
            "--check --refresh fetches remote refs before computing ahead/behind."
        ),
    )
    sync_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help=(
            "Read cached sidecar status and publication diagnostics without "
            "network, publication, commit, or push"
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
            "With --check, fetch remote refs before computing sidecar "
            "ahead/behind counts"
        ),
    )
    sync_parser.add_argument(
        "-g",
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
