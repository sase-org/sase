"""Argument parser definition for the ``sase instructions`` command group."""

import argparse


def register_instructions_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``instructions`` command group."""
    instructions_parser = subparsers.add_parser(
        "instructions",
        help="Inspect agent instruction documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect agent instruction documents. With no subcommand, defaults "
            "to `sase instructions list`."
        ),
        epilog=("examples:\n  sase instructions\n  sase instructions list\n"),
    )
    instructions_subparsers = instructions_parser.add_subparsers(
        dest="instructions_subcommand",
        help="Instructions subcommands",
        required=False,
    )
    instructions_subparsers.add_parser(
        "list",
        help="Show AGENTS.md files, provider shims, and memory reference status",
        description=(
            "Show discovered AGENTS.md files across the project, its "
            "subdirectories, home, and chezmoi source, including each H1 title, "
            "managed/custom state, memory reference counts, and provider "
            "instruction shim status. This command never writes files."
        ),
    )
