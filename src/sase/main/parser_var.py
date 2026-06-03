"""Argument parser definition for the ``sase var`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_var_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase var`` subcommand parser."""
    var_parser = subparsers.add_parser(
        "var",
        help="Attach output variables to the current SASE agent run",
    )
    var_subparsers = var_parser.add_subparsers(
        dest="var_subcommand",
        help="Variable subcommands",
    )

    set_parser = var_subparsers.add_parser(
        "set",
        help="Set output variables for the current SASE agent",
    )
    set_parser.add_argument(
        "assignments",
        nargs="+",
        help="Output variable assignment in KEY=VALUE form",
    )
