"""Argument parser definition for the ``sase vcs`` CLI subcommand."""

from __future__ import annotations

import argparse

from sase.main.parser_bead import nonnegative_int
from sase.vcs_log.dates import DATE_HELP

#: Default number of commits in the merged timeline.
_DEFAULT_LIMIT = 20


def _add_log_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-a",
        "--author",
        action="append",
        default=[],
        dest="authors",
        metavar="PATTERN",
        help="Filter by author name/email substring (repeatable; ORed)",
    )
    parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    parser.add_argument(
        "-o",
        "--current-only",
        action="store_true",
        help="Only the current/primary repo (skip linked repos and the SDD store)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["pretty", "full", "oneline", "json"],
        default="pretty",
        help="Output format: pretty, full, oneline, or json (default: pretty)",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=_DEFAULT_LIMIT,
        metavar="N",
        help=f"Max commits in the merged timeline; 0 means unlimited (default: {_DEFAULT_LIMIT})",
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
        "-R",
        "--reverse",
        action="store_true",
        help="Show the selected commits oldest-first",
    )
    parser.add_argument(
        "-s",
        "--since",
        "--after",
        dest="since",
        metavar="DATE",
        help="Only commits at/after DATE",
    )
    parser.add_argument(
        "-u",
        "--until",
        "--before",
        dest="until",
        metavar="DATE",
        help="Only commits at/before DATE",
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
        description=(
            "Show a chronological, cross-repository commit timeline across "
            "the primary repo, linked repos, and the SDD store."
        ),
        epilog=f"DATE grammar: {DATE_HELP}.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_log_options(log_parser)

    # A bare ``sase vcs`` runs ``log`` with default options.
    vcs_parser.set_defaults(
        vcs_subcommand="log",
        limit=_DEFAULT_LIMIT,
        authors=[],
        repos=[],
        current_only=False,
        format="pretty",
        color="auto",
        reverse=False,
        since=None,
        until=None,
    )
