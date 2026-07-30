"""Argument parser definition for the ``sase artifact`` command group."""

from __future__ import annotations

import argparse

from sase.core.artifact_file_facade import ARTIFACT_FILE_KINDS
from sase.main.parser_bead import nonnegative_int
from sase.main.plan_search_handler import plan_date_arg


def register_artifact_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register canonical ``artifact`` and compatibility ``artifact-file``."""

    artifact_parser = subparsers.add_parser(
        "artifact",
        aliases=["artifact-file"],
        help="Create, discover, inspect, resolve, open, and repair artifacts",
        description=(
            "Create, discover, inspect, resolve, open, and repair indexed "
            "artifacts.\n\n"
            "Bare `sase artifact` defaults to `sase artifact list`."
        ),
        epilog=(
            "examples:\n"
            "  sase artifact\n"
            "  sase artifact list --kind image --project sase\n"
            "  sase artifact show file:explicit:0123456789abcdef01234567\n"
            "  sase artifact path plans:202607/example.md\n"
            "  sase artifact-file create --path report.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    artifact_subparsers = artifact_parser.add_subparsers(
        dest="artifact_subcommand",
        help="Artifact subcommands",
    )

    create_parser = artifact_subparsers.add_parser(
        "create",
        help="Store a file as an explicit artifact for the current agent",
    )
    create_parser.add_argument(
        "-k",
        "--kind",
        choices=ARTIFACT_FILE_KINDS,
        default=None,
        help="Artifact kind (default: infer from the file extension)",
    )
    create_parser.add_argument(
        "-l",
        "--label",
        default=None,
        help="Display label (default: source file name)",
    )
    create_parser.add_argument(
        "-m",
        "--move",
        action="store_true",
        help="Remove the source file after storing it (default: copy)",
    )
    create_parser.add_argument(
        "-p",
        "--path",
        required=True,
        help="Source file to copy into durable artifact storage",
    )

    doctor_parser = artifact_subparsers.add_parser(
        "doctor",
        help="Inspect, repair, and verify the artifact index",
        description=(
            "Inspect, repair, and verify the artifact index. Exits 1 when the\n"
            "index is unhealthy.\n\n"
            "Byte-free version-control-backed rows are healthy, not missing:\n"
            "  VCS reference rows          how many rows carry provenance\n"
            "                              instead of stored bytes\n"
            "  Incomplete VCS provenance   rows with a partial vcs_repo /\n"
            "                              vcs_sha / vcs_relpath triple\n"
            "  Unresolvable VCS references rows --verify could not\n"
            "                              materialize from any checkout"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    doctor_parser.add_argument(
        "-f",
        "--fix",
        action="store_true",
        help="Backfill missing enrichment fields before inspecting",
    )
    doctor_parser.add_argument(
        "-v",
        "--verify",
        action="store_true",
        help=(
            "Re-hash live stored files and materialize VCS-backed rows to "
            "verify recorded digests"
        ),
    )

    list_parser = artifact_subparsers.add_parser(
        "list",
        help="List indexed artifacts (pretty table by default, JSON with -j)",
    )
    list_parser.add_argument(
        "-a",
        "--agent",
        default=None,
        help="Only show artifacts associated with this agent name",
    )
    list_parser.add_argument(
        "-e",
        "--explicit",
        action="store_true",
        help="Only show explicitly created artifacts",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array (stable schema)",
    )
    list_parser.add_argument(
        "-k",
        "--kind",
        action="append",
        choices=ARTIFACT_FILE_KINDS,
        default=None,
        help="Only show this artifact kind (repeatable)",
    )
    list_parser.add_argument(
        "-l",
        "--limit",
        type=nonnegative_int,
        default=50,
        help="Maximum artifacts to return (default: 50; 0 means unlimited)",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Only show a project by display name, alias, or canonical key",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        default=None,
        help="Case-insensitive substring filter over label and paths",
    )
    list_parser.add_argument(
        "-s",
        "--since",
        type=plan_date_arg,
        default=None,
        help="Only show artifacts created on or after DATE",
        metavar="DATE",
    )
    list_parser.add_argument(
        "-u",
        "--unused",
        action="store_true",
        help="Only show artifacts no agent has ever referenced",
    )

    open_parser = artifact_subparsers.add_parser(
        "open",
        help="Open a resolved artifact reference with an appropriate viewer",
    )
    open_parser.add_argument(
        "reference",
        help="Artifact reference or a bare default:/explicit: file id",
    )

    path_parser = artifact_subparsers.add_parser(
        "path",
        help="Print the absolute filesystem path for an artifact reference",
    )
    path_parser.add_argument(
        "reference",
        help="Artifact reference or a bare default:/explicit: file id",
    )

    show_parser = artifact_subparsers.add_parser(
        "show",
        help="Show artifact metadata, resolution details, and consumption",
        description=(
            "Show artifact metadata, reference-resolution details, and the "
            "recorded consumption summary."
        ),
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable resolution envelope",
    )
    show_parser.add_argument(
        "reference",
        help="Artifact reference or a bare default:/explicit: file id",
    )

    stats_parser = artifact_subparsers.add_parser(
        "stats",
        help="Report artifact-store economics and default retention selection",
        description=(
            "Report artifact-store economics, reference protections, trash "
            "occupancy, and what the default retention policy would select. "
            "This command is read-only."
        ),
    )
    stats_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one machine-readable statistics envelope",
    )
    stats_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Only report a project by display name, alias, or canonical key",
    )
    stats_parser.add_argument(
        "-t",
        "--top",
        type=nonnegative_int,
        default=10,
        metavar="N",
        help="Maximum agent groups to show (default: 10)",
    )


__all__ = ["register_artifact_parser"]
