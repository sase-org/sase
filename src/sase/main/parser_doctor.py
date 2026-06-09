"""Argument parser definition for the ``sase doctor`` top-level command."""

from __future__ import annotations

import argparse


def register_doctor_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase doctor`` command parser."""
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run bounded read-only SASE diagnostics",
        description=(
            "Run fast, read-only diagnostics for the active SASE runtime, "
            "configuration, and project checkout."
        ),
    )
    doctor_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report",
    )
    doctor_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show every check and bounded detail",
    )
    doctor_parser.add_argument(
        "-D",
        "--deep",
        action="store_true",
        help="Include slower deep checks when registered",
    )
    doctor_parser.add_argument(
        "-s",
        "--strict",
        action="store_true",
        help="Exit non-zero when warnings are present",
    )
    doctor_parser.add_argument(
        "-L",
        "--list-checks",
        action="store_true",
        help="List registered diagnostic checks without running them",
    )
    doctor_parser.add_argument(
        "-C",
        "--check",
        action="append",
        default=[],
        metavar="ID_OR_GROUP",
        help="Run only a check id or group; repeatable",
    )
    doctor_parser.add_argument(
        "-p",
        "--project",
        default=None,
        help="Project name to include in the report and later project checks",
    )


__all__ = ["register_doctor_parser"]
