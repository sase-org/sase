"""Argument parser definitions for the 'sase agent tribe' subcommand group."""

from __future__ import annotations

import argparse


def register_agent_tribe_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent tribe' subcommand group."""
    tribe_parser = agents_sub.add_parser(
        "tribe",
        help="Manage the user-defined tribe on an agent (used by the Agents tab)",
    )
    tribe_sub = tribe_parser.add_subparsers(
        dest="tribe_subcommand",
        help="Tribe subcommands",
    )

    tribe_set_parser = tribe_sub.add_parser(
        "set",
        help="Set the tribe on an agent (replaces any previous tribe)",
    )
    tribe_set_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to assign to a tribe",
    )
    tribe_set_parser.add_argument(
        "-t",
        "--tribe",
        required=True,
        help="Tribe name (without '@')",
    )

    tribe_unset_parser = tribe_sub.add_parser(
        "unset",
        help="Clear the tribe on an agent",
    )
    tribe_unset_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to remove from its tribe",
    )

    tribe_list_parser = tribe_sub.add_parser(
        "list",
        help="Print tribes as JSON (all agents, or filtered by --name)",
    )
    tribe_list_parser.add_argument(
        "-n",
        "--name",
        default=None,
        help="Limit output to a single agent",
    )
