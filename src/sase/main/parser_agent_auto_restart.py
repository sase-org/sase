"""Argument parser for the 'sase agent auto-restart' subcommand group."""

from __future__ import annotations

import argparse

# Full group order from the epic plan's CLI table. Only ``scan`` is
# registered in the witness-scan phase; the healer phase adds
# ``list``, ``resume``, ``run``, and ``show``.
_AUTO_RESTART_SUBCOMMAND_ORDER = ("list", "resume", "run", "scan", "show")


def register_agent_auto_restart_parser(
    agents_sub: argparse._SubParsersAction,
) -> None:
    """Register the 'sase agent auto-restart' subcommand group."""
    auto_restart_parser = agents_sub.add_parser(
        "auto-restart",
        description=(
            "Replay the update-skew failure classifier over history. "
            "Running `sase agent auto-restart scan` is strictly read-only: "
            "it never writes the restart ledger or relaunches anything."
        ),
        help=("Replay the update-skew classifier over past failures (read-only scan)"),
    )
    auto_restart_sub = auto_restart_parser.add_subparsers(
        dest="auto_restart_subcommand",
        help="Auto-restart subcommands",
    )

    _register_scan_parser(auto_restart_sub)
    _sort_auto_restart_subcommands(auto_restart_sub)


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
