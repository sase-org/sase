"""Argument parser definition for the ``sase workspace`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_workspace_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase workspace`` subcommand parser."""
    workspace_parser = subparsers.add_parser(
        "workspace",
        help="Inspect and manage managed workspace checkouts",
    )
    workspace_sub = workspace_parser.add_subparsers(
        dest="workspace_subcommand",
        help="Workspace subcommands",
    )

    list_parser = workspace_sub.add_parser(
        "list",
        help="List managed workspace checkouts (including primary #0)",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to query (default: infer from current directory)",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON array",
    )

    path_parser = workspace_sub.add_parser(
        "path",
        help="Print the checkout path for a workspace number",
    )
    path_parser.add_argument(
        "workspace_num",
        type=int,
        help="Workspace number (0 = primary, 10+ = managed claims)",
    )
    path_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to query (default: infer from current directory)",
    )

    open_parser = workspace_sub.add_parser(
        "open",
        help="Print or open the workspace checkout (currently just prints)",
    )
    open_parser.add_argument(
        "workspace_num",
        type=int,
        help="Workspace number (0 = primary, 10+ = managed claims)",
    )
    open_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to query (default: infer from current directory)",
    )
    open_parser.add_argument(
        "-P",
        "--print",
        action="store_true",
        dest="print_path",
        help="Print the path (current default behavior; reserved for editor mode)",
    )

    cleanup_parser = workspace_sub.add_parser(
        "cleanup",
        help="Remove stale managed checkouts no longer referenced by a claim",
    )
    cleanup_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to clean (default: infer from current directory)",
    )
    cleanup_parser.add_argument(
        "-s",
        "--stale",
        action="store_true",
        help="Remove unclaimed managed checkouts older than the configured TTL",
    )
    cleanup_parser.add_argument(
        "-i",
        "--include-shares",
        action="store_true",
        dest="include_shares",
        help="Also consider workflow-share managed checkouts for removal",
    )
    cleanup_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Report planned removals without touching the filesystem",
    )

    repair_parser = workspace_sub.add_parser(
        "repair",
        help="Reconcile the workspace registry with the filesystem",
    )
    repair_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to repair (default: infer from current directory)",
    )
    repair_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Report planned changes without touching the filesystem or registry",
    )
