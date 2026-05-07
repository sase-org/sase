"""Argument parser definition for the ``sase editor`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_editor_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase editor`` subcommand parser."""
    editor_parser = subparsers.add_parser(
        "editor",
        help="Run editor integration helpers",
    )
    editor_subparsers = editor_parser.add_subparsers(
        dest="editor_subcommand", help="Editor subcommands"
    )

    helper_bridge_parser = editor_subparsers.add_parser(
        "helper-bridge",
        help=argparse.SUPPRESS,
    )
    helper_bridge_subparsers = helper_bridge_parser.add_subparsers(
        dest="editor_helper_bridge_subcommand",
    )
    helper_bridge_subparsers.add_parser(
        "xprompt-catalog",
        help=argparse.SUPPRESS,
    )
