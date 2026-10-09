"""Argument parser definition for the ``sase autonomy`` CLI subcommand."""

from __future__ import annotations

import argparse

from sase.completion.kinds import ValueKind, set_completion_kind
from sase.main.parser_bead_common import bead_date_arg

_AUTONOMY_SUBCOMMANDS = "{explain,list,log,show}"

#: Gate kinds ``sase autonomy log --kind`` filters on. Kept beside the
#: reader in ``sase.autonomy.cli_log`` (``LOG_KIND_CHOICES``); change both.
_LOG_KIND_CHOICES = ("plan", "epic_plan", "question")

#: Decision outcomes ``sase autonomy log --outcome`` filters on. Kept
#: beside ``sase.autonomy.cli_log`` (``LOG_OUTCOME_CHOICES``); change both.
_LOG_OUTCOME_CHOICES = ("auto", "ask")

#: Built-in profiles ``sase autonomy show`` accepts. Core owns the
#: catalog; this list only drives completion and usage validation.
_PROFILE_CHOICES = ("epic", "manual", "standard", "tale")


def register_autonomy_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``sase autonomy`` subcommand parser."""
    autonomy_parser = subparsers.add_parser(
        "autonomy",
        help="Predict and inspect %%auto gate decisions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect the core-owned %auto autonomy record: predict each "
            "gate decision exactly (`explain`), list the built-in profiles "
            "(`list`), read the host decision log (`log`), and show one "
            "profile's matrix (`show`).\n"
            "\n"
            "With no subcommand, `sase autonomy` defaults to "
            "`sase autonomy list`."
        ),
        epilog=(
            "examples:\n"
            "  sase autonomy                             # same as `sase autonomy list`\n"
            "  sase autonomy explain -p '%auto:tale'\n"
            "  sase autonomy explain acme--agent\n"
            "  sase autonomy log --since 1h\n"
            "  sase autonomy show tale"
        ),
    )
    autonomy_sub = autonomy_parser.add_subparsers(
        dest="autonomy_subcommand",
        help="Autonomy subcommands",
        metavar=_AUTONOMY_SUBCOMMANDS,
    )

    _add_explain_parser(autonomy_sub)
    _add_list_parser(autonomy_sub)
    _add_log_parser(autonomy_sub)
    _add_show_parser(autonomy_sub)


def _add_json_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )


def _add_explain_parser(autonomy_sub: argparse._SubParsersAction) -> None:
    """Register ``sase autonomy explain``."""
    explain_parser = autonomy_sub.add_parser(
        "explain",
        help="Predict each %%auto decision for an agent, prompt, or gate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Predict each %auto decision exactly. With an agent name, show "
            "its live record's summary, the per-kind cells with rule and "
            "source, the decisions so far from the host log, and the "
            "coverage line. With --prompt, dry-run a prompt's %auto through "
            "the side-effect-free scan: $(...) is never executed and is "
            "labeled as unexpanded. With --gate, show the settled gate's "
            "deciding policy block, which is the revision that decided it."
        ),
        epilog=(
            "examples:\n"
            "  sase autonomy explain -p '%auto:tale'\n"
            "  sase autonomy explain -p '%auto:tale' --json\n"
            "  sase autonomy explain acme--agent\n"
            "  sase autonomy explain --gate plan/abc123\n"
            "  sase autonomy explain -g acme--gate --json"
        ),
    )
    agent_action = explain_parser.add_argument(
        "agent",
        nargs="?",
        default=None,
        metavar="AGENT",
        help="Agent name, resolved the way `sase agent show` resolves names",
    )
    set_completion_kind(agent_action, ValueKind.AGENT)
    gate_action = explain_parser.add_argument(
        "-g",
        "--gate",
        default=None,
        metavar="ID",
        help=(
            "Gate as KIND/REQUEST_ID, or a gate-turn reference "
            "(short id, member name, or owning agent name)"
        ),
    )
    set_completion_kind(gate_action, ValueKind.GATE)
    _add_json_option(explain_parser)
    explain_parser.add_argument(
        "-p",
        "--prompt",
        default=None,
        metavar="TEXT",
        help="Dry-run this prompt's %%auto without executing anything",
    )


def _add_list_parser(autonomy_sub: argparse._SubParsersAction) -> None:
    """Register ``sase autonomy list``."""
    list_parser = autonomy_sub.add_parser(
        "list",
        help="List the built-in autonomy profiles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List the built-in autonomy profiles with their one-liners. "
            "`standard` is the default profile."
        ),
        epilog=("examples:\n  sase autonomy list\n  sase autonomy list --json"),
    )
    _add_json_option(list_parser)


def _add_log_parser(autonomy_sub: argparse._SubParsersAction) -> None:
    """Register ``sase autonomy log``."""
    log_parser = autonomy_sub.add_parser(
        "log",
        help="Read the host %%auto decision log, newest first",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Read the host %auto decision log, newest first, rendered with "
            "the core decision sentence. Only non-manual evaluations are "
            "logged: manual agents leave no rows."
        ),
        epilog=(
            "examples:\n"
            "  sase autonomy log\n"
            "  sase autonomy log acme--agent\n"
            "  sase autonomy log --since 1h\n"
            "  sase autonomy log -k plan -o auto --json"
        ),
    )
    agent_action = log_parser.add_argument(
        "agent",
        nargs="?",
        default=None,
        metavar="AGENT",
        help="Only decisions created by this agent",
    )
    set_completion_kind(agent_action, ValueKind.AGENT)
    _add_json_option(log_parser)
    log_parser.add_argument(
        "-k",
        "--kind",
        choices=_LOG_KIND_CHOICES,
        default=None,
        metavar="KIND",
        help=f"Only this gate kind ({', '.join(_LOG_KIND_CHOICES)})",
    )
    log_parser.add_argument(
        "-o",
        "--outcome",
        choices=_LOG_OUTCOME_CHOICES,
        default=None,
        metavar="OUTCOME",
        help=f"Only this outcome ({', '.join(_LOG_OUTCOME_CHOICES)})",
    )
    log_parser.add_argument(
        "-s",
        "--since",
        default=None,
        metavar="DATE",
        type=bead_date_arg,
        help="Only decisions at/after DATE",
    )


def _add_show_parser(autonomy_sub: argparse._SubParsersAction) -> None:
    """Register ``sase autonomy show``."""
    show_parser = autonomy_sub.add_parser(
        "show",
        help="Show one autonomy profile's matrix",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Show one built-in profile's matrix: its layer, the selections "
            "that pick it, the per-kind cells, and the coverage line."
        ),
        epilog=(
            "examples:\n  sase autonomy show tale\n  sase autonomy show standard --json"
        ),
    )
    show_parser.add_argument(
        "profile",
        metavar="PROFILE",
        choices=_PROFILE_CHOICES,
        help=f"Profile to inspect ({', '.join(_PROFILE_CHOICES)})",
    )
    _add_json_option(show_parser)


__all__ = ["register_autonomy_parser"]
