"""Argument parser definition for the ``sase vcs`` CLI subcommand."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from sase.main.parser_bead import nonnegative_int
from sase.vcs_log.dates import DATE_HELP

#: Default number of commits in the merged timeline.
_DEFAULT_LIMIT = 40


class _NoOpAction(argparse.Action):
    """Accept a deprecated flag without changing the parsed namespace."""

    def __init__(
        self,
        option_strings: Sequence[str],
        dest: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        del parser, namespace, values, option_string


def _add_list_options(parser: argparse.ArgumentParser) -> None:
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
        choices=["pretty", "oneline", "json"],
        default="pretty",
        help="Output format: pretty, oneline, or json (default: pretty)",
    )
    parser.add_argument(
        "-N",
        "--no-fetch",
        action="store_true",
        help="Skip provider-backed description lookups",
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
        "-s",
        "--sort",
        choices=["default", "name", "commits", "recent"],
        default="default",
        help="Sort repos by default order, name, commit count, or recent activity",
    )


def _add_log_options(parser: argparse.ArgumentParser) -> None:
    scope_group = parser.add_mutually_exclusive_group()
    scope_group.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include repos from every registered enabled or disabled project",
    )
    parser.add_argument(
        "-A",
        "--author",
        action="append",
        default=[],
        dest="authors",
        metavar="PATTERN",
        help="Filter by author name/email substring (repeatable; ORed)",
    )
    parser.add_argument(
        "-b",
        "--branch",
        "--ref",
        dest="remote_ref",
        metavar="REF",
        help="Compare against REF on origin instead of the resolved remote ref",
    )
    parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    scope_group.add_argument(
        "-o",
        "--current-only",
        action="store_true",
        help="Only the current/primary repo (skip linked repos and the SDD store)",
    )
    fetch_group = parser.add_mutually_exclusive_group()
    fetch_group.add_argument(
        "-F",
        "--fetch",
        action="store_true",
        dest="force_fetch",
        help="Fetch remote refs now, bypassing the short freshness cache",
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
    fetch_group.add_argument(
        "-N",
        "--no-fetch",
        action="store_true",
        help="Skip remote fetch; compare against existing remote-tracking refs",
    )
    parser.add_argument(
        "-T",
        "--no-tags",
        action="store_false",
        default=True,
        dest="show_tags",
        help="Hide trailing SASE_* commit tags",
    )
    parser.add_argument(
        "-r",
        "--repo",
        action="append",
        default=[],
        dest="repos",
        metavar="NAME",
        help="Restrict to a repo label or unambiguous source name (repeatable)",
    )
    parser.add_argument(
        "-R",
        "--reverse",
        action="store_true",
        help="Show the selected commits oldest-first",
    )
    parser.add_argument(
        "-S",
        "--sdd",
        action="store_true",
        help="Include commits from existing separate SDD repositories",
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
        "-t",
        "--tags",
        action=_NoOpAction,
        dest="show_tags",
        help=argparse.SUPPRESS,
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

    ``sase vcs`` lists the resolved repository constellation by default.
    ``sase vcs log`` shows the chronological commit timeline for the primary
    and linked repositories, with separate SDD history available on request.
    """
    vcs_parser = subparsers.add_parser(
        "vcs",
        help="Inspect the primary + linked + SDD repository constellation",
        description=(
            "Inspect the repository constellation made up of the primary repo, "
            "configured linked repos, and the separate SDD store when present.\n\n"
            "With no subcommand, `sase vcs` defaults to `sase vcs list`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    vcs_sub = vcs_parser.add_subparsers(
        dest="vcs_subcommand",
        help="VCS subcommands",
        metavar="{list,log}",
    )
    vcs_parser.set_defaults(vcs_subcommand="list")

    list_parser = vcs_sub.add_parser(
        "list",
        help="List resolved repositories and aggregate stats",
        description=(
            "List the available primary, linked, and separate SDD repositories "
            "with per-repo stats, descriptions, branch state, and last activity. "
            "Use `sase vcs log --sdd` to include SDD commit history."
        ),
    )
    _add_list_options(list_parser)

    log_parser = vcs_sub.add_parser(
        "log",
        help="Show a chronological, cross-repository commit timeline",
        description=(
            "Show a chronological, cross-repository commit timeline across "
            "the primary repo and linked repos. Use --sdd to include separate "
            "SDD repository commits, and --all to merge repositories from every "
            "registered project."
        ),
        epilog=f"DATE grammar: {DATE_HELP}.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_log_options(log_parser)
