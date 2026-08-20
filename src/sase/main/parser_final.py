"""Argument parser definition for the ``sase final`` command group."""

from __future__ import annotations

import argparse


def register_final_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase final`` command group."""

    final_parser = subparsers.add_parser(
        "final",
        help="Inspect configured SASE finalizers",
        description=(
            "Inspect host-owned finalizer instances and provider provenance. "
            "With no subcommand, `sase final` defaults to `sase final list`."
        ),
    )
    final_subparsers = final_parser.add_subparsers(
        dest="final_subcommand",
        help="Finalizer subcommands",
        metavar="<subcommand>",
        title="subcommands",
    )

    list_parser = final_subparsers.add_parser(
        "list",
        help="List effective finalizer instances",
    )
    _add_format_argument(list_parser)

    show_parser = final_subparsers.add_parser(
        "show",
        help="Show one finalizer instance",
    )
    show_parser.add_argument("instance", help="Finalizer instance ID")
    _add_format_argument(show_parser)

    doctor_parser = final_subparsers.add_parser(
        "doctor",
        help="Diagnose finalizer configuration and providers",
    )
    _add_format_argument(doctor_parser)


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-f",
        "--format",
        choices=("pretty", "json"),
        default="pretty",
        help="Output format",
    )


__all__ = ["register_final_parser"]
