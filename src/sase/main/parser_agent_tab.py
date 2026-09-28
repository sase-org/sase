"""Argument parser definitions for the 'sase agent tab' subcommand group."""

from __future__ import annotations

import argparse


def register_agent_tab_parser(agents_sub: argparse._SubParsersAction) -> None:
    """Register the 'sase agent tab' subcommand group."""
    tab_parser = agents_sub.add_parser(
        "tab",
        help="Move agents between Agents-tab placements (used by the Agents tab)",
        description=(
            "Move an agent's whole presentation root between Agents-tab "
            "placements. With no subcommand, `sase agent tab` defaults to "
            "`sase agent tab list`."
        ),
    )
    tab_sub = tab_parser.add_subparsers(
        dest="tab_subcommand",
        help="Tab subcommands",
    )

    tab_set_parser = tab_sub.add_parser(
        "set",
        help="Move an agent's presentation root onto a named tab",
    )
    tab_set_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to move",
    )
    tab_set_parser.add_argument(
        "-t",
        "--tab",
        required=True,
        help="Destination tab name (canonicalized like %%tab)",
    )

    tab_unset_parser = tab_sub.add_parser(
        "unset",
        help="Move an agent's presentation root back to the default tab",
    )
    tab_unset_parser.add_argument(
        "-n",
        "--name",
        required=True,
        help="Name of the agent to move back to the default tab",
    )

    tab_list_parser = tab_sub.add_parser(
        "list",
        help="Print the local agent-tab catalog with root counts",
    )
    tab_list_parser.add_argument(
        "-n",
        "--name",
        default=None,
        help="Limit output to the tab holding a single agent",
    )
    tab_list_parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit a stable, machine-readable JSON envelope",
    )
