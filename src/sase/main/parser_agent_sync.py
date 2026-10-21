"""Argument parser definitions for agent-sidecar sync subcommands."""

from __future__ import annotations

import argparse

from sase.core.agent_publication_recovery import (
    PUBLICATION_ERROR_INDEX_LOCK,
    PUBLICATION_ERROR_LOCK_BUSY,
    PUBLICATION_ERROR_MANIFEST_MISMATCH,
    PUBLICATION_ERROR_OTHER,
    PUBLICATION_ERROR_REBASE_CONFLICT,
    PUBLICATION_ERROR_TIMEOUT,
    PUBLICATION_ERROR_UNKNOWN,
    PUBLICATION_ERROR_UNSTAGED_CHANGES,
)


_PUBLICATION_ERROR_CLASSES = (
    PUBLICATION_ERROR_INDEX_LOCK,
    PUBLICATION_ERROR_LOCK_BUSY,
    PUBLICATION_ERROR_MANIFEST_MISMATCH,
    PUBLICATION_ERROR_OTHER,
    PUBLICATION_ERROR_REBASE_CONFLICT,
    PUBLICATION_ERROR_TIMEOUT,
    PUBLICATION_ERROR_UNKNOWN,
    PUBLICATION_ERROR_UNSTAGED_CHANGES,
)


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


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
            "Restore missing owner-manifest hoods and normalize verified stale "
            "explicit file lists, instead of running a normal sync"
        ),
    )
    sync_parser.add_argument(
        "-e",
        "--retry-error-class",
        action="append",
        choices=_PUBLICATION_ERROR_CLASSES,
        default=[],
        metavar="CLASS",
        help=(
            "With --retry-limit, select stopped requests with this error class; "
            "repeat to accept several classes"
        ),
    )
    sync_parser.add_argument(
        "-l",
        "--retry-limit",
        type=_positive_int,
        metavar="N",
        help=(
            "Retry at most N distinct hood requests for exactly one project without "
            "full reconciliation; requires --retry-quarantined or --retry-retired"
        ),
    )
    sync_parser.add_argument(
        "-q",
        "--retry-quarantined",
        action="store_true",
        help=(
            "Clear quarantined requests for full sync; with --retry-limit, select "
            "a bounded hood-request batch"
        ),
    )
    sync_parser.add_argument(
        "-t",
        "--retry-retired",
        action="store_true",
        help=(
            "Revive this project's retired hood requests for full reconciliation, "
            "or select a bounded batch with --retry-limit; requires --project"
        ),
    )
