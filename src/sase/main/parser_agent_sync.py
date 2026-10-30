"""Argument parser definitions for agent-sidecar sync subcommands."""

from __future__ import annotations

import argparse
import re

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
_PUBLICATION_RETRY_KEY_HELP = (
    "must be GLOBAL_AGENT@REVISION with the full 40-character hex SHA stored "
    "in the outbox"
)
_FULL_OUTBOX_REVISION = re.compile(r"^[0-9a-f]{40}$")


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _publication_retry_key(raw: str) -> tuple[str, str]:
    if raw.count("@") != 1:
        raise argparse.ArgumentTypeError(_PUBLICATION_RETRY_KEY_HELP)
    global_agent, revision = raw.split("@", 1)
    if not global_agent or _FULL_OUTBOX_REVISION.fullmatch(revision) is None:
        raise argparse.ArgumentTypeError(_PUBLICATION_RETRY_KEY_HELP)
    return global_agent, revision


def _state_repair_limit(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer from 1 to 500") from exc
    if not 1 <= value <= 500:
        raise argparse.ArgumentTypeError("must be an integer from 1 to 500")
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
        "-a",
        "--apply",
        action="store_true",
        help=(
            "With --repair-revisions, write the reported repair to the "
            "outbox and audit it; with --repair-states, publish the "
            "reported state window; without either, report only and write "
            "nothing"
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
        "-R",
        "--repair-revisions",
        action="store_true",
        help=(
            "Map stale pre-commit outbox revisions to the agent's committed "
            "revision or linked scope, reporting by default and writing "
            "only with --apply; runs one project per call"
        ),
    )
    sync_parser.add_argument(
        "-s",
        "--repair-states",
        action="store_true",
        help=(
            "Report a bounded window of already-published runs whose "
            "terminal state drifted from local evidence, reporting by "
            "default and publishing only with --apply; runs one project "
            "per call"
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
        "-k",
        "--retry-key",
        type=_publication_retry_key,
        metavar="KEY",
        help=(
            "Retry exactly one hood request identified as GLOBAL_AGENT@REVISION "
            "using the full outbox SHA; requires --retry-limit 1, exactly one "
            "--project, and --retry-quarantined or --retry-retired"
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
    sync_parser.add_argument(
        "-A",
        "--state-after",
        metavar="CURSOR",
        help=(
            "Resume a state repair pass after this report's opaque cursor; "
            "only valid with --repair-states and empty to start a pass"
        ),
    )
    sync_parser.add_argument(
        "-L",
        "--state-limit",
        type=_state_repair_limit,
        metavar="N",
        help=(
            "Examine at most N published runs per state repair report "
            "across at most five hoods (1-500, default 100); only valid "
            "with --repair-states"
        ),
    )
