"""Argument parser definition for the ``sase core`` CLI subcommand."""

from __future__ import annotations

import argparse


def register_core_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase core`` subcommand parser."""
    core_parser = subparsers.add_parser(
        "core",
        help="Inspect the required sase_core_rs Rust extension",
    )
    core_subparsers = core_parser.add_subparsers(
        dest="core_subcommand", help="Core subcommands"
    )

    # sase core health [-j/--json]
    health_parser = core_subparsers.add_parser(
        "health",
        help="Check that the sase_core_rs Rust extension is installed and working",
    )
    health_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit the health report as JSON (machine-readable)",
    )
