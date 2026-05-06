"""Argument parser definition for the 'artifact' CLI subcommand."""

from __future__ import annotations

import argparse


def _add_index_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-i",
        "--index",
        default=None,
        help="Artifact SQLite index path (default: ~/.sase/artifacts.sqlite)",
    )


def _add_rebuild_arguments(parser: argparse.ArgumentParser) -> None:
    _add_index_argument(parser)
    parser.add_argument("-p", "--projects-root", help="Projects root")
    parser.add_argument("-w", "--workspace-root", help="Workspace root")
    parser.add_argument("-b", "--beads-dir", help="Beads directory")
    parser.add_argument(
        "-S",
        "--include-source",
        action="append",
        default=[],
        help="Source kind to include; repeatable",
    )
    parser.add_argument(
        "-X",
        "--exclude-source",
        action="append",
        default=[],
        help="Source kind to exclude; repeatable",
    )
    parser.add_argument("-t", "--target-path", help="Target path to upsert")
    parser.add_argument("-a", "--artifact-dir", help="Agent artifact dir")
    parser.add_argument(
        "-c",
        "--stale-cleanup",
        choices=("none", "mark"),
        default="none",
        help="Stale cleanup mode (default: none)",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit stable JSON output",
    )


def _add_query_arguments(parser: argparse.ArgumentParser) -> None:
    _add_index_argument(parser)
    parser.add_argument(
        "-k",
        "--kind",
        action="append",
        default=[],
        help="Filter by artifact kind; repeatable",
    )
    parser.add_argument(
        "-F",
        "--file-type",
        action="append",
        default=[],
        help="Filter file artifacts by semantic type; repeatable",
    )
    parser.add_argument(
        "-L",
        "--link-type",
        action="append",
        default=[],
        help="Filter by linked edge type; repeatable",
    )
    parser.add_argument("-P", "--provenance", help="Filter by provenance")
    parser.add_argument(
        "-s",
        "--source-kind",
        action="append",
        default=[],
        help="Filter by source kind; repeatable",
    )
    parser.add_argument(
        "-S",
        "--source-id",
        action="append",
        default=[],
        help="Filter by source ID; repeatable",
    )
    parser.add_argument("-q", "--text", help="Text search filter")
    parser.add_argument("-r", "--root-id", help="Restrict to artifacts under root")
    parser.add_argument(
        "-u",
        "--include-tombstoned",
        action="store_true",
        help="Include tombstoned graph rows",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=200,
        help="Maximum nodes to return (default: 200)",
    )
    parser.add_argument(
        "-o",
        "--offset",
        type=int,
        default=0,
        help="Offset into query results (default: 0)",
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit stable JSON output",
    )


