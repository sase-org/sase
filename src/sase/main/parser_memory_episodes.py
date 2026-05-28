"""Argument parser definition for ``sase memory episodes``."""

from __future__ import annotations

import argparse


def register_memory_episodes_parser(
    memory_subparsers: argparse._SubParsersAction,
) -> None:
    """Register the ``sase memory episodes`` nested command group."""

    episodes_parser = memory_subparsers.add_parser(
        "episodes",
        help="Build, inspect, verify, and recall project episodic memory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Build, inspect, verify, and recall source-grounded records of "
            "prior SASE work. Episodes are deterministic evidence records "
            "under ~/.sase/projects/<project>/episodes. They do not modify "
            "memory/short or memory/long."
        ),
        epilog=(
            "examples:\n"
            "  sase memory episodes build -n <agent>\n"
            "  sase memory episodes build -p <project> -s 2026-05-19 -u 2026-05-20 --split\n"
            "  sase memory episodes build -n <agent> -D -j\n"
            "  sase memory episodes list -s 2026-05-19 -u 2026-05-20 -g day\n"
            "  sase memory episodes show <episode-id>\n"
            "  sase memory episodes verify <episode-id>\n"
            '  sase memory episodes recall -q "retry feedback"'
        ),
    )
    episodes_subparsers = episodes_parser.add_subparsers(
        dest="episodes_subcommand",
        help="Episode subcommands",
        required=False,
    )

    _register_build_parser(episodes_subparsers)
    _register_list_parser(episodes_subparsers)
    _register_show_parser(episodes_subparsers)
    _register_verify_parser(episodes_subparsers)
    _register_recall_parser(episodes_subparsers)


def _register_build_parser(
    episodes_subparsers: argparse._SubParsersAction,
) -> None:
    build_parser = episodes_subparsers.add_parser(
        "build",
        help="Build and optionally store an episode from deterministic selectors",
    )
    _add_project_argument(build_parser)
    selector_group = build_parser.add_mutually_exclusive_group()
    selector_group.add_argument(
        "-n",
        "--agent",
        metavar="AGENT",
        help="Build from a named agent or agent family",
    )
    selector_group.add_argument(
        "-a",
        "--artifact-dir",
        metavar="DIR",
        help="Build from one agent artifact directory",
    )
    selector_group.add_argument(
        "-c",
        "--changespec",
        metavar="NAME",
        help="Build from a ChangeSpec name",
    )
    selector_group.add_argument(
        "-C",
        "--chat",
        metavar="CHAT",
        help="Build from a chat path or chat basename",
    )
    build_parser.add_argument(
        "-s",
        "--since",
        metavar="DATE",
        help="Include project-scan artifacts at or after DATE",
    )
    build_parser.add_argument(
        "-u",
        "--until",
        metavar="DATE",
        help="Include project-scan artifacts at or before DATE",
    )
    build_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        metavar="N",
        help="Limit seed records for agent or project-scan builds",
    )
    mode_group = build_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "-S",
        "--split",
        action="store_true",
        help="Build one v2 episode per connected component",
    )
    mode_group.add_argument(
        "-A",
        "--aggregate",
        action="store_true",
        help="Use the temporary aggregate v1-compatible build path",
    )
    build_parser.add_argument(
        "-D",
        "--dry-run",
        action="store_true",
        help="Build and render the episode report without writing files",
    )
    build_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help=("Record force intent in JSON output; writes remain content-idempotent"),
    )
    build_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress phase progress on stderr; print only the final summary",
    )
    _add_json_argument(build_parser)


def _register_list_parser(
    episodes_subparsers: argparse._SubParsersAction,
) -> None:
    list_parser = episodes_subparsers.add_parser(
        "list",
        help="List stored episodes for a project and time window",
    )
    _add_project_argument(list_parser)
    list_parser.add_argument(
        "-s",
        "--since",
        metavar="DATE",
        help="Show episodes whose event span overlaps DATE or later",
    )
    list_parser.add_argument(
        "-u",
        "--until",
        metavar="DATE",
        help="Show episodes whose event span overlaps DATE or earlier",
    )
    list_parser.add_argument(
        "-b",
        "--band",
        metavar="BAND",
        help="Filter by importance band",
    )
    list_parser.add_argument(
        "-n",
        "--agent",
        metavar="AGENT",
        help="Filter by root agent name",
    )
    list_parser.add_argument(
        "-c",
        "--changespec",
        metavar="NAME",
        help="Filter by ChangeSpec name",
    )
    list_parser.add_argument(
        "-B",
        "--bead",
        metavar="BEAD",
        help="Filter by bead id",
    )
    list_parser.add_argument(
        "-q",
        "--query",
        metavar="QUERY",
        help="Filter by text in title, summary, metadata, aliases, or warnings",
    )
    list_parser.add_argument(
        "-g",
        "--group",
        choices=("day", "week", "none"),
        default="none",
        help="Group human output by day, week, or none (default: none)",
    )
    list_parser.add_argument(
        "-o",
        "--order",
        choices=("time", "importance", "title"),
        default="time",
        help="Sort by time, importance, or title (default: time)",
    )
    list_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        metavar="N",
        help="Limit the number of listed episodes",
    )
    _add_json_argument(list_parser)


def _register_show_parser(
    episodes_subparsers: argparse._SubParsersAction,
) -> None:
    show_parser = episodes_subparsers.add_parser(
        "show",
        help="Show a stored episode lesson, JSON, sources, or timeline",
    )
    show_parser.add_argument(
        "episode_id",
        metavar="episode-id",
        help="Episode id or unambiguous id prefix",
    )
    _add_project_argument(show_parser)
    show_parser.add_argument(
        "-f",
        "--format",
        choices=("lesson", "json", "sources", "timeline"),
        default="lesson",
        help="Output format (default: lesson)",
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Shortcut for --format json",
    )


def _register_verify_parser(
    episodes_subparsers: argparse._SubParsersAction,
) -> None:
    verify_parser = episodes_subparsers.add_parser(
        "verify",
        help="Verify one stored episode or all stored episodes",
    )
    verify_parser.add_argument(
        "episode_id",
        nargs="?",
        metavar="episode-id",
        help="Episode id or unambiguous id prefix; omit to verify all episodes",
    )
    _add_project_argument(verify_parser)
    verify_parser.add_argument(
        "-A",
        "--all",
        action="store_true",
        help="Verify all stored episodes for the project",
    )
    _add_json_argument(verify_parser)


def _register_recall_parser(
    episodes_subparsers: argparse._SubParsersAction,
) -> None:
    recall_parser = episodes_subparsers.add_parser(
        "recall",
        help="Deterministically search stored episode lessons",
    )
    recall_parser.add_argument(
        "-q",
        "--query",
        required=True,
        metavar="QUERY",
        help="Keyword query to match against stored episodes",
    )
    _add_project_argument(recall_parser)
    recall_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Maximum number of matches to return (default: 10)",
    )
    _add_json_argument(recall_parser)


def _add_project_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--project",
        metavar="PROJECT",
        help="Project memory name (default: inferred from the current workspace)",
    )


def _add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )


__all__ = [
    "register_memory_episodes_parser",
]
