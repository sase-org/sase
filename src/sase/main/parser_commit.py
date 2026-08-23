"""Argument parser definitions for restore and revert CLI subcommands."""

import argparse


def register_restore_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'restore' subcommand parser."""
    restore_parser = subparsers.add_parser(
        "restore",
        help="Restore a reverted Patch by re-applying its diff and creating a new PR",
    )
    restore_parser.add_argument(
        "name",
        nargs="?",
        help="NAME of the reverted Patch to restore (e.g., 'foobar_feature__2')",
    )
    # Options for 'restore' (keep sorted alphabetically by long option name)
    restore_parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="List all reverted Patches",
    )


def register_revert_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'revert' subcommand parser."""
    revert_parser = subparsers.add_parser(
        "revert",
        help="Revert a Patch by pruning its PR and archiving the diff",
    )
    revert_parser.add_argument(
        "name",
        help="NAME of the Patch to revert",
    )
