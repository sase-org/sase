"""Argument parser definition for the ``sase instructions`` command group."""

import argparse

from sase.completion.kinds import ValueKind, set_completion_kind


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
        epilog=(
            "examples:\n"
            "  sase instructions\n"
            "  sase instructions list\n"
            "  sase instructions verify -n 20\n"
            "  sase instructions verify -j -n 50\n"
        ),
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
    verify_parser = instructions_subparsers.add_parser(
        "verify",
        help="Show observed instruction loads per provider",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Show what each provider's SASE runs and native helpers actually "
            "loaded, read from the providers' own session records. "
            "The command reports; it does not gate."
        ),
        epilog=(
            "examples:\n"
            "  sase instructions verify\n"
            "  sase instructions verify -n 20 --since 7d\n"
            "  sase instructions verify -p claude -H\n"
            "  sase instructions verify -j -n 50\n"
        ),
    )
    agent_action = verify_parser.add_argument(
        "-a",
        "--agent",
        default=None,
        metavar="NAME",
        help="One agent's runs, with per-session detail",
    )
    set_completion_kind(agent_action, ValueKind.AGENT)
    verify_parser.add_argument(
        "-H",
        "--helpers",
        action="store_true",
        help="Show per-helper rows",
    )
    verify_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit one stable JSON document",
    )
    verify_parser.add_argument(
        "-n",
        "--limit",
        default=20,
        type=int,
        metavar="N",
        help="Newest runs per provider (default 20, max 200)",
    )
    provider_action = verify_parser.add_argument(
        "-p",
        "--provider",
        action="append",
        default=[],
        metavar="PROVIDER",
        help="Filter to one provider; repeatable",
    )
    set_completion_kind(provider_action, ValueKind.PROVIDER)
    verify_parser.add_argument(
        "-s",
        "--since",
        default="7d",
        metavar="WHEN",
        help="Window start: duration (24h, 7d) or ISO timestamp",
    )
    verify_parser.add_argument(
        "-u",
        "--until",
        default=None,
        metavar="WHEN",
        help="Window end: duration (24h, 7d) or ISO timestamp",
    )
