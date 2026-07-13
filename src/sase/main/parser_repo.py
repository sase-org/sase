"""Argument parser definition for the ``sase repo`` CLI command."""

from __future__ import annotations

import argparse


def register_repo_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register repository inventory commands."""

    repo_parser = subparsers.add_parser(
        "repo",
        help="List primary, sidecar, and linked repositories known by SASE",
        description=(
            "Inspect repositories known by SASE. Running `sase repo` defaults "
            "to `sase repo list`."
        ),
    )
    repo_sub = repo_parser.add_subparsers(
        dest="repo_subcommand",
        help="Repository subcommands",
    )
    list_parser = repo_sub.add_parser(
        "list",
        help="List repositories for enabled projects",
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
        help="Limit results to one project (enabled or disabled)",
    )


__all__ = ["register_repo_parser"]
