"""Argument parser for the 'sase agent auto-restart' subcommand group."""

from __future__ import annotations

import argparse

# Full group order from the epic plan's CLI table.
_AUTO_RESTART_SUBCOMMAND_ORDER = ("list", "resume", "run", "scan", "show")


def register_agent_auto_restart_parser(
    agents_sub: argparse._SubParsersAction,
) -> None:
    """Register the 'sase agent auto-restart' subcommand group."""
    auto_restart_parser = agents_sub.add_parser(
        "auto-restart",
        description=(
            "Relaunch agents broken by a live sase update, once per lineage. "
            "Running `sase agent auto-restart` with no subcommand lists ledger "
            "records. `scan` is strictly read-only: it never writes the "
            "restart ledger or relaunches anything."
        ),
        help=("Relaunch agents broken by a live sase update (at most once each)"),
    )
    auto_restart_sub = auto_restart_parser.add_subparsers(
        dest="auto_restart_subcommand",
        help="Auto-restart subcommands",
    )

    _register_list_parser(auto_restart_sub)
    _register_resume_parser(auto_restart_sub)
    _register_run_parser(auto_restart_sub)
    _register_scan_parser(auto_restart_sub)
    _register_show_parser(auto_restart_sub)
    _sort_auto_restart_subcommands(auto_restart_sub)


def _register_list_parser(
    auto_restart_sub: argparse._SubParsersAction,
) -> None:
    list_parser = auto_restart_sub.add_parser(
        "list",
        help="List restart ledger records, newest first, grouped by episode",
        description=(
            "List update-skew restart ledger records, newest first, grouped "
            "by episode. A bare `sase agent auto-restart` delegates here."
        ),
    )
    list_parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Include settled and declined records, not just in-flight ones",
    )
    list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Print ledger records as JSON instead of a table",
    )


def _register_resume_parser(
    auto_restart_sub: argparse._SubParsersAction,
) -> None:
    auto_restart_sub.add_parser(
        "resume",
        help="Re-arm after the storm breaker trips",
        description=("Clear the storm-breaker pause so the healer may act again."),
    )


def _register_run_parser(
    auto_restart_sub: argparse._SubParsersAction,
) -> None:
    run_parser = auto_restart_sub.add_parser(
        "run",
        help="Claim the ledger and relaunch a failed agent once",
        description=(
            "Run the healer: claim the at-most-once ledger, verify the "
            "update-skew signature, witnesses, quiescence, and probe, then "
            "relaunch the failed agent under the same name. A manual run "
            "still honors the ledger."
        ),
    )
    target = run_parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Agent name to heal",
    )
    target.add_argument(
        "-a",
        "--artifacts-dir",
        default=None,
        metavar="DIR",
        help="Heal the failed row at DIR",
    )
    target.add_argument(
        "-p",
        "--pending",
        action="store_true",
        help="Heal every pending failure (the scheduler job's target)",
    )
    run_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Verify without claiming, relaunching, or notifying",
    )
    run_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Print healer outcomes as JSON instead of a table",
    )


def _register_show_parser(
    auto_restart_sub: argparse._SubParsersAction,
) -> None:
    show_parser = auto_restart_sub.add_parser(
        "show",
        help="Show one ledger record with its verdict and witnesses",
        description=(
            "Show one restart ledger record: the verdict, a checklist of "
            "witnesses, the state timeline, and the evidence bundle path."
        ),
    )
    show_parser.add_argument(
        "target",
        metavar="TARGET",
        help="Ledger key, lineage root, or agent name",
    )
    show_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Print the record as JSON instead of a card",
    )


def _register_scan_parser(
    auto_restart_sub: argparse._SubParsersAction,
) -> None:
    scan_parser = auto_restart_sub.add_parser(
        "scan",
        help="Replay the classifier over recent failures (read-only)",
        description=(
            "Classify failed agents and dismissed bundles within --since "
            "through the update-skew classifier and print one row per "
            "failure with its signature, witnesses, and verdict. "
            "Never writes the ledger or relaunches anything."
        ),
    )
    scan_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Print verdict wires as JSON instead of a table",
    )
    scan_parser.add_argument(
        "-l",
        "--limit",
        default=None,
        metavar="N",
        help=(
            "Show at most N rows (default: 50); the summary always covers the full set"
        ),
    )
    scan_parser.add_argument(
        "-s",
        "--since",
        default="7d",
        metavar="DURATION",
        help=(
            "Only include failures from the last DURATION: bare seconds "
            "or a duration like 90s / 45m / 2h / 7d / 2w (default: 7d)"
        ),
    )


def _sort_auto_restart_subcommands(
    auto_restart_sub: argparse._SubParsersAction,
) -> None:
    choices = auto_restart_sub.choices
    ordered = {
        name: choices[name]
        for name in _AUTO_RESTART_SUBCOMMAND_ORDER
        if name in choices
    }
    extras = {name: choices[name] for name in sorted(set(choices) - set(ordered))}
    choices.clear()
    choices.update(ordered)
    choices.update(extras)
    order = {name: index for index, name in enumerate(choices)}
    auto_restart_sub._choices_actions.sort(  # noqa: SLF001 - argparse has no public sorter.
        key=lambda action: order.get(action.dest, len(order))
    )
