"""Argument parser definition for the ``sase memory`` command group."""

import argparse


def register_memory_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``memory`` command group."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Inspect and initialize SASE memory context",
    )
    memory_subparsers = memory_parser.add_subparsers(
        dest="memory_subcommand",
        help="Memory subcommands",
        required=False,
    )

    init_parser = memory_subparsers.add_parser(
        "init",
        help="Initialize SASE memory files and provider instruction shims",
    )
    init_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="Skip the project git commit/push sequence",
    )

    memory_subparsers.add_parser(
        "list",
        help="List memory files visible from the current launch context",
    )
