"""Argument parser definition for the ``sase stats`` command group."""

from __future__ import annotations

import argparse

from sase.completion.kinds import ValueKind, set_completion_kind
from sase.stats.registry import PROJECT_REPORT_GROUPINGS, PROJECT_REPORT_LEGENDS

from ._help_format import StableInvocationHelpFormatter

_STATS_SUMMARY = "Show Admin Center Statistics views from the command line."
_PROJECT_HELP = (
    "Show the Admin Center Statistics → Projects view: what each project "
    "produced, how big its code is, and this machine's agent runs"
)
_PROJECT_DESCRIPTION = (
    "Show the Admin Center Statistics → Projects view: what each project "
    "produced (commits and committed plans, and which provider/model produced "
    "them), how big and how old its code is, and this machine's agent runs. "
    "Output and code facts come from each code repo's default branch and match "
    "on every machine; run facts come from this machine's run log and say so. "
    "Same loader and definitions as the TUI tab."
)
_FORMAT_CHOICES = ("json", "markdown", "rich")
_GROUP_CHOICES = tuple(sorted(PROJECT_REPORT_GROUPINGS))


def register_stats_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase stats`` group and its implemented views."""
    stats_parser = subparsers.add_parser(
        "stats",
        help=_STATS_SUMMARY,
        description=(
            f"{_STATS_SUMMARY} Bare `sase stats` lists implemented views. "
            "There are no stubs."
        ),
        formatter_class=StableInvocationHelpFormatter,
        epilog=(
            "examples:\n"
            "  sase stats\n"
            "  sase stats project\n"
            "  sase stats project -p sase -r all\n"
            "  sase stats project -p sase -j | jq '.data.projects[0].models'"
        ),
    )
    stats_sub = stats_parser.add_subparsers(
        dest="stats_subcommand",
        help="Statistics views",
        metavar="{project}",
    )
    _register_project_parser(stats_sub)


def _register_project_parser(stats_sub: argparse._SubParsersAction) -> None:
    project_parser = stats_sub.add_parser(
        "project",
        help=_PROJECT_HELP,
        description=_PROJECT_DESCRIPTION,
        formatter_class=StableInvocationHelpFormatter,
        epilog=_project_epilog(),
    )
    project_parser.add_argument(
        "-D",
        "--include-disabled",
        action="store_true",
        help="Also include disabled projects when no -p is given",
    )
    project_parser.add_argument(
        "-F",
        "--fetch",
        action="store_true",
        help=(
            "Fetch each code repo's default branch before measuring "
            "(default: local refs)"
        ),
    )
    project_parser.add_argument(
        "-f",
        "--format",
        choices=_FORMAT_CHOICES,
        default=None,
        help="Output format (default: rich)",
    )
    project_parser.add_argument(
        "-g",
        "--group-by",
        choices=_GROUP_CHOICES,
        default=None,
        help=(
            "Breakdown table, like the TUI's g key (default: project for "
            "several projects, model for one)"
        ),
    )
    project_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Shorthand for --format json",
    )
    project_action = project_parser.add_argument(
        "-p",
        "--project",
        action="append",
        default=None,
        metavar="PROJECT",
        help=(
            "Project name, alias, key, or +tag; repeatable "
            "(default: every enabled project)"
        ),
    )
    set_completion_kind(project_action, ValueKind.PROJECT)
    project_parser.add_argument(
        "-r",
        "--range",
        default=None,
        metavar="RANGE",
        help=(
            "today, 24h, 7d, 30d, 90d, all, Nh/Nd/Nw, YYYY-MM, YYYY-MM-DD, "
            "or START..END (default: 7d, the TUI default)"
        ),
    )


def _project_epilog() -> str:
    lines = ["definitions:"]
    lines.extend(f"  {entry.term}: {entry.meaning}" for entry in PROJECT_REPORT_LEGENDS)
    lines.extend(
        [
            "",
            "examples:",
            "  sase stats project",
            "  sase stats project -p sase -r all",
            "  sase stats project -p sase -g model -r 30d",
            "  sase stats project -p sase -g language",
            "  sase stats project -p +sase -F -f markdown > sase-stats.md",
            "  sase stats project -p sase -j | jq "
            "'.data.projects[0].models[] | {provider, model, commits, plans}'",
            "  sase stats project -p sase -j | jq "
            "'.data.projects[0].repos[] | select(.tier == \"code\") | {name, commits: .output.commits}'",
            "  sase stats project -p sase -j | jq "
            "'.data.projects[0].code.languages | sort_by(-.lines)'",
        ]
    )
    return "\n".join(lines)


__all__ = ["register_stats_parser"]
