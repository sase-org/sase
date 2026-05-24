"""Argument parser definition for the ``sase amd`` command group."""

from __future__ import annotations

import argparse


def add_amd_init_arguments(
    parser: argparse.ArgumentParser, *, suppress_check_default: bool = False
) -> None:
    """Add flags shared by ``sase amd init`` and ``sase init amd``."""
    if suppress_check_default:
        parser.add_argument(
            "-c",
            "--check",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Report AMD initialization drift without writing files",
        )
        return

    parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report AMD initialization drift without writing files",
    )


def register_amd_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``amd`` command group."""
    amd_parser = subparsers.add_parser(
        "amd",
        help="Inspect and initialize agent markdown documents",
        description=(
            "Inspect agent markdown documents. With no subcommand, defaults "
            "to `sase amd list`."
        ),
    )
    amd_subparsers = amd_parser.add_subparsers(
        dest="amd_subcommand",
        help="AMD subcommands",
        required=False,
    )

    init_parser = amd_subparsers.add_parser(
        "init",
        help="Create or refresh AGENTS.md and provider instruction shims",
        description=(
            "Create or refresh AGENTS.md and provider instruction shims. "
            "`sase init amd` is a compatibility alias for this command."
        ),
    )
    add_amd_init_arguments(init_parser)

    amd_subparsers.add_parser(
        "list",
        help="Show agent markdown document status",
        description=(
            "Show AGENTS.md files, provider instruction shims, and memory "
            "reference status without writing files."
        ),
    )
