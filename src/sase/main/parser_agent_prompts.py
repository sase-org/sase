"""Argument parser definitions for the 'sase agent prompts' subcommand group."""

from __future__ import annotations

import argparse


def _prompt_archive_month(value: str) -> str:
    if len(value) != 6 or not value.isdigit() or not 1 <= int(value[4:]) <= 12:
        raise argparse.ArgumentTypeError("month must use YYYYMM format")
    return value


def _add_prompt_archive_common_options(
    parser: argparse.ArgumentParser,
    *,
    include_month: bool,
) -> None:
    """Add selection and output flags shared by prompt commands."""

    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit stable machine-readable JSON",
    )
    if include_month:
        parser.add_argument(
            "-m",
            "--month",
            metavar="YYYYMM",
            type=_prompt_archive_month,
            help="Limit the operation to one archive month",
        )
    parser.add_argument(
        "-p",
        "--project",
        help="Select a project by name or alias (default: current project)",
    )


def register_agent_prompts_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent prompts' subcommand group."""
    prompts_parser = agents_sub.add_parser(
        "prompts",
        help="Inspect and validate canonical prompt persistence",
        description=(
            "Inspect prompts published in the agents sidecar and validate their "
            "headers, artifact bytes, local manifests, and plan links. With no "
            "subcommand, `sase agent prompts` defaults to "
            "`sase agent prompts list`."
        ),
        epilog=(
            "examples:\n"
            "  sase agent prompts\n"
            "  sase agent prompts list --month 202608\n"
            "  sase agent prompts migrate\n"
            "  sase agent prompts migrate --write\n"
            "  sase agent prompts show 202608/example.md\n"
            "  sase agent prompts validate --show-warnings\n"
            "  sase agent prompts validate --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    prompts_sub = prompts_parser.add_subparsers(
        dest="prompts_subcommand",
        help="Prompt archive subcommands",
        metavar="{list,migrate,show,validate}",
    )

    prompts_list = prompts_sub.add_parser(
        "list",
        help="List canonical archived prompts",
        description="List prompts from the selected project's agents sidecar.",
    )
    _add_prompt_archive_common_options(prompts_list, include_month=True)

    prompts_migrate = prompts_sub.add_parser(
        "migrate",
        help="Migrate historical prompts from the plans sidecar",
        description=(
            "Report historical plans-sidecar prompts by default; use --write to "
            "move them into the canonical agents-sidecar archive."
        ),
    )
    _add_prompt_archive_common_options(prompts_migrate, include_month=True)
    prompts_migrate.add_argument(
        "-w",
        "--write",
        action="store_true",
        help=("Apply, commit, and publish both sidecars (default: read-only report)"),
    )

    prompts_show = prompts_sub.add_parser(
        "show",
        help="Show one canonical archived prompt",
    )
    prompts_show.add_argument(
        "prompt",
        metavar="PROMPT",
        help="Prompt name, YYYYMM/name, or prompts/YYYYMM/name.md",
    )
    _add_prompt_archive_common_options(prompts_show, include_month=False)

    prompts_validate = prompts_sub.add_parser(
        "validate",
        help="Validate canonical prompts, artifacts, manifests, and plan links",
        epilog=(
            "examples:\n"
            "  sase agent prompts validate\n"
            "  sase agent prompts validate --month 202608\n"
            "  sase agent prompts validate --show-warnings\n"
            "  sase agent prompts validate --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_prompt_archive_common_options(prompts_validate, include_month=True)
    prompts_validate.add_argument(
        "-s",
        "--show-warnings",
        action="store_true",
        help="Show warning-severity diagnostics (hidden by default)",
    )
