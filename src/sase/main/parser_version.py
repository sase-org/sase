"""Argument parser definition for the ``sase version`` command."""

from __future__ import annotations

import argparse


def register_version_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase version`` top-level command."""
    version_parser = subparsers.add_parser(
        "version",
        help="Show the active SASE runtime package inventory",
        description=(
            "Show the exact SASE host, Rust core, and plugin packages used by "
            "this process."
        ),
    )
    version_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON object",
    )
    version_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show additional install, source, git, and plugin signal details",
    )
