"""Argument parser definition for the ``sase skills`` command group."""

import argparse

from sase.main.parser_init import add_skills_init_arguments


def register_skills_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``skills`` command group."""
    skills_parser = subparsers.add_parser(
        "skills",
        help="Inspect and initialize generated SASE skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect, initialize, and audit generated SASE skills. With no "
            "subcommand, defaults to `sase skills list`."
        ),
        epilog=(
            "examples:\n"
            "  sase skills list\n"
            "  sase skills init --force\n"
            '  sase skills use sase_plan --reason "Preparing an implementation plan"'
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

    use_parser = skills_subparsers.add_parser(
        "use",
        help="Record that the current agent is using a skill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Append an attributable skill-use audit event for the current "
            "SASE agent. This is primarily called from generated SKILL.md "
            "files before a skill's instructions are followed."
        ),
        epilog=(
            "example:\n"
            '  sase skills use sase_plan --reason "Preparing an implementation plan"'
        ),
    )
    use_parser.add_argument(
        "name",
        metavar="skill-name",
        help="Generated skill name to record, for example sase_plan",
    )
    use_parser.add_argument(
        "-r",
        "--reason",
        required=True,
        help="Non-empty reason for the audited skill use",
    )
