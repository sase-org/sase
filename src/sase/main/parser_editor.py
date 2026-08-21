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
        description=(
            "Read one JSON object from stdin and write one compact JSON response "
            "to stdout for a fixed editor helper operation."
        ),
    )
    helper_bridge_subparsers = helper_bridge_parser.add_subparsers(
        dest="editor_helper_bridge_subcommand",
        metavar="OPERATION",
    )
    helper_bridge_subparsers.add_parser(
        "agent-catalog",
        help=argparse.SUPPRESS,
    )
    helper_bridge_subparsers.add_parser(
        "finalizer-catalog",
        help="Return configured %%final completion rows as compact JSON",
        description=(
            "Read one JSON request from stdin and write one compact JSON "
            "finalizer completion catalog to stdout. ACE and the xprompt LSP "
            "use this catalog to complete %%final selectors from effective "
            "trusted configuration without loading provider code."
        ),
        epilog=(
            "Request JSON:\n"
            '  {"schema_version": 1, "project": "<optional display name>"}\n\n'
            "Response JSON:\n"
            '  {"schema_version": 1, "status": "ok"|"error",'
            ' "message": "...", "entries": [...]}\n\n'
            "schema_version must be 1. Unknown request fields are ignored so "
            "mixed-version clients stay compatible. Malformed finalizer "
            "configuration returns status=error with empty entries instead of "
            "invented rows. Catalog loading never executes a finalizer provider."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    helper_bridge_subparsers.add_parser(
        "snippet-catalog",
        help=argparse.SUPPRESS,
    )
    helper_bridge_subparsers.add_parser(
        "vcs-repo-catalog",
        help=argparse.SUPPRESS,
    )
    helper_bridge_subparsers.add_parser(
        "xprompt-catalog",
        help=argparse.SUPPRESS,
    )
