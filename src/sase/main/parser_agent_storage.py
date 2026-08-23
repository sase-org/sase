"""Argument parser definitions for agent artifact-storage subcommands."""

from __future__ import annotations

import argparse


def register_agent_archive_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent archive' subcommand group."""
    archive_parser = agents_sub.add_parser(
        "archive",
        help="Maintain dismissed-agent archive indexes",
    )
    archive_sub = archive_parser.add_subparsers(
        dest="archive_subcommand",
        help="Archive maintenance subcommands",
    )

    archive_sub.add_parser(
        "rebuild-index",
        help="Rebuild the dismissed bundle summary index",
    )
    archive_sub.add_parser(
        "verify",
        help="Verify the dismissed bundle summary index",
    )


def register_agent_artifacts_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent artifacts' subcommand group."""
    artifacts_parser = agents_sub.add_parser(
        "artifacts",
        help="Inspect and migrate agent artifact storage",
    )
    artifacts_sub = artifacts_parser.add_subparsers(
        dest="artifacts_subcommand",
        help="Artifact subcommands",
    )
    layout_parser = artifacts_sub.add_parser(
        "layout",
        help="Manage the ace-run physical artifact layout",
    )
    layout_sub = layout_parser.add_subparsers(
        dest="layout_subcommand",
        help="Layout subcommands",
    )
    for command, help_text in (
        ("migrate", "Move flat ace-run artifact dirs into day shards"),
        ("rollback", "Move migrated ace-run artifact dirs back from a manifest"),
        ("status", "Report ace-run layout counts and index alias status"),
        ("verify", "Verify ace-run layout state against a manifest"),
    ):
        layout_command = layout_sub.add_parser(command, help=help_text)
        if command == "migrate":
            layout_command.add_argument(
                "-d",
                "--dry-run",
                action="store_true",
                help="Write or print the migration manifest without moving dirs",
            )
        layout_command.add_argument(
            "-i",
            "--index-path",
            default=None,
            help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
        )
        layout_command.add_argument(
            "-j",
            "--json",
            action="store_true",
            help="Emit a machine-readable JSON object",
        )
        if command == "migrate":
            layout_command.add_argument(
                "-l",
                "--limit",
                type=int,
                default=None,
                help="Migrate at most N artifact dirs",
            )
        if command in {"migrate", "rollback", "verify"}:
            layout_command.add_argument(
                "-m",
                "--manifest",
                default=None,
                help="Manifest path for migration, verification, or rollback",
            )
        layout_command.add_argument(
            "-P",
            "--project",
            default=None,
            help="Limit to one project",
        )
        layout_command.add_argument(
            "-p",
            "--projects-root",
            default=None,
            help="Projects artifact root (default: ~/.sase/projects)",
        )


def register_agent_index_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent index' subcommand group."""
    index_parser = agents_sub.add_parser(
        "index",
        help="Manage the persistent agent artifact index",
    )
    index_sub = index_parser.add_subparsers(
        dest="index_subcommand", help="Index subcommands"
    )
    gc_parser = index_sub.add_parser(
        "gc",
        help="Reconcile stale artifact-index rows and dismissed identities",
    )
    gc_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    gc_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    gc_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    gc_parser.add_argument(
        "-r",
        "--purge-revived-bundles",
        action="store_true",
        help=(
            "Before rebuilding, purge dismissed-bundle files and summary rows "
            "for already-revived agents (suffixes absent from "
            "dismissed_agents.json) so they stop re-hiding on rebuild"
        ),
    )
    rebuild_parser = index_sub.add_parser(
        "rebuild",
        help="Rebuild the persistent agent artifact index from artifacts",
    )
    rebuild_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    rebuild_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    rebuild_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    repair_parser = index_sub.add_parser(
        "repair",
        help="Purge invalid future-dated state from historical agent imports",
        description=(
            "Find future-dated imported artifacts, dismissed bundles, index and "
            "name-registry rows, and import journals. The command is a dry run "
            "unless --apply is provided."
        ),
    )
    repair_parser.add_argument(
        "-a",
        "--apply",
        action="store_true",
        help="Apply the repair (default: report candidates without changing state)",
    )
    repair_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    repair_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    repair_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    status_parser = index_sub.add_parser(
        "status",
        help="Inspect visible-inbox index health without scanning artifacts",
    )
    status_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    status_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    status_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )
    verify_parser = index_sub.add_parser(
        "verify",
        help="Verify the persistent agent artifact index against artifacts",
    )
    verify_parser.add_argument(
        "-i",
        "--index-path",
        default=None,
        help="SQLite index path (default: ~/.sase/agent_artifact_index.sqlite)",
    )
    verify_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    verify_parser.add_argument(
        "-p",
        "--projects-root",
        default=None,
        help="Projects artifact root (default: ~/.sase/projects)",
    )


def register_agent_names_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent names' subcommand group."""
    names_parser = agents_sub.add_parser(
        "names",
        help="Maintain the permanent agent-name registry and migrations",
    )
    names_sub = names_parser.add_subparsers(
        dest="names_subcommand", help="Name maintenance subcommands"
    )
    migrate_auto_parser = names_sub.add_parser(
        "migrate-auto",
        help="Run the historical auto-name namespace migration",
    )
    migrate_auto_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Run even when the migration marker says it already completed",
    )
    migrate_auto_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