def register_artifact_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'artifact' subcommand parser."""
    artifact_parser = subparsers.add_parser(
        "artifact",
        help="Inspect and manage the unified artifact graph",
    )
    artifact_sub = artifact_parser.add_subparsers(
        dest="artifact_subcommand",
        help="Artifact subcommands",
    )

    add_parser = artifact_sub.add_parser(
        "add",
        help="Add or update a manual artifact, payload, or link",
    )
    _add_index_argument(add_parser)
    add_parser.add_argument("-a", "--artifact-id", help="Artifact ID to add/update")
    add_parser.add_argument("-k", "--kind", help="Artifact kind")
    add_parser.add_argument("-t", "--title", help="Display title")
    add_parser.add_argument("-s", "--subtitle", help="Display subtitle")
    add_parser.add_argument("-q", "--search-text", help="Search text")
    add_parser.add_argument("-m", "--metadata-json", help="Node metadata JSON object")
    add_parser.add_argument("-p", "--payload-json", help="Payload JSON value")
    add_parser.add_argument("-P", "--payload-type", help="Payload type")
    add_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit stable JSON output",
    )
    add_parser.add_argument(
        "-l",
        "--link",
        action="append",
        default=[],
        help="Compact link spec TYPE|SOURCE_ID|TARGET_ID or ID|TYPE|SOURCE_ID|TARGET_ID; repeatable",
    )
    add_parser.add_argument(
        "-L",
        "--link-json",
        action="append",
        default=[],
        help="Link JSON object; repeatable",
    )

    remove_parser = artifact_sub.add_parser(
        "remove",
        help="Remove or tombstone a manual artifact or link",
    )
    _add_index_argument(remove_parser)
    remove_parser.add_argument("-a", "--artifact-id", help="Artifact ID to remove")
    remove_parser.add_argument("-l", "--link-id", help="Link ID to remove")
    remove_parser.add_argument("-T", "--link-type", help="Link type")
    remove_parser.add_argument("-S", "--source-id", help="Link source artifact ID")
    remove_parser.add_argument("-D", "--target-id", help="Link target artifact ID")
    remove_parser.add_argument(
        "-p",
        "--provenance",
        help="Provenance selector for removal/tombstone semantics",
    )
    remove_parser.add_argument("-r", "--reason", help="Removal reason")
    remove_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit stable JSON output",
    )

    list_parser = artifact_sub.add_parser(
        "list",
        help="List artifact nodes",
    )
    _add_query_arguments(list_parser)

    search_parser = artifact_sub.add_parser(
        "search",
        help="Search artifact nodes",
    )
    _add_query_arguments(search_parser)

    show_parser = artifact_sub.add_parser(
        "show",
        help="Show one artifact detail record",
    )
    _add_index_argument(show_parser)
    show_parser.add_argument(
        "-a",
        "--artifact-id",
        required=True,
        help="Artifact ID to inspect",
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit stable JSON output",
    )

    graph_parser = artifact_sub.add_parser(
        "graph",
        help="Export a bounded artifact graph",
    )
    _add_index_argument(graph_parser)
    graph_parser.add_argument("-a", "--artifact-id", help="Root artifact ID")
    graph_parser.add_argument(
        "-d",
        "--depth",
        type=int,
        default=2,
        help="Maximum traversal depth (default: 2)",
    )
    graph_parser.add_argument(
        "-L",
        "--link-type",
        action="append",
        default=[],
        help="Filter by edge type; repeatable",
    )
    graph_parser.add_argument(
        "-I",
        "--include-inbound",
        action="store_true",
        help="Include inbound links",
    )
    graph_parser.add_argument(
        "-O",
        "--include-outbound",
        action="store_true",
        default=True,
        help="Include outbound links (default)",
    )
    graph_parser.add_argument(
        "-F",
        "--full",
        action="store_true",
        help="Export the full graph",
    )
    graph_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=500,
        help="Maximum graph rows to return (default: 500)",
    )
    graph_parser.add_argument(
        "-f",
        "--format",
        choices=("json", "text", "dot", "mermaid"),
        default="json",
        help="Output format (default: json)",
    )
    graph_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Alias for --format json",
    )

    rebuild_parser = artifact_sub.add_parser(
        "rebuild",
        help="Explicitly rebuild derived artifact graph rows",
    )
    rebuild_parser.description = (
        "Explicit derived artifact graph rebuild/backfill. This manual "
        "maintenance command is not run on startup."
    )
    _add_rebuild_arguments(rebuild_parser)

    sync_parser = artifact_sub.add_parser(
        "sync",
        help=("Explicitly sync/backfill historical artifact rows; not run on startup"),
    )
    sync_parser.description = (
        "Explicit historical artifact sync/backfill. This is an alias for rebuild "
        "with the same safe defaults and is not run on startup."
    )
    _add_rebuild_arguments(sync_parser)

    doctor_parser = artifact_sub.add_parser(
        "doctor",
        help="Check artifact graph consistency",
    )
    _add_index_argument(doctor_parser)
    doctor_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit stable JSON output",
    )
