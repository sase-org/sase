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

    open_parser = repo_sub.add_parser(
        "open",
        help="Prepare a repository checkout and print its path",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve a primary, sidecar, or linked repository in the host "
            "project, prepare it in one workspace context, and print only "
            "the prepared path. The workspace defaults to the checkout that "
            "contains the current directory."
        ),
        epilog=(
            "examples:\n"
            '  sase repo open chezmoi --reason "Update shared configuration"\n'
            '  sase repo open sase-core -r "Fix the Rust binding" -w 12\n'
            '  sase repo open sase--plans -p sase -r "Review the epic plan"'
        ),
    )
    open_parser.add_argument(
        "repo",
        metavar="REPO",
        help="Repository name shown by `sase repo list`",
    )
    open_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Host project (default: infer from current directory)",
    )
    open_parser.add_argument(
        "-r",
        "--reason",
        required=True,
        help="Non-empty reason for the audited repository open",
    )
    open_parser.add_argument(
        "-w",
        "--workspace",
        type=int,
        default=None,
        metavar="N",
        help="Host workspace number (default: infer from current directory)",
    )


__all__ = ["register_repo_parser"]
