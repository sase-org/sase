"""Argument parser definition for the ``sase skills`` command group."""

import argparse

from sase.main.parser_init import add_skills_init_arguments


def register_skills_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``skills`` command group."""
    skills_parser = subparsers.add_parser(
        "skills",
        help="Inspect and initialize generated SASE skills",
        description=(
            "Inspect generated SASE skills. With no subcommand, defaults to "
            "`sase skills list`."
        ),
    )
    skills_subparsers = skills_parser.add_subparsers(
        dest="skills_subcommand",
        help="Skills subcommands",
        required=False,
    )

    init_parser = skills_subparsers.add_parser(
        "init",
        help="Generate and deploy agent skill files from xprompt sources",
        description=(
            "Generate and deploy agent skill files from xprompt sources. "
            "`sase init skills` is a compatibility alias for this command."
        ),
    )
    add_skills_init_arguments(init_parser)

    skills_subparsers.add_parser(
        "list",
        help="Show generated skill source and target status",
        description=(
            "Show generated SASE skill sources, provider targets, and target "
            "drift without writing files."
        ),
    )
