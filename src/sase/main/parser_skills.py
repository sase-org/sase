"""Argument parser definition for the ``sase skill`` command group."""

import argparse

from sase.main.parser_init import add_skills_init_arguments


def register_skills_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``skill`` command group."""
    skills_parser = subparsers.add_parser(
        "skill",
        help="Inspect and initialize generated SASE skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect, initialize, and audit generated SASE skills. With no "
            "subcommand, defaults to `sase skill list`."
        ),
        epilog=(
            "examples:\n"
            "  sase skill list\n"
            "  sase skill init --force\n"
            "  sase skill log --runtime codex\n"
            '  sase skill use sase_plan --reason "Preparing an implementation plan"'
        ),
    )
    skills_subparsers = skills_parser.add_subparsers(
        dest="skill_subcommand",
        help="Skill subcommands",
        required=False,
    )

    init_parser = skills_subparsers.add_parser(
        "init",
        help="Generate and deploy agent skill files from canonical skill sources",
        description=(
            "Generate and deploy agent skill files from canonical skill "
            "sources (Markdown files in a skills/ directory that declare a "
            "truthy `skill:` value). Commit source changes and land them on "
            "the canonical "
            "branch before deploying: a chezmoi deploy is refused when the "
            "sources are uncommitted, when HEAD is not an ancestor of the "
            "canonical branch, or when it would move the destination off the "
            "source commit recorded in the provenance manifest. Preview with "
            "--diff or --dry-run while iterating. "
            "`sase init skills` is a compatibility alias for `sase skill init`."
        ),
    )
    add_skills_init_arguments(init_parser)

    skills_subparsers.add_parser(
        "list",
        help="Show generated skill source and target status",
        description=(
            "Show generated SASE skill sources, provider targets, and target "
            "drift without writing files, plus any source that declares "
            "`skill:` outside a canonical skills/ directory."
        ),
    )

    log_parser = skills_subparsers.add_parser(
        "log",
        help="Summarize or inspect auditable skill-use events",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Summarize auditable skill-use events recorded by `sase skill "
            "use`, or inspect matching events with --skill, --agent, "
            "--runtime, or --id."
        ),
        epilog=(
            "examples:\n"
            "  sase skill log\n"
            "  sase skill log --runtime codex\n"
            "  sase skill log --skill sase_plan\n"
            "  sase skill log --id <use-id>"
        ),
    )
    log_parser.add_argument(
        "-a",
        "--agent",
        metavar="AGENT_NAME",
        help="Only include uses by the given agent",
    )
    log_parser.add_argument(
        "-i",
        "--id",
        metavar="USE_ID",
        help="Show one skill-use event by id or unambiguous id prefix",
    )
    log_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit deterministic machine-readable JSON",
    )
    log_parser.add_argument(
        "-R",
        "--runtime",
        metavar="RUNTIME",
        help="Only include uses recorded under the given runtime",
    )
    log_parser.add_argument(
        "-s",
        "--skill",
        metavar="SKILL_NAME",
        help="Only include uses of the given skill",
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
            '  sase skill use sase_plan --reason "Preparing an implementation plan"'
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
