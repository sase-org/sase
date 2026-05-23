"""Argument parser definition for the top-level ``sase validate`` command."""

from __future__ import annotations

import argparse


def register_validate_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'validate' command parser."""
    subparsers.add_parser(
        "validate",
        help="Run SASE initialization and SDD validation checks",
    )
