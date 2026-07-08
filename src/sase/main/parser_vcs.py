"""Argument parser definition for the ``sase vcs`` CLI subcommand."""

from __future__ import annotations

import argparse

#: Default number of commits in the merged timeline.
_DEFAULT_LIMIT = 20


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _add_log_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-n",
        "--limit",
        type=_positive_int,
        default=_DEFAULT_LIMIT,
        help=f"Max commits in the merged timeline (default: {_DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "-r",
        "--repo",
        action="append",
        default=[],
        dest="repos",
        metavar="NAME",
        help="Restrict to a named repo (repeatable); "
        "names are the project, each linked repo, and 'sdd'",
    )
    parser.add_argument(
        "--current-only",
        action="store_true",
        help="Only the current/primary repo (skip linked repos and the SDD store)",
    )
    parser.add_argument(
        "--format",
        choices=["pretty", "oneline", "json"],
        default="pretty",
        help="Output format (default: pretty)",
    )
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )


def register_vcs_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase vcs`` subcommand parser.

    ``sase vcs`` shows a chronological, cross-repository commit timeline
    aggregating the primary repo, every linked repo, and the SDD store.
    A bare ``sase vcs`` defaults to the ``log`` subcommand.
    """
    vcs_parser = subparsers.add_parser(
        "vcs",
        help="Cross-repository commit timeline (primary + linked + SDD)",
    )
    vcs_sub = vcs_parser.add_subparsers(
        dest="vcs_subcommand",
        help="VCS subcommands",
        metavar="{log}",
    )

    log_parser = vcs_sub.add_parser(
        "log",
        help="Show a chronological, cross-repository commit timeline",
    )
    _add_log_options(log_parser)

    # A bare ``sase vcs`` runs ``log`` with default options.
    vcs_parser.set_defaults(
        vcs_subcommand="log",
        limit=_DEFAULT_LIMIT,
        repos=[],
        current_only=False,
        format="pretty",
        color="auto",
    )
