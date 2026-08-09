"""Read-only argument parser definitions for bead subcommands."""

from __future__ import annotations

import argparse

from sase.main.parser_bead_common import nonnegative_int, wrap_width
from sase.markdown_width import markdown_print_width


def register_bead_blocked_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead blocked``."""
    subparsers.add_parser("blocked", help="Show blocked issues")


def register_bead_history_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead history``."""
    parser = subparsers.add_parser(
        "history",
        help="Show event history or find overwritten notes",
        description=(
            "Replay the canonical event streams for one bead, or find note "
            "revisions that no longer appear in current notes. Compact "
            "history output shows one row per event; full output shows the "
            "prior and new value for every changed field."
        ),
    )
    parser.add_argument(
        "id",
        nargs="?",
        help="Full or shorthand issue ID",
    )
    parser.add_argument(
        "-F",
        "--field",
        action="append",
        help="Restrict to events changing this field (repeatable)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "full", "json"],
        default="compact",
        help="Output format: compact, full, or json (default: compact)",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=0,
        help="Newest entries to print; 0 means unlimited",
    )
    parser.add_argument(
        "-l",
        "--lost-notes",
        action="store_true",
        help="Report beads whose current notes dropped an earlier revision",
    )
    parser.add_argument(
        "-R",
        "--restore",
        action="store_true",
        help="With --lost-notes, re-append dropped revisions after confirmation",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="With --restore, skip the confirmation prompt",
    )


def register_bead_list_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead list``."""
    parser = subparsers.add_parser(
        "list",
        help="List issues",
        description=(
            "List open, claimed, ready, snoozed, and in-progress beads by default. If "
            "none match and --status was not provided, list closed beads instead. "
            "Closed listings default to the newest 20 beads unless --limit 0 "
            "is used. Bare 'sase bead' defaults to this command."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead list\n"
            "  sase bead list --status open --type phase\n"
            "  sase bead list --format json\n"
            "  sase bead list --format full --limit 3\n"
            "  sase bead list --status closed --limit 0"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "json", "full"],
        default="compact",
        help="Output format: compact, json, or full (default: compact)",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=None,
        help=(
            "Maximum beads to print; closed listings default to 20, 0 means unlimited"
        ),
    )
    parser.add_argument(
        "-s",
        "--status",
        choices=[
            "open",
            "claimed",
            "ready",
            "snoozed",
            "in_progress",
            "closed",
        ],
        action="append",
        help="Filter by status (repeatable)",
    )
    parser.add_argument(
        "-r",
        "--tier",
        choices=["plan", "epic"],
        action="append",
        help="Filter by plan-bead tier (repeatable)",
    )
    parser.add_argument(
        "-t",
        "--type",
        choices=["plan", "phase", "task"],
        action="append",
        help="Filter by type (repeatable)",
    )


def register_bead_ready_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead ready``."""
    subparsers.add_parser(
        "ready",
        help="Show unblocked task beads awaiting triage",
    )


def register_bead_search_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead search``."""
    parser = subparsers.add_parser(
        "search",
        help="Search issues by text",
        description=(
            "Find beads whose human-readable fields contain a case-insensitive "
            "literal substring by default. With --regex, interpret the query as a "
            "regular expression that is case-insensitive unless the pattern starts "
            "with (?-i). Searches every bead status by default."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead search auth\n"
            "  sase bead search '^sase-g' --regex\n"
            "  sase bead search auth --format json\n"
            "  sase bead search auth --format full --limit 3\n"
            "  sase bead search auth --status open --type phase"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "query",
        help="Literal non-empty text to search for",
    )
    parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "json", "full"],
        default="compact",
        help="Output format: compact, json, or full (default: compact)",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=nonnegative_int,
        default=None,
        help="Maximum results to print; 0 means unlimited",
    )
    parser.add_argument(
        "-e",
        "--regex",
        action="store_true",
        help="Interpret query as a regular expression",
    )
    parser.add_argument(
        "-s",
        "--status",
        choices=[
            "open",
            "claimed",
            "ready",
            "snoozed",
            "in_progress",
            "closed",
        ],
        action="append",
        help="Filter by status (repeatable)",
    )
    parser.add_argument(
        "-r",
        "--tier",
        choices=["plan", "epic"],
        action="append",
        help="Filter by plan-bead tier (repeatable)",
    )
    parser.add_argument(
        "-t",
        "--type",
        choices=["plan", "phase", "task"],
        action="append",
        help="Filter by type (repeatable)",
    )


def register_bead_show_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead show``."""
    # Resolved at parser-build time, which is per-process and lazy per
    # subcommand, so `--help` reports the live configured width.
    default_wrap_width = markdown_print_width()
    parser = subparsers.add_parser(
        "show",
        help="Show issue details",
        description=(
            "Show one bead's full detail block: status, type, tier, owner, "
            "assignee, model, phase size, parent lineage, children, "
            "dependencies, blockers, description, notes, Patch, and the "
            "linked plan. --format compact prints the same single row as "
            "'sase bead list'; --format json adds the resolved parent, child, "
            "dependency, blocker, and plan graph as machine-readable data. "
            "--color now applies to --format full as well as compact. "
            "DESCRIPTION, NOTES, and +1 evidence prose wrap at "
            f"{default_wrap_width} columns by default without breaking "
            "URLs or inline code spans."
        ),
        epilog=(
            "Examples:\n"
            "  sase bead show sase-64\n"
            "  sase bead show sase-64 --format compact\n"
            "  sase bead show sase-64 --format json\n"
            "  sase bead show sase-64 --style rich --color always\n"
            "  sase bead show sase-64 --wrap auto"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Color output: auto, always, or never (default: auto)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["compact", "json", "full"],
        default="full",
        help="Output format: compact, json, or full (default: full)",
    )
    parser.add_argument(
        "-s",
        "--style",
        choices=["auto", "plain", "rich"],
        default="auto",
        help=(
            "Styling level for --format full: auto, plain, or rich "
            "(default: auto). --color decides whether ANSI may be emitted; "
            "--style decides how much styling to apply"
        ),
    )
    parser.add_argument(
        "-w",
        "--wrap",
        metavar="WIDTH",
        type=wrap_width,
        default=default_wrap_width,
        help=(
            "Wrap DESCRIPTION, NOTES, and +1 evidence prose at WIDTH columns: "
            f"integer >= 20, 'auto', 'none', or 0 (default: {default_wrap_width})"
        ),
    )
    parser.add_argument("id", help="Full or shorthand issue ID")


def register_bead_stats_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    """Register ``sase bead stats``."""
    subparsers.add_parser("stats", help="Show project statistics")
