"""Argument parser definition for the ``sase file-hook`` command group."""

from __future__ import annotations

import argparse


def register_file_hook_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase file-hook`` command group."""
    file_hook_parser = subparsers.add_parser(
        "file-hook",
        help="Inspect configured per-file repository hooks",
        description=(
            "Inspect non-gating commands configured under `file_hooks`. "
            "With no subcommand, `sase file-hook` defaults to "
            "`sase file-hook list`."
        ),
        epilog=(
            "examples:\n"
            "  sase file-hook\n"
            "  sase file-hook list\n"
            "  sase file-hook list --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    file_hook_subparsers = file_hook_parser.add_subparsers(
        dest="file_hook_subcommand",
        help="File-hook subcommands",
        metavar="<subcommand>",
        title="subcommands",
    )

    list_parser = file_hook_subparsers.add_parser(
        "list",
        help="List effective file hooks and their config sources",
        description=(
            "List every valid effective file hook with its command, filters, "
            "timeout, description, and contributing config layer. Invalid "
            "entries are warned about and skipped. This is also the default "
            "for bare `sase file-hook`."
        ),
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )


__all__ = ["register_file_hook_parser"]
