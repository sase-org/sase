"""Argument parser definitions for bead subcommands."""

from __future__ import annotations

import argparse

from sase.main.parser_bead_common import nonnegative_int
from sase.main.parser_bead_lifecycle import (
    register_bead_close_parser,
    register_bead_create_parser,
    register_bead_note_parser,
    register_bead_onboard_parser,
    register_bead_open_parser,
    register_bead_plus_one_parser,
    register_bead_rm_parser,
    register_bead_snooze_parser,
    register_bead_update_parser,
    register_bead_work_parser,
)
from sase.main.parser_bead_queries import (
    register_bead_blocked_parser,
    register_bead_history_parser,
    register_bead_list_parser,
    register_bead_ready_parser,
    register_bead_search_parser,
    register_bead_show_parser,
    register_bead_stats_parser,
)
from sase.main.parser_bead_store import (
    register_bead_dep_parser,
    register_bead_doctor_parser,
    register_bead_init_parser,
    register_bead_pages_parser,
    register_bead_ref_parser,
    register_bead_resolve_conflicts_parser,
    register_bead_sync_external_parser,
    register_bead_sync_parser,
)


def register_bead_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``bead`` command group and its subcommands."""
    bead_parser = subparsers.add_parser(
        "bead",
        help="Lightweight git-native issue tracking",
    )
    bead_subparsers = bead_parser.add_subparsers(
        dest="bead_subcommand", help="Bead subcommands"
    )

    # Keep subcommands sorted so the public help remains easy to scan.
    register_bead_plus_one_parser(bead_subparsers)
    register_bead_blocked_parser(bead_subparsers)
    register_bead_close_parser(bead_subparsers)
    register_bead_create_parser(bead_subparsers)
    register_bead_dep_parser(bead_subparsers)
    register_bead_doctor_parser(bead_subparsers)
    register_bead_history_parser(bead_subparsers)
    register_bead_init_parser(bead_subparsers)
    register_bead_list_parser(bead_subparsers)
    register_bead_note_parser(bead_subparsers)
    register_bead_onboard_parser(bead_subparsers)
    register_bead_open_parser(bead_subparsers)
    register_bead_pages_parser(bead_subparsers)
    register_bead_ready_parser(bead_subparsers)
    register_bead_ref_parser(bead_subparsers)
    register_bead_resolve_conflicts_parser(bead_subparsers)
    register_bead_rm_parser(bead_subparsers)
    register_bead_search_parser(bead_subparsers)
    register_bead_show_parser(bead_subparsers)
    register_bead_snooze_parser(bead_subparsers)
    register_bead_stats_parser(bead_subparsers)
    register_bead_sync_parser(bead_subparsers)
    register_bead_sync_external_parser(bead_subparsers)
    register_bead_work_parser(bead_subparsers)
    register_bead_update_parser(bead_subparsers)


__all__ = ["nonnegative_int", "register_bead_parser"]
