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
        "-a",
        "--all",
        action="store_true",
        dest="all_projects",
        help="List registered workspaces across all enabled and disabled projects",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    list_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to query (default: infer from current directory)",
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
        help="Prepare the workspace checkout and print its path",
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
        "-r",
        "--reason",
        required=True,
        help="Non-empty reason for opening and preparing the workspace",
    )
    open_parser.add_argument(
        "-P",
        "--print",
        action="store_true",
        dest="print_path",
        help="Print the prepared path (default; kept for compatibility)",
    )
    open_parser.add_argument(
        "-c",
        "--clean",
        action="store_true",
        help="Prepare, clean, and update before printing (default; kept for compatibility)",
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

    migrate_parser = workspace_sub.add_parser(
        "migrate",
        help="Migrate adjacent workspaces to a managed root or finalize the transition",
    )
    migrate_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project to migrate (default: infer from current directory)",
    )
    migrate_parser.add_argument(
        "-t",
        "--to",
        choices=("xdg-state",),
        default=None,
        help="Target root policy (currently only 'xdg-state' is supported)",
    )
    migrate_parser.add_argument(
        "-s",
        "--symlink-transition",
        action="store_true",
        dest="symlink_transition",
        help="Leave a '<primary>_<num>' symlink pointing to each migrated checkout",
    )
    migrate_parser.add_argument(
        "-f",
        "--finalize",
        action="store_true",
        help="Remove transition symlinks left behind by a prior migration",
    )
    migrate_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Report planned actions without touching the filesystem or registry",
    )
