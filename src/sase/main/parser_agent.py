"""Argument parser definition for the 'agent' CLI subcommand."""

from __future__ import annotations

import argparse

from sase.main.parser_agent_lifecycle import (
    register_agent_drain_parser,
    register_agent_kill_parser,
    register_agent_list_parser,
    register_agent_restart_parser,
    register_agent_show_parser,
    register_agent_wait_parser,
)
from sase.main.parser_agent_prompts import register_agent_prompts_parser
from sase.main.parser_agent_search import register_agent_search_parser
from sase.main.parser_agent_storage import (
    register_agent_archive_parser,
    register_agent_artifacts_parser,
    register_agent_index_parser,
    register_agent_names_parser,
)
from sase.main.parser_agent_sync import (
    register_agent_retire_v1_parser,
    register_agent_sync_parser,
)
from sase.main.parser_agent_tribe import register_agent_tribe_parser

_AGENT_SUBCOMMAND_ORDER = (
    "archive",
    "artifacts",
    "drain",
    "index",
    "kill",
    "list",
    "names",
    "persist-cleanup",
    "persist-directive",
    "prompts",
    "restart",
    "retire-v1",
    "revert",
    "search",
    "show",
    "sync",
    "tribe",
    "wait",
)


def register_agent_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the 'agent' subcommand parser."""
    agents_parser = subparsers.add_parser(
        "agent",
        description=(
            "Inspect and manage agents across projects. Running bare `sase agent` "
            "delegates to `sase agent list`."
        ),
        help="List, inspect, synchronize, and manage agents across projects",
    )
    agents_sub = agents_parser.add_subparsers(
        dest="agent_subcommand", help="Agent subcommands"
    )

    register_agent_list_parser(agents_sub)

    from sase.ops.commands.agent import add_agent_operation_parsers

    add_agent_operation_parsers(agents_sub)

    register_agent_drain_parser(agents_sub)
    register_agent_kill_parser(agents_sub)
    register_agent_show_parser(agents_sub)
    register_agent_retire_v1_parser(agents_sub)
    register_agent_sync_parser(agents_sub)
    register_agent_tribe_parser(agents_sub)
    register_agent_archive_parser(agents_sub)
    register_agent_artifacts_parser(agents_sub)
    register_agent_index_parser(agents_sub)
    register_agent_names_parser(agents_sub)
    register_agent_prompts_parser(agents_sub)
    register_agent_restart_parser(agents_sub)
    register_agent_search_parser(agents_sub)
    register_agent_wait_parser(agents_sub)
    _sort_agent_subcommands(agents_sub)


def _sort_agent_subcommands(agents_sub: argparse._SubParsersAction) -> None:
    choices = agents_sub.choices
    ordered = {
        name: choices[name] for name in _AGENT_SUBCOMMAND_ORDER if name in choices
    }
    extras = {name: choices[name] for name in sorted(set(choices) - set(ordered))}
    choices.clear()
    choices.update(ordered)
    choices.update(extras)
    order = {name: index for index, name in enumerate(choices)}
    agents_sub._choices_actions.sort(  # noqa: SLF001 - argparse has no public sorter.
        key=lambda action: order.get(action.dest, len(order))
    )
