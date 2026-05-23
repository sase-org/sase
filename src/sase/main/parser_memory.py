"""Argument parser definition for the ``sase memory`` command group."""

import argparse


def register_memory_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``memory`` command group."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Inspect and initialize SASE memory context",
        description=(
            "Inspect SASE memory context. With no subcommand, defaults to "
            "`sase memory list`."
        ),
    )
    memory_subparsers = memory_parser.add_subparsers(
        dest="memory_subcommand",
        help="Memory subcommands",
        required=False,
    )

    init_parser = memory_subparsers.add_parser(
        "init",
        help="Create or refresh memory files and provider instruction shims",
        description=(
            "Create or refresh SASE memory files and provider instruction "
            "shims. `sase init memory` is a compatibility alias for this "
            "command."
        ),
    )
    init_parser.add_argument(
        "-c",
        "--check",
        action="store_true",
        help="Report memory initialization drift without writing files",
    )
    init_parser.add_argument(
        "-C",
        "--no-commit",
        action="store_true",
        help="Skip the project git commit/push sequence",
    )

    memory_subparsers.add_parser(
        "list",
        help="Show loaded, referenced, available, and missing memory files",
        description=(
            "Show the memory files visible from the current launch context, "
            "including loaded @ references, referenced-only plain memory paths, "
            "available files, and missing references."
        ),
    )
