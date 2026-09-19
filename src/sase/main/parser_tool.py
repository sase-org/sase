"""Argument parser definition for the ``sase tool`` command group."""

from __future__ import annotations

import argparse


def register_tool_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase tool`` subcommand parser."""

    tool_parser = subparsers.add_parser(
        "tool",
        help="List project-owned named tools",
        description=(
            "List the current project's named tools with LAST result and "
            "observed TYPICAL duration.\n\n"
            "Bare `sase tool` defaults to `sase tool list`.\n\n"
            "Named tools are complete entries in the project's sase/sase.yml. "
            "User, machine, plugin, and builtin config cannot change argv."
        ),
    )
    tool_subparsers = tool_parser.add_subparsers(
        dest="tool_subcommand",
        help="Tool subcommands",
        metavar="{list}",
    )

    list_parser = tool_subparsers.add_parser(
        "list",
        help="List named tools with LAST and TYPICAL",
        description=(
            "Show each project-owned named tool with its newest native result "
            "(LAST) and observed median duration (TYPICAL). Missing samples "
            "render as an em dash, never as zero or an ETA."
        ),
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a versioned machine-readable JSON object",
    )


__all__ = ["register_tool_parser"]
