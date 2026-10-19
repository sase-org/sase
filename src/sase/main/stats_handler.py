"""Dispatch for the ``sase stats`` command group."""

from __future__ import annotations

import argparse
import sys

from sase.main.parser import create_parser
from sase.main.parser_root_help import root_subparser_action


def handle_stats_command(args: argparse.Namespace) -> int:
    """Handle ``sase stats`` and its implemented views."""
    subcommand = getattr(args, "stats_subcommand", None)
    if subcommand is None:
        _print_group_help()
        return 0
    if subcommand == "project":
        from sase.main.stats_handler_project import handle_stats_project

        return handle_stats_project(args)
    print(
        f"sase stats: unknown view {subcommand!r}. Implemented views: project.",
        file=sys.stderr,
    )
    return 2


def _print_group_help() -> None:
    parser = create_parser(only="stats")
    root_subparser_action(parser).choices["stats"].print_help()


__all__ = ["handle_stats_command"]
